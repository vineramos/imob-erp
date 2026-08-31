from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.finance.bank_models import BankAccount, BankTransaction
from app.domains.finance.cashflow_schemas import (
    CashFlowPeriodDay,
    CashFlowPeriodMovement,
    CashFlowPeriodOverview,
)
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import MaintenanceFinancialEntry, OwnerRepasse, RentCharge
from app.domains.finance.treasury_models import PaymentBatch, PaymentBatchItem
from app.domains.foundation.access import UserContext, require_permission

router = APIRouter(prefix="/finance/treasury", tags=["finance-cashflow"])

ZERO = Decimal("0.00")
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def money(value: Decimal | int | float | str | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _today() -> date:
    return datetime.now(SAO_PAULO).date()


def _period(view: str, anchor: date) -> tuple[date, date]:
    if view == "day":
        return anchor, anchor
    if view == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    start = anchor.replace(day=1)
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    return start, anchor.replace(day=last_day)


def _period_mode(start: date, end: date, today: date) -> str:
    if end < today:
        return "realized"
    if start > today:
        return "projected"
    return "mixed"


def _day_mode(day: date, today: date) -> str:
    if day < today:
        return "realized"
    if day > today:
        return "projected"
    return "mixed"


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


def _bank_balance_today(
    db: Session,
    *,
    organization_id: UUID,
    account_ids: list[UUID],
    opening_balance: Decimal,
    today: date,
) -> Decimal:
    if not account_ids:
        return money(opening_balance)
    transactions = db.scalars(
        select(BankTransaction).where(
            BankTransaction.organization_id == organization_id,
            BankTransaction.bank_account_id.in_(account_ids),
            BankTransaction.transaction_date <= today,
        )
    ).all()
    balance = money(opening_balance)
    for item in transactions:
        balance += money(item.amount) if item.direction == "credit" else -money(item.amount)
    return money(balance)


def _target_category(target_type: str) -> str:
    return {
        "rent": "Locação",
        "owner_repasse": "Repasse",
        "maintenance": "Manutenção",
        "manual": "Manual",
    }.get(target_type, "Financeiro")


def _actual_movements(
    db: Session,
    *,
    organization_id: UUID,
    account_ids: list[UUID],
    start: date,
    today: date,
) -> tuple[list[BankTransaction], dict[date, list[CashFlowPeriodMovement]]]:
    if not account_ids or start > today:
        return [], {}
    transactions = db.scalars(
        select(BankTransaction)
        .options(selectinload(BankTransaction.reconciliations))
        .where(
            BankTransaction.organization_id == organization_id,
            BankTransaction.bank_account_id.in_(account_ids),
            BankTransaction.transaction_date >= start,
            BankTransaction.transaction_date <= today,
        )
        .order_by(BankTransaction.transaction_date, BankTransaction.posted_at, BankTransaction.created_at)
    ).all()
    grouped: dict[date, list[CashFlowPeriodMovement]] = defaultdict(list)
    for item in transactions:
        reconciliations = list(item.reconciliations or [])
        target_type = reconciliations[0].target_type if reconciliations else "bank"
        source_code = " · ".join(dict.fromkeys(rec.target_code for rec in reconciliations)) or None
        grouped[item.transaction_date].append(
            CashFlowPeriodMovement(
                id=str(item.id),
                source_type=target_type,
                source_code=source_code,
                description=item.description,
                counterparty_name=item.counterparty_name,
                category=_target_category(target_type) if reconciliations else "Banco",
                direction="receivable" if item.direction == "credit" else "payable",
                amount=float(money(item.amount)),
                state="realized",
            )
        )
    return transactions, dict(grouped)


def _projection_movements(
    db: Session,
    *,
    organization_id: UUID,
    fund_scope: str,
    today: date,
    end_date: date,
) -> tuple[dict[date, list[CashFlowPeriodMovement]], Decimal, Decimal]:
    schedule = _scheduled_target_dates(db, organization_id)
    grouped: dict[date, list[CashFlowPeriodMovement]] = defaultdict(list)
    overdue_receivables = ZERO
    overdue_payables = ZERO

    def add(
        target_type: str,
        target_id: UUID,
        *,
        code: str | None,
        direction: str,
        scope: str,
        due_date: date | None,
        amount: Decimal,
        description: str,
        counterparty: str | None,
        category: str,
    ) -> None:
        nonlocal overdue_receivables, overdue_payables
        amount = money(amount)
        if scope != fund_scope or amount <= 0:
            return
        original_due = due_date or today
        if original_due < today:
            if direction == "receivable":
                overdue_receivables += amount
            else:
                overdue_payables += amount
        effective = schedule.get((target_type, target_id), original_due) if direction == "payable" else original_due
        effective = max(today, effective)
        if effective > end_date:
            return
        grouped[effective].append(
            CashFlowPeriodMovement(
                id=f"{target_type}:{target_id}",
                source_type=target_type,
                source_code=code,
                description=description,
                counterparty_name=counterparty,
                category=category,
                direction=direction,
                amount=float(amount),
                state="projected",
            )
        )

    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.status.not_in(("paid", "cancelled")),
        )
    ).all()
    for item in charges:
        snapshot = item.property_snapshot or {}
        property_label = snapshot.get("code") or snapshot.get("title") or snapshot.get("name") or snapshot.get("address") or "Imóvel"
        tenants = item.tenant_snapshot or []
        tenant_name = next((str(person.get("name")) for person in tenants if isinstance(person, dict) and person.get("name")), None)
        add(
            "rent",
            item.id,
            code=f"ALUG-{item.internal_number:05d}",
            direction="receivable",
            scope="third_party",
            due_date=item.due_date,
            amount=money(item.gross_amount),
            description=f"Aluguel · {property_label}",
            counterparty=tenant_name,
            category="Locação",
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
            code=f"REP-{str(item.id)[:8].upper()}",
            direction="payable",
            scope="third_party",
            due_date=item.due_date,
            amount=money(item.amount),
            description=f"Repasse · {item.owner_name}",
            counterparty=item.owner_name,
            category="Repasse",
        )

    maintenance = db.scalars(
        select(MaintenanceFinancialEntry).where(
            MaintenanceFinancialEntry.organization_id == organization_id,
            MaintenanceFinancialEntry.status.in_(("pending", "partial")),
        )
    ).all()
    for item in maintenance:
        scope = "third_party" if item.direction == "receivable" and item.collection_method == "owner_repasse_deduction" else "operating"
        remaining = max(ZERO, money(item.amount) - money(item.settled_amount))
        add(
            "maintenance",
            item.id,
            code=f"MFIN-{item.internal_number:06d}",
            direction=item.direction,
            scope=scope,
            due_date=item.due_date or item.created_at.date(),
            amount=remaining,
            description=f"Manutenção · {item.counterparty_name}",
            counterparty=item.counterparty_name,
            category="Manutenção",
        )

    manual = db.scalars(
        select(FinancialTitle).where(
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.status.in_(("pending", "partial")),
        )
    ).all()
    for item in manual:
        remaining = max(ZERO, money(item.amount) - money(item.settled_amount))
        add(
            "manual",
            item.id,
            code=f"FIN-{item.internal_number:06d}",
            direction=item.direction,
            scope=item.fund_scope,
            due_date=item.due_date,
            amount=remaining,
            description=item.description,
            counterparty=item.counterparty_name,
            category=item.category,
        )

    return dict(grouped), money(overdue_receivables), money(overdue_payables)


