from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import MaintenanceFinancialEntry, OwnerRepasse, RentCharge
from app.domains.inspections.models import Inspection, InspectionVersion
from app.domains.inspections.pdf import inspection_code
from app.domains.lease_lifecycle.models import LeaseLifecycleCase
from app.domains.lease_lifecycle.schemas import (
    FinancialClearance,
    FinancialClearanceItem,
    LeaseLifecycleResponse,
    RenewalProposal,
)
from app.domains.leases.models import LeaseContract, LeaseContractVersion
from app.domains.leases.pdf import lease_contract_code
from app.domains.portfolio.models import Property

CENT = Decimal("0.01")
CLOSED_FINANCE_STATUSES = {"paid", "settled", "settled_zero", "cancelled"}


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def lifecycle_code(item: LeaseLifecycleCase) -> str:
    return f"CIC-{item.internal_number:06d}"


def calculate_proportional_fine(lease: LeaseContract, effective_date: date) -> Decimal:
    if effective_date >= lease.end_date or money(lease.termination_fine_months) <= 0:
        return Decimal("0.00")
    total_days = max(1, (lease.end_date - lease.start_date).days)
    remaining_days = max(0, (lease.end_date - effective_date).days)
    if remaining_days <= 0:
        return Decimal("0.00")
    full_fine = money(lease.rent_amount) * money(lease.termination_fine_months)
    return money(full_fine * Decimal(remaining_days) / Decimal(total_days))


def _remaining(amount, settled, status: str) -> Decimal:
    if status in CLOSED_FINANCE_STATUSES:
        return Decimal("0.00")
    return money(max(Decimal("0.00"), money(amount) - money(settled)))


def financial_clearance(db: Session, *, organization_id: UUID, lease_contract_id: UUID) -> FinancialClearance:
    items: list[FinancialClearanceItem] = []

    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.lease_contract_id == lease_contract_id,
        )
    ).all()
    for row in charges:
        settled = money(row.paid_amount) if row.status == "paid" else Decimal("0.00")
        remaining = _remaining(row.gross_amount, settled, row.status)
        if remaining <= 0:
            continue
        items.append(
            FinancialClearanceItem(
                id=row.id,
                code=f"COB-{row.internal_number:06d}",
                source_type="rent",
                direction="receivable",
                description=f"Locação {row.competence.strftime('%m/%Y')}",
                amount=money(row.gross_amount),
                remaining_amount=remaining,
                status=row.status,
                blocker=True,
            )
        )

    maintenance = db.scalars(
        select(MaintenanceFinancialEntry).where(
            MaintenanceFinancialEntry.organization_id == organization_id,
            MaintenanceFinancialEntry.lease_contract_id == lease_contract_id,
        )
    ).all()
    for row in maintenance:
        remaining = _remaining(row.amount, row.settled_amount, row.status)
        if remaining <= 0:
            continue
        blocker = row.direction == "receivable"
        items.append(
            FinancialClearanceItem(
                id=row.id,
                code=f"MFIN-{row.internal_number:06d}",
                source_type="maintenance",
                direction=row.direction,
                description=f"Manutenção · {row.counterparty_name}",
                amount=money(row.amount),
                remaining_amount=remaining,
                status=row.status,
                blocker=blocker,
            )
        )

    titles = db.scalars(
        select(FinancialTitle).where(
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.lease_contract_id == lease_contract_id,
        )
    ).all()
    for row in titles:
        remaining = _remaining(row.amount, row.settled_amount, row.status)
        if remaining <= 0:
            continue
        blocker = row.direction == "receivable"
        items.append(
            FinancialClearanceItem(
                id=row.id,
                code=f"FIN-{row.internal_number:06d}",
                source_type=str((row.source_snapshot or {}).get("origin") or "financial_title"),
                direction=row.direction,
                description=row.description,
                amount=money(row.amount),
                remaining_amount=remaining,
                status=row.status,
                blocker=blocker,
            )
        )

    repasses = db.scalars(
        select(OwnerRepasse).where(
            OwnerRepasse.organization_id == organization_id,
            OwnerRepasse.lease_contract_id == lease_contract_id,
        )
    ).all()
    for row in repasses:
        remaining = Decimal("0.00") if row.status in CLOSED_FINANCE_STATUSES else money(row.amount)
        if remaining <= 0:
            continue
        items.append(
            FinancialClearanceItem(
                id=row.id,
                code=f"REP-{str(row.id)[:8].upper()}",
                source_type="owner_repasse",
                direction="payable",
                description=f"Repasse ao proprietário · {row.owner_name}",
                amount=money(row.amount),
                remaining_amount=remaining,
                status=row.status,
                blocker=False,
            )
        )

    blocking = [item for item in items if item.blocker]
    followups = [item for item in items if not item.blocker]
    items.sort(key=lambda item: (not item.blocker, item.code))
    return FinancialClearance(
        blocking_count=len(blocking),
        blocking_amount=money(sum((item.remaining_amount for item in blocking), Decimal("0.00"))),
        followup_count=len(followups),
        followup_amount=money(sum((item.remaining_amount for item in followups), Decimal("0.00"))),
        items=items,
    )


