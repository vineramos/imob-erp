from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MaintenanceEntryResponse(BaseModel):
    id: UUID
    direction: Literal["payable", "receivable"]
    status: str
    counterparty_type: str
    counterparty_name: str
    responsibility: str
    collection_method: str | None
    amount: Decimal
    settled_amount: Decimal
    remaining_amount: Decimal
    margin_amount: Decimal
    due_date: date | None
    settled_at: datetime | None
    payment_reference: str | None


class MaintenanceFinanceCase(BaseModel):
    maintenance_id: UUID
    maintenance_code: str
    property_id: UUID
    property_code: str
    property_title: str
    title: str
    responsibility: str
    quote_code: str | None
    partner_name: str | None
    partner_cost: Decimal
    client_charge: Decimal
    margin: Decimal
    completed_at: datetime | None
    payable: MaintenanceEntryResponse | None
    receivable: MaintenanceEntryResponse | None


class MaintenanceFinanceDashboard(BaseModel):
    payable_pending: Decimal
    receivable_pending: Decimal
    expected_margin: Decimal
    settled_payables: Decimal
    settled_receivables: Decimal
    cases: list[MaintenanceFinanceCase]


class MaintenanceEntrySettlementRequest(BaseModel):
    settled_at: datetime | None = None
    payment_reference: str | None = Field(default=None, max_length=180)
    notes: str | None = Field(default=None, max_length=1000)
