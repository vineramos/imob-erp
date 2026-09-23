from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import AppUser, Organization, OrganizationSettings
from app.domains.portfolio.models import Person, Property, PropertyOwner, PropertyPhoto
from app.domains.portfolio.schemas import (
    PublicPropertyResponse,
    PropertyFeatures,
    PublicationChecklistItem,
    PublicationReadinessResponse,
    PublicationUpdate,
)
from app.domains.portfolio.site_models import PublicSiteInquiry

router = APIRouter(tags=["publication"])


class PublicSiteProfileResponse(BaseModel):
    organization_id: UUID
    display_name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    theme: dict


class CommercialPropertyProfileResponse(BaseModel):
    property_id: UUID
    status: str
    purpose: str
    public_title: str
    public_description: str
    rent_amount: Decimal | None = None
    condo_amount: Decimal | None = None
    iptu_amount: Decimal | None = None
    publication_enabled: bool


class CommercialPropertyProfileUpdate(BaseModel):
    status: Literal["draft", "available", "inactive"]
    public_title: str = Field(default="", max_length=180)
    public_description: str = Field(default="", max_length=5000)
    rent_amount: Decimal | None = Field(default=None, ge=0)
    condo_amount: Decimal | None = Field(default=None, ge=0)
    iptu_amount: Decimal | None = Field(default=None, ge=0)


class PublicPropertySiteResponse(PublicPropertyResponse):
    cover_photo_url: str | None = None


class PublicSiteInquiryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    preferred_contact: Literal["whatsapp", "phone", "email"] = "whatsapp"
    message: str | None = Field(default=None, max_length=2000)
    consent: bool
    website: str = Field(default="", max_length=200)


class PublicSiteInquiryAck(BaseModel):
    accepted: bool = True
    message: str


class SiteInquiryResponse(BaseModel):
    id: UUID
    property_id: UUID | None = None
    property_code: str
    property_title: str
    name: str
    email: str | None = None
    phone: str | None = None
    preferred_contact: str
    message: str | None = None
    status: str
    source: str
    responsible_user_id: UUID | None = None
    property_broker_person_id: UUID | None = None
    property_broker_name: str | None = None
    next_action_title: str | None = None
    next_action_at: datetime | None = None
    next_action_notes: str | None = None
    created_at: datetime
    updated_at: datetime


class SiteInquiryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["new", "contacted", "visit_scheduled", "qualified", "lost"]


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _load_property(db: Session, organization_id: UUID, property_id: UUID) -> Property:
    item = db.scalar(
        select(Property)
        .options(selectinload(Property.owners).selectinload(PropertyOwner.person))
        .where(Property.id == property_id, Property.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imóvel não encontrado.")
    return item


def _commercial_profile(item: Property) -> CommercialPropertyProfileResponse:
    return CommercialPropertyProfileResponse(
        property_id=item.id,
        status=item.status,
        purpose=item.purpose,
        public_title=item.public_title or "",
        public_description=item.public_description or "",
        rent_amount=item.rent_amount,
        condo_amount=item.condo_amount,
        iptu_amount=item.iptu_amount,
        publication_enabled=item.publication_enabled,
    )


def _checklist(db: Session, item: Property) -> list[PublicationChecklistItem]:
    address = item.address or {}
    ownership_total = sum((owner.ownership_percent for owner in item.owners), Decimal("0"))
    photo_count = int(db.scalar(select(func.count(PropertyPhoto.id)).where(PropertyPhoto.property_id == item.id)) or 0)
    cover_exists = db.scalar(
        select(PropertyPhoto.id).where(PropertyPhoto.property_id == item.id, PropertyPhoto.is_cover.is_(True)).limit(1)
    ) is not None
    checks = [
        ("status", "Imóvel disponível", item.status == "available", f"Status atual: {item.status}."),
        ("purpose", "Finalidade compatível", item.purpose in {"rent", "sale"}, f"Finalidade atual: {item.purpose}."),
        ("title", "Título público", bool((item.public_title or "").strip()), "Informe um título comercial para o anúncio."),
        (
            "description",
            "Descrição pública",
            len((item.public_description or "").strip()) >= 30,
            "A descrição pública deve ter pelo menos 30 caracteres.",
        ),
        (
            "price",
            "Valor comercial",
            item.rent_amount is not None and item.rent_amount > 0 if item.purpose == "rent" else True,
            "Para locação, informe um aluguel maior que zero.",
        ),
        (
            "address",
            "Endereço mínimo",
            all(str(address.get(key) or "").strip() for key in ("street", "neighborhood", "city", "state")),
            "Rua, bairro, cidade e UF são obrigatórios para publicação.",
        ),
        (
            "owners",
            "Proprietários válidos",
            bool(item.owners) and ownership_total == Decimal("100"),
            "O imóvel precisa ter proprietário(s) totalizando 100%.",
        ),
        (
            "photos",
            "Fotos do anúncio",
            photo_count > 0 and cover_exists,
            "Adicione pelo menos uma foto comercial e mantenha uma foto de capa definida.",
        ),
    ]
    return [PublicationChecklistItem(key=key, label=label, ok=ok, detail=detail) for key, label, ok, detail in checks]


def _readiness(db: Session, item: Property) -> PublicationReadinessResponse:
    checklist = _checklist(db, item)
    return PublicationReadinessResponse(
        property_id=item.id,
        code=f"{item.internal_number:06d}",
        ready=all(check.ok for check in checklist if check.required),
        publication_enabled=item.publication_enabled,
        public_slug=item.public_slug,
        checklist=checklist,
    )


@router.get("/properties/{property_id}/commercial-profile", response_model=CommercialPropertyProfileResponse)
def get_commercial_property_profile(
    property_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> CommercialPropertyProfileResponse:
    return _commercial_profile(_load_property(db, context.user.organization_id, property_id))


@router.put("/properties/{property_id}/commercial-profile", response_model=CommercialPropertyProfileResponse)
def update_commercial_property_profile(
    property_id: UUID,
    payload: CommercialPropertyProfileUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> CommercialPropertyProfileResponse:
    item = _load_property(db, context.user.organization_id, property_id)
    before = {
        "status": item.status,
        "public_title": item.public_title,
        "public_description": item.public_description,
        "rent_amount": str(item.rent_amount) if item.rent_amount is not None else None,
        "condo_amount": str(item.condo_amount) if item.condo_amount is not None else None,
        "iptu_amount": str(item.iptu_amount) if item.iptu_amount is not None else None,
        "publication_enabled": item.publication_enabled,
    }
    was_published = item.publication_enabled
    item.status = payload.status
    item.public_title = payload.public_title.strip() or None
    item.public_description = payload.public_description.strip() or None
    item.rent_amount = payload.rent_amount
    item.condo_amount = payload.condo_amount
    item.iptu_amount = payload.iptu_amount
    item.publication_updated_by_user_id = context.user.id

    if was_published:
        item.publication_enabled = False

    after = {
        "status": item.status,
        "public_title": item.public_title,
        "public_description": item.public_description,
        "rent_amount": str(item.rent_amount) if item.rent_amount is not None else None,
        "condo_amount": str(item.condo_amount) if item.condo_amount is not None else None,
        "iptu_amount": str(item.iptu_amount) if item.iptu_amount is not None else None,
        "publication_enabled": item.publication_enabled,
    }
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="properties.commercial_profile.updated",
        module="properties",
        entity_type="property",
        entity_id=str(item.id),
        before_data=before,
        after_data=after,
        reason="Publicação suspensa para nova conferência após alteração do perfil comercial." if was_published else None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return _commercial_profile(_load_property(db, context.user.organization_id, property_id))


@router.get("/properties/{property_id}/publication-readiness", response_model=PublicationReadinessResponse)
def property_publication_readiness(
    property_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> PublicationReadinessResponse:
    return _readiness(db, _load_property(db, context.user.organization_id, property_id))


@router.post("/properties/{property_id}/publication", response_model=PublicationReadinessResponse)
def update_property_publication(
    property_id: UUID,
    payload: PublicationUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("properties.publish")),
    db: Session = Depends(get_db),
) -> PublicationReadinessResponse:
    item = _load_property(db, context.user.organization_id, property_id)
    before = {"publication_enabled": item.publication_enabled, "public_slug": item.public_slug}
    readiness = _readiness(db, item)
    if payload.enabled and not readiness.ready:
        missing = [check.label for check in readiness.checklist if check.required and not check.ok]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Checklist de publicação incompleto: " + ", ".join(missing),
        )
    if not payload.enabled and item.publication_enabled and not (payload.reason or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe o motivo para retirar um imóvel publicado do ar.")

    if payload.enabled:
        item.public_slug = item.public_slug or f"imovel-{item.internal_number:06d}"
        item.publication_enabled = True
        item.published_at = datetime.now(timezone.utc)
        settings = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == context.user.organization_id))
        if settings is not None:
            integrations = dict(settings.integrations or {})
            integrations["public_site_enabled"] = True
            settings.integrations = integrations
    else:
        item.publication_enabled = False
    item.publication_updated_by_user_id = context.user.id

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="properties.published" if payload.enabled else "properties.unpublished",
        module="properties",
        entity_type="property",
        entity_id=str(item.id),
        before_data=before,
        after_data={"publication_enabled": item.publication_enabled, "public_slug": item.public_slug},
        reason=(payload.reason or "").strip() or None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return _readiness(db, _load_property(db, context.user.organization_id, property_id))


def _public_site_settings(db: Session, organization_id: UUID) -> tuple[Organization, OrganizationSettings]:
    organization = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.is_active.is_(True)))
    settings = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    if organization is None or settings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site público não disponível.")

    integrations = settings.integrations or {}
    has_published_rental = db.scalar(
        select(Property.id)
        .where(
            Property.organization_id == organization_id,
            Property.publication_enabled.is_(True),
            Property.status == "available",
            Property.purpose == "rent",
        )
        .limit(1)
    ) is not None
    if not bool(integrations.get("public_site_enabled")) and not has_published_rental:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site público não disponível.")
    return organization, settings


