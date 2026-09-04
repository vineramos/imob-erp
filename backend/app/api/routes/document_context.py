from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.documents.context import context_catalog
from app.domains.documents.schemas import DocumentCatalogItem
from app.domains.documents.service import ENTITY_TYPES
from app.domains.foundation.access import UserContext, require_permission

router = APIRouter(prefix="/documents/context", tags=["documents"])


@router.get("/{entity_type}/{entity_id}", response_model=list[DocumentCatalogItem])
def list_context_documents(
    entity_type: str,
    entity_id: UUID,
    context: UserContext = Depends(require_permission("documents.view")),
    db: Session = Depends(get_db),
) -> list[DocumentCatalogItem]:
    clean_type = entity_type.strip().lower()
    if clean_type not in ENTITY_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de contexto documental inválido.")
    rows = context_catalog(
        db,
        organization_id=context.user.organization_id,
        entity_type=clean_type,
        entity_id=entity_id,
    )
    if rows is None:
        raise HTTPException(status_code=404, detail="Cadastro não encontrado nesta empresa.")
    return rows
