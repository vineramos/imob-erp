from __future__ import annotations

import io
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.core_models import FinancialTitle
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person, Property
from app.integrations.document_storage import DocumentStorageError, get_document_storage

router = APIRouter(prefix="/finance/treasury/manual-titles", tags=["finance-treasury"])
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class ManualTitleCreate(BaseModel):
    direction: Literal["receivable", "payable"]
    fund_scope: Literal["operating", "third_party"] = "operating"
    category: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=240)
    counterparty_name: str | None = Field(default=None, max_length=220)
    counterparty_person_id: UUID | None = None
    competence: date
    due_date: date
    amount: Decimal = Field(gt=0)
    property_id: UUID | None = None
    lease_contract_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=3000)
    boleto_line: str | None = Field(default=None, max_length=180)


def _permission(context: UserContext, direction: str) -> None:
    required = "finance.charge.create" if direction == "receivable" else "finance.payment.prepare"
    if not context.has(required):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permissão necessária: {required}")


def _audit(db: Session, request: Request, context: UserContext, action: str, item: FinancialTitle, after: dict | None = None) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type="financial_title",
        entity_id=str(item.id),
        after_data=after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )


def _response(item: FinancialTitle) -> dict:
    snapshot = dict(item.source_snapshot or {})
    return {
        "id": str(item.id),
        "code": f"FIN-{item.internal_number:06d}",
        "direction": item.direction,
        "fund_scope": item.fund_scope,
        "category": item.category,
        "description": item.description,
        "counterparty_name": item.counterparty_name,
        "counterparty_person_id": snapshot.get("counterparty_person_id"),
        "property_id": str(item.property_id) if item.property_id else None,
        "lease_contract_id": str(item.lease_contract_id) if item.lease_contract_id else None,
        "competence": item.competence,
        "due_date": item.due_date,
        "amount": float(item.amount),
        "status": item.status,
        "attachments": list(snapshot.get("attachments") or []),
        "boleto_line": snapshot.get("boleto_line"),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_manual_title(
    payload: ManualTitleCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> dict:
    _permission(context, payload.direction)
    organization_id = context.user.organization_id

    person = None
    if payload.counterparty_person_id:
        person = db.scalar(
            select(Person).where(
                Person.id == payload.counterparty_person_id,
                Person.organization_id == organization_id,
                Person.is_active.is_(True),
            )
        )
        if person is None:
            raise HTTPException(status_code=422, detail="Fornecedor/cliente selecionado não foi encontrado ou está inativo.")

    property_id = payload.property_id
    if property_id:
        property_item = db.scalar(select(Property).where(Property.id == property_id, Property.organization_id == organization_id))
        if property_item is None:
            raise HTTPException(status_code=422, detail="Imóvel selecionado não foi encontrado.")

    if payload.lease_contract_id:
        lease = db.scalar(
            select(LeaseContract).where(
                LeaseContract.id == payload.lease_contract_id,
                LeaseContract.organization_id == organization_id,
            )
        )
        if lease is None:
            raise HTTPException(status_code=422, detail="Contrato de locação selecionado não foi encontrado.")
        if property_id and property_id != lease.property_id:
            raise HTTPException(status_code=422, detail="O imóvel informado não pertence ao contrato selecionado.")
        property_id = property_id or lease.property_id

    counterparty = (person.name if person else (payload.counterparty_name or "").strip()) or "Não informado"
    snapshot = {
        "counterparty_person_id": str(person.id) if person else None,
        "counterparty_document_number": person.document_number if person else None,
        "boleto_line": (payload.boleto_line or "").strip() or None,
        "attachments": [],
        "created_from": "treasury_cash_flow",
    }
    item = FinancialTitle(
        organization_id=organization_id,
        direction=payload.direction,
        fund_scope=payload.fund_scope,
        source_type="manual",
        source_id=None,
        property_id=property_id,
        lease_contract_id=payload.lease_contract_id,
        category=payload.category.strip(),
        description=payload.description.strip(),
        counterparty_name=counterparty,
        competence=payload.competence.replace(day=1),
        due_date=payload.due_date,
        amount=payload.amount,
        settled_amount=Decimal("0.00"),
        status="pending",
        notes=(payload.notes or "").strip() or None,
        source_snapshot=snapshot,
    )
    db.add(item)
    db.flush()
    _audit(db, request, context, "finance.manual_title.created", item, _response(item))
    db.commit()
    db.refresh(item)
    return _response(item)


def _extract_pdf_text(content: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if not text:
            warnings.append("O PDF parece ser somente imagem; o boleto foi aceito, mas os dados não puderam ser lidos automaticamente.")
        return text, warnings
    except Exception:
        return "", ["Não foi possível extrair texto deste PDF; o arquivo ainda pode ser anexado ao lançamento."]


def _first_date(text: str) -> str | None:
    patterns = [
        r"(?i)vencimento[^\d]{0,30}(\d{2}/\d{2}/\d{4})",
        r"(?i)data\s+de\s+vencimento[^\d]{0,30}(\d{2}/\d{2}/\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(1), "%d/%m/%Y").date().isoformat()
        except ValueError:
            pass
    return None


def _first_amount(text: str) -> float | None:
    patterns = [
        r"(?i)valor\s+(?:do\s+)?documento[^\d]{0,35}(?:R\$\s*)?([\d\.]+,\d{2})",
        r"(?i)valor\s+cobrado[^\d]{0,35}(?:R\$\s*)?([\d\.]+,\d{2})",
        r"(?i)valor[^\d]{0,20}(?:R\$\s*)?([\d\.]+,\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                continue
    return None


def _boleto_line(text: str) -> str | None:
    for match in re.finditer(r"(?:\d[\s\.\-]*){44,48}", text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) in {44, 46, 47, 48}:
            return digits
    return None


def _document_number(text: str) -> str | None:
    match = re.search(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", text)
    return re.sub(r"\D", "", match.group(0)) if match else None


def _beneficiary(text: str) -> str | None:
    match = re.search(r"(?im)^\s*(?:benefici[aá]rio|cedente)(?:\s+final)?\s*[:\-]?\s*(.{3,120})$", text)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" :-")
    return value[:120] or None


@router.post("/parse-document")
async def parse_financial_document(
    file: UploadFile = File(...),
    context: UserContext = Depends(require_permission("finance.view")),
) -> dict:
    del context
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Documento excede o limite de 10 MB.")
    filename = file.filename or "documento"
    content_type = (file.content_type or "").lower()
    warnings: list[str] = []
    text = ""
    if filename.lower().endswith(".pdf") or content_type == "application/pdf":
        text, warnings = _extract_pdf_text(content)
    elif content_type.startswith("text/") or Path(filename).suffix.lower() in {".txt", ".csv"}:
        text = content.decode("utf-8", errors="ignore")
    else:
        warnings.append("Leitura automática está disponível para PDF com texto. Este arquivo poderá ser anexado normalmente.")

    extracted = {
        "due_date": _first_date(text) if text else None,
        "amount": _first_amount(text) if text else None,
        "boleto_line": _boleto_line(text) if text else None,
        "document_number": _document_number(text) if text else None,
        "counterparty_name": _beneficiary(text) if text else None,
    }
    if text and not any(value is not None for value in extracted.values()):
        warnings.append("O texto foi lido, mas não foi possível identificar com segurança vencimento, valor ou linha do boleto.")
    return {"filename": filename, "content_type": file.content_type, "extracted": extracted, "warnings": warnings}


def _load_manual(db: Session, organization_id: UUID, title_id: UUID) -> FinancialTitle:
    item = db.scalar(
        select(FinancialTitle).where(
            FinancialTitle.id == title_id,
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.source_type == "manual",
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Lançamento financeiro manual não encontrado.")
    return item


@router.post("/{title_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    title_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> dict:
    item = _load_manual(db, context.user.organization_id, title_id)
    _permission(context, item.direction)
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Documento excede o limite de 10 MB.")
    if not content:
        raise HTTPException(status_code=422, detail="Documento vazio.")

    filename = (file.filename or "documento").replace("..", "-").replace("/", "-").replace("\\", "-")
    attachment_id = str(uuid.uuid4())
    object_name = f"finance/{context.user.organization_id}/titles/{item.id}/{attachment_id}-{filename}"
    storage = get_document_storage()
    try:
        reference = storage.upload_bytes(object_name=object_name, content=content, content_type=file.content_type or "application/octet-stream")
    except DocumentStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    snapshot = dict(item.source_snapshot or {})
    attachments = list(snapshot.get("attachments") or [])
    meta = {
        "id": attachment_id,
        "filename": filename,
        "content_type": file.content_type or "application/octet-stream",
        "size_bytes": len(content),
        "storage_reference": reference,
        "created_at": datetime.utcnow().isoformat(),
    }
    attachments.append(meta)
    snapshot["attachments"] = attachments
    item.source_snapshot = snapshot
    _audit(db, request, context, "finance.manual_title.attachment_added", item, {"attachment": {k: v for k, v in meta.items() if k != "storage_reference"}})
    db.commit()
    return {k: v for k, v in meta.items() if k != "storage_reference"}


@router.get("/{title_id}/attachments/{attachment_id}")
def download_attachment(
    title_id: UUID,
    attachment_id: str,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> Response:
    item = _load_manual(db, context.user.organization_id, title_id)
    attachments = list((item.source_snapshot or {}).get("attachments") or [])
    meta = next((entry for entry in attachments if str(entry.get("id")) == attachment_id), None)
    if meta is None:
        raise HTTPException(status_code=404, detail="Anexo não encontrado.")
    try:
        content = get_document_storage().download_bytes(str(meta.get("storage_reference") or ""))
    except DocumentStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    filename = str(meta.get("filename") or "documento").replace('"', "")
    return Response(
        content=content,
        media_type=str(meta.get("content_type") or "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