@router.get("/cash-flow-period", response_model=CashFlowPeriodOverview)
def cash_flow_period(
    view: str = Query(default="week", pattern="^(day|week|month)$"),
    anchor: date | None = Query(default=None),
    fund_scope: str = Query(default="operating", pattern="^(operating|third_party)$"),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> CashFlowPeriodOverview:
    today = _today()
    anchor_date = anchor or today
    start_date, end_date = _period(view, anchor_date)
    organization_id = context.user.organization_id

    accounts = db.scalars(
        select(BankAccount).where(
            BankAccount.organization_id == organization_id,
            BankAccount.is_active.is_(True),
            BankAccount.fund_scope == fund_scope,
        )
    ).all()
    account_ids = [item.id for item in accounts]
    account_opening = money(sum((money(item.opening_balance) for item in accounts), ZERO))
    current_bank_balance = _bank_balance_today(
        db,
        organization_id=organization_id,
        account_ids=account_ids,
        opening_balance=account_opening,
        today=today,
    )

    actual_transactions, actual_by_day = _actual_movements(
        db,
        organization_id=organization_id,
        account_ids=account_ids,
        start=start_date,
        today=today,
    )
    projection_by_day, overdue_receivables, overdue_payables = _projection_movements(
        db,
        organization_id=organization_id,
        fund_scope=fund_scope,
        today=today,
        end_date=max(end_date, today),
    )

    if start_date <= today:
        actual_net_since_start = ZERO
        for item in actual_transactions:
            amount = money(item.amount)
            actual_net_since_start += amount if item.direction == "credit" else -amount
        opening_balance = money(current_bank_balance - actual_net_since_start)
    else:
        opening_balance = current_bank_balance
        cursor = today
        while cursor < start_date:
            for movement in projection_by_day.get(cursor, []):
                amount = money(movement.amount)
                opening_balance += amount if movement.direction == "receivable" else -amount
            cursor += timedelta(days=1)
        opening_balance = money(opening_balance)

    running = opening_balance
    realized_receivables = ZERO
    realized_payables = ZERO
    projected_receivables = ZERO
    projected_payables = ZERO
    lowest_balance = opening_balance
    lowest_balance_date = start_date
    days: list[CashFlowPeriodDay] = []

    cursor = start_date
    while cursor <= end_date:
        realized = actual_by_day.get(cursor, []) if cursor <= today else []
        projected = projection_by_day.get(cursor, []) if cursor >= today else []
        movements = [*realized, *projected]

        day_realized_receivables = money(sum((money(item.amount) for item in realized if item.direction == "receivable"), ZERO))
        day_realized_payables = money(sum((money(item.amount) for item in realized if item.direction == "payable"), ZERO))
        day_projected_receivables = money(sum((money(item.amount) for item in projected if item.direction == "receivable"), ZERO))
        day_projected_payables = money(sum((money(item.amount) for item in projected if item.direction == "payable"), ZERO))

        realized_receivables += day_realized_receivables
        realized_payables += day_realized_payables
        projected_receivables += day_projected_receivables
        projected_payables += day_projected_payables

        receivables = money(day_realized_receivables + day_projected_receivables)
        payables = money(day_realized_payables + day_projected_payables)
        net = money(receivables - payables)
        running = money(running + net)
        if running < lowest_balance:
            lowest_balance = running
            lowest_balance_date = cursor

        days.append(
            CashFlowPeriodDay(
                date=cursor,
                mode=_day_mode(cursor, today),
                realized_receivables=float(day_realized_receivables),
                realized_payables=float(day_realized_payables),
                projected_receivables=float(day_projected_receivables),
                projected_payables=float(day_projected_payables),
                receivables=float(receivables),
                payables=float(payables),
                net=float(net),
                balance=float(running),
                receivable_count=sum(1 for item in movements if item.direction == "receivable"),
                payable_count=sum(1 for item in movements if item.direction == "payable"),
                movements=movements,
            )
        )
        cursor += timedelta(days=1)

    realized_receivables = money(realized_receivables)
    realized_payables = money(realized_payables)
    projected_receivables = money(projected_receivables)
    projected_payables = money(projected_payables)

    return CashFlowPeriodOverview(
        fund_scope=fund_scope,
        view=view,
        mode=_period_mode(start_date, end_date, today),
        anchor_date=anchor_date,
        start_date=start_date,
        end_date=end_date,
        today=today,
        current_bank_balance=float(current_bank_balance),
        opening_balance=float(opening_balance),
        realized_receivables=float(realized_receivables),
        realized_payables=float(realized_payables),
        projected_receivables=float(projected_receivables),
        projected_payables=float(projected_payables),
        total_receivables=float(money(realized_receivables + projected_receivables)),
        total_payables=float(money(realized_payables + projected_payables)),
        closing_balance=float(running),
        lowest_balance=float(lowest_balance),
        lowest_balance_date=lowest_balance_date,
        overdue_receivables=float(overdue_receivables),
        overdue_payables=float(overdue_payables),
        days=days,
    )
