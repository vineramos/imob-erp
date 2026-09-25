import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.portfolio.bank_models import PersonBankDetails
from app.domains.portfolio.bank_schemas import PersonBankDetailsResponse, PersonBankDetailsUpdate
from app.domains.portfolio.models import Person

router = APIRouter(prefix="/people", tags=["portfolio"])


def _clean(value: str | None) -> str | None:
    result = (value or "").strip()
    return result or None


def _digits(value: str | None) -> str | None:
    result = re.sub(r"\D", "", value or "")
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


def _response(item: PersonBankDetails) -> PersonBankDetailsResponse:
    return PersonBankDetailsResponse(
        id=item.id,
        person_id=item.person_id,
        bank_name=item.bank_name,
        bank_code=item.bank_code,
        branch=item.branch,
        account_number=item.account_number,
        account_digit=item.account_digit,
        account_type=item.account_type,
        pix_key_type=item.pix_key_type,
        pix_key=item.pix_key,
        account_holder_name=item.account_holder_name,
        account_holder_document=item.account_holder_document,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/{person_id}/bank-details", response_model=PersonBankDetailsResponse | None)
def get_bank_details(
    person_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> PersonBankDetailsResponse | None:
    _person(db, context.user.organization_id, person_id)
    item = db.scalar(
        select(PersonBankDetails).where(
            PersonBankDetails.person_id == person_id,
            PersonBankDetails.organization_id == context.user.organization_id,
        )
    )
    return _response(item) if item else None


@router.put("/{person_id}/bank-details", response_model=PersonBankDetailsResponse)
def upsert_bank_details(
    person_id: UUID,
    payload: PersonBankDetailsUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> PersonBankDetailsResponse:
    person = _person(db, context.user.organization_id, person_id)
    item = db.scalar(
        select(PersonBankDetails).where(
            PersonBankDetails.person_id == person_id,
            PersonBankDetails.organization_id == context.user.organization_id,
        )
    )
    if item is None:
        item = PersonBankDetails(
            organization_id=context.user.organization_id,
            person_id=person_id,
        )
        db.add(item)

    item.bank_name = _clean(payload.bank_name)
    item.bank_code = _digits(payload.bank_code)
    item.branch = _clean(payload.branch)
    item.account_number = _clean(payload.account_number)
    item.account_digit = _clean(payload.account_digit)
    item.account_type = payload.account_type
    item.pix_key_type = payload.pix_key_type
    item.pix_key = _clean(payload.pix_key) if payload.pix_key_type != "none" else None
    item.account_holder_name = _clean(payload.account_holder_name)
    item.account_holder_document = _digits(payload.account_holder_document)
    db.flush()

    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action="portfolio.person_bank_details.updated",
        module="portfolio",
        entity_type="person_bank_details",
        entity_id=str(item.id),
        after_data={
            "person_id": str(person.id),
            "bank_name": item.bank_name,
            "account_type": item.account_type,
            "pix_key_type": item.pix_key_type,
        },
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return _response(item)
