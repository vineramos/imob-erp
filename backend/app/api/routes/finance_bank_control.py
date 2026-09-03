from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.bank_control_models import BankDailyClose, BankPaymentInstruction
from app.domains.finance.bank_control_schemas import (
    DailyCloseCreate,
    DailyClosePreview,
    DailyClosePreviewRequest,
    DailyCloseResponse,
    ProviderCapabilityResponse,
    ProviderPaymentBatchResponse,
    ProviderPaymentInstructionResponse,
)
from app.domains.finance.bank_models import BankAccount, BankTransaction
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import MaintenanceFinancialEntry, OwnerRepasse
from app.domains.finance.providers import BankProviderError, bank_provider
from app.domains.finance.treasury_models import PaymentBatch, PaymentBatchItem
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.maintenance.models import MaintenancePartner
from app.domains.portfolio.bank_models import PersonBankDetails
from app.domains.portfolio.models import Person

router = APIRouter(prefix="/finance/bank-control", tags=["finance-bank-control"])
CENT = Decimal("0.01")
SUCCESS_PROVIDER_STATUSES = {"PAGO", "PROCESSADO", "EFETIVADO", "CONCLUIDO", "REALIZADO", "SUCESSO", "SUCCESS"}
FAILED_PROVIDER_STATUSES = {"ERRO", "ERROR", "FALHA", "FAILED", "CANCELADO", "CANCELLED", "REJEITADO"}


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _account(db: Session, organization_id: UUID, account_id: UUID) -> BankAccount:
    item = db.scalar(
        select(BankAccount).where(
            BankAccount.id == account_id,
            BankAccount.organization_id == organization_id,
            BankAccount.is_active.is_(True),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Conta bancária não encontrada ou inativa.")
    return item


def _batch(db: Session, organization_id: UUID, batch_id: UUID) -> PaymentBatch:
    item = db.scalar(
        select(PaymentBatch).where(
            PaymentBatch.id == batch_id,
            PaymentBatch.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Lote de pagamento não encontrado.")
    return item


def _audit(db: Session, request: Request, context: UserContext, *, action: str, entity_type: str, entity_id: str, after: dict | None = None) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type=entity_type,
        entity_id=entity_id,
        after_data=after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )


def _erp_balance(db: Session, account: BankAccount, closing_date: date) -> Decimal:
    balance = money(account.opening_balance)
    transactions = db.scalars(
        select(BankTransaction).where(
            BankTransaction.organization_id == account.organization_id,
            BankTransaction.bank_account_id == account.id,
            BankTransaction.transaction_date <= closing_date,
        )
    ).all()
    for item in transactions:
        balance += money(item.amount) if item.direction == "credit" else -money(item.amount)
    return money(balance)


def _pending_transactions(db: Session, account: BankAccount, closing_date: date) -> int:
    return len(
        db.scalars(
            select(BankTransaction.id).where(
                BankTransaction.organization_id == account.organization_id,
                BankTransaction.bank_account_id == account.id,
                BankTransaction.transaction_date <= closing_date,
                BankTransaction.status != "reconciled",
            )
        ).all()
    )


def _provider_balance(data: dict) -> Decimal:
    for key in ("disponivel", "saldoDisponivel", "saldo", "valor"):
        if data.get(key) is not None:
            return money(data[key])
    raise BankProviderError("O provider não retornou um saldo bancário reconhecível.")


def _close_preview(db: Session, account: BankAccount, payload: DailyClosePreviewRequest) -> DailyClosePreview:
    if payload.closing_date > date.today():
        raise HTTPException(status_code=422, detail="Não é possível fechar uma data futura.")
    erp_balance = _erp_balance(db, account, payload.closing_date)
    pending = _pending_transactions(db, account, payload.closing_date)
    if payload.bank_balance is not None:
        bank_balance = money(payload.bank_balance)
        source = "manual"
    else:
        provider = bank_provider(account.provider)
        capabilities = provider.capabilities()
        status = provider.status()
        if not capabilities.balance or not status.configured:
            raise HTTPException(
                status_code=422,
                detail="Informe o saldo bancário para esta data. Esta conta não possui consulta automática de saldo.",
            )
        try:
            bank_balance = _provider_balance(provider.balance(balance_date=payload.closing_date))
        except BankProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        source = "provider"
    difference = money(bank_balance - erp_balance)
    can_close = pending == 0 and abs(difference) <= CENT
    if pending:
        message = f"Existem {pending} movimento(s) bancário(s) pendente(s) de conciliação até esta data."
    elif abs(difference) > CENT:
        message = f"Há divergência de R$ {abs(difference):.2f} entre o banco e o ERP."
    else:
        message = "Banco e ERP conciliados. O dia pode ser fechado."
    return DailyClosePreview(
        bank_account_id=account.id,
        bank_account_name=account.name,
        closing_date=payload.closing_date,
        fund_scope=account.fund_scope,
        provider=account.provider,
        erp_balance=float(erp_balance),
        bank_balance=float(bank_balance),
        difference=float(difference),
        pending_transactions_count=pending,
        balance_source=source,
        can_close=can_close,
        message=message,
    )


def _close_response(item: BankDailyClose, account: BankAccount) -> DailyCloseResponse:
    return DailyCloseResponse(
        id=item.id,
        code=f"FEC-{item.internal_number:05d}",
        bank_account_id=item.bank_account_id,
        bank_account_name=account.name,
        closing_date=item.closing_date,
        fund_scope=item.fund_scope,
        provider=item.provider,
        erp_balance=float(money(item.erp_balance)),
        bank_balance=float(money(item.bank_balance)),
        difference=float(money(item.difference)),
        pending_transactions_count=item.pending_transactions_count,
        balance_source=item.balance_source,
        can_close=True,
        message="Fechamento confirmado. Banco e ERP estavam conciliados na data.",
        status=item.status,
        notes=item.notes,
        closed_at=item.closed_at,
    )


@router.post("/daily-closes/preview", response_model=DailyClosePreview)
def preview_daily_close(
    payload: DailyClosePreviewRequest,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> DailyClosePreview:
    account = _account(db, context.user.organization_id, payload.bank_account_id)
    return _close_preview(db, account, payload)


@router.post("/daily-closes", response_model=DailyCloseResponse)
def close_day(
    payload: DailyCloseCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> DailyCloseResponse:
    account = _account(db, context.user.organization_id, payload.bank_account_id)
    existing = db.scalar(
        select(BankDailyClose).where(
            BankDailyClose.organization_id == context.user.organization_id,
            BankDailyClose.bank_account_id == account.id,
            BankDailyClose.closing_date == payload.closing_date,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Esta conta já possui fechamento para a data informada.")
    future_close = db.scalar(
        select(BankDailyClose.id).where(
            BankDailyClose.organization_id == context.user.organization_id,
            BankDailyClose.bank_account_id == account.id,
            BankDailyClose.closing_date > payload.closing_date,
        ).limit(1)
    )
    if future_close:
        raise HTTPException(status_code=409, detail="Há um fechamento posterior nesta conta. Não é permitido fechar retroativamente antes dele.")
    preview = _close_preview(db, account, payload)
    if not preview.can_close:
        raise HTTPException(status_code=409, detail=preview.message)
    item = BankDailyClose(
        organization_id=context.user.organization_id,
        bank_account_id=account.id,
        closing_date=payload.closing_date,
        fund_scope=account.fund_scope,
        provider=account.provider,
        erp_balance=money(preview.erp_balance),
        bank_balance=money(preview.bank_balance),
        difference=money(preview.difference),
        pending_transactions_count=preview.pending_transactions_count,
        balance_source=preview.balance_source,
        status="confirmed",
        notes=(payload.notes or "").strip() or None,
        closed_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        context,
        action="finance.daily_close.confirmed",
        entity_type="bank_daily_close",
        entity_id=str(item.id),
        after={"account_id": str(account.id), "date": payload.closing_date.isoformat(), "balance": str(item.bank_balance)},
    )
    db.commit()
    db.refresh(item)
    return _close_response(item, account)


@router.get("/daily-closes", response_model=list[DailyCloseResponse])
def list_daily_closes(
    account_id: UUID | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[DailyCloseResponse]:
    stmt = select(BankDailyClose).where(BankDailyClose.organization_id == context.user.organization_id)
    if account_id:
        stmt = stmt.where(BankDailyClose.bank_account_id == account_id)
    items = db.scalars(stmt.order_by(BankDailyClose.closing_date.desc(), BankDailyClose.closed_at.desc()).limit(120)).all()
    accounts = {
        account.id: account
        for account in db.scalars(
            select(BankAccount).where(
                BankAccount.organization_id == context.user.organization_id,
                BankAccount.id.in_({item.bank_account_id for item in items}) if items else False,
            )
        ).all()
    } if items else {}
    return [_close_response(item, accounts[item.bank_account_id]) for item in items if item.bank_account_id in accounts]


def _person_pix(db: Session, organization_id: UUID, person_id: UUID, fallback_name: str) -> tuple[str, str, str]:
    person = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == organization_id))
    details = db.scalar(
        select(PersonBankDetails).where(
            PersonBankDetails.person_id == person_id,
            PersonBankDetails.organization_id == organization_id,
        )
    )
    if person is None or details is None or details.pix_key_type == "none" or not details.pix_key:
        raise ValueError(f"{fallback_name}: cadastre uma chave Pix válida no cadastro da pessoa.")
    return person.name, details.pix_key, f"person:{person.id}"


def _recipient(db: Session, organization_id: UUID, item: PaymentBatchItem) -> tuple[str, str, str]:
    if item.target_type == "owner_repasse":
        target = db.scalar(
            select(OwnerRepasse).where(OwnerRepasse.id == item.target_id, OwnerRepasse.organization_id == organization_id)
        )
        if target is None:
            raise ValueError(f"{item.target_code}: repasse não encontrado.")
        return _person_pix(db, organization_id, target.owner_person_id, item.counterparty_name)
    if item.target_type == "maintenance":
        target = db.scalar(
            select(MaintenanceFinancialEntry).where(
                MaintenanceFinancialEntry.id == item.target_id,
                MaintenanceFinancialEntry.organization_id == organization_id,
            )
        )
        if target is None or target.counterparty_id is None:
            raise ValueError(f"{item.target_code}: parceiro da manutenção não encontrado.")
        partner = db.scalar(
            select(MaintenancePartner).where(
                MaintenancePartner.id == target.counterparty_id,
                MaintenancePartner.organization_id == organization_id,
            )
        )
        if partner is None or not partner.pix_key:
            raise ValueError(f"{item.target_code}: cadastre a chave Pix do parceiro {item.counterparty_name}.")
        return partner.name, partner.pix_key, f"partner:{partner.id}"
    if item.target_type == "manual":
        target = db.scalar(
            select(FinancialTitle).where(FinancialTitle.id == item.target_id, FinancialTitle.organization_id == organization_id)
        )
        snapshot = dict(target.source_snapshot or {}) if target else {}
        raw_person_id = snapshot.get("counterparty_person_id") or snapshot.get("person_id")
        if not raw_person_id:
            raise ValueError(f"{item.target_code}: vincule uma Pessoa com dados bancários ao lançamento manual antes do Pix por API.")
        try:
            person_id = UUID(str(raw_person_id))
        except ValueError as exc:
            raise ValueError(f"{item.target_code}: vínculo bancário da contraparte é inválido.") from exc
        return _person_pix(db, organization_id, person_id, item.counterparty_name)
    raise ValueError(f"{item.target_code}: tipo de pagamento não suportado pela automação bancária.")


def _instruction_response(item: BankPaymentInstruction, batch_item: PaymentBatchItem) -> ProviderPaymentInstructionResponse:
    return ProviderPaymentInstructionResponse(
        id=item.id,
        payment_batch_item_id=item.payment_batch_item_id,
        target_code=batch_item.target_code,
        recipient_name=item.recipient_name,
        amount=float(money(item.amount)),
        provider=item.provider,
        provider_reference=item.provider_reference,
        provider_status=item.provider_status,
        last_error=item.last_error,
        submitted_at=item.submitted_at,
        confirmed_at=item.confirmed_at,
    )


def _provider_batch_response(db: Session, batch: PaymentBatch) -> ProviderPaymentBatchResponse:
    instructions = db.scalars(
        select(BankPaymentInstruction)
        .where(BankPaymentInstruction.payment_batch_id == batch.id)
        .order_by(BankPaymentInstruction.created_at)
    ).all()
    batch_items = {
        item.id: item
        for item in db.scalars(select(PaymentBatchItem).where(PaymentBatchItem.payment_batch_id == batch.id)).all()
    }
    return ProviderPaymentBatchResponse(
        payment_batch_id=batch.id,
        batch_code=f"LOT-{batch.internal_number:05d}",
        batch_status=batch.status,
        provider=(instructions[0].provider if instructions else "manual"),
        provider_status=batch.provider_status,
        instructions=[_instruction_response(item, batch_items[item.payment_batch_item_id]) for item in instructions if item.payment_batch_item_id in batch_items],
    )


@router.get("/providers", response_model=list[ProviderCapabilityResponse])
def provider_capabilities(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[ProviderCapabilityResponse]:
    accounts = db.scalars(
        select(BankAccount).where(BankAccount.organization_id == context.user.organization_id, BankAccount.is_active.is_(True))
        .order_by(BankAccount.name)
    ).all()
    result: list[ProviderCapabilityResponse] = []
    for account in accounts:
        try:
            provider = bank_provider(account.provider)
            status = provider.status()
            capabilities = provider.capabilities()
        except BankProviderError:
            status = None
            capabilities = None
        result.append(
            ProviderCapabilityResponse(
                bank_account_id=account.id,
                bank_account_name=account.name,
                provider=account.provider,
                configured=bool(status and status.configured),
                statement=bool(capabilities and capabilities.statement),
                balance=bool(capabilities and capabilities.balance),
                billing=bool(capabilities and capabilities.billing),
                pix_payment=bool(capabilities and capabilities.pix_payment),
            )
        )
    return result


@router.get("/payment-batches/{batch_id}", response_model=ProviderPaymentBatchResponse)
def provider_payment_batch(
    batch_id: UUID,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> ProviderPaymentBatchResponse:
    return _provider_batch_response(db, _batch(db, context.user.organization_id, batch_id))


@router.post("/payment-batches/{batch_id}/submit", response_model=ProviderPaymentBatchResponse)
def submit_payment_batch(
    batch_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> ProviderPaymentBatchResponse:
    batch = _batch(db, context.user.organization_id, batch_id)
    if batch.status not in {"approved", "submitted"}:
        raise HTTPException(status_code=409, detail="Somente lotes aprovados podem ser enviados ao banco.")
    if batch.payment_method != "pix":
        raise HTTPException(status_code=409, detail="A automação bancária atual executa apenas lotes Pix. Outros meios continuam com registro manual.")
    account = _account(db, context.user.organization_id, batch.bank_account_id)
    provider = bank_provider(account.provider)
    status = provider.status()
    if not status.configured or not provider.capabilities().pix_payment:
        raise HTTPException(status_code=409, detail="Esta conta não possui provider configurado para pagamento Pix. Use a execução manual da Tesouraria.")
    items = db.scalars(select(PaymentBatchItem).where(PaymentBatchItem.payment_batch_id == batch.id).order_by(PaymentBatchItem.created_at)).all()
    preflight: dict[UUID, tuple[str, str, str]] = {}
    errors: list[str] = []
    for item in items:
        try:
            preflight[item.id] = _recipient(db, context.user.organization_id, item)
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise HTTPException(status_code=422, detail=" | ".join(errors))

    existing = {
        item.payment_batch_item_id: item
        for item in db.scalars(select(BankPaymentInstruction).where(BankPaymentInstruction.payment_batch_id == batch.id)).all()
    }
    for item in items:
        if item.id in existing:
            continue
        recipient_name, pix_key, recipient_ref = preflight[item.id]
        instruction = BankPaymentInstruction(
            organization_id=context.user.organization_id,
            payment_batch_id=batch.id,
            payment_batch_item_id=item.id,
            bank_account_id=account.id,
            provider=account.provider,
            payment_method="pix",
            amount=item.amount,
            recipient_name=recipient_name,
            recipient_reference=recipient_ref,
            idempotency_key=str(uuid.uuid4()),
            provider_status="pending",
            request_snapshot={"pix_key_tail": pix_key[-4:] if len(pix_key) >= 4 else pix_key, "target_code": item.target_code},
            created_by_user_id=context.user.id,
        )
        db.add(instruction)
        db.flush()
        existing[item.id] = instruction
    db.commit()

    sent = 0
    failed = 0
    for item in items:
        instruction = existing[item.id]
        if instruction.submitted_at and not instruction.failed_at:
            sent += 1
            continue
        recipient_name, pix_key, _ = preflight[item.id]
        try:
            result = provider.pix_payment(
                amount=float(money(item.amount)),
                payment_date=batch.scheduled_date,
                description=f"{item.target_code} · {item.description}",
                pix_key=pix_key,
                idempotency_key=instruction.idempotency_key,
            )
            instruction.provider_reference = result.reference
            instruction.provider_status = result.status
            instruction.response_snapshot = {"reference": result.reference, "status": result.status}
            instruction.submitted_at = datetime.now(timezone.utc)
            instruction.failed_at = None
            instruction.last_error = None
            sent += 1
        except BankProviderError as exc:
            instruction.provider_status = "error"
            instruction.failed_at = datetime.now(timezone.utc)
            instruction.last_error = str(exc)[:2000]
            failed += 1
        db.commit()
    if sent:
        batch.status = "submitted"
        batch.provider_status = "partial_error" if failed else "submitted"
        batch.provider_batch_id = account.provider
    else:
        batch.provider_status = "error"
    _audit(
        db,
        request,
        context,
        action="finance.payment_batch.submitted_to_provider",
        entity_type="payment_batch",
        entity_id=str(batch.id),
        after={"provider": account.provider, "sent": sent, "failed": failed},
    )
    db.commit()
    return _provider_batch_response(db, batch)


@router.post("/payment-batches/{batch_id}/sync", response_model=ProviderPaymentBatchResponse)
def sync_payment_batch(
    batch_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> ProviderPaymentBatchResponse:
    batch = _batch(db, context.user.organization_id, batch_id)
    account = _account(db, context.user.organization_id, batch.bank_account_id)
    provider = bank_provider(account.provider)
    if not provider.capabilities().pix_payment or not provider.status().configured:
        raise HTTPException(status_code=409, detail="Esta conta não possui consulta de pagamentos via provider.")
    instructions = db.scalars(
        select(BankPaymentInstruction).where(BankPaymentInstruction.payment_batch_id == batch.id).order_by(BankPaymentInstruction.created_at)
    ).all()
    if not instructions:
        raise HTTPException(status_code=409, detail="Este lote ainda não possui pagamentos enviados ao provider.")
    now = datetime.now(timezone.utc)
    confirmed = 0
    failed = 0
    pending = 0
    for instruction in instructions:
        if not instruction.provider_reference:
            failed += 1
            continue
        try:
            result = provider.pix_payment_status(instruction.provider_reference)
            status = result.status.upper()
            instruction.provider_status = status
            instruction.response_snapshot = {"reference": result.reference, "status": status}
            instruction.last_error = None
            if status in SUCCESS_PROVIDER_STATUSES:
                instruction.confirmed_at = instruction.confirmed_at or now
                instruction.failed_at = None
                confirmed += 1
            elif status in FAILED_PROVIDER_STATUSES:
                instruction.failed_at = now
                failed += 1
            else:
                pending += 1
        except BankProviderError as exc:
            instruction.last_error = str(exc)[:2000]
            pending += 1
    if confirmed == len(instructions):
        batch.provider_status = "confirmed"
    elif failed:
        batch.provider_status = "partial_error" if confirmed or pending else "error"
    else:
        batch.provider_status = "processing"
    _audit(
        db,
        request,
        context,
        action="finance.payment_batch.provider_synced",
        entity_type="payment_batch",
        entity_id=str(batch.id),
        after={"provider": account.provider, "confirmed": confirmed, "pending": pending, "failed": failed},
    )
    db.commit()
    return _provider_batch_response(db, batch)
