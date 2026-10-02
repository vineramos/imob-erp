from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

DelinquencyStatus = Literal["open", "contacted", "insurer_triggered", "negotiating", "resolved"]
ContactChannel = Literal["phone", "whatsapp", "email", "other"]
GuaranteeWorkflowStatus = Literal[
    "not_applicable",
    "available",
    "prepared",
    "submitted",
    "under_review",
    "approved",
    "rejected",
    "received",
    "cancelled",
]


class DelinquencyActionRequest(BaseModel):
    status: DelinquencyStatus
    channel: ContactChannel | None = None
    notes: str | None = Field(default=None, max_length=4000)
    insurer_protocol: str | None = Field(default=None, max_length=180)
    next_action_at: datetime | None = None


class DelinquencyPromiseRequest(BaseModel):
    due_date: date
    amount: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=4000)


class DelinquencyGuaranteeRequest(BaseModel):
    status: GuaranteeWorkflowStatus
    provider_name: str | None = Field(default=None, max_length=180)
    policy_number: str | None = Field(default=None, max_length=180)
    protocol: str | None = Field(default=None, max_length=180)
    claimed_amount: float | None = Field(default=None, gt=0)
    approved_amount: float | None = Field(default=None, ge=0)
    received_amount: float | None = Field(default=None, ge=0)
    payment_reference: str | None = Field(default=None, max_length=180)
    notes: str | None = Field(default=None, max_length=4000)
    next_action_at: datetime | None = None


class DelinquencyTenantContact(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None


class DelinquencyWorkflowResponse(BaseModel):
    guarantee_type: str
    guarantee_label: str
    guarantee_provider_name: str | None
    guarantee_policy_number: str | None
    guarantee_status: str
    guarantee_protocol: str | None
    claimed_amount: float | None
    approved_amount: float | None
    received_amount: float | None
    guarantee_submitted_at: datetime | None
    guarantee_approved_at: datetime | None
    guarantee_received_at: datetime | None
    guarantee_rejected_at: datetime | None
    guarantee_payment_reference: str | None
    promise_amount: float | None
    promise_due_date: date | None
    promise_status: str | None
    promise_recorded_at: datetime | None
    promise_broken_at: datetime | None
    notes: str | None
    external_submission_performed: bool = False


class DelinquencyCaseResponse(BaseModel):
    id: UUID
    code: str
    charge_id: UUID
    charge_code: str
    lease_contract_id: UUID
    lease_code: str
    property_id: UUID
    property_code: str
    tenant_name: str
    tenant_contacts: list[DelinquencyTenantContact]
    due_date: date
    amount: float
    days_overdue: int
    first_contact_after_days: int
    followup_after_days: int
    critical_after_days: int
    critical: bool
    status: str
    suggested_action: str | None
    insurer_protocol: str | None
    assigned_user_id: UUID | None
    pending_agenda_tasks: int
    opened_at: datetime
    critical_at: datetime | None
    last_contact_at: datetime | None
    next_action_at: datetime | None
    insurer_triggered_at: datetime | None
    resolved_at: datetime | None
    notes: str | None
    action_log: list[dict[str, Any]]
    workflow: DelinquencyWorkflowResponse


class DelinquencyOverviewResponse(BaseModel):
    open_cases: int
    critical_cases: int
    overdue_amount: float
    critical_amount: float
    promises_pending: int
    promises_broken: int
    guarantees_available: int
    guarantees_submitted: int
    guarantees_received: int
    guarantees_received_amount: float
