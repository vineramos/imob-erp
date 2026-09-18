from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.finance_banking import (
    _account_balance,
    _fingerprint,
    _load_account,
    _target_details,
    money,
)
from app.core.database import get_db
from app.domains.finance.bank_models import BankAccount, BankReconciliation, BankTransaction
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import MaintenanceFinancialEntry, OwnerRepasse, RentCharge
from app.domains.finance.treasury_models import PaymentBatch, PaymentBatchItem
from app.domains.finance.treasury_schemas import (
    CashFlowDay,
    CashFlowOverview,
    PaymentBatchCreate,
    PaymentBatchExecutionRequest,
    PaymentBatchItemResponse,
    PaymentBatchResponse,
    PaymentCandidate,
    OwnerRepasseResponse,
)
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit

router = APIRouter(prefix="/finance/treasury", tags=["finance-treasury"])


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


def _load_batch(db: Session, organization_id: UUID, batch_id: UUID) -> PaymentBatch:
    item = db.scalar(
        select(PaymentBatch)
        .options(selectinload(PaymentBatch.items))
        .where(PaymentBatch.id == batch_id, PaymentBatch.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Lote de pagamento não encontrado.")
    return item


def _batch_response(db: Session, item: PaymentBatch) -> PaymentBatchResponse:
    account = _load_account(db, item.organization_id, item.bank_account_id)
    return PaymentBatchResponse(
        id=item.id,
        code=f"LOT-{item.internal_number:05d}",
        bank_account_id=item.bank_account_id,
        bank_account_name=account.name,
        name=item.name,
        scheduled_date=item.scheduled_date,
        fund_scope=item.fund_scope,
        payment_method=item.payment_method,
        status=item.status,
        total_amount=money(item.total_amount),
        item_count=int(item.item_count),
        notes=item.notes,
        provider_batch_id=item.provider_batch_id,
        provider_status=item.provider_status,
        execution_reference=item.execution_reference,
        prepared_at=item.prepared_at,
        approved_at=item.approved_at,
        executed_at=item.executed_at,
        cancelled_at=item.cancelled_at,
        created_at=item.created_at,
        items=[
            PaymentBatchItemResponse(
                id=entry.id,
                target_type=entry.target_type,
                target_id=entry.target_id,
                target_code=entry.target_code,
                description=entry.description,
                counterparty_name=entry.counterparty_name,
                due_date=entry.due_date,
                fund_scope=entry.fund_scope,
                amount=money(entry.amount),
                status=entry.status,
                bank_transaction_id=entry.bank_transaction_id,
            )
            for entry in item.items
        ],
    )


def _active_target_keys(db: Session, organization_id: UUID, *, include_draft: bool = True) -> set[tuple[str, UUID]]:
    statuses = ("draft", "ready", "approved") if include_draft else ("ready", "approved")
    rows = db.execute(
        select(PaymentBatchItem.target_type, PaymentBatchItem.target_id)
        .join(PaymentBatch, PaymentBatch.id == PaymentBatchItem.payment_batch_id)
        .where(
            PaymentBatch.organization_id == organization_id,
            PaymentBatch.status.in_(statuses),
            PaymentBatchItem.status == "pending",
        )
    ).all()
    return {(str(row[0]), row[1]) for row in rows}


def _scheduled_target_dates(db: Session, organization_id: UUID) -> dict[tuple[str, UUID], date]:
    rows = db.execute(
        select(PaymentBatchItem.target_type, PaymentBatchItem.target_id, PaymentBatch.scheduled_date)
        .join(PaymentBatch, PaymentBatch.id == PaymentBatchItem.payment_batch_id)
        .where(
            PaymentBatch.organization_id == organization_id,
            PaymentBatch.status.in_(("ready", "approved")),
            PaymentBatchItem.status == "pending",
        )
    ).all()
    return {(str(row[0]), row[1]): row[2] for row in rows}


def _candidate_targets(db: Session, organization_id: UUID) -> list[tuple[str, UUID]]:
    result: list[tuple[str, UUID]] = []
    result.extend(
        ("owner_repasse", item.id)
        for item in db.scalars(
            select(OwnerRepasse).where(
                OwnerRepasse.organization_id == organization_id,
                OwnerRepasse.status == "pending",
                OwnerRepasse.amount > 0,
            )
        ).all()
    )
    result.extend(
        ("maintenance", item.id)
        for item in db.scalars(
            select(MaintenanceFinancialEntry).where(
                MaintenanceFinancialEntry.organization_id == organization_id,
                MaintenanceFinancialEntry.direction == "payable",
                MaintenanceFinancialEntry.status.in_(("pending", "partial")),
            )
        ).all()
    )
    result.extend(
        ("manual", item.id)
        for item in db.scalars(
            select(FinancialTitle).where(
                FinancialTitle.organization_id == organization_id,
                FinancialTitle.source_type == "manual",
                FinancialTitle.direction == "payable",
                FinancialTitle.status.in_(("pending", "partial")),
            )
        ).all()
    )
    return result


def _validate_batch_targets(db: Session, batch: PaymentBatch) -> None:
    for entry in batch.items:
        details = _target_details(db, batch.organization_id, entry.target_type, entry.target_id)
        if details["direction"] != "payable":
            raise HTTPException(status_code=409, detail=f"{entry.target_code} deixou de ser uma obrigação a pagar.")
        if details["fund_scope"] != batch.fund_scope:
            raise HTTPException(status_code=409, detail=f"{entry.target_code} mudou de natureza de recurso.")
        if money(details["remaining"]) != money(entry.amount):
            raise HTTPException(
                status_code=409,
                detail=f"O saldo de {entry.target_code} mudou desde a criação do lote. Recrie o lote para continuar.",
            )


def _settle_payable(details: dict, *, amount: Decimal, settled_at: datetime, reference: str, payment_method: str) -> None:
    target = details["object"]
    target_type = details.get("target_type")
    if target_type == "owner_repasse":
        target.status = "paid"
        target.paid_at = settled_at
        target.payment_reference = reference
        target.notes = f"{target.notes or ''}\nPagamento registrado pelo lote {reference}.".strip()
        return
    if target_type == "maintenance":
        target.settled_amount = money(target.settled_amount + amount)
        target.status = "settled" if target.settled_amount >= target.amount else "partial"
        target.settled_at = settled_at if target.status == "settled" else None
        target.payment_reference = reference
        target.notes = f"{target.notes or ''}\nPagamento registrado pelo lote {reference}: R$ {amount:.2f}.".strip()
        return
    target.settled_amount = money(target.settled_amount + amount)
    target.status = "settled" if target.settled_amount >= target.amount else "partial"
    target.settled_at = settled_at if target.status == "settled" else None
    target.payment_method = payment_method
    target.payment_reference = reference
    target.notes = f"{target.notes or ''}\nPagamento registrado pelo lote {reference}: R$ {amount:.2f}.".strip()


def _projection_rows(
    db: Session,
    organization_id: UUID,
    *,
    fund_scope: str,
    end_date: date,
) -> tuple[dict[date, dict[str, Decimal | int]], Decimal, Decimal]:
    today = date.today()
    schedule = _scheduled_target_dates(db, organization_id)
    rows: dict[date, dict[str, Decimal | int]] = {}
    overdue_receivables = Decimal("0.00")
    overdue_payables = Decimal("0.00")

    def add(
        target_type: str,
        target_id: UUID,
        *,
        direction: str,
        scope: str,
        due_date: date | None,
        remaining: Decimal,
    ) -> None:
        nonlocal overdue_receivables, overdue_payables
        remaining = money(remaining)
        if scope != fund_scope or remaining <= 0:
            return
        original_due = due_date or today
        if original_due < today:
            if direction == "receivable":
                overdue_receivables += remaining
            else:
                overdue_payables += remaining
        effective = schedule.get((target_type, target_id), original_due) if direction == "payable" else original_due
        effective = max(today, effective)
        if effective > end_date:
            return
        bucket = rows.setdefault(
            effective,
            {"receivables": Decimal("0.00"), "payables": Decimal("0.00"), "receivable_count": 0, "payable_count": 0},
        )
        if direction == "receivable":
            bucket["receivables"] = money(Decimal(str(bucket["receivables"])) + remaining)
            bucket["receivable_count"] = int(bucket["receivable_count"]) + 1
        else:
            bucket["payables"] = money(Decimal(str(bucket["payables"])) + remaining)
            bucket["payable_count"] = int(bucket["payable_count"]) + 1

    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.status.not_in(("paid", "cancelled")),
        )
    ).all()
    for item in charges:
        add(
            "rent",
            item.id,
            direction="receivable",
            scope="third_party",
            due_date=item.due_date,
            remaining=money(item.gross_amount),
        )

    repasses = db.scalars(
        select(OwnerRepasse).where(
            OwnerRepasse.organization_id == organization_id,
            OwnerRepasse.status == "pending",
            OwnerRepasse.amount > 0,
        )
    ).all()
    for item in repasses:
        add(
            "owner_repasse",
            item.id,
            direction="payable",
            scope="third_party",
            due_date=item.due_date,
            remaining=money(item.amount),
        )

    maintenance = db.scalars(
        select(MaintenanceFinancialEntry).where(
            MaintenanceFinancialEntry.organization_id == organization_id,
            MaintenanceFinancialEntry.status.in_(("pending", "partial")),
        )
    ).all()
    for item in maintenance:
        scope = "third_party" if item.direction == "receivable" and item.collection_method == "owner_repasse_deduction" else "operating"
        add(
            "maintenance",
            item.id,
            direction=item.direction,
            scope=scope,
            due_date=item.due_date or item.created_at.date(),
            remaining=money(max(Decimal("0.00"), item.amount - item.settled_amount)),
        )

    manual = db.scalars(
        select(FinancialTitle).where(
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.status.in_(("pending", "partial")),
        )
    ).all()
    for item in manual:
        add(
            "manual",
            item.id,
            direction=item.direction,
            scope=item.fund_scope,
            due_date=item.due_date,
            remaining=money(max(Decimal("0.00"), item.amount - item.settled_amount)),
        )

    return rows, money(overdue_receivables), money(overdue_payables)


