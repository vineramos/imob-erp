from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.contracts.models import AdministrationContract
from app.domains.contracts.pdf import contract_code
from app.domains.documents.models import Document, DocumentVersion
from app.domains.documents.schemas import DocumentCatalogItem, DocumentDetailResponse
from app.domains.documents.service import DOCUMENT_CATEGORIES, ENTITY_TYPES, catalog, document_code, managed_detail, resolve_entity_label
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.inspections.models import Inspection
from app.domains.inspections.pdf import inspection_code
from app.domains.leases.models import LeaseContract
from app.domains.leases.pdf import lease_contract_code
from app.integrations.document_storage import DocumentStorageError, get_document_storage

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_FILE_SIZE = 20 * 1024 * 1024
ALLOWED_CONTENT_TYPES = frozenset({
    "application/pdf",
    "image/jpeg", "image/png", "image/webp",
    "text/plain",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, item: Document, action: str, *, after=None, reason=None) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="documents",
        entity_type="document",
        entity_id=str(item.id),
        after_data=after,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _load(db: Session, organization_id: UUID, document_id: UUID) -> Document:
    item = db.scalar(
        select(Document)
        .options(selectinload(Document.versions))
        .where(Document.id == document_id, Document.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    return item


def _clean_filename(value: str | None) -> str:
    filename = (value or "documento").replace("\\", "-").replace("/", "-").replace("..", "-").strip()
    filename = re.sub(r"[\x00-\x1f\x7f]+", "", filename)
    return filename[:255] or "documento"


def _validate_metadata(title: str, category: str, entity_type: str | None, entity_id: UUID | None) -> tuple[str, str, str | None]:
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=422, detail="Informe o título do documento.")
    if len(clean_title) > 220:
        raise HTTPException(status_code=422, detail="O título deve ter no máximo 220 caracteres.")
    clean_category = category.strip().lower()
    if clean_category not in DOCUMENT_CATEGORIES:
        raise HTTPException(status_code=422, detail="Categoria de documento inválida.")
    clean_entity_type = (entity_type or "").strip().lower() or None
    if (clean_entity_type is None) != (entity_id is None):
        raise HTTPException(status_code=422, detail="Informe o tipo e o registro vinculado juntos.")
    if clean_entity_type and clean_entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de vínculo documental inválido.")
    return clean_title, clean_category, clean_entity_type


async def _file_payload(file: UploadFile) -> tuple[bytes, str, str]:
    content_type = (file.content_type or "").strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Formato não permitido. Use PDF, imagem, TXT, Word ou Excel.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="O arquivo está vazio.")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="O arquivo deve ter no máximo 20 MB.")
    return content, content_type, _clean_filename(file.filename)


def _content_response(content: bytes, *, content_type: str, filename: str) -> Response:
    disposition = "inline" if content_type == "application/pdf" or content_type.startswith("image/") else "attachment"
    safe = _clean_filename(filename).replace('"', "")
    return Response(content=content, media_type=content_type, headers={"Content-Disposition": f'{disposition}; filename="{safe}"'})


def _managed_object_name(storage, *, organization_id: str, code: str, version: int, filename: str) -> str:
    # Reutiliza o namespace persistente já estabelecido. O marcador documents- mantém
    # os anexos centrais separados dos contratos mesmo no provider legado.
    return storage.object_name(
        organization_id=organization_id,
        contract_code=f"documents-{code}-v{version}",
        filename=filename,
    )


@router.get("", response_model=list[DocumentCatalogItem])
def list_documents(
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    source_kind: str | None = Query(default=None, pattern="^(managed|system)$"),
    document_status: str | None = Query(default=None, alias="status"),
    entity_type: str | None = Query(default=None),
    context: UserContext = Depends(require_permission("documents.view")),
    db: Session = Depends(get_db),
) -> list[DocumentCatalogItem]:
    return catalog(
        db,
        organization_id=context.user.organization_id,
        q=q,
        category=category,
        source_kind=source_kind,
        status=document_status,
        entity_type=entity_type,
    )


