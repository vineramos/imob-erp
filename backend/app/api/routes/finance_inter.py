from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.finance_banking import _fingerprint, _load_account
from app.core.config import get_settings
from app.core.database import get_db
from app.domains.finance.advanced_models import BillingBatch, BillingItem, InterWebhookEvent
from app.domains.finance.advanced_schemas import InterStatusResponse, InterSyncResponse
from app.domains.finance.advanced_service import money, refresh_billing_batch_counters
from app.domains.finance.bank_models import BankAccount, BankReconciliation, BankTransaction
from app.domains.finance.billing_settlement import settle_confirmed_billing_item
from app.domains.finance.models import RentCharge
from app.domains.finance.providers import BankProviderError, InterBankProvider
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit

router = APIRouter(prefix="/inter")
webhook_router = APIRouter(prefix="/integrations/inter", tags=["inter-webhook"])


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    action: str,
    entity_id: str | None,
    after: dict | None = None,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type="bank_integration",
        entity_id=entity_id,
        after_data=after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )


def _balance(data: dict) -> Decimal | None:
    for key in ("disponivel", "saldoDisponivel", "saldo", "valor"):
        if data.get(key) is not None:
            try:
                return money(data[key])
            except Exception:
                pass
    return None


def _apply_billing_event(item: BillingItem, data: dict) -> None:
    cobranca = data.get("cobranca") if isinstance(data.get("cobranca"), dict) else data
    boleto = data.get("boleto") if isinstance(data.get("boleto"), dict) else {}
    pix = data.get("pix") if isinstance(data.get("pix"), dict) else {}
    item.provider_status = str(cobranca.get("situacao") or item.provider_status or "EM_PROCESSAMENTO")
    item.boleto_line = str(boleto.get("linhaDigitavel") or "") or item.boleto_line
    item.barcode = str(boleto.get("codigoBarras") or "") or item.barcode
    item.pix_copy_paste = str(pix.get("pixCopiaECola") or "") or item.pix_copy_paste
    item.pix_txid = str(pix.get("txid") or "") or item.pix_txid
    item.response_snapshot = dict(data)
    if item.provider_status.upper() in {"RECEBIDO", "MARCADO_RECEBIDO"}:
        item.confirmed_at = item.confirmed_at or datetime.now(timezone.utc)


def _rent_already_reconciled(db: Session, charge_id: UUID) -> bool:
    return db.scalar(
        select(BankReconciliation.id).where(
            BankReconciliation.target_type == "rent",
            BankReconciliation.target_id == charge_id,
        ).limit(1)
    ) is not None


def _auto_reconcile_confirmed_rent(
    db: Session,
    *,
    transaction: BankTransaction,
    account: BankAccount,
    user_id: UUID | None,
) -> None:
    """Liga um crédito real do extrato a uma cobrança já confirmada pelo Inter.

    O casamento automático só ocorre quando há exatamente uma cobrança paga,
    confirmada pelo provider, com mesmo valor e data de confirmação até dois
    dias distante da data bancária. Em qualquer ambiguidade, a conciliação
    permanece manual para evitar baixa indevida.
    """
    if transaction.direction != "credit" or account.fund_scope != "third_party":
        return

    candidates: list[tuple[BillingItem, RentCharge]] = []
    items = db.scalars(
        select(BillingItem).where(
            BillingItem.organization_id == transaction.organization_id,
            BillingItem.confirmed_at.is_not(None),
        )
    ).all()
    for item in items:
        charge = db.get(RentCharge, item.charge_id)
        if charge is None or charge.status != "paid":
            continue
        received_amount = charge.paid_amount if charge.paid_amount is not None else charge.gross_amount
        if money(received_amount) != money(transaction.amount):
            continue
        if _rent_already_reconciled(db, charge.id):
            continue
        confirmed_date = item.confirmed_at.date() if item.confirmed_at else None
        if confirmed_date is None or abs((transaction.transaction_date - confirmed_date).days) > 2:
            continue
        candidates.append((item, charge))

    if len(candidates) != 1:
        return

    _, charge = candidates[0]
    db.add(
        BankReconciliation(
            organization_id=transaction.organization_id,
            bank_transaction_id=transaction.id,
            target_type="rent",
            target_id=charge.id,
            target_code=f"COB-{charge.internal_number:06d}",
            target_direction="receivable",
            amount=money(transaction.amount),
            notes="Conciliação automática após confirmação do Banco Inter.",
            reconciled_by_user_id=user_id,
        )
    )
    transaction.status = "reconciled"


@router.get("/status", response_model=InterStatusResponse)
def provider_status(
    context: UserContext = Depends(require_permission("finance.view")),
) -> InterStatusResponse:
    data = InterBankProvider().status()
    return InterStatusResponse(**data.__dict__)


