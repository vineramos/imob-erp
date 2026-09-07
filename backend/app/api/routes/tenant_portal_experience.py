from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.documents import _content_response
from app.api.routes.tenant_portal import PortalIdentity, _tenant_leases, require_portal_identity
from app.core.database import get_db
from app.domains.communications.models import CommunicationMessage
from app.domains.finance.models import RentCharge
from app.domains.finance.tenant_receipt_pdf import build_tenant_receipt_pdf
from app.domains.foundation.models import Organization
from app.domains.lease_lifecycle.models import LeaseLifecycleCase
from app.domains.lease_lifecycle.service import calculate_proportional_fine, financial_clearance, lifecycle_code, money
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Property

router = APIRouter(prefix="/tenant-portal", tags=["tenant-portal"])
ZERO = Decimal("0.00")


class TenantTerminationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_contract_id: UUID
    effective_date: date
    reason: str = Field(min_length=3, max_length=3000)


def _tenant_lease(db: Session, identity: PortalIdentity, lease_contract_id: UUID) -> LeaseContract:
    lease = next((item for item in _tenant_leases(db, identity) if item.id == lease_contract_id), None)
    if lease is None:
        raise HTTPException(status_code=404, detail="Contrato de locação não encontrado neste portal.")
    return lease


def _case_payload(db: Session, item: LeaseLifecycleCase) -> dict:
    clearance = financial_clearance(
        db,
        organization_id=item.organization_id,
        lease_contract_id=item.lease_contract_id,
    )
    # O portal do inquilino só precisa conhecer pendências a receber que bloqueiam
    # seu encerramento. Repasses ao proprietário e contas internas permanecem privados.
    return {
        "id": str(item.id),
        "code": lifecycle_code(item),
        "lease_contract_id": str(item.lease_contract_id),
        "process_type": item.process_type,
        "status": item.status,
        "initiated_by": item.initiated_by,
        "requested_at": item.requested_at,
        "effective_date": item.effective_date,
        "reason": item.reason,
        "termination_fine_amount": float(money(item.termination_fine_amount)),
        "fine_status": item.fine_status,
        "exit_inspection_id": str(item.exit_inspection_id) if item.exit_inspection_id else None,
        "keys_returned_at": item.keys_returned_at,
        "financial_pending_count": clearance.blocking_count,
        "financial_pending_amount": float(clearance.blocking_amount),
        "can_close": bool(
            item.process_type == "termination"
            and item.keys_returned_at is not None
            and item.fine_status != "pending"
            and clearance.blocking_count == 0
            and item.status not in {"closed", "cancelled"}
        ),
        "closed_at": item.closed_at,
        "updated_at": item.updated_at,
    }


def _reset_cancelled_termination(item: LeaseLifecycleCase) -> None:
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


def _receipt_charge(db: Session, identity: PortalIdentity, charge_id: UUID) -> tuple[RentCharge, LeaseContract, Property | None]:
    charge = db.scalar(
        select(RentCharge).where(
            RentCharge.id == charge_id,
            RentCharge.organization_id == identity.account.organization_id,
        )
    )
    if charge is None:
        raise HTTPException(status_code=404, detail="Cobrança não encontrada neste portal.")
    lease = next((item for item in _tenant_leases(db, identity) if item.id == charge.lease_contract_id), None)
    if lease is None:
        raise HTTPException(status_code=404, detail="Cobrança não encontrada neste portal.")
    prop = db.scalar(
        select(Property).where(
            Property.id == charge.property_id,
            Property.organization_id == identity.account.organization_id,
        )
    )
    return charge, lease, prop


