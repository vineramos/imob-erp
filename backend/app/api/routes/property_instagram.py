from __future__ import annotations

import io

import httpx
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from PIL import Image, ImageDraw, ImageFont, ImageOps
import qrcode
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import OrganizationSettings
from app.domains.portfolio.models import Property, PropertyPhoto
from app.integrations.document_storage import DocumentStorageError, get_document_storage
from app.integrations.instagram import (
    credentials as instagram_credentials,
    media_details,
    public_media_url,
    public_story_description_url,
    public_story_media_url,
    publish_carousel,
    publish_single,
    publish_story,
    validate_media_signature,
    validate_story_description_signature,
    validate_story_media_signature,
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


class InstagramPublicationHistoryItem(BaseModel):
    media_id: str
    permalink: str | None = None
    published_at: str
    format: Literal["carousel", "single", "story", "reel"]
    photo_count: int


class InstagramPublicationResponse(BaseModel):
    property_id: UUID
    status: Literal["draft", "ready", "publishing", "published", "inactive", "failed"]
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
    last_error: str | None = None
    history: list[InstagramPublicationHistoryItem] = Field(default_factory=list)
    story_status: Literal["draft", "ready", "publishing", "published", "failed"] = "draft"
    story_photo_id: UUID | None = None
    story_media_id: str | None = None
    story_zoom: float = 1.0
    story_offset_x: float = 0.0
    story_offset_y: float = 0.0
    story_description_media_id: str | None = None
    story_site_url: str | None = None
    story_text_scale: float = 1.0
    story_qr_scale: float = 1.0
    story_text_offset_x: float = 0.0
    story_text_offset_y: float = 0.0
    story_qr_offset_x: float = 0.0
    story_qr_offset_y: float = 0.0
    story_attributes_enabled: bool = True
    story_attributes_layout: Literal["horizontal", "vertical", "chips", "bottom_bar"] = "bottom_bar"
    story_attributes_scale: float = 1.0
    story_attributes_offset_x: float = 0.0
    story_attributes_offset_y: float = 0.0
    story_attributes: list[dict[str, str]] = Field(default_factory=list)
    story_published_at: str | None = None
    story_last_error: str | None = None
    property_active: bool
    instagram_connected: bool = False


class InstagramPublicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["carousel", "single", "story", "reel"] = "carousel"
    caption: str = Field(default="", max_length=2200)
    photo_ids: list[UUID] = Field(default_factory=list, max_length=MAX_CAROUSEL_ITEMS)


class InstagramStoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_id: UUID
    zoom: float = Field(default=1.0, ge=0.2, le=2.0)
    offset_x: float = Field(default=0.0, ge=-1.0, le=1.0)
    offset_y: float = Field(default=0.0, ge=-1.0, le=1.0)
    text_scale: float = Field(default=1.0, ge=0.6, le=1.8)
    qr_scale: float = Field(default=1.0, ge=0.6, le=1.8)
    text_offset_x: float = Field(default=0.0, ge=-1.0, le=1.0)
    text_offset_y: float = Field(default=0.0, ge=-1.0, le=1.0)
    qr_offset_x: float = Field(default=0.0, ge=-1.0, le=1.0)
    qr_offset_y: float = Field(default=0.0, ge=-1.0, le=1.0)
    attributes_enabled: bool = True
    attributes_layout: Literal["horizontal", "vertical", "chips", "bottom_bar"] = "bottom_bar"
    attributes_scale: float = Field(default=1.0, ge=0.6, le=1.6)
    attributes_offset_x: float = Field(default=0.0, ge=-1.0, le=1.0)
    attributes_offset_y: float = Field(default=0.0, ge=-1.0, le=1.0)


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


def _story_attribute_items(item: Property) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    address = dict(item.address or {})
    neighborhood = str(address.get("neighborhood") or "").strip()
    if neighborhood:
        items.append({"key": "neighborhood", "value": neighborhood, "label": "bairro"})
    if item.bedrooms:
        items.append({"key": "bedrooms", "value": str(item.bedrooms), "label": "quartos"})
    if item.bathrooms:
        items.append({"key": "bathrooms", "value": str(item.bathrooms), "label": "banheiros"})
    if item.area_m2:
        items.append({"key": "area", "value": f"{float(item.area_m2):g}", "label": "m²"})
    if item.parking_spaces:
        items.append({"key": "parking", "value": str(item.parking_spaces), "label": "vagas"})
    if item.rent_amount:
        items.append({"key": "rent", "value": _money(item.rent_amount), "label": "aluguel"})
    return items


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
    if raw_status not in {"draft", "ready", "publishing", "published", "inactive", "failed"}:
        raw_status = "draft"

    history: list[InstagramPublicationHistoryItem] = []
    for entry in list(state.get("history") or [])[:8]:
        if not isinstance(entry, dict):
            continue
        media_id = str(entry.get("media_id") or "").strip()
        published_at = str(entry.get("published_at") or "").strip()
        publication_format = str(entry.get("format") or "")
        if not media_id or not published_at or publication_format not in {"carousel", "single", "story", "reel"}:
            continue
        history.append(InstagramPublicationHistoryItem(
            media_id=media_id,
            permalink=str(entry.get("permalink") or "").strip() or None,
            published_at=published_at,
            format=publication_format,
            photo_count=max(1, int(entry.get("photo_count") or 1)),
        ))

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
        last_error=(str(state.get("last_error") or "").strip() or None),
        history=history,
        story_status=str((state.get("story") or {}).get("status") or "draft"),
        story_photo_id=UUID(str((state.get("story") or {}).get("photo_id"))) if (state.get("story") or {}).get("photo_id") else None,
        story_media_id=(str((state.get("story") or {}).get("media_id") or "").strip() or None),
        story_zoom=float((state.get("story") or {}).get("zoom") or 1.0),
        story_offset_x=float((state.get("story") or {}).get("offset_x") or 0.0),
        story_offset_y=float((state.get("story") or {}).get("offset_y") or 0.0),
        story_description_media_id=(str((state.get("story") or {}).get("description_media_id") or "").strip() or None),
        story_site_url=(str((state.get("story") or {}).get("site_url") or "").strip() or None),
        story_text_scale=float((state.get("story") or {}).get("text_scale") or 1.0),
        story_qr_scale=float((state.get("story") or {}).get("qr_scale") or 1.0),
        story_text_offset_x=float((state.get("story") or {}).get("text_offset_x") or 0.0),
        story_text_offset_y=float((state.get("story") or {}).get("text_offset_y") or 0.0),
        story_qr_offset_x=float((state.get("story") or {}).get("qr_offset_x") or 0.0),
        story_qr_offset_y=float((state.get("story") or {}).get("qr_offset_y") or 0.0),
        story_attributes_enabled=bool((state.get("story") or {}).get("attributes_enabled", True)),
        story_attributes_layout=str((state.get("story") or {}).get("attributes_layout") or "bottom_bar"),
        story_attributes_scale=float((state.get("story") or {}).get("attributes_scale") or 1.0),
        story_attributes_offset_x=float((state.get("story") or {}).get("attributes_offset_x") or 0.0),
        story_attributes_offset_y=float((state.get("story") or {}).get("attributes_offset_y") or 0.0),
        story_attributes=_story_attribute_items(item),
        story_published_at=(state.get("story") or {}).get("published_at"),
        story_last_error=(str((state.get("story") or {}).get("last_error") or "").strip() or None),
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


def _load_story_font(size: int, *, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_story_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if width <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) >= max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(lines)) < len(text):
        lines[-1] = lines[-1].rstrip(" .") + "…"
    return lines


