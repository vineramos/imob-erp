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
