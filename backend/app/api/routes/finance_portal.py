from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.finance import _owner_statement
from app.core.database import get_db
from app.domains.finance.advanced_models import BillingItem, PortalAccess
from app.domains.finance.advanced_pdf import build_annual_income_pdf
from app.domains.finance.advanced_schemas import AnnualIncomeLine, AnnualIncomeReport, PortalAccessCreate, PortalAccessCreated, PortalAccessResponse, PortalCharge, PortalPayload, PortalProperty, PortalRepasse
from app.domains.finance.advanced_service import annual_income_values, money
from app.domains.finance.models import OwnerRepasse, RentCharge
from app.domains.finance.pdf import build_owner_statement_pdf
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person, Property, PropertyOwner

admin_router = APIRouter(prefix="/portal")
public_router = APIRouter(prefix="/portal", tags=["external-portal"])
ZERO = Decimal("0.00")


def _audit(db: Session, request: Request, context: UserContext, action: str, entity_id: str | None, after: dict | None = None) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(db, context=context, action=action, module="finance", entity_type="portal_access", entity_id=entity_id, after_data=after, ip_address=forwarded or (request.client.host if request.client else None), user_agent=request.headers.get("user-agent"))


def _access_response(db: Session, item: PortalAccess) -> PortalAccessResponse:
    person = db.get(Person, item.person_id)
    active = item.is_active and item.revoked_at is None and item.expires_at > datetime.now(timezone.utc)
    return PortalAccessResponse(id=item.id, person_id=item.person_id, person_name=person.name if person else "Pessoa", portal_type=item.portal_type, label=item.label, is_active=active, expires_at=item.expires_at, revoked_at=item.revoked_at, last_used_at=item.last_used_at, created_at=item.created_at)


@admin_router.get("/access", response_model=list[PortalAccessResponse])
def list_accesses(context: UserContext = Depends(require_permission("finance.view")), db: Session = Depends(get_db)) -> list[PortalAccessResponse]:
    items = db.scalars(select(PortalAccess).where(PortalAccess.organization_id == context.user.organization_id).order_by(PortalAccess.created_at.desc()).limit(500)).all()
    return [_access_response(db, item) for item in items]


@admin_router.post("/access", response_model=PortalAccessCreated, status_code=status.HTTP_201_CREATED)
def create_access(payload: PortalAccessCreate, request: Request, context: UserContext = Depends(require_permission("finance.payment.approve")), db: Session = Depends(get_db)) -> PortalAccessCreated:
    person = db.scalar(select(Person).where(Person.id == payload.person_id, Person.organization_id == context.user.organization_id, Person.is_active.is_(True)))
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")
    token = secrets.token_urlsafe(32)
    item = PortalAccess(organization_id=context.user.organization_id, person_id=person.id, portal_type=payload.portal_type, token_hash=hashlib.sha256(token.encode()).hexdigest(), label=(payload.label or "").strip() or None, is_active=True, expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_days), created_by_user_id=context.user.id)
    db.add(item); db.flush()
    _audit(db, request, context, "finance.portal_access.created", str(item.id), {"person": person.name, "portal_type": item.portal_type, "expires_at": item.expires_at.isoformat()})
    db.commit()
    base = _access_response(db, item)
    return PortalAccessCreated(**base.model_dump(), token=token, path=f"/portal/{token}")