@router.post("/accounts/{account_id}/sync", response_model=InterSyncResponse)
def sync_account(
    account_id: UUID,
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> InterSyncResponse:
    if end_date < start_date or (end_date - start_date).days > 90:
        raise HTTPException(status_code=422, detail="O período do extrato deve ter no máximo 90 dias.")
    account = _load_account(db, context.user.organization_id, account_id)
    if account.provider != "inter":
        raise HTTPException(status_code=409, detail="A conta selecionada não usa Banco Inter.")
    provider = InterBankProvider()
    if not provider.status().configured:
        raise HTTPException(status_code=409, detail="Banco Inter ainda não está configurado no ambiente.")
    try:
        statement = provider.statement(start_date=start_date, end_date=end_date, enriched=True)
        balance_data = provider.balance()
    except BankProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    transactions = statement.get("transacoes") if isinstance(statement, dict) else []
    if not isinstance(transactions, list):
        transactions = []
    created = 0
    duplicates = 0
    now = datetime.now(timezone.utc)

    for source in transactions:
        if not isinstance(source, dict):
            continue
        operation = str(source.get("tipoOperacao") or "").upper()
        direction = "credit" if operation == "C" else "debit"
        try:
            amount = money(abs(Decimal(str(source.get("valor") or 0))))
        except Exception:
            continue
        if amount <= 0:
            continue
        raw_date = str(source.get("dataTransacao") or source.get("dataInclusao") or start_date.isoformat())[:10]
        try:
            tx_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        details = source.get("detalhes") if isinstance(source.get("detalhes"), dict) else {}
        description = str(
            source.get("descricao")
            or source.get("titulo")
            or source.get("tipoTransacao")
            or "Movimento Banco Inter"
        ).strip()
        external_id = str(
            source.get("idTransacao")
            or details.get("codigoSolicitacao")
            or details.get("endToEndId")
            or ""
        ).strip() or None
        reference = str(
            details.get("endToEndId")
            or details.get("txId")
            or source.get("numeroDocumento")
            or ""
        ).strip() or None
        fingerprint = _fingerprint(
            account.id,
            transaction_date=tx_date,
            direction=direction,
            amount=amount,
            description=description,
            external_id=external_id,
            reference=reference,
        )
        if db.scalar(
            select(BankTransaction.id).where(
                BankTransaction.bank_account_id == account.id,
                BankTransaction.fingerprint == fingerprint,
            )
        ):
            duplicates += 1
            continue

        transaction = BankTransaction(
            organization_id=context.user.organization_id,
            bank_account_id=account.id,
            external_id=external_id,
            fingerprint=fingerprint,
            transaction_date=tx_date,
            posted_at=None,
            direction=direction,
            amount=amount,
            description=description,
            document=str(
                details.get("cpfCnpjPagador")
                or details.get("cpfCnpjRecebedor")
                or source.get("numeroDocumento")
                or ""
            ).strip() or None,
            counterparty_name=str(
                details.get("nomePagador") or details.get("nomeRecebedor") or ""
            ).strip() or None,
            bank_reference=reference,
            source="inter",
            status="pending",
            raw_data=source,
            created_by_user_id=context.user.id,
        )
        db.add(transaction)
        db.flush()
        _auto_reconcile_confirmed_rent(
            db,
            transaction=transaction,
            account=account,
            user_id=context.user.id,
        )
        created += 1

    account.last_sync_at = now
    external = _balance(balance_data if isinstance(balance_data, dict) else {})
    _audit(
        db,
        request,
        context,
        "finance.inter.synced",
        str(account.id),
        {
            "created": created,
            "duplicates": duplicates,
            "from": str(start_date),
            "to": str(end_date),
        },
    )
    db.commit()
    return InterSyncResponse(
        account_id=account.id,
        start_date=start_date,
        end_date=end_date,
        created=created,
        duplicates=duplicates,
        external_balance=float(external) if external is not None else None,
        synced_at=now,
    )


@router.post("/webhook/register")
def register_webhook(
    request: Request,
    webhook_url: str = Query(..., min_length=12, max_length=700),
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> dict:
    provider = InterBankProvider()
    try:
        provider.set_billing_webhook(webhook_url)
    except BankProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _audit(db, request, context, "finance.inter.webhook_registered", "inter", {"url": webhook_url})
    db.commit()
    return {"ok": True, "webhook_url": webhook_url}


@webhook_router.post("/webhook/{secret}", status_code=204)
def inter_webhook(secret: str, payload: dict, db: Session = Depends(get_db)) -> Response:
    expected = get_settings().inter_webhook_secret
    if not expected or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=404, detail="Webhook não encontrado.")

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    event_hash = hashlib.sha256(canonical.encode()).hexdigest()
    if db.scalar(select(InterWebhookEvent.id).where(InterWebhookEvent.event_hash == event_hash)):
        return Response(status_code=204)

    provider_id = str(
        payload.get("codigoSolicitacao")
        or (payload.get("cobranca") or {}).get("codigoSolicitacao")
        or ""
    )
    item = db.scalar(
        select(BillingItem).where(BillingItem.provider_charge_id == provider_id)
    ) if provider_id else None
    event = InterWebhookEvent(
        organization_id=item.organization_id if item else None,
        event_hash=event_hash,
        event_type="billing",
        payload=payload,
        status="received",
    )
    db.add(event)

    try:
        if item:
            _apply_billing_event(item, payload)
            if item.confirmed_at:
                settle_confirmed_billing_item(db, item, paid_at=item.confirmed_at)
            batch = db.get(BillingBatch, item.billing_batch_id)
            if batch:
                refresh_billing_batch_counters(db, batch)
            event.status = "processed"
        else:
            event.status = "unmatched"
        event.processed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        event.status = "error"
        event.error = str(exc)[:2000]
        db.commit()
        raise
    return Response(status_code=204)
