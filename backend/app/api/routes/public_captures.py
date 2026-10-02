from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.publication import _public_site_settings
from app.core.database import get_db
from app.domains.portfolio.models import Capture, Person, PersonRole

router = APIRouter(tags=["public-captures"])


class PublicCaptureAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    street: str = Field(min_length=2, max_length=180)
    number: str = Field(default="", max_length=30)
    complement: str = Field(default="", max_length=120)
    neighborhood: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=2)
    postal_code: str = Field(default="", max_length=20)


class PublicCaptureCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    preferred_contact: Literal["whatsapp", "phone", "email"] = "whatsapp"
    property_type: Literal["apartment", "house", "commercial", "land", "studio", "other"]
    address: PublicCaptureAddress
    estimated_rent: Decimal | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=2000)
    consent: bool
    website: str = Field(default="", max_length=200)


class PublicCaptureAck(BaseModel):
    accepted: bool = True
    message: str


def _normalize_contact(payload: PublicCaptureCreate) -> tuple[str, str | None, str | None]:
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe seu nome.")

    email = str(payload.email).strip().lower() if payload.email else None
    phone_digits = "".join(char for char in (payload.phone or "") if char.isdigit())
    phone = phone_digits or None
    if phone and not 10 <= len(phone) <= 15:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe um telefone válido.")
    if not email and not phone:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe telefone ou e-mail para contato.")
    if payload.preferred_contact == "email" and not email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe o e-mail escolhido para contato.")
    if payload.preferred_contact in {"phone", "whatsapp"} and not phone:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe o telefone escolhido para contato.")
    if payload.consent is not True:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Autorize o contato para enviar os dados do imóvel.")
    return name, email, phone


def _normalized_address(payload: PublicCaptureAddress) -> dict[str, str]:
    postal_code = "".join(char for char in payload.postal_code if char.isdigit())
    return {
        "street": payload.street.strip(),
        "number": payload.number.strip(),
        "complement": payload.complement.strip(),
        "neighborhood": payload.neighborhood.strip(),
        "city": payload.city.strip(),
        "state": payload.state.strip().upper(),
        "postal_code": postal_code,
    }


def _ensure_owner_role(person: Person) -> None:
    role = next((item for item in person.roles if item.role_key == "owner"), None)
    if role is None:
        person.roles.append(PersonRole(role_key="owner", is_active=True))
    else:
        role.is_active = True


def _find_contact(db: Session, organization_id: UUID, email: str | None, phone: str | None) -> Person | None:
    matches = []
    if email:
        matches.append(func.lower(Person.email) == email)
    if phone:
        matches.append(func.regexp_replace(func.coalesce(Person.phone, ""), r"\D", "", "g") == phone)
    if not matches:
        return None
    return db.scalar(
        select(Person)
        .options(selectinload(Person.roles))
        .where(
            Person.organization_id == organization_id,
            Person.is_active.is_(True),
            or_(*matches),
        )
        .order_by(Person.created_at.asc())
        .limit(1)
    )


def _capture_notes(payload: PublicCaptureCreate) -> str:
    contact_label = {"whatsapp": "WhatsApp", "phone": "Ligação", "email": "E-mail"}[payload.preferred_contact]
    parts = [f"Captação recebida pelo site. Preferência de contato: {contact_label}."]
    if payload.message and payload.message.strip():
        parts.append(payload.message.strip())
    return "\n\n".join(parts)


@router.post(
    "/public/sites/{organization_id}/captures",
    response_model=PublicCaptureAck,
    status_code=status.HTTP_201_CREATED,
)
def create_public_capture(
    organization_id: UUID,
    payload: PublicCaptureCreate,
    db: Session = Depends(get_db),
) -> PublicCaptureAck:
    _public_site_settings(db, organization_id)

    # Campo invisível para pessoas; bots recebem resposta genérica sem gravar dados.
    if payload.website.strip():
        return PublicCaptureAck(message="Recebemos os dados do seu imóvel. Nossa equipe fará o contato.")

    name, email, phone = _normalize_contact(payload)
    address = _normalized_address(payload.address)
    now = datetime.now(timezone.utc)

    person = _find_contact(db, organization_id, email, phone)
    if person is None:
        person = Person(
            organization_id=organization_id,
            person_type="individual",
            name=name,
            email=email,
            phone=phone,
            address={},
            notes=None,
            is_active=True,
            created_by_user_id=None,
        )
        person.roles = [PersonRole(role_key="owner", is_active=True)]
        db.add(person)
        db.flush()
    else:
        _ensure_owner_role(person)
        if not person.email and email:
            person.email = email
        if not person.phone and phone:
            person.phone = phone

    recent = db.scalars(
        select(Capture).where(
            Capture.organization_id == organization_id,
            Capture.contact_person_id == person.id,
            Capture.source == "site",
            Capture.created_at >= now - timedelta(minutes=30),
        )
    ).all()
    if any(dict(item.property_address or {}) == address for item in recent):
        db.commit()
        return PublicCaptureAck(message="Recebemos os dados do seu imóvel. Nossa equipe fará o contato.")

    capture = Capture(
        organization_id=organization_id,
        status="new",
        source="site",
        contact_person_id=person.id,
        responsible_user_id=None,
        property_type=payload.property_type,
        property_address=address,
        estimated_rent=payload.estimated_rent,
        notes=_capture_notes(payload),
        created_by_user_id=None,
    )
    db.add(capture)
    db.commit()
    return PublicCaptureAck(message="Recebemos os dados do seu imóvel. Nossa equipe de captação fará o contato.")
