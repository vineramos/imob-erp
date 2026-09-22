import calendar
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.agenda.logic import access_map, ensure_agenda_structure, require_schedule_access, user_available
from app.domains.agenda.models import AgendaTask
from app.domains.finance.service import administration_terms, money, suggested_monthly_charge_rules
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import AppUser, OrganizationSettings
from app.domains.leases.models import LeaseContract, LeaseContractVersion
from app.domains.leases.pdf import lease_contract_code
from app.domains.leases.schemas import LeaseMonthlyChargePayload
from app.domains.portfolio.models import Person, PersonRole, Property, PropertyOwner
from app.domains.portfolio.site_models import CommercialActivity, CommercialProposal, CommercialVisit, PublicSiteInquiry

router = APIRouter(tags=["commercial"])
GuaranteeType = Literal["insurance", "deposit", "capitalization", "guarantor", "none"]


class VisitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: datetime
    duration_minutes: int = Field(default=60, ge=15, le=480)
    responsible_user_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class VisitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "cancelled", "no_show"]
    notes: str | None = Field(default=None, max_length=2000)


class ProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rent_amount: Decimal = Field(gt=0, le=Decimal("999999999999.99"))
    start_date: date
    term_months: int = Field(default=30, ge=1, le=240)
    guarantee_type: GuaranteeType = "insurance"
    notes: str | None = Field(default=None, max_length=3000)


class ProposalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["accepted", "rejected", "withdrawn"]
    reason: str | None = Field(default=None, max_length=1000)


class ProposalLeaseConversion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monthly_charges: list[LeaseMonthlyChargePayload] = Field(default_factory=list, max_length=30)


class InquiryWorkflowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_status: Literal["new", "contacted", "visit_scheduled", "qualified", "proposal", "won", "lost"] | None = None
    responsible_user_id: UUID | None = None
    next_action_title: str | None = Field(default=None, max_length=180)
    next_action_at: datetime | None = None
    next_action_notes: str | None = Field(default=None, max_length=2000)


class CommercialActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=180)
    notes: str | None = Field(default=None, max_length=4000)
    activity_type: Literal["note", "contact", "follow_up", "document", "other"] = "note"


def _metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, action: str, kind: str, entity_id: UUID, *, before=None, after=None, reason=None) -> None:
    ip, agent = _metadata(request)
    write_audit(db, context=context, action=action, module="crm", entity_type=kind, entity_id=str(entity_id), before_data=before, after_data=after, reason=reason, ip_address=ip, user_agent=agent)


def _phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _inquiry(db: Session, org_id: UUID, inquiry_id: UUID) -> PublicSiteInquiry:
    item = db.scalar(select(PublicSiteInquiry).where(PublicSiteInquiry.id == inquiry_id, PublicSiteInquiry.organization_id == org_id))
    if item is None:
        raise HTTPException(404, "Interesse comercial não encontrado.")
    return item


def _proposal_record(db: Session, org_id: UUID, proposal_id: UUID) -> CommercialProposal:
    item = db.scalar(select(CommercialProposal).where(CommercialProposal.id == proposal_id, CommercialProposal.organization_id == org_id))
    if item is None:
        raise HTTPException(404, "Proposta comercial não encontrada.")
    return item


def _property(db: Session, inquiry: PublicSiteInquiry) -> Property:
    if inquiry.property_id is None:
        raise HTTPException(409, "O imóvel original deste interesse não está mais disponível no cadastro.")
    item = db.scalar(select(Property).options(selectinload(Property.owners).selectinload(PropertyOwner.person)).where(Property.id == inquiry.property_id, Property.organization_id == inquiry.organization_id))
    if item is None:
        raise HTTPException(409, "O imóvel original deste interesse não está mais disponível no cadastro.")
    return item


def _proposal_property(db: Session, proposal: CommercialProposal) -> Property:
    if proposal.property_id is None:
        raise HTTPException(409, "A proposta não possui imóvel vinculado.")
    item = db.scalar(select(Property).options(selectinload(Property.owners).selectinload(PropertyOwner.person)).where(Property.id == proposal.property_id, Property.organization_id == proposal.organization_id))
    if item is None:
        raise HTTPException(409, "O imóvel da proposta não está mais disponível no cadastro.")
    return item


def _tenant_role(person: Person) -> None:
    role = next((row for row in person.roles if row.role_key == "tenant"), None)
    if role is None:
        person.roles.append(PersonRole(role_key="tenant", is_active=True))
    else:
        role.is_active = True


