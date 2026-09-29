from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.portfolio.models import Property, PropertyPhoto
from app.integrations.document_storage import DocumentStorageError, get_document_storage
from app.integrations.instagram import (
    credentials as instagram_credentials,
    media_details,
    public_media_url,
    publish_carousel,
    publish_single,
    validate_media_signature,
)

router = APIRouter(tags=["property-instagram"])

MAX_CAROUSEL_ITEMS = 10


class InstagramPhotoItem(BaseModel):
    id: UUID
    filename: str
    caption: str | None = None
    position: int
    is_cover: bool
    content_url: str


class InstagramPublicationResponse(BaseModel):
    property_id: UUID
    status: Literal["draft", "ready", "published", "inactive", "failed"]
    format: Literal["carousel", "single", "story", "reel"]
    caption: str
    photo_ids: list[UUID]
    photos: list[InstagramPhotoItem]
    media_id: str | None = None
    permalink: str | None = None
    published_at: str | None = None
    inactivated_at: str | None = None
    inactivation_reason: str | None = None
    external_removal_pending: bool = False
    property_active: bool
    instagram_connected: bool = False


class InstagramPublicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["carousel", "single", "story", "reel"] = "carousel"
    caption: str = Field(default="", max_length=2200)
    photo_ids: list[UUID] = Field(default_factory=list, max_length=MAX_CAROUSEL_ITEMS)


def _property(db: Session, organization_id: UUID, property_id: UUID) -> Property:
    item = db.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Imóvel não encontrado.")
    return item


def _photos(db: Session, organization_id: UUID, property_id: UUID) -> list[PropertyPhoto]:
    return list(
        db.scalars(
            select(PropertyPhoto)
            .where(
                PropertyPhoto.organization_id == organization_id,
                PropertyPhoto.property_id == property_id,
            )
            .order_by(PropertyPhoto.position.asc(), PropertyPhoto.created_at.asc())
        ).all()
    )


def _money(value) -> str:
    if value is None:
        return ""
    amount = float(value)
    raw = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {raw}"


def _default_caption(item: Property) -> str:
    address = dict(item.address or {})
    title = (item.public_title or "").strip() or {
        "apartment": "Apartamento",
        "house": "Casa",
        "commercial": "Imóvel comercial",
        "land": "Terreno",
        "studio": "Studio",
    }.get(item.property_type, "Imóvel")
    location = ", ".join(
        value for value in [
            str(address.get("neighborhood") or "").strip(),
            str(address.get("city") or "").strip(),
        ] if value
    )
    details: list[str] = []
    if item.area_m2:
        details.append(f"{float(item.area_m2):g} m²")
    if item.bedrooms:
        details.append(f"{item.bedrooms} quarto{'s' if item.bedrooms != 1 else ''}")
    if item.suites:
        details.append(f"{item.suites} suíte{'s' if item.suites != 1 else ''}")
    if item.parking_spaces:
        details.append(f"{item.parking_spaces} vaga{'s' if item.parking_spaces != 1 else ''}")

    lines = [f"🏡 {title}"]
    if location:
        lines.append(f"📍 {location}")
    if details:
        lines.extend(["", " • ".join(details)])
    if item.rent_amount:
        lines.extend(["", f"💰 {_money(item.rent_amount)}"])
    description = (item.public_description or "").strip()
    if description:
        lines.extend(["", description[:900]])
    lines.extend(["", "Entre em contato para mais informações e agende sua visita."])
    return "\n".join(lines)[:2200]


def _photo_payload(item: PropertyPhoto) -> InstagramPhotoItem:
    return InstagramPhotoItem(
        id=item.id,
        filename=item.filename,
        caption=item.caption,
        position=item.position,
        is_cover=item.is_cover,
        content_url=f"/properties/{item.property_id}/photos/{item.id}/content",
    )