@router.get("/experience")
def tenant_experience(
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> dict:
    leases = _tenant_leases(db, identity)
    lease_ids = [item.id for item in leases]
    cases = db.scalars(
        select(LeaseLifecycleCase).where(
            LeaseLifecycleCase.organization_id == identity.account.organization_id,
            LeaseLifecycleCase.lease_contract_id.in_(lease_ids),
        )
    ).all() if lease_ids else []
    messages = db.scalars(
        select(CommunicationMessage)
        .where(
            CommunicationMessage.organization_id == identity.account.organization_id,
            CommunicationMessage.person_id == identity.person.id,
            CommunicationMessage.recipient_role == "tenant",
            CommunicationMessage.status == "sent",
        )
        .order_by(CommunicationMessage.sent_at.desc(), CommunicationMessage.created_at.desc())
        .limit(100)
    ).all()
    return {
        "lifecycle": [_case_payload(db, item) for item in cases],
        "communications": [
            {
                "id": str(item.id),
                "code": f"COM-{item.internal_number:06d}",
                "channel": item.channel,
                "category": item.category,
                "subject": item.subject,
                "body": item.body,
                "source_module": item.source_module,
                "sent_at": item.sent_at,
            }
            for item in messages
        ],
    }


@router.post("/termination", status_code=status.HTTP_201_CREATED)
def request_tenant_termination(
    payload: TenantTerminationRequest,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> dict:
    lease = _tenant_lease(db, identity, payload.lease_contract_id)
    if lease.status != "signed" or lease.archive_status != "archived" or not lease.final_document_hash:
        raise HTTPException(status_code=409, detail="A desocupação só pode ser solicitada para uma locação ativa e assinada.")
    if payload.effective_date < date.today():
        raise HTTPException(status_code=422, detail="A data prevista de desocupação não pode estar no passado.")
    if payload.effective_date < lease.start_date:
        raise HTTPException(status_code=422, detail="A data prevista não pode ser anterior ao início da locação.")

    item = db.scalar(
        select(LeaseLifecycleCase).where(
            LeaseLifecycleCase.organization_id == identity.account.organization_id,
            LeaseLifecycleCase.lease_contract_id == lease.id,
        )
    )
    if item is not None and item.status not in {"cancelled", "termination_requested"}:
        raise HTTPException(status_code=409, detail="Já existe um processo de renovação ou encerramento em andamento para esta locação.")
    if item is None:
        item = LeaseLifecycleCase(
            organization_id=identity.account.organization_id,
            lease_contract_id=lease.id,
            property_id=lease.property_id,
            process_type="termination",
            status="termination_requested",
            initiated_by="tenant",
            created_by_user_id=None,
        )
        db.add(item)
        db.flush()
    elif item.status == "cancelled":
        _reset_cancelled_termination(item)

    now = datetime.now(timezone.utc)
    fine = calculate_proportional_fine(lease, payload.effective_date)
    item.process_type = "termination"
    item.status = "termination_requested"
    item.initiated_by = "tenant"
    item.requested_at = now
    item.effective_date = payload.effective_date
    item.reason = payload.reason.strip()
    item.termination_fine_amount = fine
    item.fine_status = "pending" if fine > ZERO else "not_applicable"
    lease.operational_end_date = payload.effective_date
    db.commit()
    db.refresh(item)
    return _case_payload(db, item)


@router.get("/charges/{charge_id}/receipt.pdf")
def tenant_charge_receipt(
    charge_id: UUID,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> Response:
    charge, lease, prop = _receipt_charge(db, identity, charge_id)
    if charge.status != "paid" or charge.paid_at is None or charge.paid_amount is None:
        raise HTTPException(status_code=409, detail="O recibo fica disponível somente depois da liquidação integral da cobrança.")
    organization = db.get(Organization, identity.account.organization_id)
    content = build_tenant_receipt_pdf(
        organization_name=organization.display_name if organization else "Imobiliária",
        tenant_name=identity.person.name,
        lease_code=f"LOC-{lease.internal_number:06d}",
        property_code=f"IMO-{prop.internal_number:06d}" if prop else str((charge.property_snapshot or {}).get("code") or "—"),
        property_address=dict(prop.address or {}) if prop else dict((charge.property_snapshot or {}).get("address") or {}),
        charge_code=f"COB-{charge.internal_number:06d}",
        competence=charge.competence,
        due_date=charge.due_date,
        paid_at=charge.paid_at,
        paid_amount=charge.paid_amount,
        payment_method=charge.payment_method,
        payment_reference=charge.payment_reference,
        charge_items=list(charge.charge_items or []),
    )
    return _content_response(
        content,
        content_type="application/pdf",
        filename=f"{charge.internal_number:06d}-recibo.pdf",
    )
