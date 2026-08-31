from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


Direction = Literal["receivable", "payable"]
FundScope = Literal["operating", "third_party"]


class ManualFinancialTitleCreate(BaseModel):
    direction: Direction
    fund_scope: FundScope = "operating"
    category: str = Field(default="Outros", min_length=2, max_length=100)
    description: str = Field(min_length=3, max_length=240)
    counterparty_name: str = Field(min_length=2, max_length=220)
    competence: date
    due_date: date
    amount: Decimal = Field(gt=0)
    property_id: UUID | None = None
    lease_contract_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("competence")
    @classmethod
    def normalize_competence(cls, value: date) -> date:
        return value.replace(day=1)


class ManualFinancialSettlementRequest(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    settled_at: datetime | None = None
    payment_method: Literal["pix", "boleto", "transfer", "cash", "card", "other"] = "pix"
    payment_reference: str | None = Field(default=None, max_length=180)
    notes: str | None = Field(default=None, max_length=2000)


class ManualFinancialCancellationRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class FinanceCoreItem(BaseModel):
    id: UUID
    code: str
    source_type: str
    source_id: UUID
    direction: Direction
    fund_scope: FundScope
    category: str
    description: str
    counterparty_name: str
    property_id: UUID | None
    lease_contract_id: UUID | None
    competence: date
    due_date: date | None
    amount: Decimal
    settled_amount: Decimal
    remaining_amount: Decimal
    margin_amount: Decimal
    status: str
    overdue: bool
    settled_at: datetime | None
    payment_method: str | None
    payment_reference: str | None
    manual: bool


class FinanceCoreOverview(BaseModel):
    competence: date
    receivable_open_amount: Decimal
    payable_open_amount: Decimal
    overdue_receivable_amount: Decimal
    overdue_payable_amount: Decimal
    received_amount: Decimal
    paid_amount: Decimal
    operating_open_amount: Decimal
    third_party_open_amount: Decimal
    receivable_open_count: int
    payable_open_count: int
    overdue_count: int
    items: list[FinanceCoreItem]
