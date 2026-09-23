from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.models import OwnerRepasse, RentCharge
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.models import AppUser, AuditLog
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person, Property, PropertyOwner
from app.domains.portfolio.site_models import CommercialActivity, CommercialProposal, CommercialVisit, PublicSiteInquiry

router = APIRouter(tags=["person-insights"])


def _person(db: Session, organization_id: UUID, person_id: UUID) -> Person:
    item = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == organization_id))
    if item is None:
        raise HTTPException(404, "Pessoa não encontrada.")
    return item


def _tenant_lease_ids(db: Session, organization_id: UUID, person_id: UUID) -> list[UUID]:
    rows = db.scalars(
        select(LeaseContract)
        .where(LeaseContract.organization_id == organization_id)
        .order_by(LeaseContract.created_at.desc())
        .limit(500)
    ).all()
    target = str(person_id)
    return [
        row.id
        for row in rows
        if any(str(tenant.get("person_id") or "") == target for tenant in (row.tenant_snapshot or []))
    ]


def _owner_property_ids(db: Session, organization_id: UUID, person_id: UUID) -> list[UUID]:
    return list(
        db.scalars(
            select(PropertyOwner.property_id)
            .join(Property, Property.id == PropertyOwner.property_id)
            .where(Property.organization_id == organization_id, PropertyOwner.person_id == person_id)
        ).all()
    )


