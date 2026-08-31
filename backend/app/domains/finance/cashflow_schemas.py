from datetime import date
from typing import Literal

from pydantic import BaseModel

FundScope = Literal["operating", "third_party"]
CashFlowView = Literal["day", "week", "month"]
CashFlowMode = Literal["realized", "projected", "mixed"]


class CashFlowPeriodMovement(BaseModel):
    id: str
    source_type: str
    source_code: str | None
    description: str
    counterparty_name: str | None
    category: str
    direction: Literal["receivable", "payable"]
    amount: float
    state: Literal["realized", "projected"]


class CashFlowPeriodDay(BaseModel):
    date: date
    mode: CashFlowMode
    realized_receivables: float
    realized_payables: float
    projected_receivables: float
    projected_payables: float
    receivables: float
    payables: float
    net: float
    balance: float
    receivable_count: int
    payable_count: int
    movements: list[CashFlowPeriodMovement]


class CashFlowPeriodOverview(BaseModel):
    fund_scope: FundScope
    view: CashFlowView
    mode: CashFlowMode
    anchor_date: date
    start_date: date
    end_date: date
    today: date
    current_bank_balance: float
    opening_balance: float
    realized_receivables: float
    realized_payables: float
    projected_receivables: float
    projected_payables: float
    total_receivables: float
    total_payables: float
    closing_balance: float
    lowest_balance: float
    lowest_balance_date: date
    overdue_receivables: float
    overdue_payables: float
    days: list[CashFlowPeriodDay]
