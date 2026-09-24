from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.contracts.models import AdministrationContract
from app.domains.foundation.access import UserContext, require_permission
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Capture, Person, Property, PropertyOwner
from app.domains.portfolio.site_models import CommercialProposal, CommercialVisit, PublicSiteInquiry
from app.domains.inspections.models import Inspection
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.finance.models import RentCharge

router = APIRouter(tags=["property-lifecycle"])


def _person_payload(person: Person | None) -> dict[str, Any] | None:
    if person is None:
        return None
    return {
        "id": str(person.id),
        "name": person.name,
        "document_number": person.document_number,
        "role_keys": sorted(role.role_key for role in person.roles if role.is_active),
    }


def _contract_payload(contract: AdministrationContract | None) -> dict[str, Any] | None:
    if contract is None:
        return None
    return {
        "id": str(contract.id),
        "code": f"ADM-{int(contract.internal_number):06d}",
        "property_id": str(contract.property_id),
        "status": contract.status,
        "signing_status": contract.signing_status,
        "signed_at": contract.signed_at,
        "current_version": contract.current_version,
    }


def _capture_payload(capture: Capture | None) -> dict[str, Any] | None:
    if capture is None:
        return None
    return {
        "id": str(capture.id),
        "code": f"CAP-{str(capture.id).split('-')[0].upper()}",
        "status": capture.status,
        "source": capture.source,
        "contact_person_id": str(capture.contact_person_id) if capture.contact_person_id else None,
        "property_id": str(capture.converted_property_id) if capture.converted_property_id else None,
    }



