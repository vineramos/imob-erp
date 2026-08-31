from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.advanced_models import CommissionEntry, CommissionRule
from app.domains.finance.advanced_schemas import CommissionEntryResponse, CommissionRuleCreate, CommissionRuleResponse, CommissionRuleUpdate
from app.domains.finance.advanced_service import generate_commissions_for_charge, money, sync_commission_status
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import FinancialSettlement, RentCharge
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.portfolio.models import Person

router = APIRouter(prefix="/commissions")


def _audit(db: Session, request: Request, context: UserContext, action: str, entity_type: str, entity_id: str | None, after: dict | None = None) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(db, context=context, action=action, module="finance", entity_type=entity_type, entity_id=entity_id, after_data=after, ip_address=forwarded or (request.client.host if request.client else None), user_agent=request.headers.get("user-agent"))


def _rule_response(item: CommissionRule) -> CommissionRuleResponse:
    return CommissionRuleResponse(id=item.id, code=f"COMR-{item.internal_number:04d}", name=item.name, event_type=item.event_type, basis=item.basis, calculation_type=item.calculation_type, value=float(item.value), beneficiary_type=item.beneficiary_type, beneficiary_person_id=item.beneficiary_person_id, beneficiary_name=item.beneficiary_name, property_id=item.property_id, lease_contract_id=item.lease_contract_id, due_days=item.due_days, priority=item.priority, is_active=item.is_active, notes=item.notes, created_at=item.created_at)


def _entry_response(db: Session, item: CommissionEntry) -> CommissionEntryResponse:
    sync_commission_status(db, item)
    return CommissionEntryResponse(id=item.id, code=f"COM-{item.internal_number:06d}", rule_id=item.rule_id, source_type=item.source_type, source_id=item.source_id, source_code=item.source_code, beneficiary_type=item.beneficiary_type, beneficiary_person_id=item.beneficiary_person_id, beneficiary_name=item.beneficiary_name, competence=item.competence, basis_amount=float(money(item.basis_amount)), amount=float(money(item.amount)), due_date=item.due_date, status=item.status, financial_title_id=item.financial_title_id, paid_at=item.paid_at, payment_reference=item.payment_reference, created_at=item.created_at)


def _person(db: Session, organization_id: UUID, person_id: UUID) -> Person:
    item = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == organization_id, Person.is_active.is_(True)))
    if item is None:
        raise HTTPException(status_code=422, detail="Beneficiário da comissão não encontrado.")
    return item


@router.get("/rules", response_model=list[CommissionRuleResponse])
def list_rules(context: UserContext = Depends(require_permission("finance.view")), db: Session = Depends(get_db)) -> list[CommissionRuleResponse]:
    items = db.scalars(select(CommissionRule).where(CommissionRule.organization_id == context.user.organization_id).order_by(CommissionRule.priority, CommissionRule.internal_number)).all()
    return [_rule_response(item) for item in items]


