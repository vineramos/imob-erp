from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domains.contracts.models import AdministrationContract
from app.domains.contracts.pdf import contract_code
from app.domains.documents.models import Document
from app.domains.documents.schemas import DocumentCatalogItem, DocumentDetailResponse, DocumentVersionResponse
from app.domains.inspections.models import Inspection
from app.domains.inspections.pdf import inspection_code
from app.domains.leases.models import LeaseContract
from app.domains.leases.pdf import lease_contract_code
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.portfolio.models import Person, Property


ENTITY_TYPES = frozenset({
    "person", "property", "administration_contract", "lease_contract", "inspection", "maintenance"
})
DOCUMENT_CATEGORIES = frozenset({
    "general", "identity", "property", "contract", "inspection", "maintenance", "finance", "legal", "other"
})


def document_code(item: Document) -> str:
    return f"DOC-{item.internal_number:06d}"


def resolve_entity_label(db: Session, *, organization_id: UUID, entity_type: str, entity_id: UUID) -> str | None:
    if entity_type == "person":
        item = db.scalar(select(Person).where(Person.id == entity_id, Person.organization_id == organization_id))
        return item.name if item else None
    if entity_type == "property":
        item = db.scalar(select(Property).where(Property.id == entity_id, Property.organization_id == organization_id))
        return f"Imóvel {item.internal_number:06d}" if item else None
    if entity_type == "administration_contract":
        item = db.scalar(select(AdministrationContract).where(AdministrationContract.id == entity_id, AdministrationContract.organization_id == organization_id))
        return contract_code(item) if item else None
    if entity_type == "lease_contract":
        item = db.scalar(select(LeaseContract).where(LeaseContract.id == entity_id, LeaseContract.organization_id == organization_id))
        return lease_contract_code(item) if item else None
    if entity_type == "inspection":
        item = db.scalar(select(Inspection).where(Inspection.id == entity_id, Inspection.organization_id == organization_id))
        return inspection_code(item) if item else None
    if entity_type == "maintenance":
        item = db.scalar(select(MaintenanceRequest).where(MaintenanceRequest.id == entity_id, MaintenanceRequest.organization_id == organization_id))
        return f"Manutenção {item.internal_number:06d} · {item.title}" if item else None
    return None


def managed_detail(item: Document) -> DocumentDetailResponse:
    versions = [
        DocumentVersionResponse(
            version_number=version.version_number,
            original_filename=version.original_filename,
            content_type=version.content_type,
            size_bytes=version.size_bytes,
            hash_sha256=version.hash_sha256,
            notes=version.notes,
            created_at=version.created_at,
            download_path=f"/documents/managed/{item.id}/versions/{version.version_number}/content",
        )
        for version in item.versions
    ]
    return DocumentDetailResponse(
        id=item.id,
        code=document_code(item),
        title=item.title,
        category=item.category,
        status=item.status,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        entity_label=item.entity_label,
        current_version=item.current_version,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
        versions=versions,
    )


def _managed_catalog(db: Session, organization_id: UUID) -> list[DocumentCatalogItem]:
    documents = db.scalars(
        select(Document)
        .options(selectinload(Document.versions))
        .where(Document.organization_id == organization_id)
        .order_by(Document.updated_at.desc(), Document.internal_number.desc())
        .limit(500)
    ).unique().all()
    rows: list[DocumentCatalogItem] = []
    for item in documents:
        current = next((version for version in item.versions if version.version_number == item.current_version), None)
        if current is None:
            continue
        rows.append(DocumentCatalogItem(
            key=f"managed:{item.id}",
            source_kind="managed",
            document_id=item.id,
            title=item.title,
            category=item.category,
            status=item.status,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            entity_label=item.entity_label,
            filename=current.original_filename,
            content_type=current.content_type,
            size_bytes=current.size_bytes,
            hash_sha256=current.hash_sha256,
            version=item.current_version,
            version_count=len(item.versions),
            created_at=item.created_at,
            updated_at=item.updated_at,
            download_path=f"/documents/managed/{item.id}/versions/{item.current_version}/content",
            can_version=item.status == "active",
        ))
    return rows