def _response(db: Session, item: Property, photos: list[PropertyPhoto]) -> InstagramPublicationResponse:
    state = dict(item.instagram_publication or {})
    available_ids = {str(photo.id) for photo in photos}
    selected_raw = [str(value) for value in list(state.get("photo_ids") or [])]
    selected = [UUID(value) for value in selected_raw if value in available_ids]
    if not selected:
        selected = [photo.id for photo in photos[:MAX_CAROUSEL_ITEMS]]

    inactive = item.status in {"leased", "inactive"}
    raw_status = str(state.get("status") or ("inactive" if inactive else "draft"))
    if inactive:
        raw_status = "inactive"
    if raw_status not in {"draft", "ready", "published", "inactive", "failed"}:
        raw_status = "draft"

    return InstagramPublicationResponse(
        property_id=item.id,
        status=raw_status,
        format=str(state.get("format") or "carousel"),
        caption=str(state.get("caption") or _default_caption(item)),
        photo_ids=selected,
        photos=[_photo_payload(photo) for photo in photos],
        media_id=(str(state.get("media_id") or "").strip() or None),
        permalink=(str(state.get("permalink") or "").strip() or None),
        published_at=state.get("published_at"),
        inactivated_at=state.get("inactivated_at"),
        inactivation_reason=state.get("inactivation_reason"),
        external_removal_pending=bool(state.get("external_removal_pending")),
        property_active=not inactive,
        instagram_connected=instagram_credentials(db, item.organization_id).configured,
    )