@router.get("/people/{person_id}/finance-summary")
def person_finance_summary(
    person_id: UUID,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> dict:
    _person(db, context.user.organization_id, person_id)
    org_id = context.user.organization_id
    tenant_lease_ids = _tenant_lease_ids(db, org_id, person_id)
    owner_property_ids = _owner_property_ids(db, org_id, person_id)

    charges = []
    if tenant_lease_ids:
        charges = db.scalars(
            select(RentCharge)
            .where(RentCharge.organization_id == org_id, RentCharge.lease_contract_id.in_(tenant_lease_ids))
            .order_by(RentCharge.due_date.desc())
            .limit(120)
        ).all()

    repasses = db.scalars(
        select(OwnerRepasse)
        .where(OwnerRepasse.organization_id == org_id, OwnerRepasse.owner_person_id == person_id)
        .order_by(OwnerRepasse.due_date.desc())
        .limit(120)
    ).all()

    today = date.today()
    open_charges = [row for row in charges if row.status not in {"paid", "cancelled"}]
    overdue = [row for row in open_charges if row.due_date < today]
    paid_charges = [row for row in charges if row.status == "paid"]
    pending_repasses = [row for row in repasses if row.status not in {"paid", "cancelled"}]
    paid_repasses = [row for row in repasses if row.status == "paid"]

    def amount(value: Decimal | None) -> float:
        return float(value or Decimal("0"))

    return {
        "tenant": {
            "total_charges": len(charges),
            "open_count": len(open_charges),
            "overdue_count": len(overdue),
            "open_amount": sum(amount(row.gross_amount) for row in open_charges),
            "overdue_amount": sum(amount(row.gross_amount) for row in overdue),
            "paid_amount": sum(amount(row.paid_amount or row.gross_amount) for row in paid_charges),
        },
        "owner": {
            "property_count": len(owner_property_ids),
            "total_repasses": len(repasses),
            "pending_count": len(pending_repasses),
            "pending_amount": sum(amount(row.amount) for row in pending_repasses),
            "paid_amount": sum(amount(row.amount) for row in paid_repasses),
        },
        "charges": [
            {
                "id": str(row.id),
                "lease_contract_id": str(row.lease_contract_id),
                "property_id": str(row.property_id),
                "competence": row.competence,
                "due_date": row.due_date,
                "status": row.status,
                "gross_amount": amount(row.gross_amount),
                "paid_amount": amount(row.paid_amount) if row.paid_amount is not None else None,
                "paid_at": row.paid_at,
                "property_code": str((row.property_snapshot or {}).get("code") or ""),
            }
            for row in charges[:30]
        ],
        "repasses": [
            {
                "id": str(row.id),
                "lease_contract_id": str(row.lease_contract_id),
                "property_id": str(row.property_id),
                "due_date": row.due_date,
                "status": row.status,
                "amount": amount(row.amount),
                "paid_at": row.paid_at,
            }
            for row in repasses[:30]
        ],
    }


@router.get("/people/{person_id}/commercial-summary")
def person_commercial_summary(
    person_id: UUID,
    context: UserContext = Depends(require_permission("crm.view")),
    db: Session = Depends(get_db),
) -> dict:
    _person(db, context.user.organization_id, person_id)
    org_id = context.user.organization_id
    inquiries = db.scalars(
        select(PublicSiteInquiry)
        .where(PublicSiteInquiry.organization_id == org_id, PublicSiteInquiry.person_id == person_id)
        .order_by(PublicSiteInquiry.updated_at.desc())
        .limit(80)
    ).all()
    visits = db.scalars(
        select(CommercialVisit)
        .where(CommercialVisit.organization_id == org_id, CommercialVisit.person_id == person_id)
        .order_by(CommercialVisit.starts_at.desc())
        .limit(80)
    ).all()
    proposals = db.scalars(
        select(CommercialProposal)
        .where(CommercialProposal.organization_id == org_id, CommercialProposal.person_id == person_id)
        .order_by(CommercialProposal.created_at.desc())
        .limit(80)
    ).all()
    inquiry_ids = [row.id for row in inquiries]
    activities = []
    if inquiry_ids:
        activities = db.scalars(
            select(CommercialActivity)
            .where(CommercialActivity.organization_id == org_id, CommercialActivity.inquiry_id.in_(inquiry_ids))
            .order_by(CommercialActivity.created_at.desc())
            .limit(50)
        ).all()

    user_ids = {row.responsible_user_id for row in inquiries if row.responsible_user_id}
    users = {}
    if user_ids:
        users = {row.id: row.name for row in db.scalars(select(AppUser).where(AppUser.id.in_(user_ids))).all()}

    active = [row for row in inquiries if row.status not in {"won", "lost"}]
    next_rows = [row for row in inquiries if row.next_action_at is not None]
    next_rows.sort(key=lambda row: row.next_action_at)

    return {
        "metrics": {
            "leads": len(inquiries),
            "active": len(active),
            "visits": len(visits),
            "proposals": len(proposals),
            "won": sum(1 for row in inquiries if row.status == "won"),
        },
        "next_action": (
            {
                "title": next_rows[0].next_action_title,
                "at": next_rows[0].next_action_at,
                "notes": next_rows[0].next_action_notes,
                "property_code": next_rows[0].property_code,
            }
            if next_rows else None
        ),
        "inquiries": [
            {
                "id": str(row.id),
                "property_id": str(row.property_id) if row.property_id else None,
                "property_code": row.property_code,
                "property_title": row.property_title,
                "status": row.status,
                "source": row.source,
                "responsible_name": users.get(row.responsible_user_id),
                "next_action_title": row.next_action_title,
                "next_action_at": row.next_action_at,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in inquiries
        ],
        "visits": [
            {"id": str(row.id), "property_id": str(row.property_id) if row.property_id else None, "starts_at": row.starts_at, "status": row.status, "notes": row.notes}
            for row in visits
        ],
        "proposals": [
            {"id": str(row.id), "property_id": str(row.property_id) if row.property_id else None, "status": row.status, "rent_amount": float(row.rent_amount), "start_date": row.start_date, "lease_contract_id": str(row.lease_contract_id) if row.lease_contract_id else None, "created_at": row.created_at}
            for row in proposals
        ],
        "activities": [
            {"id": str(row.id), "title": row.title, "notes": row.notes, "activity_type": row.activity_type, "created_at": row.created_at}
            for row in activities
        ],
    }


@router.get("/people/{person_id}/history")
def person_history(
    person_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    person = _person(db, context.user.organization_id, person_id)
    org_id = context.user.organization_id
    property_ids = _owner_property_ids(db, org_id, person_id)
    tenant_lease_ids = _tenant_lease_ids(db, org_id, person_id)
    owner_lease_ids = []
    if property_ids:
        owner_lease_ids = list(db.scalars(select(LeaseContract.id).where(LeaseContract.organization_id == org_id, LeaseContract.property_id.in_(property_ids))).all())
    lease_ids = list(dict.fromkeys([*tenant_lease_ids, *owner_lease_ids]))
    inquiries = db.scalars(select(PublicSiteInquiry).where(PublicSiteInquiry.organization_id == org_id, PublicSiteInquiry.person_id == person_id)).all()
    inquiry_ids = [row.id for row in inquiries]

    events: list[dict] = [
        {"kind": "person", "title": "Cadastro criado", "detail": "Pessoa adicionada ao cadastro canônico.", "at": person.created_at}
    ]

    audit_filters = [or_(AuditLog.entity_type == "person", AuditLog.entity_type == "portfolio.person")]
    audit_rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.organization_id == org_id, AuditLog.entity_id == str(person_id), *audit_filters)
        .order_by(AuditLog.created_at.desc())
        .limit(50)
    ).all()
    action_titles = {
        "portfolio.person.created": "Cadastro criado",
        "portfolio.person.updated": "Cadastro atualizado",
        "people.photo.updated": "Foto atualizada",
        "people.photo.removed": "Foto removida",
        "portfolio.person.archived": "Cadastro arquivado",
        "portfolio.person.restored": "Cadastro reativado",
    }
    for row in audit_rows:
        events.append({"kind": "audit", "title": action_titles.get(row.action, row.action.replace(".", " · ")), "detail": row.reason, "at": row.created_at})

    if property_ids:
        props = db.scalars(select(Property).where(Property.organization_id == org_id, Property.id.in_(property_ids))).all()
        for row in props:
            events.append({"kind": "property", "title": f"Imóvel #{row.internal_number:06d} vinculado", "detail": "Vínculo como proprietário.", "at": row.created_at})

    if lease_ids:
        leases = db.scalars(select(LeaseContract).where(LeaseContract.organization_id == org_id, LeaseContract.id.in_(lease_ids))).all()
        for row in leases:
            role = "Locatário" if row.id in tenant_lease_ids else "Proprietário"
            events.append({"kind": "contract", "title": f"Contrato LOC-{row.internal_number:06d}", "detail": f"{role} · status {row.status}", "at": row.created_at})
            if row.signed_at:
                events.append({"kind": "contract", "title": f"Contrato LOC-{row.internal_number:06d} assinado", "detail": role, "at": row.signed_at})

    for row in inquiries:
        events.append({"kind": "commercial", "title": f"Lead no imóvel #{row.property_code}", "detail": f"Etapa {row.status}", "at": row.created_at})

    if inquiry_ids:
        acts = db.scalars(select(CommercialActivity).where(CommercialActivity.organization_id == org_id, CommercialActivity.inquiry_id.in_(inquiry_ids)).order_by(CommercialActivity.created_at.desc()).limit(50)).all()
        for row in acts:
            events.append({"kind": "commercial", "title": row.title, "detail": row.notes, "at": row.created_at})

    events.sort(key=lambda row: row["at"], reverse=True)
    seen = set()
    result = []
    for row in events:
        key = (row["kind"], row["title"], row["at"])
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) >= 80:
            break
    return result
