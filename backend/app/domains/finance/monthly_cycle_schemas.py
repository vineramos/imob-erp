from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


MonthlyCycleState = Literal["complete", "pending", "attention", "idle"]


class MonthlyCycleStep(BaseModel):
    key: str
    title: str
    state: MonthlyCycleState
    summary: str
    detail: str
    count: int = 0
    pending_count: int = 0
    amount: Decimal = Decimal("0.00")
    pending_amount: Decimal = Decimal("0.00")
    action_label: str | None = None
    action_target: str | None = None


class MonthlyCycleAction(BaseModel):
    key: str
    title: str
    detail: str
    target: str


class MonthlyCycleResponse(BaseModel):
    competence: date
    eligible_contracts: int
    charges_count: int
    missing_charges: int
    gross_amount: Decimal
    open_charges: int
    overdue_charges: int
    paid_charges: int
    received_amount: Decimal
    settlements_count: int
    agency_revenue_amount: Decimal
    owner_entitlement_amount: Decimal
    third_party_pending_count: int
    third_party_pending_amount: Decimal
    owner_repasse_pending_count: int
    owner_repasse_pending_amount: Decimal
    statement_owner_count: int
    communications_pending_count: int
    communications_sent_count: int
    communications_failed_count: int
    attention_count: int
    next_action: MonthlyCycleAction | None
    steps: list[MonthlyCycleStep]



class MonthlyClosingReadiness(BaseModel):
    competence: date
    period_end: date
    can_close: bool
    bank_accounts_count: int
    accounts_closed_count: int
    unclosed_accounts_count: int
    unreconciled_bank_transactions_count: int
    open_bank_exceptions_count: int
    ignored_bank_exceptions_count: int
    settlement_gap_count: int
    settlement_integrity_issues_count: int
    pending_third_party_count: int
    pending_owner_repasses_count: int
    blocker_count: int
    blockers: list[str]