@router.get("/public/sites/{organization_id}", response_model=PublicSiteProfileResponse)
def public_site_profile(organization_id: UUID, db: Session = Depends(get_db)) -> PublicSiteProfileResponse:
    organization, settings = _public_site_settings(db, organization_id)
    return PublicSiteProfileResponse(
        organization_id=organization.id,
        display_name=organization.display_name,
        contact_email=organization.contact_email,
        contact_phone=organization.contact_phone,
        theme=dict(settings.site_theme or {}),
    )


def _public_address(item: Property) -> dict[str, str]:
    address = item.address or {}
    return {
        "street": "",
        "number": "",
        "complement": "",
        "neighborhood": str(address.get("neighborhood") or ""),
        "city": str(address.get("city") or ""),
        "state": str(address.get("state") or ""),
        "postal_code": "",
    }


def _public_property_item(db: Session, organization_id: UUID, slug: str) -> Property:
    item = db.scalar(
        select(Property).where(
            Property.organization_id == organization_id,
            Property.public_slug == slug,
            Property.publication_enabled.is_(True),
            Property.status == "available",
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imóvel publicado não encontrado.")
    return item


def _cover_photo_map(db: Session, items: list[Property]) -> dict[UUID, UUID]:
    property_ids = [item.id for item in items]
    if not property_ids:
        return {}
    rows = db.execute(
        select(PropertyPhoto.property_id, PropertyPhoto.id)
        .where(PropertyPhoto.property_id.in_(property_ids), PropertyPhoto.is_cover.is_(True))
        .order_by(PropertyPhoto.position.asc(), PropertyPhoto.created_at.asc())
    ).all()
    result: dict[UUID, UUID] = {}
    for property_id, photo_id in rows:
        result.setdefault(property_id, photo_id)
    return result


def _public_charge_rows(item: Property) -> list[dict]:
    # Expose only tenant-facing active charges that are included in billing.
    # Beneficiary, retention and internal routing remain private ERP data.
    return [
        {"label": str(row.get("label") or "Encargo"), "amount": row.get("amount") or 0, "frequency": row.get("frequency") or "monthly"}
        for row in (item.additional_charges or [])
        if isinstance(row, dict)
        and row.get("active", True)
        and row.get("include_in_invoice", True)
        and row.get("payer", "tenant") == "tenant"
    ]


def _public_response(item: Property, organization_id: UUID, cover_photo_id: UUID | None = None) -> PublicPropertySiteResponse:
    slug = item.public_slug or f"imovel-{item.internal_number:06d}"
    cover_photo_url = (
        f"/public/sites/{organization_id}/properties/{slug}/photos/{cover_photo_id}/content"
        if cover_photo_id
        else None
    )
    return PublicPropertySiteResponse(
        code=f"{item.internal_number:06d}",
        slug=slug,
        property_type=item.property_type,
        purpose=item.purpose,
        address=_public_address(item),
        rent_amount=item.rent_amount,
        condo_amount=item.condo_amount,
        iptu_amount=item.iptu_amount,
        additional_charges=_public_charge_rows(item),
        area_m2=item.area_m2,
        bedrooms=item.bedrooms,
        suites=item.suites,
        bathrooms=item.bathrooms,
        parking_spaces=item.parking_spaces,
        furnished=item.furnished,
        pets_allowed=item.pets_allowed,
        features=PropertyFeatures.model_validate(item.features or {}).model_dump(),
        title=item.public_title or f"Imóvel {item.internal_number:06d}",
        description=item.public_description or "",
        published_at=item.published_at,
        cover_photo_url=cover_photo_url,
    )


@router.get("/public/sites/{organization_id}/properties", response_model=list[PublicPropertySiteResponse])
def public_properties(organization_id: UUID, db: Session = Depends(get_db)) -> list[PublicPropertySiteResponse]:
    _public_site_settings(db, organization_id)
    items = list(
        db.scalars(
            select(Property)
            .where(
                Property.organization_id == organization_id,
                Property.publication_enabled.is_(True),
                Property.status == "available",
            )
            .order_by(Property.published_at.desc().nullslast(), Property.internal_number.desc())
            .limit(500)
        ).all()
    )
    covers = _cover_photo_map(db, items)
    return [_public_response(item, organization_id, covers.get(item.id)) for item in items]


@router.get("/public/sites/{organization_id}/properties/{slug}/similar", response_model=list[PublicPropertySiteResponse])
def public_similar_properties(organization_id: UUID, slug: str, db: Session = Depends(get_db)) -> list[PublicPropertySiteResponse]:
    _public_site_settings(db, organization_id)
    item = _public_property_item(db, organization_id, slug)
    candidates = list(
        db.scalars(
            select(Property)
            .where(
                Property.organization_id == organization_id,
                Property.publication_enabled.is_(True),
                Property.status == "available",
                Property.id != item.id,
            )
            .order_by(Property.published_at.desc().nullslast(), Property.internal_number.desc())
            .limit(40)
        ).all()
    )

    def similarity(candidate: Property) -> float:
        score = 0.0
        current_address = item.address or {}
        candidate_address = candidate.address or {}
        if candidate_address.get("neighborhood") and candidate_address.get("neighborhood") == current_address.get("neighborhood"):
            score += 5
        if candidate.property_type == item.property_type:
            score += 3
        score += max(0, 3 - abs(int(candidate.bedrooms or 0) - int(item.bedrooms or 0)))
        base = float(item.rent_amount or 0)
        value = float(candidate.rent_amount or 0)
        if base > 0 and value > 0:
            score += max(0, 3 - abs(value - base) / max(base, 1) * 6)
        return score

    selected = sorted(candidates, key=similarity, reverse=True)[:4]
    covers = _cover_photo_map(db, selected)
    return [_public_response(candidate, organization_id, covers.get(candidate.id)) for candidate in selected]


@router.get("/public/sites/{organization_id}/properties/{slug}", response_model=PublicPropertySiteResponse)
def public_property_detail(organization_id: UUID, slug: str, db: Session = Depends(get_db)) -> PublicPropertySiteResponse:
    _public_site_settings(db, organization_id)
    item = _public_property_item(db, organization_id, slug)
    cover_id = db.scalar(
        select(PropertyPhoto.id)
        .where(PropertyPhoto.property_id == item.id, PropertyPhoto.is_cover.is_(True))
        .order_by(PropertyPhoto.position.asc(), PropertyPhoto.created_at.asc())
        .limit(1)
    )
    return _public_response(item, organization_id, cover_id)


def _normalized_inquiry_contact(payload: PublicSiteInquiryCreate) -> tuple[str, str | None, str | None]:
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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Autorize o contato para enviar seu interesse.")
    return name, email, phone


@router.post(
    "/public/sites/{organization_id}/properties/{slug}/inquiries",
    response_model=PublicSiteInquiryAck,
    status_code=status.HTTP_201_CREATED,
)
def create_public_site_inquiry(
    organization_id: UUID,
    slug: str,
    payload: PublicSiteInquiryCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> PublicSiteInquiryAck:
    _public_site_settings(db, organization_id)
    property_item = _public_property_item(db, organization_id, slug)

    # Campo invisível para pessoas; bots que o preenchem recebem resposta genérica sem gravar PII.
    if payload.website.strip():
        return PublicSiteInquiryAck(message="Recebemos seu interesse. Nossa equipe fará o contato.")

    name, email, phone = _normalized_inquiry_contact(payload)
    ip_address, user_agent = _request_metadata(request)
    now = datetime.now(timezone.utc)

    if ip_address:
        recent_count = int(
            db.scalar(
                select(func.count(PublicSiteInquiry.id)).where(
                    PublicSiteInquiry.organization_id == organization_id,
                    PublicSiteInquiry.requester_ip == ip_address,
                    PublicSiteInquiry.created_at >= now - timedelta(minutes=10),
                )
            )
            or 0
        )
        if recent_count >= 5:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Muitas solicitações em sequência. Aguarde alguns minutos e tente novamente.",
            )

    contact_matches = []
    if email:
        contact_matches.append(func.lower(PublicSiteInquiry.email) == email)
    if phone:
        contact_matches.append(PublicSiteInquiry.phone == phone)
    if contact_matches:
        duplicate = db.scalar(
            select(PublicSiteInquiry.id)
            .where(
                PublicSiteInquiry.organization_id == organization_id,
                PublicSiteInquiry.property_id == property_item.id,
                PublicSiteInquiry.created_at >= now - timedelta(minutes=30),
                or_(*contact_matches),
            )
            .limit(1)
        )
        if duplicate is not None:
            return PublicSiteInquiryAck(message="Recebemos seu interesse. Nossa equipe fará o contato.")

    # Property brokers are Person records, while CRM assignees are AppUser records.
    # Auto-assign only when the broker has an active ERP user with the same email.
    broker_user_id = None
    if property_item.responsible_broker_person_id:
        broker = db.scalar(
            select(Person).where(
                Person.id == property_item.responsible_broker_person_id,
                Person.organization_id == organization_id,
                Person.is_active.is_(True),
            )
        )
        if broker and broker.email:
            broker_user_id = db.scalar(
                select(AppUser.id).where(
                    AppUser.organization_id == organization_id,
                    AppUser.is_active.is_(True),
                    func.lower(AppUser.email) == broker.email.strip().lower(),
                )
            )

    item = PublicSiteInquiry(
        responsible_user_id=broker_user_id,
        organization_id=organization_id,
        property_id=property_item.id,
        property_code=f"{property_item.internal_number:06d}",
        property_title=property_item.public_title or f"Imóvel {property_item.internal_number:06d}",
        name=name,
        email=email,
        phone=phone,
        preferred_contact=payload.preferred_contact,
        message=(payload.message or "").strip() or None,
        consent_at=now,
        status="new",
        source="public_site",
        requester_ip=ip_address,
        user_agent=user_agent,
    )
    db.add(item)
    db.commit()
    return PublicSiteInquiryAck(message="Recebemos seu interesse. Nossa equipe fará o contato.")


def _site_inquiry_response(item: PublicSiteInquiry, *, broker: Person | None = None) -> SiteInquiryResponse:
    return SiteInquiryResponse(
        property_broker_person_id=broker.id if broker else None,
        property_broker_name=broker.name if broker else None,
        id=item.id,
        property_id=item.property_id,
        property_code=item.property_code,
        property_title=item.property_title,
        name=item.name,
        email=item.email,
        phone=item.phone,
        preferred_contact=item.preferred_contact,
        message=item.message,
        status=item.status,
        source=item.source,
        responsible_user_id=item.responsible_user_id,
        next_action_title=item.next_action_title,
        next_action_at=item.next_action_at,
        next_action_notes=item.next_action_notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/crm/site-inquiries", response_model=list[SiteInquiryResponse])
def list_site_inquiries(
    inquiry_status: str | None = Query(default=None, alias="status", max_length=32),
    q: str = Query(default="", max_length=120),
    context: UserContext = Depends(require_permission("crm.view")),
    db: Session = Depends(get_db),
) -> list[SiteInquiryResponse]:
    stmt = (
        select(PublicSiteInquiry)
        .where(PublicSiteInquiry.organization_id == context.user.organization_id)
        .order_by(PublicSiteInquiry.created_at.desc())
        .limit(250)
    )
    if inquiry_status:
        stmt = stmt.where(PublicSiteInquiry.status == inquiry_status)
    items = list(db.scalars(stmt).all())
    term = q.strip().lower()
    if term:
        items = [
            item
            for item in items
            if term
            in " ".join(
                filter(
                    None,
                    [item.property_code, item.property_title, item.name, item.email or "", item.phone or "", item.message or ""],
                )
            ).lower()
        ]
    # Fetch property/broker names once per list; do not run N+1 on CRM cards.
    property_ids = {row.property_id for row in items if row.property_id}
    properties = db.scalars(select(Property).where(
        Property.organization_id == context.user.organization_id,
        Property.id.in_(property_ids),
    )).all() if property_ids else []
    by_property = {row.id: row.responsible_broker_person_id for row in properties}
    broker_ids = {bid for bid in by_property.values() if bid}
    broker_rows = db.scalars(select(Person).where(
        Person.organization_id == context.user.organization_id,
        Person.id.in_(broker_ids),
        Person.is_active.is_(True),
    )).all() if broker_ids else []
    broker_map = {row.id: row for row in broker_rows}
    return [_site_inquiry_response(row, broker=broker_map.get(by_property.get(row.property_id))) for row in items]


@router.patch("/crm/site-inquiries/{inquiry_id}", response_model=SiteInquiryResponse)
def update_site_inquiry(
    inquiry_id: UUID,
    payload: SiteInquiryUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("crm.manage")),
    db: Session = Depends(get_db),
) -> SiteInquiryResponse:
    item = db.scalar(
        select(PublicSiteInquiry).where(
            PublicSiteInquiry.id == inquiry_id,
            PublicSiteInquiry.organization_id == context.user.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interesse não encontrado.")

    before = {"status": item.status}
    item.status = payload.status
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="crm.site_inquiry.updated",
        module="crm",
        entity_type="public_site_inquiry",
        entity_id=str(item.id),
        before_data=before,
        after_data={"status": item.status},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(item)
    prop = db.scalar(select(Property).where(
        Property.id == item.property_id, Property.organization_id == context.user.organization_id,
    )) if item.property_id else None
    broker = db.scalar(select(Person).where(
        Person.id == prop.responsible_broker_person_id,
        Person.organization_id == context.user.organization_id,
        Person.is_active.is_(True),
    )) if prop and prop.responsible_broker_person_id else None
    return _site_inquiry_response(item, broker=broker)
