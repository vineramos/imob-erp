from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.portfolio.models import Property, PropertyPhoto
from app.integrations.document_storage import DocumentStorageError, get_document_storage

router = APIRouter(tags=["property-media"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE = 12 * 1024 * 1024
MAX_PROPERTY_PHOTOS = 80


class PropertyPhotoResponse(BaseModel):
    id: UUID
    property_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    caption: str | None = None
    position: int
    is_cover: bool
    content_url: str
    created_at: object


class PropertyPhotoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caption: str | None = Field(default=None, max_length=300)
    is_cover: bool | None = None


class PropertyPhotoReorder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_ids: list[UUID] = Field(min_length=1, max_length=MAX_PROPERTY_PHOTOS)


class PublicPropertyPhotoResponse(BaseModel):
    id: UUID
    filename: str
    content_type: str
    caption: str | None = None
    position: int
    is_cover: bool
    content_url: str


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _property(db: Session, organization_id: UUID, property_id: UUID) -> Property:
    item = db.scalar(
        select(Property).where(Property.id == property_id, Property.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imóvel não encontrado.")
    return item


def _photo(db: Session, organization_id: UUID, property_id: UUID, photo_id: UUID) -> PropertyPhoto:
    item = db.scalar(
        select(PropertyPhoto).where(
            PropertyPhoto.id == photo_id,
            PropertyPhoto.property_id == property_id,
            PropertyPhoto.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foto não encontrada.")
    return item


def _photo_response(item: PropertyPhoto) -> PropertyPhotoResponse:
    return PropertyPhotoResponse(
        id=item.id,
        property_id=item.property_id,
        filename=item.filename,
        content_type=item.content_type,
        size_bytes=item.size_bytes,
        caption=item.caption,
        position=item.position,
        is_cover=item.is_cover,
        content_url=f"/properties/{item.property_id}/photos/{item.id}/content",
        created_at=item.created_at,
    )


def _public_photo_response(organization_id: UUID, slug: str, item: PropertyPhoto) -> PublicPropertyPhotoResponse:
    return PublicPropertyPhotoResponse(
        id=item.id,
        filename=item.filename,
        content_type=item.content_type,
        caption=item.caption,
        position=item.position,
        is_cover=item.is_cover,
        content_url=f"/public/sites/{organization_id}/properties/{slug}/photos/{item.id}/content",
    )


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    property_item: Property,
    action: str,
    *,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="properties",
        entity_type="property_photo",
        entity_id=str(property_item.id),
        before_data=before,
        after_data=after,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _suspend_publication(property_item: Property, context: UserContext) -> bool:
    if not property_item.publication_enabled:
        return False
    property_item.publication_enabled = False
    property_item.publication_updated_by_user_id = context.user.id
    return True


def _ordered_photos(db: Session, property_id: UUID) -> list[PropertyPhoto]:
    return list(
        db.scalars(
            select(PropertyPhoto)
            .where(PropertyPhoto.property_id == property_id)
            .order_by(PropertyPhoto.position.asc(), PropertyPhoto.created_at.asc(), PropertyPhoto.id.asc())
        ).all()
    )


def _public_property(db: Session, organization_id: UUID, slug: str) -> Property:
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


@router.get("/properties/{property_id}/photos", response_model=list[PropertyPhotoResponse])
def list_property_photos(
    property_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> list[PropertyPhotoResponse]:
    _property(db, context.user.organization_id, property_id)
    return [_photo_response(item) for item in _ordered_photos(db, property_id)]


@router.get("/properties/{property_id}/photos/cover", response_model=PropertyPhotoResponse | None)
def property_cover_photo(
    property_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> PropertyPhotoResponse | None:
    _property(db, context.user.organization_id, property_id)
    item = db.scalar(
        select(PropertyPhoto)
        .where(
            PropertyPhoto.property_id == property_id,
            PropertyPhoto.organization_id == context.user.organization_id,
        )
        .order_by(PropertyPhoto.is_cover.desc(), PropertyPhoto.position.asc(), PropertyPhoto.created_at.asc())
        .limit(1)
    )
    return _photo_response(item) if item else None


@router.post("/properties/{property_id}/photos", response_model=PropertyPhotoResponse, status_code=status.HTTP_201_CREATED)
async def upload_property_photo(
    property_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> PropertyPhotoResponse:
    property_item = _property(db, context.user.organization_id, property_id)
    storage = get_document_storage()
    if not storage.configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Storage de documentos ainda não configurado.")

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Use imagens JPG, PNG ou WEBP.")

    photo_count = int(db.scalar(select(func.count(PropertyPhoto.id)).where(PropertyPhoto.property_id == property_id)) or 0)
    if photo_count >= MAX_PROPERTY_PHOTOS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"O imóvel já atingiu o limite de {MAX_PROPERTY_PHOTOS} fotos.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A imagem enviada está vazia.")
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Cada foto pode ter no máximo 12 MB.")

    max_position = int(db.scalar(select(func.max(PropertyPhoto.position)).where(PropertyPhoto.property_id == property_id)) or -1)
    photo_id = uuid4()
    safe_filename = Path(file.filename or "foto").name.replace("/", "-").replace("\\", "-")
    object_name = storage.property_photo_object_name(
        organization_id=str(context.user.organization_id),
        property_code=f"{property_item.internal_number:06d}",
        photo_id=str(photo_id),
        filename=safe_filename,
    )
    try:
        reference = storage.upload_bytes(object_name=object_name, content=content, content_type=content_type)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    item = PropertyPhoto(
        id=photo_id,
        organization_id=context.user.organization_id,
        property_id=property_id,
        filename=safe_filename,
        content_type=content_type,
        storage_reference=reference,
        size_bytes=len(content),
        caption=None,
        position=max_position + 1,
        is_cover=photo_count == 0,
        created_by_user_id=context.user.id,
    )
    db.add(item)
    publication_suspended = _suspend_publication(property_item, context)
    db.flush()
    _audit(
        db,
        request,
        context,
        property_item,
        "properties.photo.uploaded",
        after={"photo_id": str(item.id), "filename": item.filename, "position": item.position, "is_cover": item.is_cover},
        reason="Publicação suspensa para conferência após alteração das fotos." if publication_suspended else None,
    )
    db.commit()
    db.refresh(item)
    return _photo_response(item)


@router.patch("/properties/{property_id}/photos/{photo_id}", response_model=PropertyPhotoResponse)
def update_property_photo(
    property_id: UUID,
    photo_id: UUID,
    payload: PropertyPhotoUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> PropertyPhotoResponse:
    property_item = _property(db, context.user.organization_id, property_id)
    item = _photo(db, context.user.organization_id, property_id, photo_id)
    before = {"caption": item.caption, "is_cover": item.is_cover, "position": item.position}
    changed = False

    if "caption" in payload.model_fields_set:
        caption = (payload.caption or "").strip() or None
        if caption != item.caption:
            item.caption = caption
            changed = True

    if payload.is_cover is False and item.is_cover:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Escolha outra foto como capa antes de remover a capa atual.")
    if payload.is_cover is True and not item.is_cover:
        db.execute(
            update(PropertyPhoto)
            .where(PropertyPhoto.property_id == property_id, PropertyPhoto.is_cover.is_(True))
            .values(is_cover=False)
        )
        db.flush()
        item.is_cover = True
        changed = True

    if changed:
        publication_suspended = _suspend_publication(property_item, context)
        _audit(
            db,
            request,
            context,
            property_item,
            "properties.photo.updated",
            before=before,
            after={"photo_id": str(item.id), "caption": item.caption, "is_cover": item.is_cover, "position": item.position},
            reason="Publicação suspensa para conferência após alteração das fotos." if publication_suspended else None,
        )
        db.commit()
        db.refresh(item)
    return _photo_response(item)


@router.post("/properties/{property_id}/photos/reorder", response_model=list[PropertyPhotoResponse])
def reorder_property_photos(
    property_id: UUID,
    payload: PropertyPhotoReorder,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> list[PropertyPhotoResponse]:
    property_item = _property(db, context.user.organization_id, property_id)
    items = _ordered_photos(db, property_id)
    existing_ids = [item.id for item in items]
    if len(payload.photo_ids) != len(existing_ids) or set(payload.photo_ids) != set(existing_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A nova ordem deve conter todas as fotos do imóvel uma única vez.")
    before = [str(item.id) for item in items]
    by_id = {item.id: item for item in items}
    for position, photo_id in enumerate(payload.photo_ids):
        by_id[photo_id].position = position
    publication_suspended = _suspend_publication(property_item, context)
    _audit(
        db,
        request,
        context,
        property_item,
        "properties.photos.reordered",
        before={"order": before},
        after={"order": [str(photo_id) for photo_id in payload.photo_ids]},
        reason="Publicação suspensa para conferência após alteração da ordem das fotos." if publication_suspended else None,
    )
    db.commit()
    return [_photo_response(item) for item in _ordered_photos(db, property_id)]


@router.delete("/properties/{property_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property_photo(
    property_id: UUID,
    photo_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> Response:
    property_item = _property(db, context.user.organization_id, property_id)
    item = _photo(db, context.user.organization_id, property_id, photo_id)
    before = {"photo_id": str(item.id), "filename": item.filename, "is_cover": item.is_cover, "position": item.position}
    remaining = list(
        db.scalars(
            select(PropertyPhoto)
            .where(PropertyPhoto.property_id == property_id, PropertyPhoto.id != photo_id)
            .order_by(PropertyPhoto.position.asc(), PropertyPhoto.created_at.asc())
        ).all()
    )
    try:
        get_document_storage().delete_reference(item.storage_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    was_cover = item.is_cover
    db.delete(item)
    db.flush()
    if was_cover and remaining:
        remaining[0].is_cover = True
    for position, photo in enumerate(remaining):
        photo.position = position
    publication_suspended = _suspend_publication(property_item, context)
    _audit(
        db,
        request,
        context,
        property_item,
        "properties.photo.deleted",
        before=before,
        after={"remaining": len(remaining), "new_cover_id": str(remaining[0].id) if was_cover and remaining else None},
        reason="Publicação suspensa para conferência após exclusão de foto." if publication_suspended else None,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/properties/{property_id}/photos/{photo_id}/content")
def property_photo_content(
    property_id: UUID,
    photo_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> Response:
    _property(db, context.user.organization_id, property_id)
    item = _photo(db, context.user.organization_id, property_id, photo_id)
    try:
        content = get_document_storage().download_bytes(item.storage_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return Response(content=content, media_type=item.content_type, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/public/sites/{organization_id}/properties/{slug}/photos", response_model=list[PublicPropertyPhotoResponse])
def public_property_photos(
    organization_id: UUID,
    slug: str,
    db: Session = Depends(get_db),
) -> list[PublicPropertyPhotoResponse]:
    property_item = _public_property(db, organization_id, slug)
    return [_public_photo_response(organization_id, slug, item) for item in _ordered_photos(db, property_item.id)]


@router.get("/public/sites/{organization_id}/properties/{slug}/photos/{photo_id}/content")
def public_property_photo_content(
    organization_id: UUID,
    slug: str,
    photo_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    property_item = _public_property(db, organization_id, slug)
    item = db.scalar(
        select(PropertyPhoto).where(
            PropertyPhoto.id == photo_id,
            PropertyPhoto.property_id == property_item.id,
            PropertyPhoto.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foto não encontrada.")
    try:
        content = get_document_storage().download_bytes(item.storage_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return Response(content=content, media_type=item.content_type, headers={"Cache-Control": "public, max-age=3600"})
