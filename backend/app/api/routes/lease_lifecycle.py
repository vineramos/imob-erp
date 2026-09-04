from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.core_models import FinancialTitle
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.inspections.models import Inspection
from app.domains.lease_lifecycle.models import LeaseLifecycleCase
from app.domains.lease_lifecycle.schemas import (
    CloseLeaseRequest,
    ExitInspectionCreate,
    FineResolution,
    KeyReturnCreate,
    LeaseLifecycleResponse,
    RenewalProposal,
    TerminationRequest,
)
from app.domains.lease_lifecycle.service import (
    calculate_proportional_fine,
    create_exit_inspection,
    lifecycle_code,
    load_case,
    load_lease,
    money,
    prepare_renewal_lease,
    renewal_terms,
    require_case,
    response,
)
from app.domains.leases.pdf import lease_contract_code
from app.domains.portfolio.models import Property

router = APIRouter(tags=["lease-lifecycle"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    item: LeaseLifecycleCase,
    action: str,
    *,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="contracts",
        entity_type="lease_lifecycle_case",
        entity_id=str(item.id),
        before_data=before,
        after_data=after,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _ensure_signed(lease) -> None:
    if lease.status != "signed" or lease.archive_status != "archived" or not lease.final_document_hash:
        raise HTTPException(status_code=409, detail="O ciclo final só pode ser iniciado em uma locação assinada e arquivada.")


def _reset_case(item: LeaseLifecycleCase) -> None:
    item.initiated_by = None
    item.effective_date = None
    item.reason = None
    item.termination_fine_amount = money(0)
    item.fine_status = "not_applicable"
    item.fine_title_id = None
    item.fine_notes = None
    item.renewal_terms = {}
    item.renewed_lease_contract_id = None
    item.exit_inspection_id = None
    item.keys_returned_at = None
    item.keys_received_by = None
    item.keys_received_document = None
    item.returned_keys = []
    item.meter_readings = {}
    item.key_return_notes = None
    item.property_disposition = None
    item.financial_snapshot = {}
    item.closed_at = None
    item.closed_by_user_id = None


@router.get("/lease-contracts/{lease_contract_id}/lifecycle", response_model=LeaseLifecycleResponse | None)
def get_lifecycle(
    lease_contract_id: UUID,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse | None:
    load_lease(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    item = load_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    return response(db, item) if item else None


@router.post("/lease-contracts/{lease_contract_id}/lifecycle/renewal", response_model=LeaseLifecycleResponse)
def propose_renewal(
    lease_contract_id: UUID,
    payload: RenewalProposal,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse:
    lease = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    _ensure_signed(lease)
    if payload.start_date < lease.end_date:
        raise HTTPException(status_code=422, detail="A renovação não pode começar antes do término da locação atual.")
    item = load_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    if item and item.status not in {"cancelled", "renewal_proposed"}:
        raise HTTPException(status_code=409, detail="Já existe um ciclo final em andamento para esta locação.")
    if item is None:
        item = LeaseLifecycleCase(
            organization_id=context.user.organization_id,
            lease_contract_id=lease.id,
            property_id=lease.property_id,
            process_type="renewal",
            status="renewal_proposed",
            created_by_user_id=context.user.id,
        )
        db.add(item)
        db.flush()
    elif item.status == "cancelled":
        _reset_case(item)
    item.process_type = "renewal"
    item.status = "renewal_proposed"
    item.requested_at = datetime.now(timezone.utc)
    item.renewal_terms = renewal_terms(payload)
    item.reason = (payload.notes or "").strip() or None
    _audit(
        db, request, context, item, "contracts.lease.renewal_proposed",
        after={"lease": lease_contract_code(lease), "renewal_terms": item.renewal_terms},
        reason=item.reason,
    )
    db.commit()
    return response(db, item)


@router.post("/lease-contracts/{lease_contract_id}/lifecycle/renewal/prepare", response_model=LeaseLifecycleResponse)
def prepare_renewal(
    lease_contract_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse:
    lease = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    item = require_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    if item.process_type != "renewal" or item.status not in {"renewal_proposed", "renewal_prepared"}:
        raise HTTPException(status_code=409, detail="A renovação não está pronta para gerar uma nova minuta.")
    renewed = prepare_renewal_lease(db, case=item, lease=lease, user_id=context.user.id)
    _audit(
        db, request, context, item, "contracts.lease.renewal_prepared",
        after={"renewed_lease_contract_id": str(renewed.id), "renewed_lease_code": lease_contract_code(renewed)},
    )
    db.commit()
    return response(db, item)


@router.post("/lease-contracts/{lease_contract_id}/lifecycle/renewal/complete", response_model=LeaseLifecycleResponse)
def complete_renewal(
    lease_contract_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse:
    lease = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    item = require_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    if item.process_type != "renewal" or item.status != "renewal_prepared" or item.renewed_lease_contract_id is None:
        raise HTTPException(status_code=409, detail="Prepare a nova minuta de renovação antes de concluir.")
    renewed = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=item.renewed_lease_contract_id)
    if renewed.status != "signed" or renewed.archive_status != "archived" or not renewed.final_document_hash:
        raise HTTPException(status_code=409, detail="A nova locação precisa estar assinada e arquivada antes de concluir a renovação.")
    now = datetime.now(timezone.utc)
    lease.status = "closed"
    lease.closed_at = now
    lease.operational_end_date = lease.end_date
    item.status = "renewed"
    item.closed_at = now
    item.closed_by_user_id = context.user.id
    item.property_disposition = "available" if False else None
    property_item = db.get(Property, lease.property_id)
    if property_item is not None:
        property_item.status = "leased"
        property_item.publication_enabled = False
        property_item.publication_updated_by_user_id = context.user.id
    _audit(
        db, request, context, item, "contracts.lease.renewal_completed",
        after={"old_lease_status": lease.status, "renewed_lease": lease_contract_code(renewed), "renewed_status": renewed.status},
    )
    db.commit()
    return response(db, item)


@router.post("/lease-contracts/{lease_contract_id}/lifecycle/termination", response_model=LeaseLifecycleResponse)
def request_termination(
    lease_contract_id: UUID,
    payload: TerminationRequest,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse:
    lease = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    _ensure_signed(lease)
    if payload.effective_date < lease.start_date:
        raise HTTPException(status_code=422, detail="A data efetiva não pode ser anterior ao início da locação.")
    item = load_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    if item and item.status not in {"cancelled", "termination_requested"}:
        raise HTTPException(status_code=409, detail="Já existe um ciclo final em andamento para esta locação.")
    if item is None:
        item = LeaseLifecycleCase(
            organization_id=context.user.organization_id,
            lease_contract_id=lease.id,
            property_id=lease.property_id,
            process_type="termination",
            status="termination_requested",
            created_by_user_id=context.user.id,
        )
        db.add(item)
        db.flush()
    elif item.status == "cancelled":
        _reset_case(item)
    fine = calculate_proportional_fine(lease, payload.effective_date)
    item.process_type = "termination"
    item.status = "termination_requested"
    item.initiated_by = payload.initiated_by
    item.requested_at = datetime.now(timezone.utc)
    item.effective_date = payload.effective_date
    item.reason = payload.reason.strip()
    item.termination_fine_amount = fine
    item.fine_status = "pending" if fine > 0 else "not_applicable"
    lease.operational_end_date = payload.effective_date
    _audit(
        db, request, context, item, "contracts.lease.termination_requested",
        after={"effective_date": payload.effective_date.isoformat(), "initiated_by": payload.initiated_by, "fine": str(fine)},
        reason=item.reason,
    )
    db.commit()
    return response(db, item)


@router.post("/lease-contracts/{lease_contract_id}/lifecycle/exit-inspection", response_model=LeaseLifecycleResponse)
def open_exit_inspection(
    lease_contract_id: UUID,
    payload: ExitInspectionCreate,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse:
    lease = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    item = require_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    if item.process_type != "termination" or item.status in {"cancelled", "closed"}:
        raise HTTPException(status_code=409, detail="A vistoria de saída exige uma desocupação em andamento.")
    inspection = create_exit_inspection(
        db,
        case=item,
        lease=lease,
        scheduled_at=payload.scheduled_at,
        inspector_name=payload.inspector_name,
        notes=payload.notes,
        user_id=context.user.id,
    )
    _audit(
        db, request, context, item, "contracts.lease.exit_inspection_created",
        after={"inspection_id": str(inspection.id), "inspection_status": inspection.status},
    )
    db.commit()
    return response(db, item)


@router.post("/lease-contracts/{lease_contract_id}/lifecycle/keys-return", response_model=LeaseLifecycleResponse)
def return_keys(
    lease_contract_id: UUID,
    payload: KeyReturnCreate,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse:
    item = require_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    if item.process_type != "termination" or item.exit_inspection_id is None:
        raise HTTPException(status_code=409, detail="Crie e conclua a vistoria de saída antes da devolução das chaves.")
    if item.keys_returned_at is not None:
        raise HTTPException(status_code=409, detail="A devolução das chaves já foi registrada.")
    inspection = db.get(Inspection, item.exit_inspection_id)
    if inspection is None or inspection.organization_id != context.user.organization_id:
        raise HTTPException(status_code=404, detail="Vistoria de saída não encontrada.")
    if inspection.status not in {"ready", "finalized"}:
        raise HTTPException(status_code=409, detail="Conclua o laudo da vistoria de saída antes de receber as chaves.")
    now = datetime.now(timezone.utc)
    if inspection.status == "ready":
        inspection.status = "finalized"
        inspection.finalized_at = now
        inspection.finalized_by_user_id = context.user.id
    item.keys_returned_at = payload.returned_at
    item.keys_received_by = payload.received_by.strip()
    item.keys_received_document = (payload.received_document or "").strip() or None
    item.returned_keys = [entry.model_dump(mode="json") for entry in payload.keys]
    item.meter_readings = dict(payload.meter_readings or {})
    item.key_return_notes = (payload.notes or "").strip() or None
    item.status = "financial_clearance_pending"
    _audit(
        db, request, context, item, "contracts.lease.keys_returned",
        after={"returned_at": payload.returned_at.isoformat(), "received_by": item.keys_received_by, "inspection_status": inspection.status},
    )
    db.commit()
    return response(db, item)


@router.post("/lease-contracts/{lease_contract_id}/lifecycle/fine", response_model=LeaseLifecycleResponse)
def resolve_fine(
    lease_contract_id: UUID,
    payload: FineResolution,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse:
    lease = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    item = require_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    if item.process_type != "termination" or item.status in {"cancelled", "closed"}:
        raise HTTPException(status_code=409, detail="Não há multa de desocupação ativa para tratar.")
    if item.fine_status == "registered":
        raise HTTPException(status_code=409, detail="A multa já foi registrada no Financeiro. Trate o título financeiro antes de alterar esta decisão.")
    if payload.action == "waive":
        item.fine_status = "waived"
        item.fine_notes = (payload.notes or "").strip() or "Multa dispensada no processo de desocupação."
    else:
        amount = money(payload.amount if payload.amount is not None else item.termination_fine_amount)
        if amount <= 0:
            raise HTTPException(status_code=422, detail="O valor da multa precisa ser maior que zero para gerar o título.")
        tenants = " / ".join(str(entry.get("name") or "").strip() for entry in list(lease.tenant_snapshot or []) if entry.get("name")) or "Locatário"
        due_date = payload.due_date or item.effective_date
        if due_date is None:
            raise HTTPException(status_code=422, detail="Informe o vencimento da multa.")
        title = FinancialTitle(
            organization_id=context.user.organization_id,
            direction="receivable",
            fund_scope="third_party" if payload.beneficiary == "owner" else "operating",
            source_type="manual",
            source_id=item.id,
            property_id=lease.property_id,
            lease_contract_id=lease.id,
            category="Multa rescisória",
            description=f"Multa rescisória · {lease_contract_code(lease)}",
            counterparty_name=tenants,
            competence=due_date.replace(day=1),
            due_date=due_date,
            amount=amount,
            settled_amount=money(0),
            status="pending",
            notes=(payload.notes or "").strip() or None,
            source_snapshot={
                "origin": "lease_termination_fine",
                "lifecycle_case_id": str(item.id),
                "beneficiary": payload.beneficiary,
                "calculated_amount": str(money(item.termination_fine_amount)),
            },
            created_by_user_id=context.user.id,
        )
        db.add(title)
        db.flush()
        item.fine_title_id = title.id
        item.termination_fine_amount = amount
        item.fine_status = "registered"
        item.fine_notes = (payload.notes or "").strip() or None
    _audit(
        db, request, context, item, "contracts.lease.termination_fine_resolved",
        after={"fine_status": item.fine_status, "fine_amount": str(item.termination_fine_amount), "fine_title_id": str(item.fine_title_id) if item.fine_title_id else None},
        reason=item.fine_notes,
    )
    db.commit()
    return response(db, item)


@router.post("/lease-contracts/{lease_contract_id}/lifecycle/close", response_model=LeaseLifecycleResponse)
def close_lease(
    lease_contract_id: UUID,
    payload: CloseLeaseRequest,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse:
    lease = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    item = require_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    current = response(db, item)
    if not current.can_close:
        reasons: list[str] = []
        if item.exit_inspection_id is None or current.exit_inspection_status != "finalized": reasons.append("vistoria de saída finalizada")
        if item.keys_returned_at is None: reasons.append("devolução de chaves")
        if item.fine_status == "pending": reasons.append("decisão sobre a multa rescisória")
        if current.financial_clearance.blocking_count: reasons.append(f"{current.financial_clearance.blocking_count} pendência(s) financeira(s) do locatário")
        raise HTTPException(status_code=409, detail="Não é possível encerrar ainda. Falta: " + ", ".join(reasons) + ".")
    now = datetime.now(timezone.utc)
    property_item = db.get(Property, lease.property_id)
    if property_item is None or property_item.organization_id != context.user.organization_id:
        raise HTTPException(status_code=404, detail="Imóvel da locação não encontrado.")
    lease.status = "closed"
    lease.closed_at = now
    item.status = "closed"
    item.property_disposition = payload.property_disposition
    item.closed_at = now
    item.closed_by_user_id = context.user.id
    item.reason = (item.reason or "") + (("\nEncerramento: " + payload.notes.strip()) if payload.notes and payload.notes.strip() else "")
    item.financial_snapshot = current.financial_clearance.model_dump(mode="json")
    property_item.status = "available" if payload.property_disposition == "available" else "inactive"
    property_item.publication_enabled = False
    property_item.publication_updated_by_user_id = context.user.id
    _audit(
        db, request, context, item, "contracts.lease.closed",
        before={"lease_status": "signed", "property_status": "leased"},
        after={"lease_status": lease.status, "property_status": property_item.status, "property_disposition": payload.property_disposition},
        reason=(payload.notes or "").strip() or None,
    )
    db.commit()
    return response(db, item)


@router.post("/lease-contracts/{lease_contract_id}/lifecycle/cancel", response_model=LeaseLifecycleResponse)
def cancel_lifecycle(
    lease_contract_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseLifecycleResponse:
    lease = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    item = require_case(db, organization_id=context.user.organization_id, lease_contract_id=lease_contract_id)
    if item.status in {"closed", "renewed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Este ciclo não pode mais ser cancelado.")
    if item.keys_returned_at is not None:
        raise HTTPException(status_code=409, detail="Não cancele o processo depois da devolução das chaves; conclua o acerto final.")
    if item.renewed_lease_contract_id:
        renewed = load_lease(db, organization_id=context.user.organization_id, lease_contract_id=item.renewed_lease_contract_id)
        if renewed.status == "signed":
            raise HTTPException(status_code=409, detail="A nova locação já está assinada e a renovação não pode ser descartada.")
        if renewed.status != "cancelled":
            renewed.status = "cancelled"
    if item.exit_inspection_id:
        inspection = db.get(Inspection, item.exit_inspection_id)
        if inspection is not None and inspection.status not in {"finalized", "cancelled"}:
            inspection.status = "cancelled"
    if item.process_type == "termination":
        lease.operational_end_date = None
    item.status = "cancelled"
    _audit(db, request, context, item, "contracts.lease.lifecycle_cancelled", after={"status": item.status})
    db.commit()
    return response(db, item)