def _story_site_url(request: Request, item: Property) -> str:
    base = _public_base_url(request)
    if item.public_slug:
        return f"{base}/site/{item.organization_id}/imoveis/{item.public_slug}"
    return f"{base}/site/{item.organization_id}"


def _story_brand_logo(db: Session, request: Request, item: Property) -> Image.Image | None:
    settings = db.scalar(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == item.organization_id)
    )
    theme = dict(settings.erp_theme or {}) if settings else {}
    logo_url = str(theme.get("logoUrl") or "").strip()
    if not logo_url:
        return None
    if logo_url.startswith("/"):
        logo_url = f"{_public_base_url(request)}{logo_url}"
    if not logo_url.startswith(("http://", "https://")):
        return None
    try:
        response = httpx.get(logo_url, timeout=8.0, follow_redirects=True)
        response.raise_for_status()
        logo = Image.open(io.BytesIO(response.content))
        return ImageOps.exif_transpose(logo).convert("RGBA")
    except (httpx.HTTPError, OSError, ValueError):
        return None


def _story_description_image(request: Request, item: Property, db: Session) -> bytes:
    width, height = 1080, 1920
    image = Image.new("RGB", (width, height), (16, 20, 27))
    draw = ImageDraw.Draw(image)

    state = dict(item.instagram_publication or {})
    story = dict(state.get("story") or {})
    text_scale = max(0.6, min(1.8, float(story.get("text_scale") or 1.0)))
    qr_scale = max(0.6, min(1.8, float(story.get("qr_scale") or 1.0)))
    text_offset_x = max(-1.0, min(1.0, float(story.get("text_offset_x") or 0.0)))
    text_offset_y = max(-1.0, min(1.0, float(story.get("text_offset_y") or 0.0)))
    qr_offset_x = max(-1.0, min(1.0, float(story.get("qr_offset_x") or 0.0)))
    qr_offset_y = max(-1.0, min(1.0, float(story.get("qr_offset_y") or 0.0)))

    title_font = _load_story_font(max(34, round(64 * text_scale)), bold=True)
    heading_font = _load_story_font(max(22, round(34 * text_scale)), bold=True)
    body_font = _load_story_font(max(20, round(30 * text_scale)))
    small_font = _load_story_font(max(16, round(24 * text_scale)))

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
        details.append(f"{item.bedrooms} quartos")
    if item.suites:
        details.append(f"{item.suites} suítes")
    if item.parking_spaces:
        details.append(f"{item.parking_spaces} vagas")

    accent = (202, 168, 91)
    muted = (184, 191, 202)
    white = (245, 247, 250)

    logo = _story_brand_logo(db, request, item)
    if logo is not None:
        max_w, max_h = 250, 120
        ratio = min(max_w / logo.width, max_h / logo.height)
        logo = logo.resize((max(1, round(logo.width * ratio)), max(1, round(logo.height * ratio))), Image.Resampling.LANCZOS)
        image.paste(logo, (72, 72), logo)
        brand_y = 72 + logo.height + 36
    else:
        settings = db.scalar(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == item.organization_id)
        )
        theme = dict(settings.erp_theme or {}) if settings else {}
        brand_name = str(theme.get("companyShortName") or theme.get("companyName") or "Imobiliária").strip()
        draw.rounded_rectangle((72, 72, 180, 180), radius=26, fill=(33, 40, 52))
        initials = "".join(part[:1].upper() for part in brand_name.split()[:2]) or "IM"
        draw.text((94, 96), initials, font=_load_story_font(36, bold=True), fill=accent)
        draw.text((204, 104), brand_name, font=_load_story_font(34, bold=True), fill=white)
        brand_y = 228

    tx = 72 + round(text_offset_x * 120)
    y = brand_y + 12 + round(text_offset_y * 250)
    draw.text((tx, y), "IMÓVEL EM DESTAQUE", font=small_font, fill=accent)
    y += max(54, round(70 * text_scale))

    max_text_width = max(500, min(930, round(930 / max(0.8, text_scale))))
    for line in _wrap_story_text(draw, title, title_font, max_text_width, 3):
        draw.text((tx, y), line, font=title_font, fill=white)
        y += max(50, round(78 * text_scale))

    if location:
        y += 12
        draw.text((tx, y), location, font=heading_font, fill=muted)
        y += max(42, round(62 * text_scale))

    if details:
        y += 26
        detail_text = "  •  ".join(details)
        for line in _wrap_story_text(draw, detail_text, heading_font, max_text_width, 2):
            draw.text((tx, y), line, font=heading_font, fill=white)
            y += max(38, round(52 * text_scale))

    if item.rent_amount:
        y += 24
        price_w = max(300, round(448 * text_scale))
        price_h = max(70, round(96 * text_scale))
        draw.rounded_rectangle((tx, y, min(1008, tx + price_w), y + price_h), radius=22, fill=(33, 40, 52))
        draw.text((tx + 24, y + max(16, round(24 * text_scale))), _money(item.rent_amount), font=heading_font, fill=accent)
        y += price_h + 30

    description = (item.public_description or "").strip()
    if description:
        y += 8
        for line in _wrap_story_text(draw, description, body_font, max_text_width, 6):
            draw.text((tx, y), line, font=body_font, fill=white)
            y += max(34, round(46 * text_scale))

    site_url = _story_site_url(request, item)
    qr = qrcode.QRCode(version=None, box_size=8, border=2)
    qr.add_data(site_url)
    qr.make(fit=True)
    qr_size = max(170, min(430, round(280 * qr_scale)))
    qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((qr_size, qr_size), Image.Resampling.NEAREST)

    footer_y = 1455
    draw.rounded_rectangle((54, footer_y, 1026, 1840), radius=34, fill=(245, 247, 250))

    # O CTA do rodapé tem tipografia própria e não acompanha o zoom da caixa
    # de texto principal. Assim o QR pode crescer sem cortar a chamada.
    footer_heading = _load_story_font(34, bold=True)
    footer_body = _load_story_font(28)
    footer_tx = 88 + round(text_offset_x * 80)

    qr_x = 700 + round(qr_offset_x * 170) - (qr_size - 280) // 2
    qr_y = footer_y + 48 + round(qr_offset_y * 100) - (qr_size - 280) // 2
    qr_x = max(560, min(width - qr_size - 48, qr_x))
    qr_y = max(footer_y + 18, min(height - qr_size - 48, qr_y))

    # Reserva sempre uma faixa real entre o texto e o QR Code. Se o QR for
    # ampliado ou movido para a esquerda, a chamada quebra de linha em vez de
    # ficar escondida atrás dele.
    footer_text_width = max(260, qr_x - footer_tx - 34)
    footer_text_y = footer_y + 58
    for line in _wrap_story_text(draw, "Veja todos os detalhes no site", footer_heading, footer_text_width, 2):
        draw.text((footer_tx, footer_text_y), line, font=footer_heading, fill=(22, 27, 35))
        footer_text_y += 44

    footer_text_y += 8
    for line in _wrap_story_text(draw, "Aponte a câmera para o QR Code", footer_body, footer_text_width, 2):
        draw.text((footer_tx, footer_text_y), line, font=footer_body, fill=(75, 83, 95))
        footer_text_y += 36

    image.paste(qr_image, (qr_x, qr_y))

    # Não exibimos a URL bruta no card. Ela fica codificada somente no QR Code.

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=94, optimize=True)
    return output.getvalue()


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