def load_lease(db: Session, *, organization_id: UUID, lease_contract_id: UUID) -> LeaseContract:
    item = db.scalar(
        select(LeaseContract).where(
            LeaseContract.id == lease_contract_id,
            LeaseContract.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Contrato de locação não encontrado.")
    return item


def load_case(db: Session, *, organization_id: UUID, lease_contract_id: UUID) -> LeaseLifecycleCase | None:
    return db.scalar(
        select(LeaseLifecycleCase).where(
            LeaseLifecycleCase.organization_id == organization_id,
            LeaseLifecycleCase.lease_contract_id == lease_contract_id,
        )
    )


def require_case(db: Session, *, organization_id: UUID, lease_contract_id: UUID) -> LeaseLifecycleCase:
    item = load_case(db, organization_id=organization_id, lease_contract_id=lease_contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Esta locação ainda não possui processo de renovação ou encerramento.")
    return item


def _renewed_lease(db: Session, item: LeaseLifecycleCase) -> LeaseContract | None:
    if item.renewed_lease_contract_id is None:
        return None
    return db.scalar(
        select(LeaseContract).where(
            LeaseContract.id == item.renewed_lease_contract_id,
            LeaseContract.organization_id == item.organization_id,
        )
    )


def _exit_inspection(db: Session, item: LeaseLifecycleCase) -> Inspection | None:
    if item.exit_inspection_id is None:
        return None
    return db.scalar(
        select(Inspection).where(
            Inspection.id == item.exit_inspection_id,
            Inspection.organization_id == item.organization_id,
        )
    )


def response(db: Session, item: LeaseLifecycleCase) -> LeaseLifecycleResponse:
    lease = load_lease(db, organization_id=item.organization_id, lease_contract_id=item.lease_contract_id)
    renewed = _renewed_lease(db, item)
    inspection = _exit_inspection(db, item)
    clearance = financial_clearance(
        db,
        organization_id=item.organization_id,
        lease_contract_id=item.lease_contract_id,
    )
    final_inspection_ok = inspection is not None and inspection.status == "finalized"
    can_close = (
        item.process_type == "termination"
        and item.keys_returned_at is not None
        and final_inspection_ok
        and item.fine_status != "pending"
        and clearance.blocking_count == 0
        and item.status not in {"closed", "cancelled"}
    )
    return LeaseLifecycleResponse(
        id=item.id,
        code=lifecycle_code(item),
        lease_contract_id=item.lease_contract_id,
        lease_code=lease_contract_code(lease),
        property_id=item.property_id,
        process_type=item.process_type,
        status=item.status,
        initiated_by=item.initiated_by,
        requested_at=item.requested_at,
        effective_date=item.effective_date,
        reason=item.reason,
        termination_fine_amount=money(item.termination_fine_amount),
        fine_status=item.fine_status,
        fine_title_id=item.fine_title_id,
        fine_notes=item.fine_notes,
        renewal_terms=dict(item.renewal_terms or {}),
        renewed_lease_contract_id=item.renewed_lease_contract_id,
        renewed_lease_code=lease_contract_code(renewed) if renewed else None,
        renewed_lease_status=renewed.status if renewed else None,
        exit_inspection_id=item.exit_inspection_id,
        exit_inspection_code=inspection_code(inspection) if inspection else None,
        exit_inspection_status=inspection.status if inspection else None,
        keys_returned_at=item.keys_returned_at,
        keys_received_by=item.keys_received_by,
        returned_keys=list(item.returned_keys or []),
        meter_readings=dict(item.meter_readings or {}),
        key_return_notes=item.key_return_notes,
        property_disposition=item.property_disposition,
        financial_clearance=clearance,
        can_close=can_close,
        closed_at=item.closed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _lease_version_snapshot(item: LeaseContract) -> dict:
    return {
        "property": deepcopy(item.property_snapshot or {}),
        "owners": deepcopy(item.owner_snapshot or []),
        "tenants": deepcopy(item.tenant_snapshot or []),
        "rules": deepcopy(item.rules_snapshot or {}),
        "signers": deepcopy(item.signers_snapshot or []),
    }


def prepare_renewal_lease(
    db: Session,
    *,
    case: LeaseLifecycleCase,
    lease: LeaseContract,
    user_id: UUID | None,
) -> LeaseContract:
    existing = _renewed_lease(db, case)
    if existing is not None:
        return existing
    terms = dict(case.renewal_terms or {})
    start_date = date.fromisoformat(str(terms["start_date"]))
    term_months = int(terms["term_months"])
    end_date = add_months(start_date, term_months)
    adjustment_period = int(terms.get("adjustment_period_months") or lease.adjustment_period_months)
    rules = deepcopy(lease.rules_snapshot or {})
    rules.update(
        {
            "rent_amount": str(terms["rent_amount"]),
            "adjustment_index": str(terms["adjustment_index"]),
            "adjustment_period_months": adjustment_period,
            "adjustment_base_date": start_date.isoformat(),
            "next_adjustment_date": add_months(start_date, adjustment_period).isoformat(),
            "term_months": term_months,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "notes": terms.get("notes") or lease.notes,
        }
    )
    renewed = LeaseContract(
        organization_id=lease.organization_id,
        property_id=lease.property_id,
        status="draft",
        rent_amount=money(terms["rent_amount"]),
        due_day=lease.due_day,
        adjustment_index=str(terms["adjustment_index"]),
        adjustment_period_months=adjustment_period,
        adjustment_base_date=start_date,
        next_adjustment_date=add_months(start_date, adjustment_period),
        term_months=term_months,
        start_date=start_date,
        end_date=end_date,
        termination_fine_months=lease.termination_fine_months,
        inspection_contest_days=lease.inspection_contest_days,
        guarantee_type=lease.guarantee_type,
        guarantee_details=deepcopy(lease.guarantee_details or {}),
        property_snapshot=deepcopy(lease.property_snapshot or {}),
        owner_snapshot=deepcopy(lease.owner_snapshot or []),
        tenant_snapshot=deepcopy(lease.tenant_snapshot or []),
        rules_snapshot=rules,
        signers_snapshot=deepcopy(lease.signers_snapshot or []),
        current_version=1,
        notes=str(terms.get("notes") or lease.notes or "").strip() or None,
        signing_provider=lease.signing_provider,
        signing_status="not_prepared",
        signing_metadata={},
        archive_status="not_started",
        created_by_user_id=user_id,
    )
    db.add(renewed)
    db.flush()
    db.add(
        LeaseContractVersion(
            contract_id=renewed.id,
            version_number=1,
            snapshot=_lease_version_snapshot(renewed),
            change_summary=f"Renovação originada de {lease_contract_code(lease)}",
            created_by_user_id=user_id,
        )
    )
    case.renewed_lease_contract_id = renewed.id
    case.status = "renewal_prepared"
    return renewed


def renewal_terms(payload: RenewalProposal) -> dict:
    return {
        "start_date": payload.start_date.isoformat(),
        "term_months": payload.term_months,
        "rent_amount": str(money(payload.rent_amount)),
        "adjustment_index": payload.adjustment_index,
        "adjustment_period_months": payload.adjustment_period_months,
        "notes": (payload.notes or "").strip() or None,
    }


def build_exit_environments(db: Session, lease: LeaseContract) -> list[dict]:
    initial = db.scalar(
        select(Inspection).where(
            Inspection.organization_id == lease.organization_id,
            Inspection.lease_contract_id == lease.id,
            Inspection.inspection_type == "initial",
            Inspection.status != "cancelled",
        )
    )
    if initial is None:
        return [
            {
                "key": "geral",
                "name": "Geral",
                "notes": None,
                "items": [
                    {
                        "key": "condicao-geral",
                        "label": "Condição geral do imóvel",
                        "condition": "not_applicable",
                        "notes": None,
                        "photos": [],
                    }
                ],
            }
        ]
    environments: list[dict] = []
    for env in list(initial.environments or []):
        items = []
        for entry in list(env.get("items") or []):
            items.append(
                {
                    "key": str(entry.get("key") or "item"),
                    "label": str(entry.get("label") or "Item"),
                    "condition": "not_applicable",
                    "notes": None,
                    "photos": [],
                }
            )
        environments.append(
            {
                "key": str(env.get("key") or "ambiente"),
                "name": str(env.get("name") or "Ambiente"),
                "notes": None,
                "items": items or [{"key": "condicao-geral", "label": "Condição geral", "condition": "not_applicable", "notes": None, "photos": []}],
            }
        )
    return environments


def create_exit_inspection(
    db: Session,
    *,
    case: LeaseLifecycleCase,
    lease: LeaseContract,
    scheduled_at: datetime | None,
    inspector_name: str | None,
    notes: str | None,
    user_id: UUID | None,
) -> Inspection:
    if case.exit_inspection_id:
        inspection = _exit_inspection(db, case)
        if inspection is not None:
            return inspection
    existing = db.scalar(
        select(Inspection).where(
            Inspection.organization_id == lease.organization_id,
            Inspection.lease_contract_id == lease.id,
            Inspection.inspection_type == "final",
        )
    )
    if existing is not None:
        case.exit_inspection_id = existing.id
        case.status = "exit_inspection_pending" if existing.status == "draft" else "key_return_pending"
        return existing
    lease_snapshot = {
        "lease_code": lease_contract_code(lease),
        "property": deepcopy(lease.property_snapshot or {}),
        "owners": deepcopy(lease.owner_snapshot or []),
        "tenants": deepcopy(lease.tenant_snapshot or []),
        "inspection_contest_days": lease.inspection_contest_days,
        "signed_at": lease.signed_at.isoformat() if lease.signed_at else None,
        "final_document_hash": lease.final_document_hash,
        "lifecycle_case_id": str(case.id),
        "inspection_purpose": "lease_exit",
    }
    inspection = Inspection(
        organization_id=lease.organization_id,
        lease_contract_id=lease.id,
        property_id=lease.property_id,
        inspection_type="final",
        status="draft",
        lease_snapshot=lease_snapshot,
        environments=build_exit_environments(db, lease),
        contestations=[],
        inspector_name=(inspector_name or "").strip() or None,
        scheduled_at=scheduled_at,
        notes=(notes or "").strip() or "Vistoria de saída. Compare cada item com o laudo inicial antes de concluir.",
        current_version=1,
        created_by_user_id=user_id,
    )
    db.add(inspection)
    db.flush()
    db.add(
        InspectionVersion(
            inspection_id=inspection.id,
            version_number=1,
            snapshot={
                "status": inspection.status,
                "lease": deepcopy(inspection.lease_snapshot),
                "environments": deepcopy(inspection.environments),
                "contestations": [],
                "inspector_name": inspection.inspector_name,
                "scheduled_at": inspection.scheduled_at.isoformat() if inspection.scheduled_at else None,
                "performed_at": None,
                "contest_deadline": None,
                "notes": inspection.notes,
            },
            change_summary="Vistoria de saída criada pelo encerramento da locação",
            created_by_user_id=user_id,
        )
    )
    case.exit_inspection_id = inspection.id
    case.status = "exit_inspection_pending"
    return inspection
