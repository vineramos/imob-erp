from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

Category = Literal["general", "electrical", "plumbing", "structural", "painting", "appliance", "condominium", "other"]
Priority = Literal["low", "normal", "high", "urgent"]
Responsibility = Literal["pending", "owner", "tenant", "agency"]
Status = Literal["requested", "triage", "awaiting_quote", "awaiting_approval", "approved", "scheduled", "in_progress", "completed", "cancelled"]


class MaintenanceOpenRequest(BaseModel):
    property_id: UUID
    lease_contract_id: UUID | None = None
    requester_person_id: UUID | None = None
    title: str = Field(min_length=3, max_length=180)
    category: Category = "general"
    priority: Priority = "normal"
    description: str = Field(min_length=3, max_length=5000)
    notes: str | None = Field(default=None, max_length=5000)


class MaintenanceEditRequest(MaintenanceOpenRequest):
    responsibility: Responsibility = "pending"


class MaintenanceServiceInput(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    description: str | None = Field(default=None, max_length=3000)
    quantity: Decimal = Field(default=Decimal("1"), gt=0, max_digits=12, decimal_places=3)
    unit: str = Field(default="serviço", min_length=1, max_length=40)


class MaintenanceServiceResponse(MaintenanceServiceInput):
    id: UUID
    created_at: datetime
    created_by_user_id: UUID | None = None


class QuoteServicePrice(BaseModel):
    service_id: UUID
    partner_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    client_price: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class MaintenanceQuoteV2Create(BaseModel):
    partner_id: UUID
    items: list[QuoteServicePrice] = Field(min_length=1)
    valid_until: date | None = None
    payment_terms: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class MaintenanceWorkflowV2(BaseModel):
    action: Literal["triage", "request_quotes", "approve", "schedule", "start", "complete", "cancel", "return_triage"]
    reason: str | None = Field(default=None, max_length=2000)
    scheduled_at: datetime | None = None


class MaintenanceV2Response(BaseModel):
    id: UUID
    internal_number: int
    code: str
    property_id: UUID
    property_code: str
    property_title: str
    property_address: dict
    lease_contract_id: UUID | None
    lease_code: str | None
    requester_person_id: UUID | None
    requester_name: str | None
    title: str
    category: Category
    priority: Priority
    status: Status
    description: str
    responsibility: Responsibility
    services: list[dict]
    selected_quote_id: str | None
    quotes: list[dict]
    history: list[dict]
    partner_cost_total: Decimal | None
    client_charge_total: Decimal | None
    margin_total: Decimal | None
    finance_status: str | None
    reported_at: datetime
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    approved_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