def _system_catalog(db: Session, organization_id: UUID) -> list[DocumentCatalogItem]:
    rows: list[DocumentCatalogItem] = []
    administration = db.scalars(
        select(AdministrationContract).where(AdministrationContract.organization_id == organization_id).order_by(AdministrationContract.internal_number.desc()).limit(300)
    ).all()
    for item in administration:
        code = contract_code(item)
        if item.generated_document_reference:
            version = item.generated_document_version or item.current_version
            rows.append(DocumentCatalogItem(
                key=f"system:administration_contract:{item.id}:generated", source_kind="system",
                title=f"{code} · Contrato de Administração · Original", category="contract", status=item.status,
                entity_type="administration_contract", entity_id=item.id, entity_label=code,
                filename=f"{code}-v{version}-original.pdf", content_type="application/pdf", size_bytes=None,
                hash_sha256=item.generated_document_hash, version=version, version_count=1,
                created_at=item.created_at, updated_at=item.updated_at,
                download_path=f"/documents/system/administration_contract/{item.id}/generated/content", can_version=False,
            ))
        if item.archived_document_reference:
            rows.append(DocumentCatalogItem(
                key=f"system:administration_contract:{item.id}:archived", source_kind="system",
                title=f"{code} · Contrato de Administração · Assinado", category="contract", status="archived",
                entity_type="administration_contract", entity_id=item.id, entity_label=code,
                filename=f"{code}-v{item.current_version}-ASSINADO.pdf", content_type="application/pdf", size_bytes=None,
                hash_sha256=item.final_document_hash, version=item.current_version, version_count=1,
                created_at=item.archived_at or item.created_at, updated_at=item.archived_at or item.updated_at,
                download_path=f"/documents/system/administration_contract/{item.id}/archived/content", can_version=False,
            ))

    leases = db.scalars(
        select(LeaseContract).where(LeaseContract.organization_id == organization_id).order_by(LeaseContract.internal_number.desc()).limit(300)
    ).all()
    for item in leases:
        code = lease_contract_code(item)
        if item.generated_document_reference:
            version = item.generated_document_version or item.current_version
            rows.append(DocumentCatalogItem(
                key=f"system:lease_contract:{item.id}:generated", source_kind="system",
                title=f"{code} · Contrato de Locação · Original", category="contract", status=item.status,
                entity_type="lease_contract", entity_id=item.id, entity_label=code,
                filename=f"{code}-v{version}-original.pdf", content_type="application/pdf", size_bytes=None,
                hash_sha256=item.generated_document_hash, version=version, version_count=1,
                created_at=item.created_at, updated_at=item.updated_at,
                download_path=f"/documents/system/lease_contract/{item.id}/generated/content", can_version=False,
            ))
        if item.archived_document_reference:
            rows.append(DocumentCatalogItem(
                key=f"system:lease_contract:{item.id}:archived", source_kind="system",
                title=f"{code} · Contrato de Locação · Assinado", category="contract", status="archived",
                entity_type="lease_contract", entity_id=item.id, entity_label=code,
                filename=f"{code}-v{item.current_version}-ASSINADO.pdf", content_type="application/pdf", size_bytes=None,
                hash_sha256=item.final_document_hash, version=item.current_version, version_count=1,
                created_at=item.archived_at or item.created_at, updated_at=item.archived_at or item.updated_at,
                download_path=f"/documents/system/lease_contract/{item.id}/archived/content", can_version=False,
            ))

    inspections = db.scalars(
        select(Inspection).where(Inspection.organization_id == organization_id, Inspection.report_reference.is_not(None)).order_by(Inspection.internal_number.desc()).limit(300)
    ).all()
    for item in inspections:
        code = inspection_code(item)
        version = item.report_version or item.current_version
        rows.append(DocumentCatalogItem(
            key=f"system:inspection:{item.id}:report", source_kind="system",
            title=f"{code} · Laudo de Vistoria", category="inspection", status=item.status,
            entity_type="inspection", entity_id=item.id, entity_label=code,
            filename=f"{code}-v{version}.pdf", content_type="application/pdf", size_bytes=None,
            hash_sha256=item.report_hash, version=version, version_count=1,
            created_at=item.performed_at or item.created_at, updated_at=item.updated_at,
            download_path=f"/documents/system/inspection/{item.id}/report/content", can_version=False,
        ))
    return rows


def catalog(
    db: Session,
    *,
    organization_id: UUID,
    q: str | None = None,
    category: str | None = None,
    source_kind: str | None = None,
    status: str | None = None,
    entity_type: str | None = None,
) -> list[DocumentCatalogItem]:
    rows = [*_managed_catalog(db, organization_id), *_system_catalog(db, organization_id)]
    query = (q or "").strip().lower()
    if query:
        rows = [row for row in rows if query in " ".join(filter(None, [row.title, row.filename, row.entity_label])).lower()]
    if category:
        rows = [row for row in rows if row.category == category]
    if source_kind:
        rows = [row for row in rows if row.source_kind == source_kind]
    if status:
        rows = [row for row in rows if row.status == status]
    if entity_type:
        rows = [row for row in rows if row.entity_type == entity_type]
    rows.sort(key=lambda row: row.updated_at or row.created_at, reverse=True)
    return rows