def _person(db: Session, inquiry: PublicSiteInquiry, user_id: UUID) -> Person:
    if inquiry.person_id:
        linked = db.scalar(select(Person).options(selectinload(Person.roles)).where(Person.id == inquiry.person_id, Person.organization_id == inquiry.organization_id, Person.is_active.is_(True)))
        if linked:
            _tenant_role(linked)
            return linked
        inquiry.person_id = None

    email, phone = (inquiry.email or "").strip().lower(), _phone(inquiry.phone)
    predicates = []
    if email:
        predicates.append(func.lower(func.coalesce(Person.email, "")) == email)
    if phone:
        predicates.append(func.regexp_replace(func.coalesce(Person.phone, ""), r"\D", "", "g") == phone)
    candidates = db.scalars(select(Person).options(selectinload(Person.roles)).where(Person.organization_id == inquiry.organization_id, Person.is_active.is_(True), or_(*predicates)).limit(10)).unique().all() if predicates else []
    chosen = candidates[0] if len(candidates) == 1 else None
    if len(candidates) > 1:
        exact = [row for row in candidates if (not email or (row.email or "").strip().lower() == email) and (not phone or _phone(row.phone) == phone)]
        if len(exact) != 1:
            raise HTTPException(409, "Há mais de uma pessoa compatível com este contato. Revise o cadastro antes de continuar.")
        chosen = exact[0]
    if chosen is None:
        chosen = Person(organization_id=inquiry.organization_id, person_type="individual", name=inquiry.name.strip(), email=email or None, phone=phone or None, address={}, notes=f"Cadastro criado a partir do interesse do site no imóvel #{inquiry.property_code}.", created_by_user_id=user_id)
        chosen.roles = [PersonRole(role_key="tenant", is_active=True)]
        db.add(chosen)
        db.flush()
    else:
        _tenant_role(chosen)
        chosen.email = chosen.email or email or None
        chosen.phone = chosen.phone or phone or None
    inquiry.person_id = chosen.id
    return chosen


def _responsible(db: Session, context: UserContext, requested: UUID | None) -> AppUser:
    user_id = requested or context.user.id
    user = db.scalar(select(AppUser).where(AppUser.id == user_id, AppUser.organization_id == context.user.organization_id, AppUser.is_active.is_(True)))
    if user is None:
        raise HTTPException(422, "Responsável comercial não encontrado.")
    if user.id != context.user.id:
        require_schedule_access(access_map(db, context.user.organization_id, context.user.id), user.id)
    return user


def _location(address: dict) -> str | None:
    value = ", ".join(str(address.get(key)) for key in ("street", "number", "complement", "neighborhood", "city", "state") if address.get(key))
    return value or None


def _visit(db: Session, item: CommercialVisit) -> dict:
    user = db.get(AppUser, item.responsible_user_id) if item.responsible_user_id else None
    return {"id": item.id, "code": f"VIS-{item.internal_number:06d}", "inquiry_id": item.inquiry_id, "property_id": item.property_id, "person_id": item.person_id, "agenda_task_id": item.agenda_task_id, "responsible_user_id": item.responsible_user_id, "responsible_name": user.name if user else None, "starts_at": item.starts_at, "ends_at": item.ends_at, "status": item.status, "notes": item.notes, "created_at": item.created_at, "updated_at": item.updated_at}


def _proposal(db: Session, item: CommercialProposal) -> dict:
    lease = db.get(LeaseContract, item.lease_contract_id) if item.lease_contract_id else None
    return {"id": item.id, "code": f"PROP-{item.internal_number:06d}", "inquiry_id": item.inquiry_id, "property_id": item.property_id, "person_id": item.person_id, "responsible_user_id": item.responsible_user_id, "status": item.status, "rent_amount": item.rent_amount, "start_date": item.start_date, "term_months": item.term_months, "guarantee_type": item.guarantee_type, "notes": item.notes, "closed_reason": item.closed_reason, "accepted_at": item.accepted_at, "lease_contract_id": item.lease_contract_id, "lease_code": lease_contract_code(lease) if lease else None, "created_at": item.created_at, "updated_at": item.updated_at}


