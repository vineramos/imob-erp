from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

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
    open_payment_batches_count: int = 0
    failed_payment_batches_count: int = 0
    blocker_count: int
    blockers: list[str]



class MonthlyClosureRequest(BaseModel):
    note: str | None = None


class MonthlyReopenRequest(BaseModel):
    reason: str


class MonthlyClosureEventResponse(BaseModel):
    id: UUID
    action: Literal["closed", "reopened"]
    reason: str | None
    actor_user_id: UUID | None
    created_at: datetime


class MonthlyClosureResponse(BaseModel):
    id: UUID | None
    competence: date
    status: Literal["open", "closed"]
    closed_at: datetime | None = None
    reopened_at: datetime | None = None
    closing_note: str | None = None
    reopen_reason: str | None = None
    readiness: MonthlyClosingReadiness
    events: list[MonthlyClosureEventResponse] = []
