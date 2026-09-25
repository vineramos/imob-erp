from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class DocumentVersionResponse(BaseModel):
    version_number: int
    original_filename: str
    content_type: str
    size_bytes: int
    hash_sha256: str
    notes: str | None
    created_at: datetime
    download_path: str


class DocumentCatalogItem(BaseModel):
    key: str
    source_kind: Literal["managed", "system"]
    document_id: UUID | None = None
    title: str
    category: str
    status: str
    entity_type: str | None = None
    entity_id: UUID | None = None
    entity_label: str | None = None
    filename: str
    content_type: str
    size_bytes: int | None = None
    hash_sha256: str | None = None
    version: int
    version_count: int
    created_at: datetime
    updated_at: datetime
    download_path: str
    can_version: bool = False


class DocumentDetailResponse(BaseModel):
    id: UUID
    code: str
    title: str
    category: str
    status: str
    entity_type: str | None
    entity_id: UUID | None
    entity_label: str | None
    current_version: int
    notes: str | None
    created_at: datetime
    updated_at: datetime
    versions: list[DocumentVersionResponse]