def _funnel(db: Session, inquiry: PublicSiteInquiry) -> dict:
    person = db.get(Person, inquiry.person_id) if inquiry.person_id else None
    prop = db.get(Property, inquiry.property_id) if inquiry.property_id else None
    responsible = db.get(AppUser, inquiry.responsible_user_id) if inquiry.responsible_user_id else None
    visits = db.scalars(select(CommercialVisit).where(CommercialVisit.organization_id == inquiry.organization_id, CommercialVisit.inquiry_id == inquiry.id).order_by(CommercialVisit.starts_at.desc())).all()
    proposals = db.scalars(select(CommercialProposal).where(CommercialProposal.organization_id == inquiry.organization_id, CommercialProposal.inquiry_id == inquiry.id).order_by(CommercialProposal.internal_number.desc())).all()
    activities = db.scalars(select(CommercialActivity).where(CommercialActivity.organization_id == inquiry.organization_id, CommercialActivity.inquiry_id == inquiry.id).order_by(CommercialActivity.created_at.desc())).all()
    timeline = [
        {"kind": "lead_created", "label": "Lead recebido", "detail": inquiry.source, "at": inquiry.created_at, "author_name": None},
        {"kind": "status", "label": "Etapa atual", "detail": inquiry.status, "at": inquiry.updated_at, "author_name": None},
    ]
    if inquiry.next_action_title and inquiry.next_action_at:
        timeline.append({"kind": "next_action", "label": inquiry.next_action_title, "detail": inquiry.next_action_notes, "at": inquiry.next_action_at, "author_name": None})
    for row in visits:
        timeline.append({"kind": "visit", "label": f"VIS-{row.internal_number:06d} · visita", "detail": row.status, "at": row.starts_at, "author_name": None})
    for row in proposals:
        timeline.append({"kind": "proposal", "label": f"PROP-{row.internal_number:06d} · proposta", "detail": row.status, "at": row.created_at, "author_name": None})
    for row in activities:
        author = db.get(AppUser, row.created_by_user_id) if row.created_by_user_id else None
        timeline.append({"kind": "manual", "label": row.title, "detail": row.notes, "at": row.created_at, "author_name": author.name if author else None})
    timeline.sort(key=lambda event: event["at"] or inquiry.created_at, reverse=True)
    return {
        "inquiry": {"id": inquiry.id, "property_id": inquiry.property_id, "property_code": inquiry.property_code, "property_title": inquiry.property_title, "name": inquiry.name, "email": inquiry.email, "phone": inquiry.phone, "preferred_contact": inquiry.preferred_contact, "message": inquiry.message, "status": inquiry.status, "source": inquiry.source, "responsible_user_id": inquiry.responsible_user_id, "next_action_title": inquiry.next_action_title, "next_action_at": inquiry.next_action_at, "next_action_notes": inquiry.next_action_notes, "created_at": inquiry.created_at, "updated_at": inquiry.updated_at},
        "responsible": {"id": responsible.id, "name": responsible.name, "email": responsible.email} if responsible else None,
        "person": {"id": person.id, "name": person.name, "document_number": person.document_number, "email": person.email, "phone": person.phone} if person else None,
        "property_status": prop.status if prop else None,
        "property_publication_enabled": bool(prop.publication_enabled) if prop else False,
        "suggested_rent_amount": prop.rent_amount if prop else None,
        "visits": [_visit(db, row) for row in visits],
        "proposals": [_proposal(db, row) for row in proposals],
        "timeline": timeline,
    }

def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _suggested_conversion_charges(db: Session, proposal: CommercialProposal, prop: Property) -> list[dict]:
    end_date = _add_months(proposal.start_date, proposal.term_months)
    rows = suggested_monthly_charge_rules(prop, administration_terms(db, proposal.organization_id, prop.id))
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        item["start_date"] = proposal.start_date.isoformat()
        item["end_date"] = end_date.isoformat()
        result.append(item)
    return result


def _validate_conversion_charges(proposal: CommercialProposal, charges: list[LeaseMonthlyChargePayload]) -> list[dict]:
    end_date = _add_months(proposal.start_date, proposal.term_months)
    result: list[dict] = []
    for charge in charges:
        if charge.start_date and charge.start_date < proposal.start_date:
            raise HTTPException(422, f"A vigência de {charge.label} não pode começar antes da locação.")
        if charge.end_date and charge.end_date > end_date:
            raise HTTPException(422, f"A vigência de {charge.label} não pode terminar depois da locação.")
        result.append(charge.model_dump(mode="json"))
    return result