def _draw_story_attribute_icon(draw: ImageDraw.ImageDraw, key: str, x: int, y: int, size: int, color: tuple[int, int, int]) -> None:
    stroke = max(2, round(size * 0.08))
    if key == "neighborhood":
        draw.ellipse((x + size * 0.22, y + size * 0.08, x + size * 0.78, y + size * 0.64), outline=color, width=stroke)
        draw.ellipse((x + size * 0.43, y + size * 0.28, x + size * 0.57, y + size * 0.42), fill=color)
        draw.polygon([(x + size * 0.5, y + size * 0.92), (x + size * 0.3, y + size * 0.56), (x + size * 0.7, y + size * 0.56)], fill=color)
    elif key == "bedrooms":
        draw.rectangle((x, y + size * 0.46, x + size, y + size * 0.78), outline=color, width=stroke)
        draw.rectangle((x + size * 0.08, y + size * 0.27, x + size * 0.42, y + size * 0.48), outline=color, width=stroke)
        draw.line((x, y + size * 0.22, x, y + size * 0.88), fill=color, width=stroke)
        draw.line((x + size, y + size * 0.44, x + size, y + size * 0.88), fill=color, width=stroke)
    elif key == "bathrooms":
        draw.arc((x + size * 0.08, y + size * 0.36, x + size * 0.92, y + size * 0.82), 0, 180, fill=color, width=stroke)
        draw.line((x + size * 0.12, y + size * 0.58, x + size * 0.12, y + size * 0.25, x + size * 0.5, y + size * 0.25), fill=color, width=stroke)
        draw.arc((x + size * 0.42, y + size * 0.14, x + size * 0.68, y + size * 0.4), 180, 300, fill=color, width=stroke)
    elif key == "area":
        draw.line((x + size * 0.12, y + size * 0.82, x + size * 0.82, y + size * 0.12), fill=color, width=stroke)
        draw.line((x + size * 0.08, y + size * 0.62, x + size * 0.38, y + size * 0.92), fill=color, width=stroke)
        draw.line((x + size * 0.62, y + size * 0.08, x + size * 0.92, y + size * 0.38), fill=color, width=stroke)
    elif key == "parking":
        draw.rounded_rectangle((x + size * 0.08, y + size * 0.34, x + size * 0.92, y + size * 0.72), radius=max(3, round(size * 0.12)), outline=color, width=stroke)
        draw.line((x + size * 0.24, y + size * 0.34, x + size * 0.36, y + size * 0.16, x + size * 0.7, y + size * 0.16, x + size * 0.82, y + size * 0.34), fill=color, width=stroke)
        draw.ellipse((x + size * 0.2, y + size * 0.66, x + size * 0.38, y + size * 0.84), outline=color, width=stroke)
        draw.ellipse((x + size * 0.62, y + size * 0.66, x + size * 0.8, y + size * 0.84), outline=color, width=stroke)
    else:
        font = _load_story_font(max(18, round(size * 0.82)), bold=True)
        draw.text((x + size * 0.08, y - size * 0.08), "$", font=font, fill=color)


