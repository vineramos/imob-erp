from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

AdjustmentIndex = Literal["IPCA", "IGP-M", "INPC", "IPC-FIPE", "IGP-DI"]
GuaranteeType = Literal["insurance", "deposit", "capitalization", "guarantor", "none"]
LeaseStatus = Literal["draft", "review", "approved", "pending_signature", "signed", "cancelled"]
LeaseWorkflowAction = Literal["submit_review", "approve", "prepare_signature", "return_draft", "cancel"]
LeaseSignerRole = Literal["owner", "tenant", "agency", "witness", "other"]
SignerCommunication = Literal["email", "sms", "whatsapp", "none"]


class LeaseSignerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: LeaseSignerRole
    name: str = Field(min_length=2, max_length=180)
    email: EmailStr | Literal[""] = ""
    document_number: str | None = Field(default=None, max_length=24)
    phone: str | None = Field(default=None, max_length=40)
    sign_order: int = Field(default=1, ge=1, le=50)
    communication: SignerCommunication = "email"


class LeaseContractTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rent_amount: Decimal = Field(gt=0)
    due_day: int = Field(default=10, ge=1, le=28)
    adjustment_index: AdjustmentIndex = "IPCA"
    adjustment_period_months: int = Field(default=12, ge=1, le=36)
    adjustment_base_date: date
    next_adjustment_date: date
    term_months: int = Field(default=30, ge=1, le=240)
    start_date: date
    end_date: date
    termination_fine_months: Decimal = Field(default=Decimal("3"), ge=0, le=12)
    inspection_contest_days: int = Field(default=5, ge=1, le=30)
    guarantee_type: GuaranteeType = "insurance"
    guarantee_details: dict = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=4000)
    signers: list[LeaseSignerPayload] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_dates_and_signers(self):
        if self.end_date <= self.start_date:
            raise ValueError("A data final precisa ser posterior ao início do contrato.")
        if self.next_adjustment_date <= self.adjustment_base_date:
            raise ValueError("O próximo reajuste precisa ser posterior à data-base.")
        normalized_emails = [str(signer.email).strip().lower() for signer in self.signers]
        if len(normalized_emails) != len(set(normalized_emails)):
            raise ValueError("Não repita o mesmo e-mail na lista de signatários.")
        return self


class LeaseContractCreate(LeaseContractTerms):
    property_id: UUID
    tenant_ids: list[UUID] = Field(min_length=1, max_length=10)


class LeaseContractUpdate(LeaseContractTerms):
    tenant_ids: list[UUID] = Field(min_length=1, max_length=10)
    change_summary: str = Field(min_length=3, max_length=500)


class LeaseContractWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: LeaseWorkflowAction
    reason: str | None = Field(default=None, max_length=1000)


class LeaseContractVersionResponse(BaseModel):
    version_number: int
    change_summary: str | None = None
    created_at: datetime


class LeaseContractResponse(BaseModel):
    id: UUID
    internal_number: int
    code: str
    property_id: UUID
    property_code: str
    property_address: dict
    owners: list[dict]
    tenants: list[dict]
    status: LeaseStatus
    rent_amount: Decimal
    due_day: int
    adjustment_index: AdjustmentIndex
    adjustment_period_months: int
    adjustment_base_date: date
    next_adjustment_date: date
    term_months: int
    start_date: date
    end_date: date
    termination_fine_months: Decimal
    inspection_contest_days: int
    guarantee_type: GuaranteeType
    guarantee_details: dict
    notes: str | None = None
    signers: list[dict]
    current_version: int
    generated_document_reference: str | None = None
    generated_document_hash: str | None = None
    generated_document_version: int | None = None
    signing_provider: str
    signing_status: str
    signing_envelope_id: str | None = None
    signing_document_id: str | None = None
    approved_at: datetime | None = None
    signed_at: datetime | None = None
    archive_status: str
    archived_document_reference: str | None = None
    final_document_hash: str | None = None
    archived_at: datetime | None = None
    versions: list[LeaseContractVersionResponse]
    created_at: datetime
    updated_at: datetime