def _lease_from_proposal(db: Session, proposal: CommercialProposal, context: UserContext, charges: list[dict]) -> LeaseContract:
    if proposal.property_id is None or proposal.person_id is None:
        raise HTTPException(409, "A proposta não possui imóvel e interessado vinculados.")
    prop = _proposal_property(db, proposal)
    tenant = db.scalar(select(Person).where(Person.id == proposal.person_id, Person.organization_id == proposal.organization_id, Person.is_active.is_(True)))
    if tenant is None:
        raise HTTPException(409, "O interessado da proposta não está mais disponível.")
    if not prop.owners or sum((row.ownership_percent for row in prop.owners), Decimal("0")) != Decimal("100"):
        raise HTTPException(422, "O imóvel precisa ter proprietário(s) totalizando 100% antes do contrato.")
    if db.scalar(select(LeaseContract.id).where(LeaseContract.organization_id == proposal.organization_id, LeaseContract.property_id == prop.id, LeaseContract.status.not_in(("cancelled", "closed"))).limit(1)):
        raise HTTPException(409, "Este imóvel já possui contrato de locação em andamento ou vigente.")

    end_date, next_adjustment = _add_months(proposal.start_date, proposal.term_months), _add_months(proposal.start_date, 12)
    property_snapshot = {"property_id": str(prop.id), "code": f"{prop.internal_number:06d}", "property_type": prop.property_type, "purpose": prop.purpose, "address": dict(prop.address or {}), "rent_amount": str(proposal.rent_amount)}
    owners = [{"person_id": str(row.person_id), "name": row.person.name, "document_number": row.person.document_number, "email": row.person.email, "phone": row.person.phone, "ownership_percent": str(row.ownership_percent)} for row in prop.owners]
    tenants = [{"person_id": str(tenant.id), "name": tenant.name, "document_number": tenant.document_number, "email": tenant.email, "phone": tenant.phone}]
    signers = [{"role": role, "name": party.get("name") or "", "email": party.get("email") or "", "document_number": party.get("document_number"), "phone": party.get("phone"), "sign_order": 1, "communication": "email"} for role, parties in (("owner", owners), ("tenant", tenants)) for party in parties]
    rules = {"rent_amount": str(proposal.rent_amount), "due_day": 10, "adjustment_index": "IPCA", "adjustment_period_months": 12, "adjustment_base_date": proposal.start_date.isoformat(), "next_adjustment_date": next_adjustment.isoformat(), "term_months": proposal.term_months, "start_date": proposal.start_date.isoformat(), "end_date": end_date.isoformat(), "termination_fine_months": "3", "inspection_contest_days": 5, "guarantee_type": proposal.guarantee_type, "guarantee_details": {}, "monthly_charges": charges, "notes": proposal.notes}
    settings = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == proposal.organization_id))
    provider = str(((settings.integrations if settings else {}) or {}).get("signature_provider") or "clicksign")
    lease = LeaseContract(organization_id=proposal.organization_id, property_id=prop.id, status="draft", rent_amount=proposal.rent_amount, due_day=10, adjustment_index="IPCA", adjustment_period_months=12, adjustment_base_date=proposal.start_date, next_adjustment_date=next_adjustment, term_months=proposal.term_months, start_date=proposal.start_date, end_date=end_date, termination_fine_months=Decimal("3"), inspection_contest_days=5, guarantee_type=proposal.guarantee_type, guarantee_details={}, property_snapshot=property_snapshot, owner_snapshot=owners, tenant_snapshot=tenants, rules_snapshot=rules, signers_snapshot=signers, current_version=1, notes=(proposal.notes or "").strip() or f"Gerado a partir da PROP-{proposal.internal_number:06d}.", signing_provider=provider, signing_status="not_prepared", signing_metadata={}, archive_status="not_started", created_by_user_id=context.user.id)
    db.add(lease); db.flush()
    db.add(LeaseContractVersion(contract_id=lease.id, version_number=1, snapshot={"property": property_snapshot, "owners": owners, "tenants": tenants, "rules": rules, "signers": signers}, change_summary=f"Gerado da proposta PROP-{proposal.internal_number:06d}", created_by_user_id=context.user.id))
    return lease


