from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.finance import _owner_statement
from app.core.database import get_db
from app.domains.finance.advanced_models import BillingItem, PortalAccess
from app.domains.finance.advanced_pdf import build_annual_income_pdf
from app.domains.finance.advanced_schemas import AnnualIncomeLine, AnnualIncomeReport
from app.domains.finance.advanced_service import annual_income_values, money
from app.domains.finance.charge_values import charge_financial_view
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


class PersonPortalCreate(BaseModel):
    person_id: UUID
    label: str | None = Field(default=None, max_length=160)


def _audit(db: Session, request: Request, context: UserContext, action: str, entity_id: str | None, after: dict | None = None) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(db, context=context, action=action, module="finance", entity_type="portal_access", entity_id=entity_id, after_data=after, ip_address=forwarded or (request.client.host if request.client else None), user_agent=request.headers.get("user-agent"))


def _tenant_leases(db: Session, organization_id: UUID, person_id: UUID) -> list[LeaseContract]:
    leases = db.scalars(select(LeaseContract).where(LeaseContract.organization_id == organization_id)).all()
    return [lease for lease in leases if any(isinstance(entry, dict) and str(entry.get("person_id")) == str(person_id) for entry in list(lease.tenant_snapshot or []))]


def _roles(db: Session, organization_id: UUID, person_id: UUID) -> list[str]:
    roles: list[str] = []
    owner_link = db.scalar(
        select(PropertyOwner.id)
        .join(Property, Property.id == PropertyOwner.property_id)
        .where(PropertyOwner.person_id == person_id, Property.organization_id == organization_id)
        .limit(1)
    )
    if owner_link is not None:
        roles.append("owner")
    if _tenant_leases(db, organization_id, person_id):
        roles.append("tenant")
    return roles


def _stable_path(item: PortalAccess) -> str:
    return f"/portal/p-{item.id}"


def _admin_access(db: Session, item: PortalAccess) -> dict:
    person = db.get(Person, item.person_id)
    return {
        "id": str(item.id),
        "person_id": str(item.person_id),
        "person_name": person.name if person else "Pessoa",
        "document_number": person.document_number if person else None,
        "roles": _roles(db, item.organization_id, item.person_id),
        "label": item.label,
        "is_active": bool(item.is_active and item.revoked_at is None),
        "expires_at": item.expires_at,
        "revoked_at": item.revoked_at,
        "last_used_at": item.last_used_at,
        "created_at": item.created_at,
        "path": _stable_path(item),
    }


