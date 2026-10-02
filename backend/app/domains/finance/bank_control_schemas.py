from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DailyClosePreviewRequest(BaseModel):
    bank_account_id: UUID
    closing_date: date
    bank_balance: float | None = None


class DailyCloseCreate(DailyClosePreviewRequest):
    notes: str | None = Field(default=None, max_length=2000)


class DailyClosePreview(BaseModel):
    bank_account_id: UUID
    bank_account_name: str
    closing_date: date
    fund_scope: Literal["operating", "third_party"]
    provider: str
    erp_balance: float
    bank_balance: float
    difference: float
    pending_transactions_count: int
    balance_source: Literal["manual", "provider"]
    can_close: bool
    message: str


class DailyCloseResponse(DailyClosePreview):
    id: UUID
    code: str
    status: str
    notes: str | None
    closed_at: datetime


class ProviderCapabilityResponse(BaseModel):
    bank_account_id: UUID
    bank_account_name: str
    provider: str
    configured: bool
    statement: bool
    balance: bool
    billing: bool
    pix_payment: bool


class ProviderPaymentInstructionResponse(BaseModel):
    id: UUID
    payment_batch_item_id: UUID
    target_code: str
    recipient_name: str
    amount: float
    provider: str
    provider_reference: str | None
    provider_status: str
    last_error: str | None
    submitted_at: datetime | None
    confirmed_at: datetime | None


class ProviderPaymentBatchResponse(BaseModel):
    payment_batch_id: UUID
    batch_code: str
    batch_status: str
    provider: str
    provider_status: str | None
    instructions: list[ProviderPaymentInstructionResponse]
