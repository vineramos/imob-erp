from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization, OrganizationSettings
from app.domains.portfolio.models import Property, PropertyOwner
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


def _checklist(item: Property) -> list[PublicationChecklistItem]:
    address = item.address or {}
    ownership_total = sum((owner.ownership_percent for owner in item.owners), Decimal("0"))
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
    ]
    return [PublicationChecklistItem(key=key, label=label, ok=ok, detail=detail) for key, label, ok, detail in checks]


def _readiness(item: Property) -> PublicationReadinessResponse:
    checklist = _checklist(item)
    return PublicationReadinessResponse(
        property_id=item.id,
        code=f"{item.internal_number:06d}",
        ready=all(check.ok for check in checklist if check.required),
        publication_enabled=item.publication_enabled,
        public_slug=item.public_slug,
        checklist=checklist,
    )


@router.get("/properties/{property_id}/publication-readiness", response_model=PublicationReadinessResponse)
def property_publication_readiness(
    property_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> PublicationReadinessResponse:
    return _readiness(_load_property(db, context.user.organization_id, property_id))


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
    readiness = _readiness(item)
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
    return _readiness(_load_property(db, context.user.organization_id, property_id))


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


def _public_response(item: Property) -> PublicPropertyResponse:
    return PublicPropertyResponse(
        code=f"{item.internal_number:06d}",
        slug=item.public_slug or f"imovel-{item.internal_number:06d}",
        property_type=item.property_type,
        purpose=item.purpose,
        address=dict(item.address or {}),
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