@router.get("/crm/brokers/{person_id}/activity")
def broker_commercial_activity(person_id: UUID, context: UserContext = Depends(require_permission("crm.view")), db: Session = Depends(get_db)):
    broker = db.scalar(
        select(Person).options(selectinload(Person.roles)).where(
            Person.id == person_id,
            Person.organization_id == context.user.organization_id,
            Person.is_active.is_(True),
        )
    )
    if broker is None or not any(role.role_key == "broker" and role.is_active for role in broker.roles):
        raise HTTPException(404, "Corretor não encontrado.")

    linked_user = None
    if broker.email:
        linked_user = db.scalar(
            select(AppUser).where(
                AppUser.organization_id == context.user.organization_id,
                AppUser.is_active.is_(True),
                func.lower(AppUser.email) == broker.email.strip().lower(),
            )
        )

    if linked_user is None:
        return {
            "broker_person_id": broker.id,
            "linked_user": None,
            "link_status": "missing_user_link",
            "leads": [],
            "visits": [],
            "proposals": [],
        }

    inquiries = db.scalars(
        select(PublicSiteInquiry).where(
            PublicSiteInquiry.organization_id == context.user.organization_id,
            PublicSiteInquiry.responsible_user_id == linked_user.id,
        ).order_by(PublicSiteInquiry.updated_at.desc()).limit(100)
    ).all()
    visits = db.scalars(
        select(CommercialVisit).where(
            CommercialVisit.organization_id == context.user.organization_id,
            CommercialVisit.responsible_user_id == linked_user.id,
        ).order_by(CommercialVisit.starts_at.desc()).limit(100)
    ).all()
    proposals = db.scalars(
        select(CommercialProposal).where(
            CommercialProposal.organization_id == context.user.organization_id,
            CommercialProposal.responsible_user_id == linked_user.id,
        ).order_by(CommercialProposal.internal_number.desc()).limit(100)
    ).all()

    inquiry_map = {row.id: row for row in inquiries}
    for row in visits:
        if row.inquiry_id not in inquiry_map:
            inquiry_map[row.inquiry_id] = db.get(PublicSiteInquiry, row.inquiry_id)
    for row in proposals:
        if row.inquiry_id not in inquiry_map:
            inquiry_map[row.inquiry_id] = db.get(PublicSiteInquiry, row.inquiry_id)

    return {
        "broker_person_id": broker.id,
        "linked_user": {"id": linked_user.id, "name": linked_user.name, "email": linked_user.email},
        "link_status": "linked_by_email",
        "leads": [
            {
                "id": row.id,
                "property_code": row.property_code,
                "property_title": row.property_title,
                "name": row.name,
                "email": row.email,
                "phone": row.phone,
                "status": row.status,
                "next_action_title": row.next_action_title,
                "next_action_at": row.next_action_at,
                "updated_at": row.updated_at,
            }
            for row in inquiries
        ],
        "visits": [
            {
                **_visit(db, row),
                "lead_name": inquiry_map[row.inquiry_id].name if inquiry_map.get(row.inquiry_id) else None,
                "property_code": inquiry_map[row.inquiry_id].property_code if inquiry_map.get(row.inquiry_id) else None,
                "property_title": inquiry_map[row.inquiry_id].property_title if inquiry_map.get(row.inquiry_id) else None,
            }
            for row in visits
        ],
        "proposals": [
            {
                **_proposal(db, row),
                "lead_name": inquiry_map[row.inquiry_id].name if inquiry_map.get(row.inquiry_id) else None,
                "property_code": inquiry_map[row.inquiry_id].property_code if inquiry_map.get(row.inquiry_id) else None,
                "property_title": inquiry_map[row.inquiry_id].property_title if inquiry_map.get(row.inquiry_id) else None,
            }
            for row in proposals
        ],
    }


@router.get("/crm/responsibles")
def list_crm_responsibles(context: UserContext = Depends(require_permission("crm.view")), db: Session = Depends(get_db)):
    rows = db.scalars(select(AppUser).where(AppUser.organization_id == context.user.organization_id, AppUser.is_active.is_(True)).order_by(AppUser.name.asc())).all()
    return [{"id": row.id, "name": row.name, "email": row.email} for row in rows]