@router.get("/cash-flow", response_model=CashFlowOverview)
def cash_flow(
    fund_scope: str = Query(default="operating", pattern="^(operating|third_party)$"),
    horizon: int = Query(default=90, ge=7, le=365),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> CashFlowOverview:
    today = date.today()
    end_date = today + timedelta(days=horizon)
    accounts = db.scalars(
        select(BankAccount).where(
            BankAccount.organization_id == context.user.organization_id,
            BankAccount.is_active.is_(True),
            BankAccount.fund_scope == fund_scope,
        )
    ).all()
    current_balance = money(sum((_account_balance(db, account) for account in accounts), Decimal("0.00")))
    projections, overdue_receivables, overdue_payables = _projection_rows(
        db,
        context.user.organization_id,
        fund_scope=fund_scope,
        end_date=end_date,
    )

    running = current_balance
    projected_receivables = Decimal("0.00")
    projected_payables = Decimal("0.00")
    lowest = current_balance
    lowest_date = today
    days: list[CashFlowDay] = []

    cursor = today
    while cursor <= end_date:
        bucket = projections.get(
            cursor,
            {"receivables": Decimal("0.00"), "payables": Decimal("0.00"), "receivable_count": 0, "payable_count": 0},
        )
        receivables = money(bucket["receivables"])
        payables = money(bucket["payables"])
        projected_receivables += receivables
        projected_payables += payables
        net = money(receivables - payables)
        running = money(running + net)
        if running < lowest:
            lowest = running
            lowest_date = cursor
        if receivables or payables or cursor in {today, end_date}:
            days.append(
                CashFlowDay(
                    date=cursor,
                    receivables=receivables,
                    payables=payables,
                    net=net,
                    projected_balance=running,
                    receivable_count=int(bucket["receivable_count"]),
                    payable_count=int(bucket["payable_count"]),
                )
            )
        cursor += timedelta(days=1)

    return CashFlowOverview(
        fund_scope=fund_scope,
        start_date=today,
        end_date=end_date,
        current_bank_balance=current_balance,
        projected_receivables=money(projected_receivables),
        projected_payables=money(projected_payables),
        projected_end_balance=running,
        lowest_projected_balance=lowest,
        lowest_balance_date=lowest_date,
        overdue_receivables=overdue_receivables,
        overdue_payables=overdue_payables,
        days=days,
    )


@router.get("/repasses", response_model=list[OwnerRepasseResponse])
def list_repasses(
    status: str | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[OwnerRepasseResponse]:
    stmt = select(OwnerRepasse).where(OwnerRepasse.organization_id == context.user.organization_id)
    if status:
        stmt = stmt.where(OwnerRepasse.status == status)
    items = db.scalars(
        stmt.order_by(OwnerRepasse.due_date.asc(), OwnerRepasse.owner_name.asc()).limit(500)
    ).all()
    result: list[OwnerRepasseResponse] = []
    for item in items:
        charge = db.get(RentCharge, item.charge_id)
        lease_code = "LOC-—"
        if charge is not None:
            lease_code = f"LOC-{charge.internal_number:06d}"
        result.append(
            OwnerRepasseResponse(
                id=item.id,
                charge_id=item.charge_id,
                charge_code=f"COB-{charge.internal_number:06d}" if charge else "COB-—",
                lease_contract_id=item.lease_contract_id,
                lease_code=lease_code,
                property_id=item.property_id,
                property_code=str((charge.property_snapshot or {}).get("code") or "—") if charge else "—",
                competence=item.settlement.charge.competence if item.settlement and item.settlement.charge else date.today(),
                owner_person_id=item.owner_person_id,
                owner_name=item.owner_name,
                ownership_percent=float(item.ownership_percent),
                amount=float(money(item.amount)),
                due_date=item.due_date,
                status=item.status,
                paid_at=item.paid_at,
                payment_reference=item.payment_reference,
            )
        )
    return result


@router.get("/payment-candidates", response_model=list[PaymentCandidate])
def payment_candidates(
    account_id: UUID = Query(...),
    until: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[PaymentCandidate]:
    account = _load_account(db, context.user.organization_id, account_id)
    active = _active_target_keys(db, context.user.organization_id)
    result: list[PaymentCandidate] = []
    for target_type, target_id in _candidate_targets(db, context.user.organization_id):
        if (target_type, target_id) in active:
            continue
        details = _target_details(db, context.user.organization_id, target_type, target_id)
        due = details["due_date"]
        remaining = money(details["remaining"])
        if details["fund_scope"] != account.fund_scope or details["direction"] != "payable" or remaining <= 0:
            continue
        if until and due and due > until:
            continue
        result.append(
            PaymentCandidate(
                target_type=target_type,
                target_id=target_id,
                target_code=details["code"],
                description=details["description"],
                counterparty_name=details["counterparty"],
                due_date=due,
                fund_scope=details["fund_scope"],
                remaining_amount=remaining,
                overdue=bool(due and due < date.today()),
            )
        )
    return sorted(result, key=lambda item: (not item.overdue, item.due_date or date.max, item.target_code))


@router.get("/payment-batches", response_model=list[PaymentBatchResponse])
def list_payment_batches(
    account_id: UUID | None = Query(default=None),
    batch_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[PaymentBatchResponse]:
    stmt = (
        select(PaymentBatch)
        .options(selectinload(PaymentBatch.items))
        .where(PaymentBatch.organization_id == context.user.organization_id)
    )
    if account_id:
        stmt = stmt.where(PaymentBatch.bank_account_id == account_id)
    if batch_status:
        stmt = stmt.where(PaymentBatch.status == batch_status)
    items = db.scalars(stmt.order_by(PaymentBatch.created_at.desc()).limit(300)).unique().all()
    return [_batch_response(db, item) for item in items]


@router.post("/payment-batches", response_model=PaymentBatchResponse)
def create_payment_batch(
    payload: PaymentBatchCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> PaymentBatchResponse:
    if payload.scheduled_date < date.today():
        raise HTTPException(status_code=422, detail="A data programada não pode estar no passado.")
    account = _load_account(db, context.user.organization_id, payload.bank_account_id)
    if not account.is_active:
        raise HTTPException(status_code=409, detail="A conta bancária selecionada está inativa.")

    refs = [(entry.target_type, entry.target_id) for entry in payload.items]
    if len(refs) != len(set(refs)):
        raise HTTPException(status_code=422, detail="O lote contém títulos repetidos.")
    occupied = _active_target_keys(db, context.user.organization_id)
    duplicate = next((ref for ref in refs if ref in occupied), None)
    if duplicate:
        raise HTTPException(status_code=409, detail="Um dos títulos selecionados já pertence a outro lote em aberto.")

    batch = PaymentBatch(
        organization_id=context.user.organization_id,
        bank_account_id=account.id,
        name=payload.name.strip(),
        scheduled_date=payload.scheduled_date,
        fund_scope=account.fund_scope,
        payment_method=payload.payment_method,
        status="draft",
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=context.user.id,
    )
    db.add(batch)
    db.flush()

    total = Decimal("0.00")
    for target_type, target_id in refs:
        details = _target_details(db, context.user.organization_id, target_type, target_id)
        if details["direction"] != "payable":
            raise HTTPException(status_code=409, detail=f"{details['code']} não é uma obrigação a pagar.")
        if details["fund_scope"] != account.fund_scope:
            raise HTTPException(
                status_code=409,
                detail=f"{details['code']} não pode ser pago por esta conta porque a natureza do recurso é diferente.",
            )
        remaining = money(details["remaining"])
        if remaining <= 0:
            raise HTTPException(status_code=409, detail=f"{details['code']} não possui saldo pendente.")
        item = PaymentBatchItem(
            organization_id=context.user.organization_id,
            payment_batch_id=batch.id,
            target_type=target_type,
            target_id=target_id,
            target_code=details["code"],
            description=details["description"],
            counterparty_name=details["counterparty"],
            due_date=details["due_date"],
            fund_scope=details["fund_scope"],
            amount=remaining,
            status="pending",
        )
        db.add(item)
        total += remaining

    batch.total_amount = money(total)
    batch.item_count = len(refs)
    db.flush()
    _audit(
        db,
        request,
        context,
        action="finance.payment_batch.created",
        entity_type="payment_batch",
        entity_id=str(batch.id),
        after={
            "code": f"LOT-{batch.internal_number:05d}",
            "account_id": str(account.id),
            "scheduled_date": batch.scheduled_date.isoformat(),
            "fund_scope": batch.fund_scope,
            "total_amount": str(batch.total_amount),
            "item_count": batch.item_count,
        },
    )
    db.commit()
    return _batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/payment-batches/{batch_id}/prepare", response_model=PaymentBatchResponse)
def prepare_payment_batch(
    batch_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> PaymentBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    if batch.status != "draft":
        raise HTTPException(status_code=409, detail="Somente lotes em rascunho podem ser preparados.")
    _validate_batch_targets(db, batch)
    batch.status = "ready"
    batch.prepared_by_user_id = context.user.id
    batch.prepared_at = datetime.now(timezone.utc)
    _audit(
        db, request, context, action="finance.payment_batch.prepared",
        entity_type="payment_batch", entity_id=str(batch.id),
        after={"status": batch.status, "total_amount": str(batch.total_amount)},
    )
    db.commit()
    return _batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/payment-batches/{batch_id}/approve", response_model=PaymentBatchResponse)
def approve_payment_batch(
    batch_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> PaymentBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    if batch.status != "ready":
        raise HTTPException(status_code=409, detail="Somente lotes preparados podem ser aprovados.")
    _validate_batch_targets(db, batch)
    batch.status = "approved"
    batch.approved_by_user_id = context.user.id
    batch.approved_at = datetime.now(timezone.utc)
    _audit(
        db, request, context, action="finance.payment_batch.approved",
        entity_type="payment_batch", entity_id=str(batch.id),
        after={"status": batch.status, "total_amount": str(batch.total_amount)},
    )
    db.commit()
    return _batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/payment-batches/{batch_id}/execute", response_model=PaymentBatchResponse)
def execute_payment_batch(
    batch_id: UUID,
    payload: PaymentBatchExecutionRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> PaymentBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    if batch.status != "approved":
        raise HTTPException(status_code=409, detail="Somente lotes aprovados podem ter a execução registrada.")
    if payload.execution_date > date.today():
        raise HTTPException(status_code=422, detail="A execução só pode ser registrada na data atual ou em data passada.")
    account = _load_account(db, context.user.organization_id, batch.bank_account_id)
    _validate_batch_targets(db, batch)

    settled_at = datetime.combine(payload.execution_date, time(12, 0), tzinfo=timezone.utc)
    batch_reference = (payload.reference or "").strip() or f"LOT-{batch.internal_number:05d}"
    for entry in batch.items:
        details = _target_details(db, context.user.organization_id, entry.target_type, entry.target_id)
        details["target_type"] = entry.target_type
        fingerprint = _fingerprint(
            account.id,
            transaction_date=payload.execution_date,
            direction="debit",
            amount=entry.amount,
            description=f"Pagamento {entry.target_code} {entry.counterparty_name}",
            external_id=f"payment-batch:{batch.id}:{entry.id}",
            reference=batch_reference,
        )
        transaction = BankTransaction(
            organization_id=context.user.organization_id,
            bank_account_id=account.id,
            external_id=f"payment-batch:{batch.id}:{entry.id}",
            fingerprint=fingerprint,
            transaction_date=payload.execution_date,
            posted_at=settled_at,
            direction="debit",
            amount=money(entry.amount),
            description=f"Pagamento {entry.target_code} · {entry.description}"[:300],
            counterparty_name=entry.counterparty_name[:220],
            bank_reference=batch_reference,
            source="payment_batch",
            status="reconciled",
            raw_data={"payment_batch_id": str(batch.id), "payment_batch_item_id": str(entry.id)},
            created_by_user_id=context.user.id,
        )
        db.add(transaction)
        db.flush()

        reference = f"EXT-{transaction.internal_number:06d}"
        _settle_payable(
            details,
            amount=money(entry.amount),
            settled_at=settled_at,
            reference=reference,
            payment_method=batch.payment_method,
        )
        db.add(
            BankReconciliation(
                organization_id=context.user.organization_id,
                bank_transaction_id=transaction.id,
                target_type=entry.target_type,
                target_id=entry.target_id,
                target_code=entry.target_code,
                target_direction="payable",
                amount=money(entry.amount),
                notes=f"Executado pelo lote LOT-{batch.internal_number:05d}.",
                reconciled_by_user_id=context.user.id,
            )
        )
        entry.status = "executed"
        entry.bank_transaction_id = transaction.id

    batch.status = "executed"
    batch.executed_by_user_id = context.user.id
    batch.executed_at = settled_at
    batch.execution_reference = batch_reference
    batch.provider_status = "recorded_manual"
    _audit(
        db, request, context, action="finance.payment_batch.executed",
        entity_type="payment_batch", entity_id=str(batch.id),
        after={
            "status": batch.status,
            "execution_date": payload.execution_date.isoformat(),
            "reference": batch_reference,
            "item_count": batch.item_count,
            "total_amount": str(batch.total_amount),
        },
    )
    db.commit()
    return _batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/payment-batches/{batch_id}/cancel", response_model=PaymentBatchResponse)
def cancel_payment_batch(
    batch_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> PaymentBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    if batch.status not in {"draft", "ready", "approved"}:
        raise HTTPException(status_code=409, detail="Este lote não pode mais ser cancelado.")
    required = "finance.payment.approve" if batch.status == "approved" else "finance.payment.prepare"
    if not context.has(required):
        raise HTTPException(status_code=403, detail=f"Permissão necessária: {required}")
    batch.status = "cancelled"
    batch.cancelled_by_user_id = context.user.id
    batch.cancelled_at = datetime.now(timezone.utc)
    for entry in batch.items:
        if entry.status == "pending":
            entry.status = "cancelled"
    _audit(
        db, request, context, action="finance.payment_batch.cancelled",
        entity_type="payment_batch", entity_id=str(batch.id), after={"status": batch.status},
    )
    db.commit()
    return _batch_response(db, _load_batch(db, context.user.organization_id, batch.id))