@router.post("/rules", response_model=CommissionRuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(payload: CommissionRuleCreate, request: Request, context: UserContext = Depends(require_permission("finance.payment.prepare")), db: Session = Depends(get_db)) -> CommissionRuleResponse:
    person = _person(db, context.user.organization_id, payload.beneficiary_person_id)
    item = CommissionRule(organization_id=context.user.organization_id, name=payload.name.strip(), event_type=payload.event_type, basis=payload.basis, calculation_type=payload.calculation_type, value=Decimal(str(payload.value)), beneficiary_type=payload.beneficiary_type, beneficiary_person_id=person.id, beneficiary_name=person.name, property_id=payload.property_id, lease_contract_id=payload.lease_contract_id, due_days=payload.due_days, priority=payload.priority, notes=(payload.notes or "").strip() or None, created_by_user_id=context.user.id)
    db.add(item); db.flush()
    _audit(db, request, context, "finance.commission_rule.created", "commission_rule", str(item.id), {"name": item.name, "beneficiary": item.beneficiary_name})
    db.commit()
    return _rule_response(item)


@router.put("/rules/{rule_id}", response_model=CommissionRuleResponse)
def update_rule(rule_id: UUID, payload: CommissionRuleUpdate, request: Request, context: UserContext = Depends(require_permission("finance.payment.prepare")), db: Session = Depends(get_db)) -> CommissionRuleResponse:
    item = db.scalar(select(CommissionRule).where(CommissionRule.id == rule_id, CommissionRule.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Regra de comissão não encontrada.")
    person = _person(db, context.user.organization_id, payload.beneficiary_person_id)
    item.name=payload.name.strip(); item.event_type=payload.event_type; item.basis=payload.basis; item.calculation_type=payload.calculation_type; item.value=Decimal(str(payload.value)); item.beneficiary_type=payload.beneficiary_type; item.beneficiary_person_id=person.id; item.beneficiary_name=person.name; item.property_id=payload.property_id; item.lease_contract_id=payload.lease_contract_id; item.due_days=payload.due_days; item.priority=payload.priority; item.is_active=payload.is_active; item.notes=(payload.notes or "").strip() or None
    _audit(db, request, context, "finance.commission_rule.updated", "commission_rule", str(item.id), {"active": item.is_active, "beneficiary": item.beneficiary_name})
    db.commit()
    return _rule_response(item)


@router.post("/generate", response_model=list[CommissionEntryResponse])
def generate_entries(request: Request, start_date: date = Query(...), end_date: date = Query(...), context: UserContext = Depends(require_permission("finance.payment.prepare")), db: Session = Depends(get_db)) -> list[CommissionEntryResponse]:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="Período inválido.")
    charges = db.scalars(select(RentCharge).where(RentCharge.organization_id == context.user.organization_id, RentCharge.status == "paid")).all()
    settlements = {item.charge_id:item for item in db.scalars(select(FinancialSettlement).where(FinancialSettlement.organization_id == context.user.organization_id)).all()}
    created:list[CommissionEntry]=[]
    for charge in charges:
        if not charge.paid_at or not (start_date <= charge.paid_at.date() <= end_date):
            continue
        settlement=settlements.get(charge.id)
        if settlement:
            created.extend(generate_commissions_for_charge(db, charge=charge, settlement=settlement))
    _audit(db, request, context, "finance.commissions.generated", "commission_batch", f"{start_date}:{end_date}", {"created":len(created)})
    db.commit()
    return [_entry_response(db,item) for item in created]


@router.get("", response_model=list[CommissionEntryResponse])
def list_entries(competence: date | None = Query(default=None), entry_status: str | None = Query(default=None,alias="status"), context: UserContext = Depends(require_permission("finance.view")), db: Session = Depends(get_db)) -> list[CommissionEntryResponse]:
    stmt=select(CommissionEntry).where(CommissionEntry.organization_id==context.user.organization_id)
    if competence: stmt=stmt.where(CommissionEntry.competence==competence.replace(day=1))
    items=db.scalars(stmt.order_by(CommissionEntry.due_date.desc(),CommissionEntry.internal_number.desc()).limit(500)).all()
    responses=[_entry_response(db,item) for item in items]; db.commit()
    return [item for item in responses if not entry_status or item.status==entry_status]


@router.post("/{entry_id}/approve", response_model=CommissionEntryResponse)
def approve_entry(entry_id:UUID,request:Request,context:UserContext=Depends(require_permission("finance.payment.approve")),db:Session=Depends(get_db))->CommissionEntryResponse:
    item=db.scalar(select(CommissionEntry).where(CommissionEntry.id==entry_id,CommissionEntry.organization_id==context.user.organization_id))
    if item is None: raise HTTPException(status_code=404,detail="Comissão não encontrada.")
    sync_commission_status(db,item)
    if item.status in {"paid","cancelled"}: raise HTTPException(status_code=409,detail="Esta comissão não pode mais ser aprovada.")
    item.status="approved"; item.approved_by_user_id=context.user.id; item.approved_at=datetime.now(timezone.utc)
    _audit(db,request,context,"finance.commission.approved","commission_entry",str(item.id),{"amount":str(item.amount),"beneficiary":item.beneficiary_name}); db.commit(); return _entry_response(db,item)


@router.post("/{entry_id}/cancel", response_model=CommissionEntryResponse)
def cancel_entry(entry_id:UUID,request:Request,context:UserContext=Depends(require_permission("finance.payment.approve")),db:Session=Depends(get_db))->CommissionEntryResponse:
    item=db.scalar(select(CommissionEntry).where(CommissionEntry.id==entry_id,CommissionEntry.organization_id==context.user.organization_id))
    if item is None: raise HTTPException(status_code=404,detail="Comissão não encontrada.")
    sync_commission_status(db,item)
    if item.status=="paid": raise HTTPException(status_code=409,detail="Comissão já paga não pode ser cancelada.")
    item.status="cancelled"
    if item.financial_title_id:
        title=db.get(FinancialTitle,item.financial_title_id)
        if title and title.status!="settled": title.status="cancelled"
    _audit(db,request,context,"finance.commission.cancelled","commission_entry",str(item.id)); db.commit(); return _entry_response(db,item)
