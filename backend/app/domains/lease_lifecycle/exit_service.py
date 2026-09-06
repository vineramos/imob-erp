from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.finance.core_models import FinancialTitle
from app.domains.inspections.models import Inspection
from app.domains.inspections.pdf import inspection_code
from app.domains.lease_lifecycle.exit_schemas import (
    InspectionDifference,
    LeaseExitAdjustmentCreate,
    LeaseExitAdjustmentResponse,
    LeaseExitWorkspaceResponse,
)
from app.domains.lease_lifecycle.models import LeaseExitAdjustment, LeaseLifecycleCase
from app.domains.lease_lifecycle.service import financial_clearance, lifecycle_code, load_lease, response as lifecycle_response
from app.domains.leases.models import LeaseContract
from app.domains.leases.pdf import lease_contract_code
from app.domains.portfolio.models import Property

CENT = Decimal("0.01")
CLOSED_TITLE_STATUSES = {"paid", "settled", "settled_zero", "cancelled"}
CONDITION_RANK = {
    "excellent": 5,
    "good": 4,
    "regular": 3,
    "poor": 2,
    "damaged": 1,
}


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _initial_inspection(db: Session, lease: LeaseContract) -> Inspection | None:
    return db.scalar(
        select(Inspection)
        .where(
            Inspection.organization_id == lease.organization_id,
            Inspection.lease_contract_id == lease.id,
            Inspection.inspection_type == "initial",
            Inspection.status != "cancelled",
        )
        .order_by(Inspection.created_at.asc())
    )


def _exit_inspection(db: Session, case: LeaseLifecycleCase) -> Inspection | None:
    if case.exit_inspection_id is None:
        return None
    return db.scalar(
        select(Inspection).where(
            Inspection.id == case.exit_inspection_id,
            Inspection.organization_id == case.organization_id,
        )
    )


def _item_index(inspection: Inspection | None) -> dict[tuple[str, str], tuple[str, dict]]:
    result: dict[tuple[str, str], tuple[str, dict]] = {}
    if inspection is None:
        return result
    for environment in list(inspection.environments or []):
        env_key = str(environment.get("key") or "")
        env_name = str(environment.get("name") or env_key or "Ambiente")
        for item in list(environment.get("items") or []):
            item_key = str(item.get("key") or "")
            if env_key and item_key:
                result[(env_key, item_key)] = (env_name, dict(item))
    return result


def inspection_differences(db: Session, *, lease: LeaseContract, case: LeaseLifecycleCase) -> list[InspectionDifference]:
    initial = _item_index(_initial_inspection(db, lease))
    final = _item_index(_exit_inspection(db, case))
    differences: list[InspectionDifference] = []
    for key, (environment_name, initial_item) in initial.items():
        final_row = final.get(key)
        if final_row is None:
            continue
        final_environment_name, final_item = final_row
        initial_condition = str(initial_item.get("condition") or "not_applicable")
        final_condition = str(final_item.get("condition") or "not_applicable")
        initial_rank = CONDITION_RANK.get(initial_condition)
        final_rank = CONDITION_RANK.get(final_condition)
        if initial_rank is None or final_rank is None or final_rank >= initial_rank:
            continue
        differences.append(
            InspectionDifference(
                environment_key=key[0],
                environment_name=final_environment_name or environment_name,
                item_key=key[1],
                item_label=str(final_item.get("label") or initial_item.get("label") or key[1]),
                initial_condition=initial_condition,
                final_condition=final_condition,
                severity_delta=initial_rank - final_rank,
                initial_notes=(str(initial_item.get("notes")).strip() if initial_item.get("notes") else None),
                final_notes=(str(final_item.get("notes")).strip() if final_item.get("notes") else None),
            )
        )
    differences.sort(key=lambda item: (-item.severity_delta, item.environment_name.lower(), item.item_label.lower()))
    return differences


def _title_remaining(title: FinancialTitle | None, fallback_amount: Decimal) -> tuple[Decimal, Decimal, str | None]:
    if title is None:
        return Decimal("0.00"), fallback_amount, None
    settled = money(title.settled_amount)
    if title.status in CLOSED_TITLE_STATUSES:
        return settled, Decimal("0.00"), title.status
    return settled, money(max(Decimal("0.00"), money(title.amount) - settled)), title.status