@router.patch("/crm/site-inquiries/{inquiry_id}/workflow")
def update_inquiry_workflow(inquiry_id: UUID, payload: InquiryWorkflowUpdate, request: Request, context: UserContext = Depends(require_permission("crm.manage")), db: Session = Depends(get_db)):
    inquiry = _inquiry(db, context.user.organization_id, inquiry_id)
    before = {"status": inquiry.status, "responsible_user_id": str(inquiry.responsible_user_id) if inquiry.responsible_user_id else None, "next_action_title": inquiry.next_action_title, "next_action_at": inquiry.next_action_at.isoformat() if inquiry.next_action_at else None, "next_action_notes": inquiry.next_action_notes}
    if "stage_status" in payload.model_fields_set and payload.stage_status is not None:
        inquiry.status = payload.stage_status
    if "responsible_user_id" in payload.model_fields_set:
        if payload.responsible_user_id is None:
            inquiry.responsible_user_id = None
        else:
            user = db.scalar(select(AppUser).where(AppUser.id == payload.responsible_user_id, AppUser.organization_id == context.user.organization_id, AppUser.is_active.is_(True)))
            if user is None:
                raise HTTPException(422, "Responsável comercial não encontrado.")
            inquiry.responsible_user_id = user.id
    if "next_action_title" in payload.model_fields_set:
        inquiry.next_action_title = (payload.next_action_title or "").strip() or None
    if "next_action_at" in payload.model_fields_set:
        if payload.next_action_at is not None and payload.next_action_at.tzinfo is None:
            raise HTTPException(422, "Informe data e hora da próxima ação com fuso horário.")
        inquiry.next_action_at = payload.next_action_at
    if "next_action_notes" in payload.model_fields_set:
        inquiry.next_action_notes = (payload.next_action_notes or "").strip() or None
    if inquiry.next_action_at and not inquiry.next_action_title:
        raise HTTPException(422, "Informe o título da próxima ação.")
    after = {"status": inquiry.status, "responsible_user_id": str(inquiry.responsible_user_id) if inquiry.responsible_user_id else None, "next_action_title": inquiry.next_action_title, "next_action_at": inquiry.next_action_at.isoformat() if inquiry.next_action_at else None, "next_action_notes": inquiry.next_action_notes}
    _audit(db, request, context, "crm.inquiry.workflow.updated", "public_site_inquiry", inquiry.id, before=before, after=after)
    db.commit()
    db.refresh(inquiry)
    responsible = db.get(AppUser, inquiry.responsible_user_id) if inquiry.responsible_user_id else None
    return {"id": inquiry.id, "status": inquiry.status, "responsible_user_id": inquiry.responsible_user_id, "responsible_name": responsible.name if responsible else None, "next_action_title": inquiry.next_action_title, "next_action_at": inquiry.next_action_at, "next_action_notes": inquiry.next_action_notes}


