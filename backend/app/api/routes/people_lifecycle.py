from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.leases.models import LeaseContract
from app.domains.portal.models import PortalAccount
from app.domains.portfolio.models import Capture, Person, Property, PropertyOwner
from app.domains.portfolio.schemas import PersonResponse

router = APIRouter(tags=["portfolio"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _response(person: Person) -> PersonResponse:
    return PersonResponse(
        id=person.id,
        person_type=person.person_type,
        name=person.name,
        document_number=person.document_number,
        email=person.email,
        phone=person.phone,
        address=person.address,
        notes=person.notes,
        is_active=person.is_active,
        role_keys=sorted(role.role_key for role in person.roles if role.is_active),
        created_at=person.created_at,
    )


def _load_person(db: Session, organization_id: UUID, person_id: UUID, *, active: bool) -> Person:
    person = db.scalar(
        select(Person)
        .options(selectinload(Person.roles))
        .where(
            Person.id == person_id,
            Person.organization_id == organization_id,
            Person.is_active.is_(active),
        )
    )
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada.")
    return person


def _ensure_can_archive(db: Session, organization_id: UUID, person: Person) -> None:
    active_property = db.scalar(
        select(Property.id)
        .join(PropertyOwner, PropertyOwner.property_id == Property.id)
        .where(
            Property.organization_id == organization_id,
            PropertyOwner.person_id == person.id,
            Property.status != "inactive",
        )
        .limit(1)
    )
    if active_property is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta pessoa ainda é proprietária de um imóvel ativo. Inative ou transfira o vínculo do imóvel antes de arquivá-la.",
        )

    active_capture = db.scalar(
        select(Capture.id)
        .where(
            Capture.organization_id == organization_id,
            Capture.contact_person_id == person.id,
            Capture.status != "lost",
        )
        .limit(1)
    )
    if active_capture is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta pessoa possui uma captação em andamento. Encerre a captação antes de arquivá-la.",
        )

    person_ref = str(person.id)
    active_lease = db.scalar(
        select(LeaseContract.id)
        .where(
            LeaseContract.organization_id == organization_id,
            LeaseContract.status.notin_(["closed", "cancelled"]),
            or_(
                LeaseContract.owner_snapshot.contains([{"person_id": person_ref}]),
                LeaseContract.tenant_snapshot.contains([{"person_id": person_ref}]),
            ),
        )
        .limit(1)
    )
    if active_lease is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta pessoa participa de uma locação ativa. Encerre ou cancele a locação antes de arquivá-la.",
        )

    active_portal = db.scalar(
        select(PortalAccount.id)
        .where(
            PortalAccount.organization_id == organization_id,
            PortalAccount.person_id == person.id,
            PortalAccount.is_active.is_(True),
        )
        .limit(1)
    )
    if active_portal is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta pessoa ainda possui acesso ativo ao portal. Desative o acesso antes de arquivá-la.",
        )


@router.get("/people/archived", response_model=list[PersonResponse])
def list_archived_people(
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> list[PersonResponse]:
    people = db.scalars(
        select(Person)
        .options(selectinload(Person.roles))
        .where(
            Person.organization_id == context.user.organization_id,
            Person.is_active.is_(False),
        )
        .order_by(Person.name.asc())
        .limit(100)
    ).unique().all()
    return [_response(person) for person in people]


@router.post("/people/{person_id}/archive", response_model=PersonResponse)
def archive_person(
    person_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> PersonResponse:
    person = _load_person(db, context.user.organization_id, person_id, active=True)
    _ensure_can_archive(db, context.user.organization_id, person)
    person.is_active = False
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="portfolio.person.archived",
        module="portfolio",
        entity_type="person",
        entity_id=str(person.id),
        before_data={"is_active": True, "name": person.name},
        after_data={"is_active": False, "name": person.name},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(person)
    return _response(person)


@router.post("/people/{person_id}/restore", response_model=PersonResponse)
def restore_person(
    person_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> PersonResponse:
    person = _load_person(db, context.user.organization_id, person_id, active=False)
    person.is_active = True
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="portfolio.person.restored",
        module="portfolio",
        entity_type="person",
        entity_id=str(person.id),
        before_data={"is_active": False, "name": person.name},
        after_data={"is_active": True, "name": person.name},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(person)
    return _response(person)