@admin_router.post("/access/{access_id}/revoke", response_model=PortalAccessResponse)
def revoke_access(access_id: UUID, request: Request, context: UserContext = Depends(require_permission("finance.payment.approve")), db: Session = Depends(get_db)) -> PortalAccessResponse:
    item = db.scalar(select(PortalAccess).where(PortalAccess.id == access_id, PortalAccess.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Acesso externo não encontrado.")
    item.is_active=False; item.revoked_at=datetime.now(timezone.utc)
    _audit(db,request,context,"finance.portal_access.revoked",str(item.id)); db.commit(); return _access_response(db,item)


def _public_access(db: Session, token: str) -> PortalAccess:
    digest=hashlib.sha256(token.encode()).hexdigest()
    item=db.scalar(select(PortalAccess).where(PortalAccess.token_hash==digest))
    now=datetime.now(timezone.utc)
    if item is None or not item.is_active or item.revoked_at is not None or item.expires_at<=now:
        raise HTTPException(status_code=404,detail="Acesso externo inválido ou expirado.")
    item.last_used_at=now
    return item


def _property_code(charge: RentCharge) -> str:
    return str((charge.property_snapshot or {}).get("code") or "—")


def _payload(db: Session, access: PortalAccess) -> PortalPayload:
    organization=db.get(Organization,access.organization_id); person=db.get(Person,access.person_id)
    if person is None: raise HTTPException(status_code=404,detail="Pessoa vinculada ao portal não encontrada.")
    properties:list[PortalProperty]=[]; charges_out:list[PortalCharge]=[]; repasses_out:list[PortalRepasse]=[]; year_total=ZERO; open_amount=ZERO
    if access.portal_type=="owner":
        links=db.scalars(select(PropertyOwner).where(PropertyOwner.person_id==person.id)).all(); ids=[link.property_id for link in links]
        props={item.id:item for item in db.scalars(select(Property).where(Property.id.in_(ids))).all()} if ids else {}
        for link in links:
            prop=props.get(link.property_id)
            if prop: properties.append(PortalProperty(id=prop.id,code=f"{prop.internal_number:06d}",address=dict(prop.address or {}),ownership_percent=float(link.ownership_percent)))
        repasses=db.scalars(select(OwnerRepasse).where(OwnerRepasse.organization_id==access.organization_id,OwnerRepasse.owner_person_id==person.id).order_by(OwnerRepasse.due_date.desc()).limit(100)).all()
        for repasse in repasses:
            charge=db.get(RentCharge,repasse.charge_id)
            if not charge: continue
            repasses_out.append(PortalRepasse(id=repasse.id,competence=charge.competence,property_code=_property_code(charge),amount=float(money(repasse.amount)),due_date=repasse.due_date,status=repasse.status,paid_at=repasse.paid_at))
            if repasse.status=="paid" and repasse.paid_at and repasse.paid_at.year==date.today().year: year_total+=money(repasse.amount)
            if repasse.status=="pending": open_amount+=money(repasse.amount)
    else:
        leases=db.scalars(select(LeaseContract).where(LeaseContract.organization_id==access.organization_id)).all()
        tenant_leases=[lease for lease in leases if any(isinstance(item,dict) and str(item.get("person_id"))==str(person.id) for item in list(lease.tenant_snapshot or []))]
        lease_ids=[lease.id for lease in tenant_leases]; property_ids=list({lease.property_id for lease in tenant_leases})
        props={item.id:item for item in db.scalars(select(Property).where(Property.id.in_(property_ids))).all()} if property_ids else {}
        for prop in props.values(): properties.append(PortalProperty(id=prop.id,code=f"{prop.internal_number:06d}",address=dict(prop.address or {})))
        charges=db.scalars(select(RentCharge).where(RentCharge.organization_id==access.organization_id,RentCharge.lease_contract_id.in_(lease_ids)).order_by(RentCharge.due_date.desc()).limit(100)).all() if lease_ids else []
        billing={item.charge_id:item for item in db.scalars(select(BillingItem).where(BillingItem.charge_id.in_([c.id for c in charges]))).all()} if charges else {}
        for charge in charges:
            bill=billing.get(charge.id); charges_out.append(PortalCharge(id=charge.id,code=f"COB-{charge.internal_number:06d}",competence=charge.competence,due_date=charge.due_date,property_code=_property_code(charge),amount=float(money(charge.gross_amount)),status=charge.status,paid_at=charge.paid_at,boleto_line=bill.boleto_line if bill else None,pix_copy_paste=bill.pix_copy_paste if bill else None))
            if charge.status=="paid" and charge.paid_at and charge.paid_at.year==date.today().year: year_total+=money(charge.paid_amount)
            if charge.status in {"generated","sent","overdue"}: open_amount+=money(charge.gross_amount)
    return PortalPayload(organization_name=organization.display_name if organization else "Imobiliária",portal_type=access.portal_type,person_id=person.id,person_name=person.name,expires_at=access.expires_at,properties=properties,charges=charges_out,repasses=repasses_out,current_year_total=float(money(year_total)),open_amount=float(money(open_amount)))


@public_router.get("/{token}",response_model=PortalPayload)
def portal(token:str,db:Session=Depends(get_db))->PortalPayload:
    access=_public_access(db,token); result=_payload(db,access); db.commit(); return result


@public_router.get("/{token}/statement.pdf")
def statement_pdf(token:str,competence:date=Query(...),property_id:UUID|None=Query(default=None),db:Session=Depends(get_db))->Response:
    access=_public_access(db,token)
    if access.portal_type!="owner": raise HTTPException(status_code=403,detail="Este acesso não pertence ao portal do proprietário.")
    statement=_owner_statement(db,access.organization_id,access.person_id,competence,property_id); organization=db.get(Organization,access.organization_id); payload=build_owner_statement_pdf(statement=statement,organization_name=organization.display_name if organization else "Imobiliária"); db.commit()
    return Response(content=payload,media_type="application/pdf",headers={"Content-Disposition":f'inline; filename="prestacao-contas-{competence:%Y-%m}.pdf"'})


@public_router.get("/{token}/annual-income.pdf")
def annual_pdf(token:str,year:int=Query(...,ge=2000,le=2200),db:Session=Depends(get_db))->Response:
    access=_public_access(db,token)
    try: person,raw_lines,allocation=annual_income_values(db,organization_id=access.organization_id,year=year,party_type=access.portal_type,person_id=access.person_id)
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    lines=[AnnualIncomeLine(**{key:float(value) if isinstance(value,Decimal) else value for key,value in raw.items()}) for raw in raw_lines]
    report=AnnualIncomeReport(year=year,party_type=access.portal_type,person_id=person.id,person_name=person.name,allocation_method=allocation,total_rent=float(money(sum((money(x["rent_amount"]) for x in raw_lines),ZERO))),total_additional_charges=float(money(sum((money(x["additional_charges"]) for x in raw_lines),ZERO))),total_paid=float(money(sum((money(x["total_amount"]) for x in raw_lines),ZERO))),total_administration_fee=float(money(sum((money(x["administration_fee"]) for x in raw_lines),ZERO))),total_owner_net=float(money(sum((money(x["owner_net_amount"]) for x in raw_lines),ZERO))),lines=lines)
    organization=db.get(Organization,access.organization_id); payload=build_annual_income_pdf(report,organization.display_name if organization else "Imobiliária"); db.commit()
    return Response(content=payload,media_type="application/pdf",headers={"Content-Disposition":f'inline; filename="informe-{year}.pdf"'})