@admin_router.get("/access")
def list_accesses(context: UserContext = Depends(require_permission("finance.view")), db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(
        select(PortalAccess)
        .where(PortalAccess.organization_id == context.user.organization_id)
        .order_by(PortalAccess.created_at.desc())
        .limit(500)
    ).all()
    # O portal é da pessoa: registros antigos por papel são consolidados visualmente
    # no acesso mais recente para manter um único link estável por cliente.
    unique: dict[UUID, PortalAccess] = {}
    for item in items:
        unique.setdefault(item.person_id, item)
    return [_admin_access(db, item) for item in unique.values()]


@admin_router.post("/access", status_code=status.HTTP_201_CREATED)
def create_access(payload: PersonPortalCreate, request: Request, context: UserContext = Depends(require_permission("finance.payment.approve")), db: Session = Depends(get_db)) -> dict:
    person = db.scalar(select(Person).where(Person.id == payload.person_id, Person.organization_id == context.user.organization_id, Person.is_active.is_(True)))
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")

    item = db.scalar(
        select(PortalAccess)
        .where(PortalAccess.organization_id == context.user.organization_id, PortalAccess.person_id == person.id)
        .order_by(PortalAccess.created_at.desc())
        .limit(1)
    )
    now = datetime.now(timezone.utc)
    if item is None:
        # token_hash continua preenchido para compatibilidade com o esquema legado,
        # porém o novo link permanente usa o UUID aleatório do próprio acesso.
        legacy_seed = hashlib.sha256(f"portal:{person.id}:{now.isoformat()}".encode()).hexdigest()
        item = PortalAccess(
            organization_id=context.user.organization_id,
            person_id=person.id,
            portal_type="owner",
            token_hash=legacy_seed,
            label=(payload.label or "").strip() or None,
            is_active=True,
            expires_at=now + timedelta(days=3650),
            created_by_user_id=context.user.id,
        )
        db.add(item)
        db.flush()
        action = "finance.portal_access.created"
    else:
        item.is_active = True
        item.revoked_at = None
        item.expires_at = now + timedelta(days=3650)
        if payload.label is not None:
            item.label = payload.label.strip() or None
        action = "finance.portal_access.reactivated"

    result = _admin_access(db, item)
    _audit(db, request, context, action, str(item.id), {"person": person.name, "roles": result["roles"], "path": result["path"]})
    db.commit()
    return result


@admin_router.post("/access/{access_id}/revoke")
def revoke_access(access_id: UUID, request: Request, context: UserContext = Depends(require_permission("finance.payment.approve")), db: Session = Depends(get_db)) -> dict:
    item = db.scalar(select(PortalAccess).where(PortalAccess.id == access_id, PortalAccess.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Acesso externo não encontrado.")
    item.is_active = False
    item.revoked_at = datetime.now(timezone.utc)
    result = _admin_access(db, item)
    _audit(db, request, context, "finance.portal_access.revoked", str(item.id))
    db.commit()
    return result


def _public_access(db: Session, token: str) -> PortalAccess:
    now = datetime.now(timezone.utc)
    item = None
    if token.startswith("p-"):
        try:
            access_id = UUID(token[2:])
        except ValueError:
            access_id = None
        if access_id:
            item = db.get(PortalAccess, access_id)
        # O endereço p-UUID é permanente: só revogação explícita o desativa.
        if item is None or not item.is_active or item.revoked_at is not None:
            raise HTTPException(status_code=404, detail="Acesso externo inválido ou revogado.")
    else:
        # Links antigos continuam funcionando até o vencimento original.
        digest = hashlib.sha256(token.encode()).hexdigest()
        item = db.scalar(select(PortalAccess).where(PortalAccess.token_hash == digest))
        if item is None or not item.is_active or item.revoked_at is not None or item.expires_at <= now:
            raise HTTPException(status_code=404, detail="Acesso externo inválido ou expirado.")
    item.last_used_at = now
    return item


def _property_code(charge: RentCharge) -> str:
    return str((charge.property_snapshot or {}).get("code") or "—")


def _address_payload(prop: Property) -> dict:
    return dict(prop.address or {})


def _portal_payload(db: Session, access: PortalAccess) -> dict:
    organization = db.get(Organization, access.organization_id)
    person = db.get(Person, access.person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa vinculada ao portal não encontrada.")

    roles = _roles(db, access.organization_id, person.id)
    owner_properties: list[dict] = []
    tenant_properties: list[dict] = []
    charges_out: list[dict] = []
    repasses_out: list[dict] = []
    owner_year_total = ZERO
    owner_open_amount = ZERO
    tenant_year_total = ZERO
    tenant_open_amount = ZERO

    links = db.scalars(
        select(PropertyOwner)
        .join(Property, Property.id == PropertyOwner.property_id)
        .where(PropertyOwner.person_id == person.id, Property.organization_id == access.organization_id)
    ).all()
    owner_property_ids = [link.property_id for link in links]
    owner_props = {item.id: item for item in db.scalars(select(Property).where(Property.id.in_(owner_property_ids))).all()} if owner_property_ids else {}
    for link in links:
        prop = owner_props.get(link.property_id)
        if prop:
            owner_properties.append({"id": str(prop.id), "code": f"{prop.internal_number:06d}", "address": _address_payload(prop), "ownership_percent": float(link.ownership_percent), "relation": "owner"})

    repasses = db.scalars(
        select(OwnerRepasse)
        .where(OwnerRepasse.organization_id == access.organization_id, OwnerRepasse.owner_person_id == person.id)
        .order_by(OwnerRepasse.due_date.desc())
        .limit(150)
    ).all()
    for repasse in repasses:
        charge = db.get(RentCharge, repasse.charge_id)
        if not charge:
            continue
        repasses_out.append({"id": str(repasse.id), "competence": charge.competence, "property_code": _property_code(charge), "amount": float(money(repasse.amount)), "due_date": repasse.due_date, "status": repasse.status, "paid_at": repasse.paid_at})
        if repasse.status == "paid" and repasse.paid_at and repasse.paid_at.year == date.today().year:
            owner_year_total += money(repasse.amount)
        if repasse.status == "pending":
            owner_open_amount += money(repasse.amount)

    tenant_leases = _tenant_leases(db, access.organization_id, person.id)
    lease_ids = [lease.id for lease in tenant_leases]
    tenant_property_ids = list({lease.property_id for lease in tenant_leases})
    tenant_props = {item.id: item for item in db.scalars(select(Property).where(Property.id.in_(tenant_property_ids))).all()} if tenant_property_ids else {}
    for lease in tenant_leases:
        prop = tenant_props.get(lease.property_id)
        if prop:
            tenant_properties.append({"id": str(prop.id), "code": f"{prop.internal_number:06d}", "address": _address_payload(prop), "ownership_percent": None, "relation": "tenant", "lease_id": str(lease.id), "lease_code": f"LOC-{lease.internal_number:06d}"})

    charges = db.scalars(
        select(RentCharge)
        .where(RentCharge.organization_id == access.organization_id, RentCharge.lease_contract_id.in_(lease_ids))
        .order_by(RentCharge.due_date.desc())
        .limit(150)
    ).all() if lease_ids else []
    billing = {item.charge_id: item for item in db.scalars(select(BillingItem).where(BillingItem.charge_id.in_([charge.id for charge in charges]))).all()} if charges else {}
    for charge in charges:
        bill = billing.get(charge.id)
        financial = charge_financial_view(db, charge)
        charges_out.append({
            "id": str(charge.id),
            "code": f"COB-{charge.internal_number:06d}",
            "competence": charge.competence,
            "due_date": charge.due_date,
            "property_code": _property_code(charge),
            "amount": float(financial.payable_amount),
            "nominal_amount": float(financial.nominal_amount),
            "late_fee_amount": float(financial.late_fee_amount),
            "late_interest_amount": float(financial.late_interest_amount),
            "days_overdue": financial.days_overdue,
            "amount_updated_at": financial.as_of,
            "status": charge.status,
            "paid_at": charge.paid_at,
            "boleto_line": bill.boleto_line if bill else None,
            "pix_copy_paste": bill.pix_copy_paste if bill else None,
        })
        if charge.status == "paid" and charge.paid_at and charge.paid_at.year == date.today().year:
            tenant_year_total += money(charge.paid_amount)
        if charge.status in {"generated", "sent", "overdue"}:
            tenant_open_amount += financial.payable_amount

    return {
        "organization_name": organization.display_name if organization else "Imobiliária",
        "portal_type": "person",
        "roles": roles,
        "person_id": str(person.id),
        "person_name": person.name,
        "document_number": person.document_number,
        "owner_properties": owner_properties,
        "tenant_properties": tenant_properties,
        "charges": charges_out,
        "repasses": repasses_out,
        "owner_year_total": float(money(owner_year_total)),
        "owner_open_amount": float(money(owner_open_amount)),
        "tenant_year_total": float(money(tenant_year_total)),
        "tenant_open_amount": float(money(tenant_open_amount)),
        "last_used_at": access.last_used_at,
    }


@public_router.get("/{token}")
def portal(token: str, db: Session = Depends(get_db)) -> dict:
    access = _public_access(db, token)
    result = _portal_payload(db, access)
    db.commit()
    return result


@public_router.get("/{token}/statement.pdf")
def statement_pdf(token: str, competence: date = Query(...), property_id: UUID | None = Query(default=None), db: Session = Depends(get_db)) -> Response:
    access = _public_access(db, token)
    if "owner" not in _roles(db, access.organization_id, access.person_id):
        raise HTTPException(status_code=403, detail="Esta pessoa não possui patrimônio administrado como proprietária.")
    statement = _owner_statement(db, access.organization_id, access.person_id, competence, property_id)
    organization = db.get(Organization, access.organization_id)
    payload = build_owner_statement_pdf(statement=statement, organization_name=organization.display_name if organization else "Imobiliária")
    db.commit()
    return Response(content=payload, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="prestacao-contas-{competence:%Y-%m}.pdf"'})


@public_router.get("/{token}/annual-income.pdf")
def annual_pdf(token: str, year: int = Query(..., ge=2000, le=2200), context: Literal["owner", "tenant"] = Query(default="owner"), db: Session = Depends(get_db)) -> Response:
    access = _public_access(db, token)
    if context not in _roles(db, access.organization_id, access.person_id):
        raise HTTPException(status_code=403, detail="O contexto selecionado não pertence a esta pessoa.")
    try:
        person, raw_lines, allocation = annual_income_values(db, organization_id=access.organization_id, year=year, party_type=context, person_id=access.person_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    lines = [AnnualIncomeLine(**{key: float(value) if isinstance(value, Decimal) else value for key, value in raw.items()}) for raw in raw_lines]
    report = AnnualIncomeReport(
        year=year,
        party_type=context,
        person_id=person.id,
        person_name=person.name,
        allocation_method=allocation,
        total_rent=float(money(sum((money(entry["rent_amount"]) for entry in raw_lines), ZERO))),
        total_additional_charges=float(money(sum((money(entry["additional_charges"]) for entry in raw_lines), ZERO))),
        total_paid=float(money(sum((money(entry["total_amount"]) for entry in raw_lines), ZERO))),
        total_administration_fee=float(money(sum((money(entry["administration_fee"]) for entry in raw_lines), ZERO))),
        total_owner_net=float(money(sum((money(entry["owner_net_amount"]) for entry in raw_lines), ZERO))),
        lines=lines,
    )
    organization = db.get(Organization, access.organization_id)
    payload = build_annual_income_pdf(report, organization.display_name if organization else "Imobiliária")
    db.commit()
    filename = f"informe-rendimentos-{year}.pdf" if context == "owner" else f"comprovante-pagamentos-{year}.pdf"
    return Response(content=payload, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})
