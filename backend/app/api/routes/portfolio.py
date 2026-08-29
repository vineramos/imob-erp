from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import AppUser
from app.domains.portfolio.economic_indices import INDEX_DEFINITIONS, sync_index
from app.domains.portfolio.models import Capture, EconomicIndexValue, Person, PersonRole, Property, PropertyOwner
from app.domains.portfolio.schemas import (
    CaptureCreate,
    CaptureResponse,
    EconomicIndexSyncResponse,
    EconomicIndexValueResponse,
    PersonCreate,
    PersonResponse,
    PropertyCreate,
    PropertyResponse,
)

router = APIRouter(tags=["portfolio"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _person_response(person: Person) -> PersonResponse:
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


def _property_response(item: Property) -> PropertyResponse:
    return PropertyResponse(
        id=item.id,
        internal_number=item.internal_number,
        code=f"{item.internal_number:06d}",
        property_type=item.property_type,
        purpose=item.purpose,
        status=item.status,
        address=item.address,
        rent_amount=item.rent_amount,
        condo_amount=item.condo_amount,
        iptu_amount=item.iptu_amount,
        area_m2=item.area_m2,
        bedrooms=item.bedrooms,
        suites=item.suites,
        bathrooms=item.bathrooms,
        parking_spaces=item.parking_spaces,
        furnished=item.furnished,
        pets_allowed=item.pets_allowed,
        public_title=item.public_title,
        publication_enabled=item.publication_enabled,
        owners=[
            {
                "person_id": str(owner.person_id),
                "name": owner.person.name,
                "ownership_percent": float(owner.ownership_percent),
            }
            for owner in item.owners
        ],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _capture_response(item: Capture) -> CaptureResponse:
    return CaptureResponse(
        id=item.id,
        status=item.status,
        source=item.source,
        contact_person_id=item.contact_person_id,
        contact_person_name=item.contact_person.name if item.contact_person else None,
        responsible_user_id=item.responsible_user_id,
        converted_property_id=item.converted_property_id,
        property_type=item.property_type,
        property_address=item.property_address,
        estimated_rent=item.estimated_rent,
        notes=item.notes,
        lost_reason=item.lost_reason,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/people", response_model=list[PersonResponse])
def list_people(
    q: str = Query(default="", max_length=120),
    role: str | None = Query(default=None, max_length=40),
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> list[PersonResponse]:
    stmt = (
        select(Person)
        .options(selectinload(Person.roles))
        .where(Person.organization_id == context.user.organization_id, Person.is_active.is_(True))
        .order_by(Person.name.asc())
        .limit(100)
    )
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Person.name.ilike(term), Person.document_number.ilike(term), Person.email.ilike(term)))
    if role:
        stmt = stmt.join(PersonRole).where(PersonRole.role_key == role, PersonRole.is_active.is_(True))
    people = db.scalars(stmt).unique().all()
    return [_person_response(person) for person in people]


@router.post("/people", response_model=PersonResponse, status_code=status.HTTP_201_CREATED)
def create_person(
    payload: PersonCreate,
    request: Request,
    context: UserContext = Depends(require_permission("properties.create")),
    db: Session = Depends(get_db),
) -> PersonResponse:
    person = Person(
        organization_id=context.user.organization_id,
        person_type=payload.person_type,
        name=payload.name.strip(),
        document_number=(payload.document_number or "").strip() or None,
        email=str(payload.email) if payload.email else None,
        phone=(payload.phone or "").strip() or None,
        address=payload.address.model_dump(),
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=context.user.id,
    )
    person.roles = [PersonRole(role_key=key, is_active=True) for key in sorted(set(payload.role_keys))]
    db.add(person)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma pessoa com este CPF/CNPJ.") from exc

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="portfolio.person.created",
        module="portfolio",
        entity_type="person",
        entity_id=str(person.id),
        after_data={"name": person.name, "document_number": person.document_number, "role_keys": list(payload.role_keys)},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    person = db.scalar(select(Person).options(selectinload(Person.roles)).where(Person.id == person.id))
    return _person_response(person)


@router.get("/properties", response_model=list[PropertyResponse])
def list_properties(
    q: str = Query(default="", max_length=120),
    property_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> list[PropertyResponse]:
    stmt = (
        select(Property)
        .options(selectinload(Property.owners).selectinload(PropertyOwner.person))
        .where(Property.organization_id == context.user.organization_id)
        .order_by(Property.internal_number.desc())
        .limit(150)
    )
    if property_status:
        stmt = stmt.where(Property.status == property_status)
    items = db.scalars(stmt).unique().all()
    if q.strip():
        term = q.strip().lower()
        items = [item for item in items if term in f"{item.internal_number:06d}" or term in str(item.address).lower() or term in (item.public_title or "").lower()]
    return [_property_response(item) for item in items]


@router.post("/properties", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED)
def create_property(
    payload: PropertyCreate,
    request: Request,
    context: UserContext = Depends(require_permission("properties.create")),
    db: Session = Depends(get_db),
) -> PropertyResponse:
    owner_ids = [owner.person_id for owner in payload.owners]
    if owner_ids:
        total = sum((owner.ownership_percent for owner in payload.owners), Decimal("0"))
        if total != Decimal("100"):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A participação dos proprietários deve totalizar 100%.")
        found = db.scalars(
            select(Person).options(selectinload(Person.roles)).where(
                Person.organization_id == context.user.organization_id,
                Person.id.in_(owner_ids),
                Person.is_active.is_(True),
            )
        ).unique().all()
        if len(found) != len(set(owner_ids)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Um ou mais proprietários são inválidos.")
        found_map = {person.id: person for person in found}
    else:
        found_map = {}

    item = Property(
        organization_id=context.user.organization_id,
        property_type=payload.property_type,
        purpose=payload.purpose,
        status=payload.status,
        address=payload.address.model_dump(),
        rent_amount=payload.rent_amount,
        condo_amount=payload.condo_amount,
        iptu_amount=payload.iptu_amount,
        area_m2=payload.area_m2,
        bedrooms=payload.bedrooms,
        suites=payload.suites,
        bathrooms=payload.bathrooms,
        parking_spaces=payload.parking_spaces,
        furnished=payload.furnished,
        pets_allowed=payload.pets_allowed,
        public_title=(payload.public_title or "").strip() or None,
        public_description=(payload.public_description or "").strip() or None,
        publication_enabled=payload.publication_enabled,
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()

    for owner in payload.owners:
        person = found_map[owner.person_id]
        if not any(role.role_key == "owner" and role.is_active for role in person.roles):
            person.roles.append(PersonRole(role_key="owner", is_active=True))
        db.add(PropertyOwner(property_id=item.id, person_id=owner.person_id, ownership_percent=owner.ownership_percent))

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="properties.created",
        module="properties",
        entity_type="property",
        entity_id=str(item.id),
        after_data={"code": f"{item.internal_number:06d}", "status": item.status, "property_type": item.property_type},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    item = db.scalar(
        select(Property).options(selectinload(Property.owners).selectinload(PropertyOwner.person)).where(Property.id == item.id)
    )
    return _property_response(item)


@router.get("/captures", response_model=list[CaptureResponse])
def list_captures(
    capture_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("captures.view")),
    db: Session = Depends(get_db),
) -> list[CaptureResponse]:
    stmt = (
        select(Capture)
        .options(selectinload(Capture.contact_person), selectinload(Capture.converted_property))
        .where(Capture.organization_id == context.user.organization_id)
        .order_by(Capture.created_at.desc())
        .limit(150)
    )
    if capture_status:
        stmt = stmt.where(Capture.status == capture_status)
    items = db.scalars(stmt).unique().all()
    return [_capture_response(item) for item in items]


@router.post("/captures", response_model=CaptureResponse, status_code=status.HTTP_201_CREATED)
def create_capture(
    payload: CaptureCreate,
    request: Request,
    context: UserContext = Depends(require_permission("captures.manage")),
    db: Session = Depends(get_db),
) -> CaptureResponse:
    if payload.contact_person_id:
        person = db.scalar(
            select(Person).where(
                Person.id == payload.contact_person_id,
                Person.organization_id == context.user.organization_id,
                Person.is_active.is_(True),
            )
        )
        if person is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pessoa de contato inválida.")
    if payload.responsible_user_id:
        user = db.scalar(
            select(AppUser).where(
                AppUser.id == payload.responsible_user_id,
                AppUser.organization_id == context.user.organization_id,
                AppUser.is_active.is_(True),
            )
        )
        if user is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Responsável inválido.")

    item = Capture(
        organization_id=context.user.organization_id,
        status=payload.status,
        source=payload.source,
        contact_person_id=payload.contact_person_id,
        responsible_user_id=payload.responsible_user_id,
        property_type=payload.property_type,
        property_address=payload.property_address.model_dump(),
        estimated_rent=payload.estimated_rent,
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="captures.created",
        module="captures",
        entity_type="capture",
        entity_id=str(item.id),
        after_data={"status": item.status, "source": item.source, "property_type": item.property_type},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    item = db.scalar(select(Capture).options(selectinload(Capture.contact_person)).where(Capture.id == item.id))
    return _capture_response(item)


@router.get("/economic-indices/latest", response_model=list[EconomicIndexValueResponse])
def latest_economic_indices(
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> list[EconomicIndexValueResponse]:
    result: list[EconomicIndexValueResponse] = []
    for index_code in INDEX_DEFINITIONS:
        row = db.scalar(
            select(EconomicIndexValue)
            .where(EconomicIndexValue.index_code == index_code)
            .order_by(EconomicIndexValue.competence.desc())
            .limit(1)
        )
        if row:
            result.append(
                EconomicIndexValueResponse(
                    index_code=row.index_code,
                    sgs_code=row.sgs_code,
                    competence=row.competence,
                    monthly_rate=row.monthly_rate,
                    source=row.source,
                    fetched_at=row.fetched_at,
                )
            )
    return result


@router.post("/economic-indices/sync/{index_code}", response_model=EconomicIndexSyncResponse)
def sync_economic_index(
    index_code: str,
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> EconomicIndexSyncResponse:
    code = index_code.upper()
    if code not in INDEX_DEFINITIONS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Índice econômico não suportado.")
    return EconomicIndexSyncResponse.model_validate(sync_index(db, code))
