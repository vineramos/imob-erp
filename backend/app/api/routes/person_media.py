from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.portfolio.models import Person
from app.integrations.document_storage import DocumentStorageError, get_document_storage

router = APIRouter(tags=["person-media"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE = 8 * 1024 * 1024


def _person(db: Session, organization_id: UUID, person_id: UUID) -> Person:
    item = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == organization_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada.")
    return item


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


@router.post("/people/{person_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
async def upload_person_photo(
    person_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> Response:
    person = _person(db, context.user.organization_id, person_id)
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Use imagens JPG, PNG ou WEBP.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A imagem enviada está vazia.")
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="A foto pode ter no máximo 8 MB.")

    storage = get_document_storage()
    if not storage.configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Storage de documentos ainda não configurado.")

    safe_filename = Path(file.filename or "foto").name.replace("/", "-").replace("\\", "-")
    object_name = f"imob/{context.user.organization_id}/people/{person.id}/profile/{safe_filename}"

    old_reference = person.photo_storage_reference
    try:
        reference = storage.upload_bytes(object_name=object_name, content=content, content_type=content_type)
        if old_reference and old_reference != reference:
            storage.delete_reference(old_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    person.photo_filename = safe_filename
    person.photo_content_type = content_type
    person.photo_storage_reference = reference
    person.photo_size_bytes = len(content)
    person.photo_updated_at = datetime.now(timezone.utc)

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="people.photo.updated",
        module="properties",
        entity_type="person",
        entity_id=str(person.id),
        after_data={"filename": safe_filename, "content_type": content_type, "size_bytes": len(content)},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/people/{person_id}/photo/content")
def person_photo_content(
    person_id: UUID,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
) -> Response:
    person = _person(db, context.user.organization_id, person_id)
    if not person.photo_storage_reference:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foto não cadastrada.")
    try:
        content = get_document_storage().download_bytes(person.photo_storage_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=person.photo_content_type or "image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete("/people/{person_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
def delete_person_photo(
    person_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("properties.edit")),
    db: Session = Depends(get_db),
) -> Response:
    person = _person(db, context.user.organization_id, person_id)
    if not person.photo_storage_reference:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        get_document_storage().delete_reference(person.photo_storage_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    person.photo_filename = None
    person.photo_content_type = None
    person.photo_storage_reference = None
    person.photo_size_bytes = None
    person.photo_updated_at = None

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="people.photo.removed",
        module="properties",
        entity_type="person",
        entity_id=str(person.id),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
