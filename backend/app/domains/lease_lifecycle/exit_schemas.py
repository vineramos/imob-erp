from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ExitAdjustmentKind = Literal[
    "damage",
    "cleaning",
    "water",
    "energy",
    "gas",
    "condo_adjustment",
    "iptu_adjustment",
    "key_replacement",
    "other",
]
ExitAdjustmentBeneficiary = Literal["owner", "agency", "third_party"]


class LeaseExitAdjustmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ExitAdjustmentKind
    description: str = Field(min_length=3, max_length=240)
    beneficiary: ExitAdjustmentBeneficiary = "owner"
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    due_date: date
    source_context: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=2000)


class InspectionDifference(BaseModel):
    environment_key: str
    environment_name: str
    item_key: str
    item_label: str
    initial_condition: str
    final_condition: str
    severity_delta: int
    initial_notes: str | None = None
    final_notes: str | None = None


class LeaseExitAdjustmentResponse(BaseModel):
    id: UUID
    code: str
    kind: ExitAdjustmentKind | str
    description: str
    beneficiary: ExitAdjustmentBeneficiary | str
    amount: Decimal
    due_date: date
    status: str
    financial_title_id: UUID | None = None
    financial_title_code: str | None = None
    financial_status: str | None = None
    settled_amount: Decimal
    remaining_amount: Decimal
    source_context: dict[str, Any]
    notes: str | None = None
    cancelled_at: datetime | None = None
    created_at: datetime


class LeaseExitWorkspaceResponse(BaseModel):
    lifecycle_case_id: UUID
    lifecycle_code: str
    lease_contract_id: UUID
    lease_code: str
    lifecycle_status: str
    effective_date: date | None = None
    initiated_by: str | None = None
    property_id: UUID
    property_code: str
    property_address: dict[str, Any]
    tenants: list[dict[str, Any]]
    exit_inspection_id: UUID | None = None
    exit_inspection_code: str | None = None
    exit_inspection_status: str | None = None
    inspection_ready_for_adjustments: bool
    inspection_differences: list[InspectionDifference]
    keys_returned_at: datetime | None = None
    returned_keys: list[dict[str, Any]]
    meter_readings: dict[str, Any]
    adjustments: list[LeaseExitAdjustmentResponse]
    adjustment_open_amount: Decimal
    financial_blocking_count: int
    financial_blocking_amount: Decimal
    financial_followup_count: int
    financial_followup_amount: Decimal
    can_close: bool
    closed_at: datetime | None = None
