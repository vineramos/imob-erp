from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


Category = Literal["general", "electrical", "plumbing", "structural", "painting", "appliance", "condominium", "other"]
Priority = Literal["low", "normal", "high", "urgent"]
Responsibility = Literal["pending", "owner", "tenant", "agency"]
Status = Literal["requested", "triage", "awaiting_quote", "awaiting_approval", "approved", "scheduled", "in_progress", "completed", "cancelled"]


class MaintenanceCreate(BaseModel):
    property_id: UUID
    lease_contract_id: UUID | None = None
    requester_person_id: UUID | None = None
    title: str = Field(min_length=3, max_length=180)
    category: Category = "general"
    priority: Priority = "normal"
    description: str = Field(min_length=3, max_length=5000)
    responsibility: Responsibility = "pending"
    approval_required: bool = True
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    scheduled_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5000)


class MaintenanceUpdate(MaintenanceCreate):
    pass


class MaintenancePartnerBase(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    legal_name: str | None = Field(default=None, max_length=220)
    document_number: str | None = Field(default=None, max_length=24)
    contact_name: str | None = Field(default=None, max_length=180)
    email: str | None = Field(default=None, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    whatsapp: str | None = Field(default=None, max_length=40)
    address: dict[str, str] = Field(default_factory=dict)
    specialties: list[str] = Field(default_factory=list, max_length=30)
    pix_key: str | None = Field(default=None, max_length=180)
    bank_details: dict[str, str] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool = True


class MaintenancePartnerCreate(MaintenancePartnerBase):
    pass


class MaintenancePartnerUpdate(MaintenancePartnerBase):
    pass


class MaintenancePartnerResponse(MaintenancePartnerBase):
    id: UUID
    internal_number: int
    code: str
    has_logo: bool
    logo_url: str | None
    created_at: datetime
    updated_at: datetime


class MaintenanceQuoteCreate(BaseModel):
    partner_id: UUID | None = None
    supplier_person_id: UUID | None = None
    supplier_name: str | None = Field(default=None, max_length=180)
    amount: Decimal = Field(gt=0)
    description: str | None = Field(default=None, max_length=3000)
    valid_until: date | None = None
    payment_terms: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def supplier_required(self):
        if not self.partner_id and not self.supplier_person_id and not (self.supplier_name or "").strip():
            raise ValueError("Informe o parceiro cadastrado, fornecedor cadastrado ou nome do fornecedor.")
        return self


class MaintenanceWorkflow(BaseModel):
    action: Literal["triage", "request_quotes", "approve", "schedule", "start", "complete", "cancel", "return_triage"]
    reason: str | None = Field(default=None, max_length=2000)
    scheduled_at: datetime | None = None
    approved_cost: Decimal | None = Field(default=None, ge=0)
    actual_cost: Decimal | None = Field(default=None, ge=0)


class MaintenanceResponse(BaseModel):
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
    supplier_person_id: UUID | None
    supplier_name: str | None
    title: str
    category: Category
    priority: Priority
    status: Status
    description: str
    responsibility: Responsibility
    approval_required: bool
    estimated_cost: Decimal | None
    approved_cost: Decimal | None
    actual_cost: Decimal | None
    selected_quote_id: str | None
    quotes: list[dict]
    history: list[dict]
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
