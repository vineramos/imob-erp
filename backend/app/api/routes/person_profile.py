from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.portfolio.models import Person
from app.domains.portfolio.profile_models import PersonProfile
from app.domains.portfolio.profile_schemas import PersonProfileResponse, PersonProfileUpdate

router = APIRouter(prefix="/people", tags=["portfolio"])


def _clean(value: str | None) -> str | None:
    result = (value or "").strip()
    return result or None


def _person(db: Session, organization_id: UUID, person_id: UUID) -> Person:
    item = db.scalar(
        select(Person).where(
            Person.id == person_id,
            Person.organization_id == organization_id,
            Person.is_active.is_(True),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")
    return item


def _response(item: PersonProfile) -> PersonProfileResponse:
    return PersonProfileResponse(
        id=item.id,
        person_id=item.person_id,
        secondary_phone=item.secondary_phone,
        identity_number=item.identity_number,
        identity_issuer=item.identity_issuer,
        birth_date=item.birth_date,
        nationality=item.nationality,
        marital_status=item.marital_status,
        occupation=item.occupation,
        trade_name=item.trade_name,
        state_registration=item.state_registration,
        municipal_registration=item.municipal_registration,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/{person_id}/profile", response_model=PersonProfileResponse | None)
def get_person_profile(
    person_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> PersonProfileResponse | None:
    _person(db, context.user.organization_id, person_id)
    item = db.scalar(
        select(PersonProfile).where(
            PersonProfile.person_id == person_id,
            PersonProfile.organization_id == context.user.organization_id,
        )
    )
    return _response(item) if item else None


@router.put("/{person_id}/profile", response_model=PersonProfileResponse)
def upsert_person_profile(
    person_id: UUID,
    payload: PersonProfileUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> PersonProfileResponse:
    person = _person(db, context.user.organization_id, person_id)
    item = db.scalar(
        select(PersonProfile).where(
            PersonProfile.person_id == person_id,
            PersonProfile.organization_id == context.user.organization_id,
        )
    )
    if item is None:
        item = PersonProfile(organization_id=context.user.organization_id, person_id=person_id)
        db.add(item)

    item.secondary_phone = _clean(payload.secondary_phone)

    if person.person_type == "individual":
        item.identity_number = _clean(payload.identity_number)
        item.identity_issuer = _clean(payload.identity_issuer)
        item.birth_date = payload.birth_date
        item.nationality = _clean(payload.nationality)
        item.marital_status = payload.marital_status
        item.occupation = _clean(payload.occupation)
        item.trade_name = None
        item.state_registration = None
        item.municipal_registration = None
    else:
        item.identity_number = None
        item.identity_issuer = None
        item.birth_date = None
        item.nationality = None
        item.marital_status = None
        item.occupation = None
        item.trade_name = _clean(payload.trade_name)
        item.state_registration = _clean(payload.state_registration)
        item.municipal_registration = _clean(payload.municipal_registration)

    db.flush()
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action="portfolio.person_profile.updated",
        module="portfolio",
        entity_type="person_profile",
        entity_id=str(item.id),
        after_data={
            "person_id": str(person.id),
            "person_type": person.person_type,
            "has_identity": bool(item.identity_number),
            "has_secondary_phone": bool(item.secondary_phone),
            "has_company_registration": bool(item.state_registration or item.municipal_registration),
        },
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return _response(item)
