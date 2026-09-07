from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.finance.bank_models import BankAccount, BankReconciliation, BankStatementImport, BankTransaction
from app.domains.finance.bank_schemas import (
    BankAccountCreate,
    BankAccountResponse,
    BankImportResponse,
    BankingOverview,
    BankReconciliationRequest,
    BankReconciliationResponse,
    BankTransactionCreate,
    BankTransactionResponse,
    ReconciliationCandidate,
)
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.late_charges import amount_due, record_payment_with_late_charges
from app.domains.finance.models import MaintenanceFinancialEntry, OwnerRepasse, RentCharge
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit

router = APIRouter(prefix="/finance/banking", tags=["finance-banking"])
CENT = Decimal("0.01")
MAX_IMPORT_BYTES = 5 * 1024 * 1024


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def month_start(value: date) -> date:
    return value.replace(day=1)


def month_end(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    after: dict | None = None,
) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type=entity_type,
        entity_id=entity_id,
        after_data=after,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _load_account(db: Session, organization_id: UUID, account_id: UUID) -> BankAccount:
    item = db.scalar(
        select(BankAccount).where(
            BankAccount.id == account_id,
            BankAccount.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Conta bancária não encontrada.")
    return item


def _load_transaction(db: Session, organization_id: UUID, transaction_id: UUID) -> BankTransaction:
    item = db.scalar(
        select(BankTransaction)
        .options(selectinload(BankTransaction.reconciliations))
        .where(
            BankTransaction.id == transaction_id,
            BankTransaction.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Movimento bancário não encontrado.")
    return item


def _account_balance(db: Session, account: BankAccount) -> Decimal:
    transactions = db.scalars(
        select(BankTransaction).where(BankTransaction.bank_account_id == account.id)
    ).all()
    balance = money(account.opening_balance)
    for item in transactions:
        balance += money(item.amount) if item.direction == "credit" else -money(item.amount)
    return money(balance)


def _account_response(db: Session, item: BankAccount) -> BankAccountResponse:
    return BankAccountResponse(
        id=item.id,
        code=f"BCO-{item.internal_number:04d}",
        name=item.name,
        bank_name=item.bank_name,
        bank_code=item.bank_code,
        branch=item.branch,
        account_number=item.account_number,
        account_digit=item.account_digit,
        account_type=item.account_type,
        fund_scope=item.fund_scope,
        provider=item.provider,
        pix_key=item.pix_key,
        opening_balance=money(item.opening_balance),
        current_balance=_account_balance(db, item),
        is_active=item.is_active,
        last_sync_at=item.last_sync_at,
        created_at=item.created_at,
    )


def _reconciliation_response(item: BankReconciliation) -> BankReconciliationResponse:
    return BankReconciliationResponse(
        id=item.id,
        target_type=item.target_type,
        target_id=item.target_id,
        target_code=item.target_code,
        target_direction=item.target_direction,
        amount=money(item.amount),
        notes=item.notes,
        reconciled_at=item.reconciled_at,
    )


def _transaction_response(item: BankTransaction) -> BankTransactionResponse:
    reconciled = sum((money(entry.amount) for entry in item.reconciliations), Decimal("0.00"))
    remaining = money(max(Decimal("0.00"), money(item.amount) - reconciled))
    return BankTransactionResponse(
        id=item.id,
        code=f"EXT-{item.internal_number:06d}",
        bank_account_id=item.bank_account_id,
        transaction_date=item.transaction_date,
        posted_at=item.posted_at,
        direction=item.direction,
        amount=money(item.amount),
        description=item.description,
        document=item.document,
        counterparty_name=item.counterparty_name,
        bank_reference=item.bank_reference,
        balance_after=item.balance_after,
        source=item.source,
        status=item.status,
        reconciled_amount=money(reconciled),
        remaining_amount=remaining,
        reconciliations=[_reconciliation_response(entry) for entry in item.reconciliations],
        created_at=item.created_at,
    )


def _fingerprint(
    account_id: UUID,
    *,
    transaction_date: date,
    direction: str,
    amount: Decimal,
    description: str,
    external_id: str | None = None,
    reference: str | None = None,
) -> str:
    payload = "|".join(
        [
            str(account_id),
            external_id or "",
            transaction_date.isoformat(),
            direction,
            f"{money(amount):.2f}",
            " ".join(description.lower().split()),
            reference or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strip_accents(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


def _header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _strip_accents(value).lower()).strip("_")


def _parse_decimal(raw: str) -> Decimal:
    value = (raw or "").strip().replace("R$", "").replace(" ", "")
    if not value:
        raise ValueError("valor vazio")
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    return money(Decimal(value))


def _parse_date(raw: str) -> date:
    value = (raw or "").strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value[:10] if pattern != "%Y%m%d" else value[:8], pattern).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {value}")


def _first(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    for key in aliases:
        if row.get(key):
            return str(row[key]).strip()
    return ""


def _parse_csv_rows(content: bytes) -> list[dict]:
    text = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Não foi possível identificar a codificação do CSV.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("CSV sem cabeçalho.")
    normalized_fields = [_header(field or "") for field in reader.fieldnames]
    rows: list[dict] = []
    for source_row in reader:
        row = {
            normalized_fields[index]: str(source_row.get(original) or "").strip()
            for index, original in enumerate(reader.fieldnames)
        }
        date_raw = _first(row, ("data", "date", "data_movimento", "transaction_date", "data_lancamento"))
        description = _first(row, ("descricao", "description", "historico", "memo", "lancamento"))
        amount_raw = _first(row, ("valor", "amount", "valor_lancamento"))
        if not date_raw or not amount_raw:
            continue
        signed = _parse_decimal(amount_raw)
        direction_raw = _first(row, ("tipo", "direction", "natureza", "credito_debito")).lower()
        if direction_raw in {"debit", "debito", "d", "saida", "out"}:
            direction = "debit"
        elif direction_raw in {"credit", "credito", "c", "entrada", "in"}:
            direction = "credit"
        else:
            direction = "debit" if signed < 0 else "credit"
        amount = money(abs(signed))
        if amount <= 0:
            continue
        rows.append(
            {
                "transaction_date": _parse_date(date_raw),
                "direction": direction,
                "amount": amount,
                "description": description or "Movimento bancário",
                "document": _first(row, ("documento", "document", "doc")),
                "counterparty_name": _first(row, ("contraparte", "counterparty", "favorecido", "pagador", "nome")),
                "bank_reference": _first(row, ("referencia", "reference", "id", "fitid", "identificador")),
                "external_id": _first(row, ("id", "fitid", "external_id", "identificador")) or None,
                "raw_data": row,
            }
        )
    return rows


def _tag(block: str, name: str) -> str:
    match = re.search(rf"<{name}>([^<\r\n]+)", block, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _parse_ofx_rows(content: bytes) -> list[dict]:
    text = content.decode("utf-8", errors="ignore")
    if "<STMTTRN>" not in text.upper():
        text = content.decode("latin-1", errors="ignore")
    blocks = re.findall(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|$)", text, flags=re.IGNORECASE | re.DOTALL)
    rows: list[dict] = []
    for block in blocks:
        amount_raw = _tag(block, "TRNAMT")
        date_raw = _tag(block, "DTPOSTED")
        if not amount_raw or not date_raw:
            continue
        signed = money(Decimal(amount_raw.replace(",", ".")))
        amount = money(abs(signed))
        if amount <= 0:
            continue
        name = _tag(block, "NAME")
        memo = _tag(block, "MEMO")
        description = " · ".join(part for part in (name, memo) if part) or _tag(block, "TRNTYPE") or "Movimento bancário"
        rows.append(
            {
                "transaction_date": _parse_date(date_raw[:8]),
                "direction": "debit" if signed < 0 else "credit",
                "amount": amount,
                "description": description[:300],
                "document": _tag(block, "CHECKNUM") or None,
                "counterparty_name": name[:220] if name else None,
                "bank_reference": _tag(block, "REFNUM") or _tag(block, "FITID") or None,
                "external_id": _tag(block, "FITID") or None,
                "raw_data": {
                    "trntype": _tag(block, "TRNTYPE"),
                    "fitid": _tag(block, "FITID"),
                    "name": name,
                    "memo": memo,
                },
            }
        )
    return rows


def _target_details(
    db: Session,
    organization_id: UUID,
    target_type: str,
    target_id: UUID,
    *,
    as_of: date | None = None,
) -> dict:
    if target_type == "rent":
        item = db.scalar(
            select(RentCharge).where(
                RentCharge.id == target_id,
                RentCharge.organization_id == organization_id,
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Cobrança de locação não encontrada.")
        tenants = " / ".join(
            str(entry.get("name") or "").strip()
            for entry in list(item.tenant_snapshot or [])
            if entry.get("name")
        )
        outstanding = Decimal("0.00") if item.status in {"paid", "cancelled"} else amount_due(db, item, as_of=as_of)
        return {
            "object": item,
            "direction": "receivable",
            "fund_scope": "third_party",
            "remaining": outstanding,
            "code": f"COB-{item.internal_number:06d}",
            "description": "Cobrança mensal de locação",
            "counterparty": tenants or "Locatário",
            "due_date": item.due_date,
        }

    if target_type == "owner_repasse":
        item = db.scalar(
            select(OwnerRepasse).where(
                OwnerRepasse.id == target_id,
                OwnerRepasse.organization_id == organization_id,
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Repasse ao proprietário não encontrado.")
        outstanding = Decimal("0.00") if item.status in {"paid", "settled_zero"} else money(item.amount)
        return {
            "object": item,
            "direction": "payable",
            "fund_scope": "third_party",
            "remaining": outstanding,
            "code": f"REP-{str(item.id)[:8].upper()}",
            "description": "Repasse ao proprietário",
            "counterparty": item.owner_name,
            "due_date": item.due_date,
        }

    if target_type == "maintenance":
        item = db.scalar(
            select(MaintenanceFinancialEntry).where(
                MaintenanceFinancialEntry.id == target_id,
                MaintenanceFinancialEntry.organization_id == organization_id,
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Lançamento financeiro da manutenção não encontrado.")
        outstanding = Decimal("0.00") if item.status == "settled" else money(max(Decimal("0.00"), item.amount - item.settled_amount))
        scope = "third_party" if item.direction == "receivable" and item.collection_method == "owner_repasse_deduction" else "operating"
        snapshot = dict(item.source_snapshot or {})
        return {
            "object": item,
            "direction": item.direction,
            "fund_scope": scope,
            "remaining": outstanding,
            "code": f"MFIN-{item.internal_number:06d}",
            "description": str(snapshot.get("title") or "Manutenção"),
            "counterparty": item.counterparty_name,
            "due_date": item.due_date,
        }

    if target_type in {"manual", "financial_title"}:
        stmt = select(FinancialTitle).where(
            FinancialTitle.id == target_id,
            FinancialTitle.organization_id == organization_id,
        )
        if target_type == "manual":
            stmt = stmt.where(FinancialTitle.source_type == "manual")
        item = db.scalar(stmt)
        if item is None:
            detail = "Título financeiro manual não encontrado." if target_type == "manual" else "Título financeiro não encontrado."
            raise HTTPException(status_code=404, detail=detail)
        outstanding = Decimal("0.00") if item.status == "cancelled" else money(max(Decimal("0.00"), item.amount - item.settled_amount))
        return {
            "object": item,
            "direction": item.direction,
            "fund_scope": item.fund_scope,
            "remaining": outstanding,
            "code": f"FIN-{item.internal_number:06d}",
            "description": item.description,
            "counterparty": item.counterparty_name,
            "due_date": item.due_date,
        }

    raise HTTPException(status_code=422, detail="Tipo de origem financeira inválido.")


def _candidate_score(transaction: BankTransaction, details: dict) -> int:
    remaining = money(details["remaining"])
    available = _transaction_response(transaction).remaining_amount
    score = 0
    if remaining == available:
        score += 70
    elif remaining <= available:
        score += 42
    else:
        diff = abs(remaining - available)
        if diff <= Decimal("1.00"):
            score += 35
        elif diff <= Decimal("10.00"):
            score += 20

    due = details.get("due_date")
    if due:
        days = abs((transaction.transaction_date - due).days)
        if days <= 2:
            score += 20
        elif days <= 7:
            score += 12
        elif days <= 30:
            score += 5

    haystack = f"{transaction.description} {transaction.counterparty_name or ''}".lower()
    counterparty = str(details.get("counterparty") or "").strip().lower()
    if len(counterparty) >= 4 and counterparty in haystack:
        score += 10
    return score


def _open_candidates(db: Session, transaction: BankTransaction, account: BankAccount) -> list[ReconciliationCandidate]:
    target_direction = "receivable" if transaction.direction == "credit" else "payable"
    candidates: list[tuple[str, UUID]] = []

    if target_direction == "receivable":
        candidates.extend(
            ("rent", item.id)
            for item in db.scalars(
                select(RentCharge).where(
                    RentCharge.organization_id == transaction.organization_id,
                    RentCharge.status.not_in(("paid", "cancelled")),
                )
            ).all()
        )
    else:
        candidates.extend(
            ("owner_repasse", item.id)
            for item in db.scalars(
                select(OwnerRepasse).where(
                    OwnerRepasse.organization_id == transaction.organization_id,
                    OwnerRepasse.status == "pending",
                    OwnerRepasse.amount > 0,
                )
            ).all()
        )

    candidates.extend(
        ("maintenance", item.id)
        for item in db.scalars(
            select(MaintenanceFinancialEntry).where(
                MaintenanceFinancialEntry.organization_id == transaction.organization_id,
                MaintenanceFinancialEntry.direction == target_direction,
                MaintenanceFinancialEntry.status.in_(("pending", "partial")),
            )
        ).all()
    )
    financial_titles = db.scalars(
        select(FinancialTitle).where(
            FinancialTitle.organization_id == transaction.organization_id,
            FinancialTitle.direction == target_direction,
            FinancialTitle.status.in_(("pending", "partial")),
        )
    ).all()
    candidates.extend(
        ("manual" if item.source_type == "manual" else "financial_title", item.id)
        for item in financial_titles
    )

    result: list[ReconciliationCandidate] = []
    for target_type, target_id in candidates:
        details = _target_details(
            db,
            transaction.organization_id,
            target_type,
            target_id,
            as_of=transaction.transaction_date,
        )
        if details["fund_scope"] != account.fund_scope or money(details["remaining"]) <= 0:
            continue
        score = _candidate_score(transaction, details)
        result.append(
            ReconciliationCandidate(
                target_type=target_type,
                target_id=target_id,
                target_code=details["code"],
                direction=details["direction"],
                fund_scope=details["fund_scope"],
                description=details["description"],
                counterparty_name=details["counterparty"],
                due_date=details["due_date"],
                remaining_amount=money(details["remaining"]),
                score=score,
            )
        )
    return sorted(result, key=lambda item: (-item.score, item.due_date or date.max, item.target_code))[:80]


@router.get("/accounts", response_model=list[BankAccountResponse])
def list_bank_accounts(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[BankAccountResponse]:
    items = db.scalars(
        select(BankAccount)
        .where(BankAccount.organization_id == context.user.organization_id)
        .order_by(BankAccount.is_active.desc(), BankAccount.internal_number.asc())
    ).all()
    return [_account_response(db, item) for item in items]


@router.post("/accounts", response_model=BankAccountResponse)
def create_bank_account(
    payload: BankAccountCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> BankAccountResponse:
    item = BankAccount(
        organization_id=context.user.organization_id,
        name=payload.name.strip(),
        bank_name=payload.bank_name.strip(),
        bank_code=(payload.bank_code or "").strip() or None,
        branch=(payload.branch or "").strip() or None,
        account_number=(payload.account_number or "").strip() or None,
        account_digit=(payload.account_digit or "").strip() or None,
        account_type=payload.account_type,
        fund_scope=payload.fund_scope,
        provider=payload.provider,
        provider_account_id=(payload.provider_account_id or "").strip() or None,
        pix_key=(payload.pix_key or "").strip() or None,
        opening_balance=money(payload.opening_balance),
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        context,
        action="finance.bank_account.created",
        entity_type="bank_account",
        entity_id=str(item.id),
        after={"name": item.name, "bank": item.bank_name, "fund_scope": item.fund_scope, "provider": item.provider},
    )
    db.commit()
    db.refresh(item)
    return _account_response(db, item)


@router.get("/transactions", response_model=list[BankTransactionResponse])
def list_transactions(
    account_id: UUID = Query(...),
    competence: date | None = Query(default=None),
    transaction_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[BankTransactionResponse]:
    _load_account(db, context.user.organization_id, account_id)
    stmt = (
        select(BankTransaction)
        .options(selectinload(BankTransaction.reconciliations))
        .where(
            BankTransaction.organization_id == context.user.organization_id,
            BankTransaction.bank_account_id == account_id,
        )
    )
    if competence:
        start = month_start(competence)
        stmt = stmt.where(BankTransaction.transaction_date >= start, BankTransaction.transaction_date < month_end(start))
    if transaction_status:
        stmt = stmt.where(BankTransaction.status == transaction_status)
    items = db.scalars(stmt.order_by(BankTransaction.transaction_date.desc(), BankTransaction.internal_number.desc()).limit(1500)).unique().all()
    return [_transaction_response(item) for item in items]


@router.get("/overview", response_model=BankingOverview)
def banking_overview(
    account_id: UUID = Query(...),
    competence: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> BankingOverview:
    account = _load_account(db, context.user.organization_id, account_id)
    competence = month_start(competence or date.today())
    items = db.scalars(
        select(BankTransaction)
        .options(selectinload(BankTransaction.reconciliations))
        .where(
            BankTransaction.organization_id == context.user.organization_id,
            BankTransaction.bank_account_id == account_id,
            BankTransaction.transaction_date >= competence,
            BankTransaction.transaction_date < month_end(competence),
        )
        .order_by(BankTransaction.transaction_date.desc(), BankTransaction.internal_number.desc())
    ).unique().all()
    responses = [_transaction_response(item) for item in items]
    return BankingOverview(
        account=_account_response(db, account),
        competence=competence,
        credits_amount=sum((money(item.amount) for item in responses if item.direction == "credit"), Decimal("0.00")),
        debits_amount=sum((money(item.amount) for item in responses if item.direction == "debit"), Decimal("0.00")),
        pending_credits_amount=sum((money(item.remaining_amount) for item in responses if item.direction == "credit"), Decimal("0.00")),
        pending_debits_amount=sum((money(item.remaining_amount) for item in responses if item.direction == "debit"), Decimal("0.00")),
        reconciled_amount=sum((money(item.reconciled_amount) for item in responses), Decimal("0.00")),
        pending_count=sum(1 for item in responses if item.remaining_amount > 0),
        reconciled_count=sum(1 for item in responses if item.remaining_amount <= 0),
        transactions=responses,
    )


@router.post("/accounts/{account_id}/transactions", response_model=BankTransactionResponse)
def create_manual_transaction(
    account_id: UUID,
    payload: BankTransactionCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> BankTransactionResponse:
    account = _load_account(db, context.user.organization_id, account_id)
    fingerprint = _fingerprint(
        account.id,
        transaction_date=payload.transaction_date,
        direction=payload.direction,
        amount=payload.amount,
        description=payload.description,
        reference=payload.bank_reference,
    )
    existing = db.scalar(
        select(BankTransaction).where(
            BankTransaction.bank_account_id == account.id,
            BankTransaction.fingerprint == fingerprint,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Este movimento bancário já existe nesta conta.")
    item = BankTransaction(
        organization_id=context.user.organization_id,
        bank_account_id=account.id,
        fingerprint=fingerprint,
        transaction_date=payload.transaction_date,
        posted_at=datetime.combine(payload.transaction_date, time(12, 0), tzinfo=timezone.utc),
        direction=payload.direction,
        amount=money(payload.amount),
        description=payload.description.strip(),
        document=(payload.document or "").strip() or None,
        counterparty_name=(payload.counterparty_name or "").strip() or None,
        bank_reference=(payload.bank_reference or "").strip() or None,
        source="manual",
        status="pending",
        raw_data={},
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        context,
        action="finance.bank_transaction.created",
        entity_type="bank_transaction",
        entity_id=str(item.id),
        after={"account": str(account.id), "direction": item.direction, "amount": str(item.amount)},
    )
    db.commit()
    return _transaction_response(_load_transaction(db, context.user.organization_id, item.id))


@router.post("/accounts/{account_id}/import", response_model=BankImportResponse)
async def import_statement(
    account_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> BankImportResponse:
    account = _load_account(db, context.user.organization_id, account_id)
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="O arquivo de extrato deve ter no máximo 5 MB.")
    filename = Path(file.filename or "extrato").name
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".csv":
            rows = _parse_csv_rows(content)
            source = "csv"
        elif suffix == ".ofx":
            rows = _parse_ofx_rows(content)
            source = "ofx"
        else:
            raise HTTPException(status_code=422, detail="Formato não suportado. Envie um extrato CSV ou OFX.")
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=f"Não foi possível ler o extrato: {exc}") from exc
    if not rows:
        raise HTTPException(status_code=422, detail="Nenhum movimento válido foi encontrado no extrato.")

    import_item = BankStatementImport(
        organization_id=context.user.organization_id,
        bank_account_id=account.id,
        source=source,
        filename=filename,
        file_hash=hashlib.sha256(content).hexdigest(),
        total_rows=len(rows),
        imported_by_user_id=context.user.id,
    )
    db.add(import_item)
    db.flush()

    created = 0
    duplicates = 0
    for row in rows:
        fingerprint = _fingerprint(
            account.id,
            transaction_date=row["transaction_date"],
            direction=row["direction"],
            amount=row["amount"],
            description=row["description"],
            external_id=row.get("external_id"),
            reference=row.get("bank_reference"),
        )
        existing = db.scalar(
            select(BankTransaction.id).where(
                BankTransaction.bank_account_id == account.id,
                BankTransaction.fingerprint == fingerprint,
            )
        )
        if existing:
            duplicates += 1
            continue
        db.add(
            BankTransaction(
                organization_id=context.user.organization_id,
                bank_account_id=account.id,
                statement_import_id=import_item.id,
                external_id=row.get("external_id"),
                fingerprint=fingerprint,
                transaction_date=row["transaction_date"],
                posted_at=datetime.combine(row["transaction_date"], time(12, 0), tzinfo=timezone.utc),
                direction=row["direction"],
                amount=money(row["amount"]),
                description=row["description"][:300],
                document=(row.get("document") or "")[:120] or None,
                counterparty_name=(row.get("counterparty_name") or "")[:220] or None,
                bank_reference=(row.get("bank_reference") or "")[:180] or None,
                source=source,
                status="pending",
                raw_data=row.get("raw_data") or {},
                created_by_user_id=context.user.id,
            )
        )
        created += 1

    import_item.created_rows = created
    import_item.duplicate_rows = duplicates
    _audit(
        db,
        request,
        context,
        action="finance.bank_statement.imported",
        entity_type="bank_statement_import",
        entity_id=str(import_item.id),
        after={"account": str(account.id), "source": source, "created": created, "duplicates": duplicates},
    )
    db.commit()
    return BankImportResponse(
        import_id=import_item.id,
        filename=filename,
        source=source,
        total_rows=len(rows),
        created_rows=created,
        duplicate_rows=duplicates,
    )


@router.get("/transactions/{transaction_id}/candidates", response_model=list[ReconciliationCandidate])
def reconciliation_candidates(
    transaction_id: UUID,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[ReconciliationCandidate]:
    transaction = _load_transaction(db, context.user.organization_id, transaction_id)
    account = _load_account(db, context.user.organization_id, transaction.bank_account_id)
    if _transaction_response(transaction).remaining_amount <= 0:
        return []
    return _open_candidates(db, transaction, account)


@router.post("/transactions/{transaction_id}/reconcile", response_model=BankTransactionResponse)
def reconcile_transaction(
    transaction_id: UUID,
    payload: BankReconciliationRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> BankTransactionResponse:
    transaction = _load_transaction(db, context.user.organization_id, transaction_id)
    account = _load_account(db, context.user.organization_id, transaction.bank_account_id)
    required = "finance.reconcile" if transaction.direction == "credit" else "finance.payment.approve"
    if not context.has(required):
        raise HTTPException(status_code=403, detail=f"Permissão necessária: {required}")

    tx_response = _transaction_response(transaction)
    if tx_response.remaining_amount <= 0:
        raise HTTPException(status_code=409, detail="Este movimento bancário já está totalmente conciliado.")

    settled_at = transaction.posted_at or datetime.combine(transaction.transaction_date, time(12, 0), tzinfo=timezone.utc)
    details = _target_details(
        db,
        context.user.organization_id,
        payload.target_type,
        payload.target_id,
        as_of=settled_at.date(),
    )
    expected_direction = "receivable" if transaction.direction == "credit" else "payable"
    if details["direction"] != expected_direction:
        raise HTTPException(status_code=409, detail="A natureza do movimento bancário não corresponde ao título selecionado.")
    if details["fund_scope"] != account.fund_scope:
        raise HTTPException(
            status_code=409,
            detail="A conta bancária e o título possuem naturezas de recurso diferentes (operacional x terceiros).",
        )
    target_remaining = money(details["remaining"])
    if target_remaining <= 0:
        raise HTTPException(status_code=409, detail="O título selecionado não possui saldo pendente.")

    allocation = money(payload.amount or min(tx_response.remaining_amount, target_remaining))
    if allocation <= 0 or allocation > tx_response.remaining_amount or allocation > target_remaining:
        raise HTTPException(status_code=409, detail="Valor de conciliação inválido para os saldos disponíveis.")
    if payload.target_type in {"rent", "owner_repasse"} and allocation != target_remaining:
        raise HTTPException(status_code=409, detail="Esta origem exige conciliação integral do saldo do título.")

    reference = f"EXT-{transaction.internal_number:06d}"
    target = details["object"]

    if payload.target_type == "rent":
        try:
            record_payment_with_late_charges(
                db,
                charge=target,
                paid_amount=target_remaining,
                paid_at=settled_at,
                payment_method="transfer",
                payment_reference=reference,
                notes="Recebimento conciliado pelo extrato bancário.",
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif payload.target_type == "owner_repasse":
        target.status = "paid"
        target.paid_at = settled_at
        target.payment_reference = reference
        target.notes = f"{target.notes or ''}\nConciliado pelo extrato bancário {reference}.".strip()
    elif payload.target_type == "maintenance":
        target.settled_amount = money(target.settled_amount + allocation)
        target.status = "settled" if target.settled_amount >= target.amount else "partial"
        target.settled_at = settled_at if target.status == "settled" else None
        target.payment_reference = reference
        target.notes = f"{target.notes or ''}\nConciliação bancária {reference}: R$ {allocation:.2f}.".strip()
    else:
        target.settled_amount = money(target.settled_amount + allocation)
        target.status = "settled" if target.settled_amount >= target.amount else "partial"
        target.settled_at = settled_at if target.status == "settled" else None
        target.payment_method = "transfer"
        target.payment_reference = reference
        target.notes = f"{target.notes or ''}\nConciliação bancária {reference}: R$ {allocation:.2f}.".strip()

    reconciliation = BankReconciliation(
        organization_id=context.user.organization_id,
        transaction=transaction,
        target_type=payload.target_type,
        target_id=payload.target_id,
        target_code=details["code"],
        target_direction=details["direction"],
        amount=allocation,
        notes=(payload.notes or "").strip() or None,
        reconciled_by_user_id=context.user.id,
    )
    db.add(reconciliation)
    db.flush()
    allocated_after = money(tx_response.reconciled_amount + allocation)
    transaction.status = "reconciled" if allocated_after >= transaction.amount else "partial"
    _audit(
        db,
        request,
        context,
        action="finance.bank_transaction.reconciled",
        entity_type="bank_transaction",
        entity_id=str(transaction.id),
        after={
            "target_type": payload.target_type,
            "target_id": str(payload.target_id),
            "target_code": details["code"],
            "amount": str(allocation),
            "status": transaction.status,
        },
    )
    db.commit()
    return _transaction_response(_load_transaction(db, context.user.organization_id, transaction.id))