def _render_story_attributes(image: Image.Image, item: Property, story: dict) -> None:
    if not bool(story.get("attributes_enabled", True)):
        return
    items = _story_attribute_items(item)
    if not items:
        return

    width, height = image.size
    layout = str(story.get("attributes_layout") or "bottom_bar")
    if layout not in {"horizontal", "vertical", "chips", "bottom_bar"}:
        layout = "bottom_bar"
    scale = max(0.6, min(1.6, float(story.get("attributes_scale") or 1.0)))
    offset_x = max(-1.0, min(1.0, float(story.get("attributes_offset_x") or 0.0)))
    offset_y = max(-1.0, min(1.0, float(story.get("attributes_offset_y") or 0.0)))

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    white = (248, 250, 252, 255)
    muted = (216, 222, 230, 255)
    accent = (222, 186, 98, 255)
    panel = (13, 18, 25, 205)
    border = (255, 255, 255, 35)
    value_font = _load_story_font(max(24, round(34 * scale)), bold=True)
    label_font = _load_story_font(max(16, round(21 * scale)))
    icon_size = max(28, round(38 * scale))
    pad = max(18, round(24 * scale))
    gap = max(12, round(18 * scale))

    def item_size(entry: dict[str, str]) -> tuple[int, int]:
        value_bbox = draw.textbbox((0, 0), entry["value"], font=value_font)
        label_bbox = draw.textbbox((0, 0), entry["label"], font=label_font)
        text_w = max(value_bbox[2] - value_bbox[0], label_bbox[2] - label_bbox[0])
        return icon_size + gap + text_w + pad * 2, max(icon_size, 62 * scale) + pad * 2

    sizes = [item_size(entry) for entry in items]

    def fit_font(text: str, max_size: int, min_size: int, max_width: int, *, bold: bool = False):
        size = max_size
        while size > min_size:
            candidate = _load_story_font(size, bold=bold)
            bbox = draw.textbbox((0, 0), text, font=candidate)
            if bbox[2] - bbox[0] <= max_width:
                return candidate
            size -= 2
        return _load_story_font(min_size, bold=bold)
    if layout == "vertical":
        box_w = min(round(width * 0.52), max(w for w, _ in sizes))
        box_h = sum(h for _, h in sizes) + gap * (len(items) - 1)
        center_x = width * 0.5 + offset_x * width * 0.5
        center_y = height * 0.62 + offset_y * height * 0.5
        box_x = round(center_x - box_w / 2)
        box_y = round(center_y - box_h / 2)
        box_x = max(36, min(width - box_w - 36, box_x))
        box_y = max(36, min(height - box_h - 36, box_y))
        y = box_y
        for entry, (_, h) in zip(items, sizes):
            draw.rounded_rectangle((box_x, y, box_x + box_w, y + h), radius=24, fill=panel, outline=border, width=2)
            iy = y + (h - icon_size) // 2
            _draw_story_attribute_icon(draw, entry["key"], box_x + pad, iy, icon_size, accent if entry["key"] == "rent" else white)
            tx = box_x + pad + icon_size + gap
            draw.text((tx, y + pad - 2), entry["value"], font=value_font, fill=accent if entry["key"] == "rent" else white)
            draw.text((tx, y + pad + round(35 * scale)), entry["label"], font=label_font, fill=muted)
            y += h + gap
    elif layout == "chips":
        chip_gap = gap
        max_row_w = width - 96
        lines: list[list[tuple[dict[str, str], int, int]]] = []
        current_line: list[tuple[dict[str, str], int, int]] = []
        current_width = 0

        for entry, (w, h) in zip(items, sizes):
            chip_w = min(w, round(width * 0.54))
            projected = chip_w if not current_line else current_width + chip_gap + chip_w
            if current_line and projected > max_row_w:
                lines.append(current_line)
                current_line = []
                current_width = 0
            current_line.append((entry, chip_w, h))
            current_width = chip_w if len(current_line) == 1 else current_width + chip_gap + chip_w
        if current_line:
            lines.append(current_line)

        line_widths = [sum(chip_w for _, chip_w, _ in line) + chip_gap * max(0, len(line) - 1) for line in lines]
        line_heights = [max(h for _, _, h in line) for line in lines]
        block_w = max(line_widths)
        block_h = sum(line_heights) + chip_gap * max(0, len(lines) - 1)

        center_x = width * 0.5 + offset_x * width * 0.5
        center_y = height * 0.74 + offset_y * height * 0.5
        origin_x = round(center_x - block_w / 2)
        origin_y = round(center_y - block_h / 2)
        origin_x = max(30, min(width - block_w - 30, origin_x))
        origin_y = max(30, min(height - block_h - 30, origin_y))

        cy = origin_y
        for line, line_width, line_height in zip(lines, line_widths, line_heights):
            cx = origin_x + round((block_w - line_width) / 2)
            for entry, chip_w, h in line:
                item_y = cy + round((line_height - h) / 2)
                draw.rounded_rectangle((cx, item_y, cx + chip_w, item_y + h), radius=round(h / 2), fill=panel, outline=border, width=2)
                iy = item_y + (h - icon_size) // 2
                _draw_story_attribute_icon(draw, entry["key"], cx + pad, iy, icon_size, accent if entry["key"] == "rent" else white)
                tx = cx + pad + icon_size + gap
                draw.text((tx, item_y + pad - 2), entry["value"], font=value_font, fill=accent if entry["key"] == "rent" else white)
                draw.text((tx, item_y + pad + round(35 * scale)), entry["label"], font=label_font, fill=muted)
                cx += chip_w + chip_gap
            cy += line_height + chip_gap
    else:
        bottom_bar = layout == "bottom_bar"
        box_h = max(132, round(156 * scale))
        box_w = width - (72 if bottom_bar else 108)
        center_x = width * 0.5 + offset_x * width * 0.5
        base_y = 0.82 if bottom_bar else 0.78
        center_y = height * base_y + offset_y * height * 0.5
        box_x = round(center_x - box_w / 2)
        box_y = round(center_y - box_h / 2)
        box_x = max(28, min(width - box_w - 28, box_x))
        box_y = max(28, min(height - box_h - 28, box_y))
        draw.rounded_rectangle((box_x, box_y, box_x + box_w, box_y + box_h), radius=30, fill=panel, outline=border, width=2)
        cell_w = box_w / len(items)
        for index, entry in enumerate(items):
            cx = box_x + index * cell_w
            if index:
                draw.line((cx, box_y + 24, cx, box_y + box_h - 24), fill=(255, 255, 255, 26), width=2)
            local_icon_size = min(icon_size, max(24, round(cell_w * 0.2)))
            icon_x = round(cx + cell_w / 2 - local_icon_size / 2)
            icon_y = box_y + max(10, round(13 * scale))
            _draw_story_attribute_icon(draw, entry["key"], icon_x, icon_y, local_icon_size, accent if entry["key"] == "rent" else white)

            usable_width = max(44, round(cell_w - 18))
            local_value_font = fit_font(entry["value"], max(18, round(30 * scale)), 16, usable_width, bold=True)
            local_label_font = fit_font(entry["label"], max(13, round(18 * scale)), 11, usable_width)
            value_bbox = draw.textbbox((0, 0), entry["value"], font=local_value_font)
            label_bbox = draw.textbbox((0, 0), entry["label"], font=local_label_font)
            draw.text((round(cx + cell_w / 2 - (value_bbox[2]-value_bbox[0])/2), box_y + round(55 * scale)), entry["value"], font=local_value_font, fill=accent if entry["key"] == "rent" else white)
            draw.text((round(cx + cell_w / 2 - (label_bbox[2]-label_bbox[0])/2), box_y + round(96 * scale)), entry["label"], font=local_label_font, fill=muted)

    image.paste(overlay, (0, 0), overlay)