def _public_base_url(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    if forwarded_proto in {"http", "https"} and "://" in base:
        base = forwarded_proto + "://" + base.split("://", 1)[1]
    elif request.url.hostname and request.url.hostname.endswith(".run.app") and base.startswith("http://"):
        base = "https://" + base.removeprefix("http://")
    return base


@router.get("/properties/{property_id}/instagram-publication", response_model=InstagramPublicationResponse)
def get_instagram_publication(
    property_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> InstagramPublicationResponse:
    item = _property(db, context.user.organization_id, property_id)
    return _response(db, item, _photos(db, context.user.organization_id, property_id))


@router.put("/properties/{property_id}/instagram-publication", response_model=InstagramPublicationResponse)
def update_instagram_publication(
    property_id: UUID,
    payload: InstagramPublicationUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> InstagramPublicationResponse:
    item = _property(db, context.user.organization_id, property_id)
    if item.status in {"leased", "inactive"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O imóvel está inativo/locado e não pode preparar nova publicação no Instagram.",
        )

    photos = _photos(db, context.user.organization_id, property_id)
    valid_ids = {photo.id for photo in photos}
    if len(payload.photo_ids) != len(set(payload.photo_ids)):
        raise HTTPException(status_code=422, detail="Uma mesma foto não pode aparecer duas vezes no carrossel.")
    if any(photo_id not in valid_ids for photo_id in payload.photo_ids):
        raise HTTPException(status_code=422, detail="Uma ou mais fotos não pertencem a este imóvel.")
    if payload.format in {"carousel", "single", "story"} and not payload.photo_ids:
        raise HTTPException(status_code=422, detail="Selecione ao menos uma foto para a publicação.")
    if payload.format == "single" and len(payload.photo_ids) != 1:
        raise HTTPException(status_code=422, detail="Post de foto única deve conter exatamente uma imagem.")

    before = dict(item.instagram_publication or {})
    now = datetime.now(timezone.utc).isoformat()
    existing_media_id = str(before.get("media_id") or "").strip() or None
    item.instagram_publication = {
        **before,
        "status": "ready" if payload.caption.strip() and payload.photo_ids else "draft",
        "format": payload.format,
        "caption": payload.caption.strip(),
        "photo_ids": [str(photo_id) for photo_id in payload.photo_ids],
        "updated_at": now,
        "external_removal_pending": bool(before.get("external_removal_pending", False)),
        **({"media_id": existing_media_id} if existing_media_id else {}),
    }

    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    write_audit(
        db,
        context=context,
        action="properties.instagram.draft_updated",
        module="properties",
        entity_type="property",
        entity_id=str(item.id),
        before_data={"instagram_publication": before},
        after_data={"instagram_publication": dict(item.instagram_publication or {})},
        ip_address=ip_address,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(item)
    return _response(db, item, photos)


@router.get("/public/instagram-media/{organization_id}/{property_id}/{photo_id}")
def public_instagram_media(
    organization_id: UUID,
    property_id: UUID,
    photo_id: UUID,
    expires: int = Query(..., ge=1),
    signature: str = Query(..., min_length=32, max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    if not validate_media_signature(organization_id, property_id, photo_id, expires, signature):
        raise HTTPException(status_code=404, detail="Mídia temporária não encontrada.")
    photo = db.scalar(
        select(PropertyPhoto).where(
            PropertyPhoto.id == photo_id,
            PropertyPhoto.property_id == property_id,
            PropertyPhoto.organization_id == organization_id,
        )
    )
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto não encontrada.")
    try:
        content = get_document_storage().download_bytes(photo.storage_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=404, detail="Foto indisponível.") from exc
    return Response(
        content=content,
        media_type=photo.content_type,
        headers={"Cache-Control": "public, max-age=900"},
    )


@router.post("/properties/{property_id}/instagram-publication/publish", response_model=InstagramPublicationResponse)
def publish_instagram_property(
    property_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("properties.publish")),
    db: Session = Depends(get_db),
) -> InstagramPublicationResponse:
    item = _property(db, context.user.organization_id, property_id)
    if item.status in {"leased", "inactive"}:
        raise HTTPException(status_code=409, detail="O imóvel está inativo/locado e não pode ser publicado.")
    state = dict(item.instagram_publication or {})
    publication_format = str(state.get("format") or "carousel")
    if publication_format not in {"single", "carousel"}:
        raise HTTPException(status_code=422, detail="Neste momento o envio real está habilitado para Foto única e Carrossel.")

    photos = _photos(db, context.user.organization_id, property_id)
    by_id = {str(photo.id): photo for photo in photos}
    selected_ids = [str(value) for value in list(state.get("photo_ids") or [])]
    selected = [by_id[value] for value in selected_ids if value in by_id]
    if not selected:
        raise HTTPException(status_code=422, detail="Salve ao menos uma foto na publicação antes de enviar.")
    if publication_format == "single" and len(selected) != 1:
        raise HTTPException(status_code=422, detail="Foto única precisa conter exatamente uma imagem.")
    if publication_format == "carousel" and not 2 <= len(selected) <= MAX_CAROUSEL_ITEMS:
        raise HTTPException(status_code=422, detail="O carrossel precisa ter entre 2 e 10 imagens.")

    caption = str(state.get("caption") or "").strip()
    if not caption:
        raise HTTPException(status_code=422, detail="Salve a legenda antes de publicar.")

    creds = instagram_credentials(db, context.user.organization_id)
    if not creds.configured:
        raise HTTPException(status_code=422, detail="Conecte e teste a conta do Instagram em Configurações > Integrações.")

    base_url = _public_base_url(request)
    urls = [
        public_media_url(
            base_url=base_url,
            organization_id=context.user.organization_id,
            property_id=item.id,
            photo_id=photo.id,
        )
        for photo in selected
    ]
    before = dict(state)
    state["status"] = "publishing"
    state["last_error"] = None
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    item.instagram_publication = state
    db.commit()

    try:
        media_id = (
            publish_single(creds, image_url=urls[0], caption=caption)
            if publication_format == "single"
            else publish_carousel(creds, image_urls=urls, caption=caption)
        )
        details = media_details(creds, media_id)
    except HTTPException as exc:
        failed = dict(item.instagram_publication or {})
        failed["status"] = "failed"
        failed["last_error"] = str(exc.detail)[:1000]
        failed["updated_at"] = datetime.now(timezone.utc).isoformat()
        item.instagram_publication = failed
        db.commit()
        raise

    now = datetime.now(timezone.utc)
    published = dict(item.instagram_publication or {})
    published.update({
        "status": "published",
        "media_id": media_id,
        "permalink": str(details.get("permalink") or "").strip() or None,
        "published_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "external_removal_pending": False,
        "last_error": None,
    })
    item.instagram_publication = published

    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action="properties.instagram.published",
        module="properties",
        entity_type="property",
        entity_id=str(item.id),
        before_data={"instagram_publication": before},
        after_data={
            "status": "published",
            "media_id": media_id,
            "permalink": published.get("permalink"),
            "format": publication_format,
            "photo_count": len(selected),
        },
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(item)
    return _response(db, item, photos)
