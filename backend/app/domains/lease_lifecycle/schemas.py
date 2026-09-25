from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

LifecycleProcessType = Literal["renewal", "termination"]
LifecycleStatus = Literal[
    "renewal_proposed",
    "renewal_prepared",
    "renewed",
    "termination_requested",
    "exit_inspection_pending",
    "key_return_pending",
    "financial_clearance_pending",
    "closed",
    "cancelled",
]
InitiatedBy = Literal["tenant", "owner", "mutual", "term_end", "breach", "other"]
FineStatus = Literal["not_applicable", "pending", "waived", "registered"]
PropertyDisposition = Literal["available", "inactive"]


class RenewalProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date
    term_months: int = Field(default=30, ge=1, le=240)
    rent_amount: Decimal = Field(gt=0)
    adjustment_index: str = Field(default="IPCA", min_length=2, max_length=30)
    adjustment_period_months: int = Field(default=12, ge=1, le=36)
    notes: str | None = Field(default=None, max_length=3000)


class TerminationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_date: date
    initiated_by: InitiatedBy
    reason: str = Field(min_length=3, max_length=3000)


class ExitInspectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: datetime | None = None
    inspector_name: str | None = Field(default=None, max_length=180)
    notes: str | None = Field(default=None, max_length=2000)


class ReturnedKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=50)
    notes: str | None = Field(default=None, max_length=500)


class KeyReturnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    returned_at: datetime
    received_by: str = Field(min_length=2, max_length=180)
    received_document: str | None = Field(default=None, max_length=30)
    keys: list[ReturnedKey] = Field(min_length=1, max_length=30)
    meter_readings: dict = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=2000)


class FineResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["waive", "register"]
    beneficiary: Literal["owner", "agency"] | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_registration(self):
        if self.action == "register" and self.beneficiary is None:
            raise ValueError("Informe o beneficiário da multa.")
        return self


class CloseLeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_disposition: PropertyDisposition = "available"
    notes: str | None = Field(default=None, max_length=2000)


class FinancialClearanceItem(BaseModel):
    id: UUID
    code: str
    source_type: str
    direction: Literal["receivable", "payable"]
    description: str
    amount: Decimal
    remaining_amount: Decimal
    status: str
    blocker: bool


class FinancialClearance(BaseModel):
    blocking_count: int
    blocking_amount: Decimal
    followup_count: int
    followup_amount: Decimal
    items: list[FinancialClearanceItem]


class LeaseLifecycleResponse(BaseModel):
    id: UUID
    code: str
    lease_contract_id: UUID
    lease_code: str
    property_id: UUID
    process_type: LifecycleProcessType
    status: LifecycleStatus
    initiated_by: InitiatedBy | None = None
    requested_at: datetime
    effective_date: date | None = None
    reason: str | None = None
    termination_fine_amount: Decimal
    fine_status: FineStatus
    fine_title_id: UUID | None = None
    fine_notes: str | None = None
    renewal_terms: dict
    renewed_lease_contract_id: UUID | None = None
    renewed_lease_code: str | None = None
    renewed_lease_status: str | None = None
    exit_inspection_id: UUID | None = None
    exit_inspection_code: str | None = None
    exit_inspection_status: str | None = None
    keys_returned_at: datetime | None = None
    keys_received_by: str | None = None
    returned_keys: list[dict]
    meter_readings: dict
    key_return_notes: str | None = None
    property_disposition: PropertyDisposition | None = None
    financial_clearance: FinancialClearance
    can_close: bool
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
