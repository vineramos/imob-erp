from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

FundScope = Literal["operating", "third_party"]
PaymentMethod = Literal["pix", "transfer", "boleto", "other"]


class PaymentCandidate(BaseModel):
    target_type: Literal["owner_repasse", "maintenance", "manual"]
    target_id: UUID
    target_code: str
    description: str
    counterparty_name: str
    due_date: date | None
    fund_scope: FundScope
    remaining_amount: float
    overdue: bool


class PaymentBatchCreateItem(BaseModel):
    target_type: Literal["owner_repasse", "maintenance", "manual"]
    target_id: UUID


class PaymentBatchCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    bank_account_id: UUID
    scheduled_date: date
    payment_method: PaymentMethod = "pix"
    notes: str | None = Field(default=None, max_length=2000)
    items: list[PaymentBatchCreateItem] = Field(min_length=1, max_length=200)


class PaymentBatchItemResponse(BaseModel):
    id: UUID
    target_type: str
    target_id: UUID
    target_code: str
    description: str
    counterparty_name: str
    due_date: date | None
    fund_scope: FundScope
    amount: float
    status: str
    bank_transaction_id: UUID | None


class PaymentBatchResponse(BaseModel):
    id: UUID
    code: str
    bank_account_id: UUID
    bank_account_name: str
    name: str
    scheduled_date: date
    fund_scope: FundScope
    payment_method: str
    status: str
    total_amount: float
    item_count: int
    notes: str | None
    provider_batch_id: str | None
    provider_status: str | None
    execution_reference: str | None
    prepared_at: datetime | None
    approved_at: datetime | None
    executed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    items: list[PaymentBatchItemResponse]


class PaymentBatchExecutionRequest(BaseModel):
    execution_date: date
    reference: str | None = Field(default=None, max_length=180)


class CashFlowDay(BaseModel):
    date: date
    receivables: float
    payables: float
    net: float
    projected_balance: float
    receivable_count: int
    payable_count: int


class CashFlowOverview(BaseModel):
    fund_scope: FundScope
    start_date: date
    end_date: date
    current_bank_balance: float
    projected_receivables: float
    projected_payables: float
    projected_end_balance: float
    lowest_projected_balance: float
    lowest_balance_date: date
    overdue_receivables: float
    overdue_payables: float
    days: list[CashFlowDay]