@router.post("/crm/site-inquiries/{inquiry_id}/activities", status_code=status.HTTP_201_CREATED)
def create_commercial_activity(inquiry_id: UUID, payload: CommercialActivityCreate, request: Request, context: UserContext = Depends(require_permission("crm.manage")), db: Session = Depends(get_db)):
    inquiry = _inquiry(db, context.user.organization_id, inquiry_id)
    item = CommercialActivity(
        organization_id=context.user.organization_id,
        inquiry_id=inquiry.id,
        activity_type=payload.activity_type,
        title=payload.title.strip(),
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    _audit(db, request, context, "crm.activity.created", "commercial_activity", item.id, after={"inquiry_id": str(inquiry.id), "activity_type": item.activity_type, "title": item.title})
    db.commit()
    db.refresh(item)
    return {"id": item.id, "kind": "manual", "label": item.title, "detail": item.notes, "at": item.created_at, "author_name": context.user.name}


@router.get("/crm/site-inquiries/{inquiry_id}/funnel")
def get_funnel(inquiry_id: UUID, context: UserContext = Depends(require_permission("crm.view")), db: Session = Depends(get_db)):
    return _funnel(db, _inquiry(db, context.user.organization_id, inquiry_id))


@router.post("/crm/site-inquiries/{inquiry_id}/visits", status_code=status.HTTP_201_CREATED)
def create_visit(inquiry_id: UUID, payload: VisitCreate, request: Request, context: UserContext = Depends(require_permission("crm.manage")), db: Session = Depends(get_db)):
    if payload.starts_at.tzinfo is None:
        raise HTTPException(422, "Informe data e hora da visita com fuso horário.")
    inquiry = _inquiry(db, context.user.organization_id, inquiry_id)
    prop = _property(db, inquiry)
    if prop.status not in {"available", "reserved"}:
        raise HTTPException(409, "Este imóvel não está disponível para agendamento de visita.")
    person, responsible = _person(db, inquiry, context.user.id), _responsible(db, context, payload.responsible_user_id)
    starts, ends = payload.starts_at, payload.starts_at + timedelta(minutes=payload.duration_minutes)
    available, reason = user_available(db, context.user.organization_id, responsible.id, starts, ends)
    if not available:
        raise HTTPException(409, f"Horário indisponível para {responsible.name}: {reason or 'conflito de agenda'}.")
    _, profiles, _ = ensure_agenda_structure(db, context.user.organization_id)
    visit = CommercialVisit(organization_id=context.user.organization_id, inquiry_id=inquiry.id, property_id=prop.id, person_id=person.id, responsible_user_id=responsible.id, starts_at=starts, ends_at=ends, status="scheduled", notes=(payload.notes or "").strip() or None, created_by_user_id=context.user.id)
    db.add(visit); db.flush()
    task = AgendaTask(organization_id=context.user.organization_id, title=f"Visita · Imóvel #{inquiry.property_code} · {person.name}", description=(payload.notes or inquiry.message or "Visita originada pelo atendimento comercial do site.").strip(), kind="visit", starts_at=starts, ends_at=ends, due_at=starts, all_day=False, priority="normal", status="pending", privacy="normal", location=_location(prop.address or {}), assigned_user_id=responsible.id, department_id=profiles[responsible.id].department_id, source_module="crm", source_type="commercial_visit", source_id=str(visit.id), automatic=False, mandatory_action=False, completion_source="agenda", original_scheduled_at=starts, created_by_user_id=context.user.id)
    db.add(task); db.flush()
    visit.agenda_task_id, inquiry.responsible_user_id, inquiry.status = task.id, responsible.id, "visit_scheduled"
    _audit(db, request, context, "crm.visit.scheduled", "commercial_visit", visit.id, after={"inquiry_id": str(inquiry.id), "property_id": str(prop.id), "person_id": str(person.id), "agenda_task_id": str(task.id), "starts_at": starts.isoformat()})
    db.commit(); db.refresh(visit)
    return _visit(db, visit)


@router.patch("/crm/visits/{visit_id}")
def update_visit(visit_id: UUID, payload: VisitUpdate, request: Request, context: UserContext = Depends(require_permission("crm.manage")), db: Session = Depends(get_db)):
    visit = db.scalar(select(CommercialVisit).where(CommercialVisit.id == visit_id, CommercialVisit.organization_id == context.user.organization_id))
    if visit is None:
        raise HTTPException(404, "Visita comercial não encontrada.")
    if visit.status != "scheduled":
        raise HTTPException(409, "Esta visita já foi encerrada.")
    before, visit.status = visit.status, payload.status
    if payload.notes is not None:
        visit.notes = payload.notes.strip() or None
    task = db.get(AgendaTask, visit.agenda_task_id) if visit.agenda_task_id else None
    if task:
        task.status, task.completion_source = ("completed" if payload.status == "completed" else "cancelled"), "crm"
        if payload.status == "completed":
            task.completed_at, task.completed_by_user_id = datetime.now(timezone.utc), context.user.id
    inquiry = _inquiry(db, context.user.organization_id, visit.inquiry_id)
    if inquiry.status == "visit_scheduled":
        inquiry.status = "qualified" if payload.status == "completed" else "contacted"
    _audit(db, request, context, f"crm.visit.{payload.status}", "commercial_visit", visit.id, before={"status": before}, after={"status": visit.status, "agenda_status": task.status if task else None}, reason=(payload.notes or "").strip() or None)
    db.commit(); db.refresh(visit)
    return _visit(db, visit)


@router.post("/crm/site-inquiries/{inquiry_id}/proposals", status_code=status.HTTP_201_CREATED)
def create_proposal(inquiry_id: UUID, payload: ProposalCreate, request: Request, context: UserContext = Depends(require_permission("crm.manage")), db: Session = Depends(get_db)):
    inquiry = _inquiry(db, context.user.organization_id, inquiry_id)
    prop = _property(db, inquiry)
    if prop.status != "available":
        raise HTTPException(409, "Este imóvel não está disponível para uma nova proposta.")
    person = _person(db, inquiry, context.user.id)
    if db.scalar(select(CommercialProposal.id).where(CommercialProposal.organization_id == context.user.organization_id, CommercialProposal.inquiry_id == inquiry.id, CommercialProposal.status.in_(("submitted", "accepted", "converted", "won"))).limit(1)):
        raise HTTPException(409, "Este atendimento já possui uma proposta ativa.")
    proposal = CommercialProposal(organization_id=context.user.organization_id, inquiry_id=inquiry.id, property_id=prop.id, person_id=person.id, responsible_user_id=inquiry.responsible_user_id or context.user.id, status="submitted", rent_amount=payload.rent_amount, start_date=payload.start_date, term_months=payload.term_months, guarantee_type=payload.guarantee_type, notes=(payload.notes or "").strip() or None, created_by_user_id=context.user.id)
    db.add(proposal); db.flush(); inquiry.status = "proposal"
    _audit(db, request, context, "crm.proposal.created", "commercial_proposal", proposal.id, after={"code": f"PROP-{proposal.internal_number:06d}", "property_id": str(prop.id), "person_id": str(person.id), "rent_amount": str(proposal.rent_amount)})
    db.commit(); db.refresh(proposal)
    return _proposal(db, proposal)


@router.patch("/crm/proposals/{proposal_id}")
def update_proposal(proposal_id: UUID, payload: ProposalUpdate, request: Request, context: UserContext = Depends(require_permission("crm.manage")), db: Session = Depends(get_db)):
    proposal = _proposal_record(db, context.user.organization_id, proposal_id)
    if proposal.status in {"converted", "won", "rejected", "withdrawn"}:
        raise HTTPException(409, "Esta proposta já está encerrada.")
    if payload.status in {"rejected", "withdrawn"} and not (payload.reason or "").strip():
        raise HTTPException(422, "Informe o motivo do encerramento da proposta.")
    before = proposal.status
    proposal.status, proposal.closed_reason = payload.status, (payload.reason or "").strip() or None
    proposal.accepted_at = datetime.now(timezone.utc) if payload.status == "accepted" else None
    inquiry = _inquiry(db, context.user.organization_id, proposal.inquiry_id)
    inquiry.status = "proposal" if payload.status == "accepted" else ("qualified" if inquiry.status == "proposal" else inquiry.status)
    _audit(db, request, context, f"crm.proposal.{payload.status}", "commercial_proposal", proposal.id, before={"status": before}, after={"status": proposal.status}, reason=proposal.closed_reason)
    db.commit(); db.refresh(proposal)
    return _proposal(db, proposal)


@router.get("/crm/proposals/{proposal_id}/lease-composition")
def proposal_lease_composition(proposal_id: UUID, context: UserContext = Depends(require_permission("crm.manage")), db: Session = Depends(get_db)):
    if not context.has("contracts.create"):
        raise HTTPException(403, "Permissão necessária: contracts.create")
    proposal = _proposal_record(db, context.user.organization_id, proposal_id)
    if proposal.status != "accepted":
        raise HTTPException(409, "A proposta precisa estar aceita para preparar a composição da locação.")
    prop = _proposal_property(db, proposal)
    charges = _suggested_conversion_charges(db, proposal, prop)
    monthly_extras = sum((money(item.get("amount")) for item in charges if item.get("active") and item.get("payer") == "tenant" and item.get("include_in_invoice", True) is not False and item.get("frequency") == "monthly"), Decimal("0.00"))
    return {
        "proposal_id": str(proposal.id),
        "rent_amount": str(money(proposal.rent_amount)),
        "start_date": proposal.start_date,
        "end_date": _add_months(proposal.start_date, proposal.term_months),
        "monthly_charges": charges,
        "tenant_monthly_total": str(money(proposal.rent_amount) + monthly_extras),
    }


@router.post("/crm/proposals/{proposal_id}/convert-to-lease", status_code=status.HTTP_201_CREATED)
def convert_proposal(proposal_id: UUID, payload: ProposalLeaseConversion | None, request: Request, context: UserContext = Depends(require_permission("crm.manage")), db: Session = Depends(get_db)):
    if not context.has("contracts.create"):
        raise HTTPException(403, "Permissão necessária: contracts.create")
    proposal = _proposal_record(db, context.user.organization_id, proposal_id)
    if proposal.status != "accepted":
        raise HTTPException(409, "A proposta precisa estar aceita antes de gerar o contrato.")
    prop = _proposal_property(db, proposal)
    charges = _validate_conversion_charges(proposal, payload.monthly_charges) if payload is not None else _suggested_conversion_charges(db, proposal, prop)
    lease = _lease_from_proposal(db, proposal, context, charges)
    proposal.status, proposal.lease_contract_id = "converted", lease.id
    inquiry = _inquiry(db, context.user.organization_id, proposal.inquiry_id)
    inquiry.status = "converted"
    _audit(db, request, context, "crm.proposal.converted_to_lease", "commercial_proposal", proposal.id, before={"status": "accepted"}, after={"status": "converted", "lease_contract_id": str(lease.id), "lease_code": lease_contract_code(lease), "property_status": "unchanged_until_signature", "charge_count": len(charges)})
    db.commit(); db.refresh(proposal)
    return {"proposal": _proposal(db, proposal), "lease_contract_id": lease.id, "lease_code": lease_contract_code(lease), "lease_status": lease.status, "message": "Contrato de locação criado em rascunho com a composição financeira definida. O imóvel permanece no estoque até a assinatura final."}