@router.post("", response_model=DocumentDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    request: Request,
    title: str = Form(...),
    category: str = Form(default="general"),
    entity_type: str | None = Form(default=None),
    entity_id: UUID | None = Form(default=None),
    notes: str | None = Form(default=None),
    file: UploadFile = File(...),
    context: UserContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    clean_title, clean_category, clean_entity_type = _validate_metadata(title, category, entity_type, entity_id)
    entity_label = None
    if clean_entity_type and entity_id:
        entity_label = resolve_entity_label(db, organization_id=context.user.organization_id, entity_type=clean_entity_type, entity_id=entity_id)
        if entity_label is None:
            raise HTTPException(status_code=404, detail="Registro vinculado não encontrado nesta empresa.")
    content, content_type, filename = await _file_payload(file)
    storage = get_document_storage()
    if not storage.configured:
        raise HTTPException(status_code=409, detail="O storage de documentos não está configurado.")

    item = Document(
        organization_id=context.user.organization_id,
        title=clean_title,
        category=clean_category,
        entity_type=clean_entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        status="active",
        current_version=1,
        notes=(notes or "").strip() or None,
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    digest = hashlib.sha256(content).hexdigest()
    object_name = _managed_object_name(storage, organization_id=str(item.organization_id), code=document_code(item), version=1, filename=filename)
    try:
        reference = storage.upload_bytes(object_name=object_name, content=content, content_type=content_type)
    except DocumentStorageError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.add(DocumentVersion(
        document_id=item.id,
        version_number=1,
        original_filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        storage_reference=reference,
        hash_sha256=digest,
        notes="Versão inicial",
        uploaded_by_user_id=context.user.id,
    ))
    _audit(db, request, context, item, "documents.created", after={"code": document_code(item), "category": item.category, "entity_type": item.entity_type, "entity_id": str(item.entity_id) if item.entity_id else None, "hash": digest})
    db.commit()
    return managed_detail(_load(db, context.user.organization_id, item.id))


@router.get("/managed/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: UUID,
    context: UserContext = Depends(require_permission("documents.view")),
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    return managed_detail(_load(db, context.user.organization_id, document_id))


@router.post("/managed/{document_id}/versions", response_model=DocumentDetailResponse)
async def create_document_version(
    document_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    notes: str | None = Form(default=None),
    context: UserContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    item = _load(db, context.user.organization_id, document_id)
    if item.status != "active":
        raise HTTPException(status_code=409, detail="Documento arquivado não recebe novas versões.")
    content, content_type, filename = await _file_payload(file)
    storage = get_document_storage()
    if not storage.configured:
        raise HTTPException(status_code=409, detail="O storage de documentos não está configurado.")
    next_version = item.current_version + 1
    digest = hashlib.sha256(content).hexdigest()
    object_name = _managed_object_name(storage, organization_id=str(item.organization_id), code=document_code(item), version=next_version, filename=filename)
    try:
        reference = storage.upload_bytes(object_name=object_name, content=content, content_type=content_type)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    item.current_version = next_version
    item.updated_at = datetime.now(timezone.utc)
    db.add(DocumentVersion(
        document_id=item.id,
        version_number=next_version,
        original_filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        storage_reference=reference,
        hash_sha256=digest,
        notes=(notes or "").strip() or None,
        uploaded_by_user_id=context.user.id,
    ))
    _audit(db, request, context, item, "documents.version_created", after={"version": next_version, "hash": digest, "filename": filename}, reason=(notes or "").strip() or None)
    db.commit()
    return managed_detail(_load(db, context.user.organization_id, item.id))


@router.post("/managed/{document_id}/archive", response_model=DocumentDetailResponse)
def archive_document(
    document_id: UUID,
    request: Request,
    reason: str | None = Form(default=None),
    context: UserContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    item = _load(db, context.user.organization_id, document_id)
    if item.status == "archived":
        return managed_detail(item)
    item.status = "archived"
    item.updated_at = datetime.now(timezone.utc)
    _audit(db, request, context, item, "documents.archived", after={"status": "archived", "version": item.current_version}, reason=(reason or "").strip() or None)
    db.commit()
    return managed_detail(_load(db, context.user.organization_id, item.id))


@router.get("/managed/{document_id}/versions/{version_number}/content")
def download_managed_document(
    document_id: UUID,
    version_number: int,
    context: UserContext = Depends(require_permission("documents.view")),
    db: Session = Depends(get_db),
) -> Response:
    item = _load(db, context.user.organization_id, document_id)
    version = next((row for row in item.versions if row.version_number == version_number), None)
    if version is None:
        raise HTTPException(status_code=404, detail="Versão do documento não encontrada.")
    try:
        content = get_document_storage().download_bytes(version.storage_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _content_response(content, content_type=version.content_type, filename=version.original_filename)


def _system_reference(db: Session, organization_id: UUID, entity_type: str, entity_id: UUID, variant: str) -> tuple[str, str]:
    if entity_type == "administration_contract":
        item = db.scalar(select(AdministrationContract).where(AdministrationContract.id == entity_id, AdministrationContract.organization_id == organization_id))
        if item is None:
            raise HTTPException(status_code=404, detail="Contrato de administração não encontrado.")
        code = contract_code(item)
        if variant == "generated" and item.generated_document_reference:
            return item.generated_document_reference, f"{code}-v{item.generated_document_version or item.current_version}-original.pdf"
        if variant == "archived" and item.archived_document_reference:
            return item.archived_document_reference, f"{code}-v{item.current_version}-ASSINADO.pdf"
    elif entity_type == "lease_contract":
        item = db.scalar(select(LeaseContract).where(LeaseContract.id == entity_id, LeaseContract.organization_id == organization_id))
        if item is None:
            raise HTTPException(status_code=404, detail="Contrato de locação não encontrado.")
        code = lease_contract_code(item)
        if variant == "generated" and item.generated_document_reference:
            return item.generated_document_reference, f"{code}-v{item.generated_document_version or item.current_version}-original.pdf"
        if variant == "archived" and item.archived_document_reference:
            return item.archived_document_reference, f"{code}-v{item.current_version}-ASSINADO.pdf"
    elif entity_type == "inspection" and variant == "report":
        item = db.scalar(select(Inspection).where(Inspection.id == entity_id, Inspection.organization_id == organization_id))
        if item is None:
            raise HTTPException(status_code=404, detail="Vistoria não encontrada.")
        if item.report_reference:
            code = inspection_code(item)
            return item.report_reference, f"{code}-v{item.report_version or item.current_version}.pdf"
    else:
        raise HTTPException(status_code=422, detail="Tipo ou variante de documento automático inválido.")
    raise HTTPException(status_code=404, detail="Arquivo automático não encontrado.")


@router.get("/system/{entity_type}/{entity_id}/{variant}/content")
def download_system_document(
    entity_type: str,
    entity_id: UUID,
    variant: str,
    context: UserContext = Depends(require_permission("documents.view")),
    db: Session = Depends(get_db),
) -> Response:
    reference, filename = _system_reference(db, context.user.organization_id, entity_type, entity_id, variant)
    try:
        content = get_document_storage().download_bytes(reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _content_response(content, content_type="application/pdf", filename=filename)