def adjustment_response(db: Session, item: LeaseExitAdjustment) -> LeaseExitAdjustmentResponse:
    title = db.get(FinancialTitle, item.financial_title_id) if item.financial_title_id else None
    settled, remaining, financial_status = _title_remaining(title, money(item.amount))
    return LeaseExitAdjustmentResponse(
        id=item.id,
        code=f"AJU-{item.internal_number:06d}",
        kind=item.kind,
        description=item.description,
        beneficiary=item.beneficiary,
        amount=money(item.amount),
        due_date=item.due_date,
        status=item.status,
        financial_title_id=item.financial_title_id,
        financial_title_code=f"FIN-{title.internal_number:06d}" if title else None,
        financial_status=financial_status,
        settled_amount=settled,
        remaining_amount=remaining,
        source_context=dict(item.source_context or {}),
        notes=item.notes,
        cancelled_at=item.cancelled_at,
        created_at=item.created_at,
    )


def exit_workspace(db: Session, case: LeaseLifecycleCase) -> LeaseExitWorkspaceResponse:
    lease = load_lease(db, organization_id=case.organization_id, lease_contract_id=case.lease_contract_id)
    prop = db.scalar(select(Property).where(Property.id == lease.property_id, Property.organization_id == case.organization_id))
    final = _exit_inspection(db, case)
    clearance = financial_clearance(db, organization_id=case.organization_id, lease_contract_id=lease.id)
    lifecycle = lifecycle_response(db, case)
    adjustments = db.scalars(
        select(LeaseExitAdjustment)
        .where(
            LeaseExitAdjustment.organization_id == case.organization_id,
            LeaseExitAdjustment.lifecycle_case_id == case.id,
        )
        .order_by(LeaseExitAdjustment.internal_number.asc())
    ).all()
    adjustment_rows = [adjustment_response(db, item) for item in adjustments]
    prop_snapshot = dict(lease.property_snapshot or {})
    property_code = str(prop_snapshot.get("code") or (f"{prop.internal_number:06d}" if prop else "—"))
    property_address = dict(prop.address or {}) if prop is not None else dict(prop_snapshot.get("address") or {})
    return LeaseExitWorkspaceResponse(
        lifecycle_case_id=case.id,
        lifecycle_code=lifecycle_code(case),
        lease_contract_id=lease.id,
        lease_code=lease_contract_code(lease),
        lifecycle_status=case.status,
        effective_date=case.effective_date,
        initiated_by=case.initiated_by,
        property_id=lease.property_id,
        property_code=property_code,
        property_address=property_address,
        tenants=list(lease.tenant_snapshot or []),
        exit_inspection_id=case.exit_inspection_id,
        exit_inspection_code=inspection_code(final) if final else None,
        exit_inspection_status=final.status if final else None,
        inspection_ready_for_adjustments=bool(final and final.status in {"ready", "finalized"}),
        inspection_differences=inspection_differences(db, lease=lease, case=case),
        keys_returned_at=case.keys_returned_at,
        returned_keys=list(case.returned_keys or []),
        meter_readings=dict(case.meter_readings or {}),
        adjustments=adjustment_rows,
        adjustment_open_amount=money(sum((row.remaining_amount for row in adjustment_rows), Decimal("0.00"))),
        financial_blocking_count=clearance.blocking_count,
        financial_blocking_amount=money(clearance.blocking_amount),
        financial_followup_count=clearance.followup_count,
        financial_followup_amount=money(clearance.followup_amount),
        can_close=lifecycle.can_close,
        closed_at=case.closed_at,
    )


def list_exit_workspaces(db: Session, *, organization_id: UUID) -> list[LeaseExitWorkspaceResponse]:
    cases = db.scalars(
        select(LeaseLifecycleCase)
        .where(
            LeaseLifecycleCase.organization_id == organization_id,
            LeaseLifecycleCase.process_type == "termination",
        )
        .order_by(LeaseLifecycleCase.requested_at.desc())
        .limit(200)
    ).all()
    return [exit_workspace(db, item) for item in cases]


