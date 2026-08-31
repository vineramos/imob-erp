from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.advanced_models import DelinquencyCase
from app.domains.finance.advanced_schemas import DelinquencyActionRequest, DelinquencyCaseResponse
from app.domains.finance.advanced_service import money, refresh_delinquency_cases
from app.domains.finance.models import RentCharge
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.leases.models import LeaseContract

router = APIRouter(prefix="/delinquency")


def _audit(db: Session, request: Request, context: UserContext, action: str, entity_id: str | None, after: dict | None = None) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(db, context=context, action=action, module="finance", entity_type="delinquency_case", entity_id=entity_id, after_data=after, ip_address=forwarded or (request.client.host if request.client else None), user_agent=request.headers.get("user-agent"))


def _property_code(charge: RentCharge) -> str:
    return str((charge.property_snapshot or {}).get("code") or "—")


def _tenant_name(charge: RentCharge) -> str:
    return next((str(item.get("name")) for item in list(charge.tenant_snapshot or []) if isinstance(item, dict) and item.get("name")), "Locatário")


def _response(db: Session, item: DelinquencyCase) -> DelinquencyCaseResponse:
    charge = db.get(RentCharge, item.charge_id)
    if charge is None:
        raise HTTPException(status_code=409, detail="Cobrança da inadimplência não foi encontrada.")
    lease = db.get(LeaseContract, item.lease_contract_id)
    days = max(0, (date.today() - charge.due_date).days) if charge.status == "overdue" else 0
    return DelinquencyCaseResponse(
        id=item.id, code=f"INA-{item.internal_number:05d}", charge_id=charge.id, charge_code=f"COB-{charge.internal_number:06d}",
        lease_contract_id=item.lease_contract_id, lease_code=f"LOC-{lease.internal_number:06d}" if lease else "LOC-—",
        property_id=item.property_id, property_code=_property_code(charge), tenant_name=_tenant_name(charge), due_date=charge.due_date,
        amount=float(money(charge.gross_amount)), days_overdue=days, critical=days >= item.critical_after_days and item.status != "resolved",
        status=item.status, insurer_protocol=item.insurer_protocol, opened_at=item.opened_at, critical_at=item.critical_at,
        last_contact_at=item.last_contact_at, next_action_at=item.next_action_at, insurer_triggered_at=item.insurer_triggered_at,
        resolved_at=item.resolved_at, notes=item.notes, action_log=list(item.action_log or []),
    )


@router.post("/refresh", response_model=list[DelinquencyCaseResponse])
def refresh_cases(request: Request, context: UserContext = Depends(require_permission("finance.view")), db: Session = Depends(get_db)) -> list[DelinquencyCaseResponse]:
    items = refresh_delinquency_cases(db, organization_id=context.user.organization_id)
    _audit(db, request, context, "finance.delinquency.refreshed", None, {"cases": len(items)})
    db.commit()
    return [_response(db, item) for item in items]


@router.get("", response_model=list[DelinquencyCaseResponse])
def list_cases(case_status: str | None = Query(default=None, alias="status"), context: UserContext = Depends(require_permission("finance.view")), db: Session = Depends(get_db)) -> list[DelinquencyCaseResponse]:
    items = refresh_delinquency_cases(db, organization_id=context.user.organization_id)
    db.commit()
    if case_status:
        items = [item for item in items if item.status == case_status]
    charge_dates = {item.charge_id: (db.get(RentCharge, item.charge_id).due_date if db.get(RentCharge, item.charge_id) else date.max) for item in items}
    items.sort(key=lambda item: (item.status == "resolved", charge_dates[item.charge_id]))
    return [_response(db, item) for item in items]


@router.post("/{case_id}/action", response_model=DelinquencyCaseResponse)
def case_action(case_id: UUID, payload: DelinquencyActionRequest, request: Request, context: UserContext = Depends(require_permission("finance.payment.approve")), db: Session = Depends(get_db)) -> DelinquencyCaseResponse:
    item = db.scalar(select(DelinquencyCase).where(DelinquencyCase.id == case_id, DelinquencyCase.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Caso de inadimplência não encontrado.")
    now = datetime.now(timezone.utc)
    previous = item.status
    item.status = payload.status
    if payload.notes is not None:
        item.notes = payload.notes.strip() or None
    item.next_action_at = payload.next_action_at
    if payload.status in {"contacted", "negotiating"}:
        item.last_contact_at = now
    if payload.status == "insurer_triggered":
        item.insurer_triggered_at = item.insurer_triggered_at or now
        item.insurer_protocol = (payload.insurer_protocol or item.insurer_protocol or "").strip() or None
    if payload.status == "resolved":
        item.resolved_at = now
    elif previous == "resolved":
        item.resolved_at = None
    item.action_log = [*list(item.action_log or []), {"at": now.isoformat(), "action": payload.status, "actor_user_id": str(context.user.id), "notes": payload.notes, "insurer_protocol": item.insurer_protocol}]
    _audit(db, request, context, "finance.delinquency.action", str(item.id), {"from": previous, "to": item.status, "protocol": item.insurer_protocol})
    db.commit()
    return _response(db, item)
