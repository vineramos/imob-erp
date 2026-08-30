from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization, OrganizationSettings
from app.domains.portfolio.models import Property, PropertyOwner, PropertyPhoto
from app.domains.portfolio.schemas import (
    PublicPropertyResponse,
    PublicationChecklistItem,
    PublicationReadinessResponse,
    PublicationUpdate,
)

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
    integrations = (settings.integrations if settings else {}) or {}
    if organization is None or settings is None or not bool(integrations.get("public_site_enabled")):
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


def _public_response(item: Property) -> PublicPropertyResponse:
    return PublicPropertyResponse(
        code=f"{item.internal_number:06d}",
        slug=item.public_slug or f"imovel-{item.internal_number:06d}",
        property_type=item.property_type,
        purpose=item.purpose,
        address=_public_address(item),
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
        title=item.public_title or f"Imóvel {item.internal_number:06d}",
        description=item.public_description or "",
        published_at=item.published_at,
    )


@router.get("/public/sites/{organization_id}/properties", response_model=list[PublicPropertyResponse])
def public_properties(organization_id: UUID, db: Session = Depends(get_db)) -> list[PublicPropertyResponse]:
    _public_site_settings(db, organization_id)
    items = db.scalars(
        select(Property)
        .where(
            Property.organization_id == organization_id,
            Property.publication_enabled.is_(True),
            Property.status == "available",
        )
        .order_by(Property.published_at.desc().nullslast(), Property.internal_number.desc())
        .limit(500)
    ).all()
    return [_public_response(item) for item in items]


@router.get("/public/sites/{organization_id}/properties/{slug}", response_model=PublicPropertyResponse)
def public_property_detail(organization_id: UUID, slug: str, db: Session = Depends(get_db)) -> PublicPropertyResponse:
    _public_site_settings(db, organization_id)
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
    return _public_response(item)
