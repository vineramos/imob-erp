from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

FundScope = Literal["operating", "third_party"]
BankDirection = Literal["credit", "debit"]


class BankAccountCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    bank_name: str = Field(min_length=2, max_length=120)
    bank_code: str | None = Field(default=None, max_length=10)
    branch: str | None = Field(default=None, max_length=30)
    account_number: str | None = Field(default=None, max_length=40)
    account_digit: str | None = Field(default=None, max_length=10)
    account_type: Literal["checking", "savings", "payment", "other"] = "checking"
    fund_scope: FundScope = "operating"
    provider: str = Field(default="manual", min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    provider_account_id: str | None = Field(default=None, max_length=120)
    pix_key: str | None = Field(default=None, max_length=180)
    opening_balance: Decimal = Decimal("0.00")


class BankProviderCapabilitiesResponse(BaseModel):
    statement: bool
    balance: bool
    billing: bool
    pix_payment: bool


class BankProviderResponse(BaseModel):
    key: str
    name: str
    direct_integration: bool
    capabilities: BankProviderCapabilitiesResponse


class BankAccountResponse(BaseModel):
    id: UUID
    code: str
    name: str
    bank_name: str
    bank_code: str | None
    branch: str | None
    account_number: str | None
    account_digit: str | None
    account_type: str
    fund_scope: FundScope
    provider: str
    pix_key: str | None
    opening_balance: Decimal
    current_balance: Decimal
    is_active: bool
    last_sync_at: datetime | None
    created_at: datetime


class BankReconciliationResponse(BaseModel):
    id: UUID
    target_type: str
    target_id: UUID
    target_code: str
    target_direction: str
    amount: Decimal
    notes: str | None
    reconciled_at: datetime


class BankTransactionCreate(BaseModel):
    transaction_date: date
    direction: BankDirection
    amount: Decimal = Field(gt=0)
    description: str = Field(min_length=2, max_length=300)
    document: str | None = Field(default=None, max_length=120)
    counterparty_name: str | None = Field(default=None, max_length=220)
    bank_reference: str | None = Field(default=None, max_length=180)


class BankTransactionResponse(BaseModel):
    id: UUID
    code: str
    bank_account_id: UUID
    transaction_date: date
    posted_at: datetime | None
    direction: BankDirection
    amount: Decimal
    description: str
    document: str | None
    counterparty_name: str | None
    bank_reference: str | None
    balance_after: Decimal | None
    source: str
    status: str
    reconciled_amount: Decimal
    remaining_amount: Decimal
    reconciliations: list[BankReconciliationResponse]
    created_at: datetime


class BankImportResponse(BaseModel):
    import_id: UUID
    filename: str
    source: str
    total_rows: int
    created_rows: int
    duplicate_rows: int


class BankImportHistoryItem(BaseModel):
    import_id: UUID
    filename: str
    source: str
    total_rows: int
    created_rows: int
    duplicate_rows: int
    imported_at: datetime


class BankReconciliationSummary(BaseModel):
    pending_count: int
    routine_count: int
    exception_count: int
    ignored_count: int
    deterministic_count: int
    strong_candidate_count: int
    ambiguous_count: int
    review_required_count: int
    no_candidate_count: int


class ReconciliationCandidate(BaseModel):
    target_type: str
    target_id: UUID
    target_code: str
    direction: Literal["receivable", "payable"]
    fund_scope: FundScope
    description: str
    counterparty_name: str
    due_date: date | None
    remaining_amount: Decimal
    transaction_remaining_amount: Decimal = Decimal("0.00")
    suggested_allocation: Decimal = Decimal("0.00")
    difference_amount: Decimal = Decimal("0.00")
    difference_kind: Literal["exact", "bank_excess", "title_exceeds_bank"] = "exact"
    settlement_compatible: bool = True
    score: int
    identifier_match: bool = False
    matched_identifier: str | None = None


class BankReconciliationException(BaseModel):
    id: UUID
    transaction_id: UUID
    transaction_code: str
    transaction_date: date
    direction: BankDirection
    amount: Decimal
    remaining_amount: Decimal
    description: str
    bank_reference: str | None
    reason: Literal[
        "ambiguous_identifier",
        "identifier_detected",
        "strong_candidate",
        "review_required",
        "no_candidate",
    ]
    severity: Literal["routine", "exception"]
    status: Literal["open", "ignored", "resolved"]
    reason_label: str
    candidate_count: int
    top_candidate_code: str | None = None
    top_candidate_score: int | None = None
    matched_identifier: str | None = None
    resolution_note: str | None = None
    resolved_at: datetime | None = None
    updated_at: datetime


class BankReconciliationExceptionAction(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class BankResidualAdjustmentCreate(BaseModel):
    category: Literal["bank_fee", "interest", "penalty", "discount", "revenue", "expense", "adjustment"]
    description: str = Field(min_length=3, max_length=240)
    amount: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)


class BankExceptionResolveRequest(BaseModel):
    target_type: Literal["rent", "owner_repasse", "maintenance", "manual", "financial_title"]
    target_id: UUID
    amount: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)


class BankReconciliationRequest(BaseModel):
    target_type: Literal["rent", "owner_repasse", "maintenance", "manual", "financial_title"]
    target_id: UUID
    amount: Decimal | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=1000)


class BankingOverview(BaseModel):
    account: BankAccountResponse
    competence: date
    credits_amount: Decimal
    debits_amount: Decimal
    pending_credits_amount: Decimal
    pending_debits_amount: Decimal
    reconciled_amount: Decimal
    pending_count: int
    reconciled_count: int
    transactions: list[BankTransactionResponse]