def require_active_termination(db: Session, *, organization_id: UUID, lease_contract_id: UUID) -> tuple[LeaseLifecycleCase, LeaseContract]:
    case = db.scalar(
        select(LeaseLifecycleCase).where(
            LeaseLifecycleCase.organization_id == organization_id,
            LeaseLifecycleCase.lease_contract_id == lease_contract_id,
        )
    )
    if case is None or case.process_type != "termination":
        raise HTTPException(status_code=404, detail="Esta locação não possui desocupação em andamento.")
    if case.status in {"closed", "cancelled"}:
        raise HTTPException(status_code=409, detail="O acerto final não pode ser alterado depois do encerramento ou cancelamento.")
    lease = load_lease(db, organization_id=organization_id, lease_contract_id=lease_contract_id)
    return case, lease


def create_adjustment(
    db: Session,
    *,
    organization_id: UUID,
    lease_contract_id: UUID,
    payload: LeaseExitAdjustmentCreate,
    user_id: UUID | None,
) -> LeaseExitAdjustment:
    case, lease = require_active_termination(db, organization_id=organization_id, lease_contract_id=lease_contract_id)
    final = _exit_inspection(db, case)
    if final is None or final.status not in {"ready", "finalized"}:
        raise HTTPException(status_code=409, detail="Conclua o laudo da vistoria de saída antes de registrar ajustes do acerto final.")

    item = LeaseExitAdjustment(
        organization_id=organization_id,
        lifecycle_case_id=case.id,
        lease_contract_id=lease.id,
        property_id=lease.property_id,
        kind=payload.kind,
        description=payload.description.strip(),
        beneficiary=payload.beneficiary,
        amount=money(payload.amount),
        due_date=payload.due_date,
        status="registered",
        source_context=dict(payload.source_context or {}),
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=user_id,
    )
    db.add(item)
    db.flush()

    tenants = " / ".join(
        str(entry.get("name") or "").strip()
        for entry in list(lease.tenant_snapshot or [])
        if isinstance(entry, dict) and entry.get("name")
    ) or "Locatário"
    fund_scope = "operating" if payload.beneficiary == "agency" else "third_party"
    title = FinancialTitle(
        organization_id=organization_id,
        direction="receivable",
        fund_scope=fund_scope,
        source_type="lease_exit_adjustment",
        source_id=item.id,
        property_id=lease.property_id,
        lease_contract_id=lease.id,
        category="Acerto final da locação",
        description=item.description,
        counterparty_name=tenants,
        competence=payload.due_date.replace(day=1),
        due_date=payload.due_date,
        amount=money(payload.amount),
        settled_amount=money(0),
        status="pending",
        notes=item.notes,
        source_snapshot={
            "origin": "lease_exit_adjustment",
            "lifecycle_case_id": str(case.id),
            "adjustment_id": str(item.id),
            "adjustment_kind": payload.kind,
            "beneficiary": payload.beneficiary,
            "source_context": dict(payload.source_context or {}),
        },
        created_by_user_id=user_id,
    )
    db.add(title)
    db.flush()
    item.financial_title_id = title.id
    return item


def cancel_adjustment(
    db: Session,
    *,
    organization_id: UUID,
    lease_contract_id: UUID,
    adjustment_id: UUID,
    user_id: UUID | None,
) -> LeaseExitAdjustment:
    case, _ = require_active_termination(db, organization_id=organization_id, lease_contract_id=lease_contract_id)
    item = db.scalar(
        select(LeaseExitAdjustment).where(
            LeaseExitAdjustment.id == adjustment_id,
            LeaseExitAdjustment.organization_id == organization_id,
            LeaseExitAdjustment.lifecycle_case_id == case.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Ajuste do acerto final não encontrado.")
    if item.status == "cancelled":
        return item
    title = db.get(FinancialTitle, item.financial_title_id) if item.financial_title_id else None
    if title is not None and (money(title.settled_amount) > 0 or title.status in {"paid", "settled", "settled_zero"}):
        raise HTTPException(status_code=409, detail="Este ajuste já possui liquidação financeira e não pode ser cancelado por aqui.")
    if title is not None:
        title.status = "cancelled"
    item.status = "cancelled"
    item.cancelled_at = datetime.now(timezone.utc)
    item.cancelled_by_user_id = user_id
    return item