@router.get("/public/instagram-story-media/{organization_id}/{property_id}/{photo_id}")
def public_instagram_story_media(
    organization_id: UUID,
    property_id: UUID,
    photo_id: UUID,
    expires: int = Query(..., ge=1),
    zoom: float = Query(..., ge=0.2, le=2.0),
    offset_x: float = Query(default=0.0, ge=-1.0, le=1.0),
    offset_y: float = Query(default=0.0, ge=-1.0, le=1.0),
    signature: str = Query(..., min_length=32, max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    normalized_zoom = round(zoom, 2)
    normalized_x = round(offset_x, 3)
    normalized_y = round(offset_y, 3)
    if not validate_story_media_signature(
        organization_id,
        property_id,
        photo_id,
        expires,
        normalized_zoom,
        normalized_x,
        normalized_y,
        signature,
    ):
        raise HTTPException(status_code=404, detail="Mídia temporária do Story não encontrada.")

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
        source = Image.open(io.BytesIO(content))
        source = ImageOps.exif_transpose(source).convert("RGB")
    except (DocumentStorageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Foto indisponível para o Story.") from exc

    target_width, target_height = 1080, 1920
    base_scale = min(target_width / source.width, target_height / source.height)
    scale = base_scale * normalized_zoom
    resized_width = max(1, round(source.width * scale))
    resized_height = max(1, round(source.height * scale))
    resized = source.resize((resized_width, resized_height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (target_width, target_height), (0, 0, 0))
    left = (target_width - resized_width) // 2 + round(normalized_x * target_width / 2)
    top = (target_height - resized_height) // 2 + round(normalized_y * target_height / 2)
    canvas.paste(resized, (left, top))

    item = _property(db, organization_id, property_id)
    story_state = dict((dict(item.instagram_publication or {}).get("story") or {}))
    _render_story_attributes(canvas, item, story_state)

    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=92, optimize=True)
    return Response(
        content=output.getvalue(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=900"},
    )


@router.get("/public/instagram-story-description/{organization_id}/{property_id}")
def public_instagram_story_description(
    organization_id: UUID,
    property_id: UUID,
    request: Request,
    expires: int = Query(..., ge=1),
    signature: str = Query(..., min_length=32, max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    if not validate_story_description_signature(organization_id, property_id, expires, signature):
        raise HTTPException(status_code=404, detail="Card temporário do Story não encontrado.")
    item = _property(db, organization_id, property_id)
    content = _story_description_image(request, item, db)
    return Response(
        content=content,
        media_type="image/jpeg",
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
    permalink = str(details.get("permalink") or "").strip() or None
    publication_entry = {
        "media_id": media_id,
        "permalink": permalink,
        "published_at": now.isoformat(),
        "format": publication_format,
        "photo_count": len(selected),
    }
    previous_history = [
        entry for entry in list(published.get("history") or [])
        if isinstance(entry, dict) and str(entry.get("media_id") or "") != media_id
    ]
    published.update({
        "status": "published",
        "media_id": media_id,
        "permalink": permalink,
        "published_at": now.isoformat(),
        "photo_count": len(selected),
        "updated_at": now.isoformat(),
        "external_removal_pending": False,
        "last_error": None,
        "history": [publication_entry, *previous_history][:8],
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


@router.put("/properties/{property_id}/instagram-publication/story", response_model=InstagramPublicationResponse)
def update_instagram_story(
    property_id: UUID,
    payload: InstagramStoryUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> InstagramPublicationResponse:
    item = _property(db, context.user.organization_id, property_id)
    if item.status in {"leased", "inactive"}:
        raise HTTPException(status_code=409, detail="O imóvel está inativo/locado e não pode preparar Story.")

    photos = _photos(db, context.user.organization_id, property_id)
    valid_ids = {photo.id for photo in photos}
    if payload.photo_id not in valid_ids:
        raise HTTPException(status_code=422, detail="A foto selecionada não pertence a este imóvel.")

    before = dict(item.instagram_publication or {})
    story = dict(before.get("story") or {})
    story.update({
        "status": "ready",
        "photo_id": str(payload.photo_id),
        "zoom": round(payload.zoom, 2),
        "offset_x": round(payload.offset_x, 3),
        "offset_y": round(payload.offset_y, 3),
        "text_scale": round(payload.text_scale, 2),
        "qr_scale": round(payload.qr_scale, 2),
        "text_offset_x": round(payload.text_offset_x, 3),
        "text_offset_y": round(payload.text_offset_y, 3),
        "qr_offset_x": round(payload.qr_offset_x, 3),
        "qr_offset_y": round(payload.qr_offset_y, 3),
        "attributes_enabled": payload.attributes_enabled,
        "attributes_layout": payload.attributes_layout,
        "attributes_scale": round(payload.attributes_scale, 2),
        "attributes_offset_x": round(payload.attributes_offset_x, 3),
        "attributes_offset_y": round(payload.attributes_offset_y, 3),
        "media_id": None,
        "description_media_id": None,
        "permalink": None,
        "description_permalink": None,
        "site_url": None,
        "published_at": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_error": None,
    })
    item.instagram_publication = {**before, "story": story}

    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action="properties.instagram.story_draft_updated",
        module="properties",
        entity_type="property",
        entity_id=str(item.id),
        before_data={"story": before.get("story")},
        after_data={"story": story},
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(item)
    return _response(db, item, photos)


@router.post("/properties/{property_id}/instagram-publication/story/publish", response_model=InstagramPublicationResponse)
def publish_instagram_story_property(
    property_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("properties.publish")),
    db: Session = Depends(get_db),
) -> InstagramPublicationResponse:
    item = _property(db, context.user.organization_id, property_id)
    if item.status in {"leased", "inactive"}:
        raise HTTPException(status_code=409, detail="O imóvel está inativo/locado e não pode ser publicado em Story.")

    state = dict(item.instagram_publication or {})
    story = dict(state.get("story") or {})
    photo_id_raw = str(story.get("photo_id") or "").strip()
    if not photo_id_raw:
        raise HTTPException(status_code=422, detail="Selecione e salve uma foto para o Story.")
    try:
        photo_id = UUID(photo_id_raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Foto do Story inválida.") from exc

    photo = db.scalar(
        select(PropertyPhoto).where(
            PropertyPhoto.id == photo_id,
            PropertyPhoto.property_id == property_id,
            PropertyPhoto.organization_id == context.user.organization_id,
        )
    )
    if photo is None:
        raise HTTPException(status_code=422, detail="A foto selecionada para o Story não está mais disponível.")

    creds = instagram_credentials(db, context.user.organization_id)
    if not creds.configured:
        raise HTTPException(status_code=422, detail="Conecte e teste a conta do Instagram em Configurações > Integrações.")

    story["status"] = "publishing"
    story["last_error"] = None
    story["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["story"] = story
    item.instagram_publication = state
    db.commit()

    story_zoom = round(float(story.get("zoom") or 1.0), 2)
    story_offset_x = round(float(story.get("offset_x") or 0.0), 3)
    story_offset_y = round(float(story.get("offset_y") or 0.0), 3)
    base_url = _public_base_url(request)
    image_url = public_story_media_url(
        base_url=base_url,
        organization_id=context.user.organization_id,
        property_id=item.id,
        photo_id=photo.id,
        zoom=story_zoom,
        offset_x=story_offset_x,
        offset_y=story_offset_y,
    )
    description_url = public_story_description_url(
        base_url=base_url,
        organization_id=context.user.organization_id,
        property_id=item.id,
    )
    try:
        existing_media_id = str(story.get("media_id") or "").strip()
        if existing_media_id:
            media_id = existing_media_id
        else:
            media_id = publish_story(creds, image_url=image_url)
            partial_state = dict(item.instagram_publication or {})
            partial_story = dict(partial_state.get("story") or {})
            partial_story.update({
                "status": "publishing",
                "media_id": media_id,
                "site_url": _story_site_url(request, item),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
            })
            partial_state["story"] = partial_story
            item.instagram_publication = partial_state
            db.commit()

        current_story = dict((dict(item.instagram_publication or {}).get("story") or {}))
        existing_description_media_id = str(current_story.get("description_media_id") or "").strip()
        if existing_description_media_id:
            description_media_id = existing_description_media_id
        else:
            description_media_id = publish_story(creds, image_url=description_url)

    except HTTPException as exc:
        failed_state = dict(item.instagram_publication or {})
        failed_story = dict(failed_state.get("story") or {})
        failed_story.update({
            "status": "failed",
            "last_error": str(exc.detail)[:1000],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        failed_state["story"] = failed_story
        item.instagram_publication = failed_state
        db.commit()
        raise

    now = datetime.now(timezone.utc)
    final_state = dict(item.instagram_publication or {})
    final_story = dict(final_state.get("story") or {})
    permalink = None
    description_permalink = None
    site_url = _story_site_url(request, item)
    final_story.update({
        "status": "published",
        "media_id": media_id,
        "description_media_id": description_media_id,
        "permalink": permalink,
        "description_permalink": description_permalink,
        "site_url": site_url,
        "published_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "last_error": None,
    })
    previous_history = [
        entry for entry in list(final_state.get("history") or [])
        if isinstance(entry, dict) and str(entry.get("media_id") or "") != media_id
    ]
    history_entry = {
        "media_id": media_id,
        "permalink": permalink,
        "published_at": now.isoformat(),
        "format": "story",
        "photo_count": 2,
    }
    final_state["story"] = final_story
    final_state["history"] = [history_entry, *previous_history][:8]
    item.instagram_publication = final_state

    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action="properties.instagram.story_published",
        module="properties",
        entity_type="property",
        entity_id=str(item.id),
        after_data={
            "status": "published",
            "media_id": media_id,
            "description_media_id": description_media_id,
            "format": "story",
            "story_count": 2,
            "photo_id": str(photo.id),
            "site_url": site_url,
        },
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(item)
    return _response(db, item, _photos(db, context.user.organization_id, property_id))