def _timeline_payload(db: Session, organization_id: UUID, property_item: Property) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add_event(
        *,
        event_id: str,
        kind: str,
        stage: str,
        title: str,
        detail: str,
        occurred_at,
        status_value: str | None = None,
        code: str | None = None,
        route: str | None = None,
    ) -> None:
        if occurred_at is None:
            return
        events.append({
            "id": event_id,
            "kind": kind,
            "stage": stage,
            "title": title,
            "detail": detail,
            "occurred_at": occurred_at,
            "status": status_value,
            "code": code,
            "route": route,
        })

    capture_rows = db.execute(
        select(Capture.id, Capture.status, Capture.source, Capture.created_at)
        .where(
            Capture.organization_id == organization_id,
            Capture.converted_property_id == property_item.id,
        )
        .order_by(Capture.created_at.desc())
        .limit(5)
    ).all()
    for capture_id, capture_status, source, created_at in capture_rows:
        add_event(
            event_id=f"capture:{capture_id}",
            kind="capture",
            stage="acquisition",
            title="Captação vinculada",
            detail=f"Origem {source or 'não informada'}",
            occurred_at=created_at,
            status_value=capture_status,
            code=f"CAP-{str(capture_id).split('-')[0].upper()}",
            route="/app/captures",
        )

    add_event(
        event_id=f"property:{property_item.id}",
        kind="property",
        stage="acquisition",
        title="Imóvel cadastrado",
        detail=f"Imóvel IMO-{int(property_item.internal_number):06d}",
        occurred_at=property_item.created_at,
        status_value=property_item.status,
        code=f"IMO-{int(property_item.internal_number):06d}",
        route=f"/app/properties/{property_item.id}",
    )
    if property_item.published_at:
        add_event(
            event_id=f"publication:{property_item.id}",
            kind="publication",
            stage="commercial",
            title="Imóvel publicado",
            detail="Anúncio disponibilizado no site público",
            occurred_at=property_item.published_at,
            status_value="active" if property_item.publication_enabled else "inactive",
            code=f"IMO-{int(property_item.internal_number):06d}",
            route=f"/app/properties/{property_item.id}",
        )

    admin_rows = db.execute(
        select(
            AdministrationContract.id,
            AdministrationContract.internal_number,
            AdministrationContract.status,
            AdministrationContract.created_at,
            AdministrationContract.signed_at,
        )
        .where(
            AdministrationContract.organization_id == organization_id,
            AdministrationContract.property_id == property_item.id,
        )
        .order_by(AdministrationContract.created_at.desc())
        .limit(10)
    ).all()
    for contract_id, internal_number, contract_status, created_at, signed_at in admin_rows:
        code = f"ADM-{int(internal_number):06d}"
        route = f"/app/contracts/administration/{contract_id}"
        add_event(event_id=f"administration-created:{contract_id}", kind="administration", stage="contract", title="Contrato de administração criado", detail=code, occurred_at=created_at, status_value=contract_status, code=code, route=route)
        if signed_at:
            add_event(event_id=f"administration-signed:{contract_id}", kind="administration", stage="contract", title="Administração assinada", detail=code, occurred_at=signed_at, status_value="signed", code=code, route=route)

    inquiry_rows = db.execute(
        select(PublicSiteInquiry.id, PublicSiteInquiry.status, PublicSiteInquiry.source, PublicSiteInquiry.name, PublicSiteInquiry.created_at)
        .where(
            PublicSiteInquiry.organization_id == organization_id,
            PublicSiteInquiry.property_id == property_item.id,
        )
        .order_by(PublicSiteInquiry.created_at.desc())
        .limit(25)
    ).all()
    for inquiry_id, inquiry_status, source, name, created_at in inquiry_rows:
        add_event(
            event_id=f"inquiry:{inquiry_id}",
            kind="lead",
            stage="commercial",
            title="Lead recebido",
            detail=f"{name or 'Interessado'} · {source or 'origem não informada'}",
            occurred_at=created_at,
            status_value=inquiry_status,
            code=f"LEAD-{str(inquiry_id).split('-')[0].upper()}",
            route="/app/crm",
        )

    visit_rows = db.execute(
        select(CommercialVisit.id, CommercialVisit.internal_number, CommercialVisit.status, CommercialVisit.starts_at)
        .where(
            CommercialVisit.organization_id == organization_id,
            CommercialVisit.property_id == property_item.id,
        )
        .order_by(CommercialVisit.starts_at.desc())
        .limit(25)
    ).all()
    for visit_id, internal_number, visit_status, starts_at in visit_rows:
        code = f"VIS-{int(internal_number):06d}"
        add_event(event_id=f"visit:{visit_id}", kind="visit", stage="commercial", title="Visita ao imóvel", detail=code, occurred_at=starts_at, status_value=visit_status, code=code, route="/app/crm")

    proposal_rows = db.execute(
        select(
            CommercialProposal.id,
            CommercialProposal.internal_number,
            CommercialProposal.status,
            CommercialProposal.rent_amount,
            CommercialProposal.created_at,
            CommercialProposal.accepted_at,
        )
        .where(
            CommercialProposal.organization_id == organization_id,
            CommercialProposal.property_id == property_item.id,
        )
        .order_by(CommercialProposal.created_at.desc())
        .limit(25)
    ).all()
    for proposal_id, internal_number, proposal_status, rent_amount, created_at, accepted_at in proposal_rows:
        code = f"PROP-{int(internal_number):06d}"
        add_event(event_id=f"proposal:{proposal_id}", kind="proposal", stage="commercial", title="Proposta registrada", detail=f"{code} · R$ {float(rent_amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), occurred_at=created_at, status_value=proposal_status, code=code, route="/app/crm")
        if accepted_at:
            add_event(event_id=f"proposal-accepted:{proposal_id}", kind="proposal", stage="commercial", title="Proposta aceita", detail=code, occurred_at=accepted_at, status_value="accepted", code=code, route="/app/crm")

    lease_rows = db.execute(
        select(
            LeaseContract.id,
            LeaseContract.internal_number,
            LeaseContract.status,
            LeaseContract.created_at,
            LeaseContract.signed_at,
            LeaseContract.closed_at,
        )
        .where(
            LeaseContract.organization_id == organization_id,
            LeaseContract.property_id == property_item.id,
        )
        .order_by(LeaseContract.created_at.desc())
        .limit(15)
    ).all()
    for lease_id, internal_number, lease_status, created_at, signed_at, closed_at in lease_rows:
        code = f"LOC-{int(internal_number):06d}"
        route = f"/app/contracts/lease/{lease_id}"
        add_event(event_id=f"lease-created:{lease_id}", kind="lease", stage="contract", title="Contrato de locação criado", detail=code, occurred_at=created_at, status_value=lease_status, code=code, route=route)
        if signed_at:
            add_event(event_id=f"lease-signed:{lease_id}", kind="lease", stage="contract", title="Locação assinada", detail=code, occurred_at=signed_at, status_value="signed", code=code, route=route)
        if closed_at:
            add_event(event_id=f"lease-closed:{lease_id}", kind="lease", stage="contract", title="Locação encerrada", detail=code, occurred_at=closed_at, status_value="closed", code=code, route=route)

    inspection_rows = db.execute(
        select(
            Inspection.id,
            Inspection.internal_number,
            Inspection.inspection_type,
            Inspection.status,
            Inspection.created_at,
            Inspection.finalized_at,
        )
        .where(
            Inspection.organization_id == organization_id,
            Inspection.property_id == property_item.id,
        )
        .order_by(Inspection.created_at.desc())
        .limit(20)
    ).all()
    for inspection_id, internal_number, inspection_type, inspection_status, created_at, finalized_at in inspection_rows:
        code = f"VIS-{int(internal_number):06d}"
        route = f"/app/inspections/{inspection_id}"
        add_event(event_id=f"inspection-created:{inspection_id}", kind="inspection", stage="operation", title="Vistoria criada", detail=f"{code} · {inspection_type}", occurred_at=created_at, status_value=inspection_status, code=code, route=route)
        if finalized_at:
            add_event(event_id=f"inspection-finalized:{inspection_id}", kind="inspection", stage="operation", title="Vistoria finalizada", detail=code, occurred_at=finalized_at, status_value="finalized", code=code, route=route)

    charge_rows = db.execute(
        select(
            RentCharge.id,
            RentCharge.internal_number,
            RentCharge.status,
            RentCharge.gross_amount,
            RentCharge.competence,
            RentCharge.created_at,
            RentCharge.paid_at,
        )
        .where(
            RentCharge.organization_id == organization_id,
            RentCharge.property_id == property_item.id,
        )
        .order_by(RentCharge.created_at.desc())
        .limit(24)
    ).all()
    for charge_id, internal_number, charge_status, gross_amount, competence, created_at, paid_at in charge_rows:
        code = f"COB-{int(internal_number):06d}"
        amount = f"R$ {float(gross_amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        competence_label = competence.strftime("%m/%Y")
        add_event(
            event_id=f"charge:{charge_id}",
            kind="finance",
            stage="finance",
            title="Cobrança recebida" if paid_at else "Cobrança gerada",
            detail=f"{code} · {competence_label} · {amount}",
            occurred_at=paid_at or created_at,
            status_value=charge_status,
            code=code,
            route=f"/app/finance/charge/{charge_id}",
        )

    maintenance_rows = db.execute(
        select(
            MaintenanceRequest.id,
            MaintenanceRequest.internal_number,
            MaintenanceRequest.title,
            MaintenanceRequest.status,
            MaintenanceRequest.reported_at,
            MaintenanceRequest.completed_at,
        )
        .where(
            MaintenanceRequest.organization_id == organization_id,
            MaintenanceRequest.property_id == property_item.id,
        )
        .order_by(MaintenanceRequest.reported_at.desc())
        .limit(20)
    ).all()
    for maintenance_id, internal_number, title, maintenance_status, reported_at, completed_at in maintenance_rows:
        code = f"MAN-{int(internal_number):06d}"
        route = f"/app/maintenance/{maintenance_id}"
        add_event(event_id=f"maintenance-open:{maintenance_id}", kind="maintenance", stage="maintenance", title="Manutenção aberta", detail=f"{code} · {title}", occurred_at=reported_at, status_value=maintenance_status, code=code, route=route)
        if completed_at:
            add_event(event_id=f"maintenance-completed:{maintenance_id}", kind="maintenance", stage="maintenance", title="Manutenção concluída", detail=f"{code} · {title}", occurred_at=completed_at, status_value="completed", code=code, route=route)

    events.sort(key=lambda event: event["occurred_at"], reverse=True)
    return events[:80]


def _property_lifecycle_payload(db: Session, organization_id: UUID, property_item: Property) -> dict[str, Any]:
    owners = db.scalars(
        select(PropertyOwner)
        .where(PropertyOwner.property_id == property_item.id)
        .options(selectinload(PropertyOwner.person).selectinload(Person.roles))
    ).all()
    owner_people = [
        {**(_person_payload(owner.person) or {}), "ownership_percent": float(owner.ownership_percent)}
        for owner in owners
        if owner.person is not None
    ]

    capture = db.scalar(
        select(Capture)
        .where(Capture.organization_id == organization_id, Capture.converted_property_id == property_item.id)
        .order_by(Capture.created_at.desc())
    )
    administration = db.scalar(
        select(AdministrationContract)
        .where(
            AdministrationContract.organization_id == organization_id,
            AdministrationContract.property_id == property_item.id,
            AdministrationContract.status != "cancelled",
        )
        .order_by(AdministrationContract.internal_number.desc())
    )
    active_lease = db.scalar(
        select(LeaseContract)
        .where(
            LeaseContract.organization_id == organization_id,
            LeaseContract.property_id == property_item.id,
            LeaseContract.status != "cancelled",
        )
        .order_by(LeaseContract.internal_number.desc())
    )
    capture_contact = db.get(Person, capture.contact_person_id) if capture and capture.contact_person_id else None

    return {
        "property": {
            "id": str(property_item.id),
            "code": f"IMO-{int(property_item.internal_number):06d}",
            "internal_number": property_item.internal_number,
            "status": property_item.status,
            "property_type": property_item.property_type,
            "publication_enabled": property_item.publication_enabled,
        },
        "capture": _capture_payload(capture),
        "contact_person": _person_payload(capture_contact),
        "owners": owner_people,
        "administration": _contract_payload(administration),
        "lease": {
            "id": str(active_lease.id),
            "code": f"LOC-{int(active_lease.internal_number):06d}",
            "status": active_lease.status,
            "signed_at": active_lease.signed_at,
        } if active_lease else None,
        "publication": {
            "enabled": property_item.publication_enabled,
            "slug": property_item.public_slug,
            "published_at": property_item.published_at,
        },
        "timeline": _timeline_payload(db, organization_id, property_item),
        "lifecycle": [
            {"key": "capture", "label": "Captação", "status": capture.status if capture else "not_created", "linked": capture is not None},
            {"key": "person", "label": "Pessoa / proprietário", "status": "linked" if owner_people else "pending", "linked": bool(owner_people)},
            {"key": "property", "label": "Imóvel", "status": property_item.status, "linked": True},
            {"key": "administration", "label": "Administração", "status": administration.status if administration else "not_created", "linked": administration is not None},
            {"key": "publication", "label": "Publicação", "status": "active" if property_item.publication_enabled else "inactive", "linked": property_item.publication_enabled},
            {"key": "lease", "label": "Locação", "status": active_lease.status if active_lease else "not_started", "linked": active_lease is not None},
        ],
    }


@router.get("/properties/{property_id}/lifecycle")
def property_lifecycle(
    property_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    property_item = db.scalar(
        select(Property).where(Property.id == property_id, Property.organization_id == context.user.organization_id)
    )
    if property_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imóvel não encontrado.")
    return _property_lifecycle_payload(db, context.user.organization_id, property_item)


@router.get("/captures/{capture_id}/lifecycle")
def capture_lifecycle(
    capture_id: UUID,
    context: UserContext = Depends(require_permission("captures.view")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    capture = db.scalar(
        select(Capture).where(Capture.id == capture_id, Capture.organization_id == context.user.organization_id)
    )
    if capture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Captação não encontrada.")

    property_item = None
    if capture.converted_property_id:
        property_item = db.scalar(
            select(Property).where(
                Property.id == capture.converted_property_id,
                Property.organization_id == context.user.organization_id,
            )
        )

    if property_item is None:
        person = db.get(Person, capture.contact_person_id) if capture.contact_person_id else None
        return {
            "capture": _capture_payload(capture),
            "contact_person": _person_payload(person),
            "property": None,
            "administration": None,
            "publication": None,
            "lease": None,
            "lifecycle": [
                {"key": "capture", "label": "Captação", "status": capture.status, "linked": True},
                {"key": "person", "label": "Pessoa / proprietário", "status": "linked" if person else "pending", "linked": person is not None},
                {"key": "property", "label": "Imóvel", "status": "not_created", "linked": False},
                {"key": "administration", "label": "Administração", "status": "not_created", "linked": False},
                {"key": "publication", "label": "Publicação", "status": "not_started", "linked": False},
                {"key": "lease", "label": "Locação", "status": "not_started", "linked": False},
            ],
        }

    payload = _property_lifecycle_payload(db, context.user.organization_id, property_item)
    payload["capture"] = _capture_payload(capture)
    return payload
