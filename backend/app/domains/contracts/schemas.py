from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


AdministrationContractStatus = Literal[
    "draft", "review", "approved", "pending_signature", "signed", "cancelled"
]
AdministrationPlan = Literal["essential", "complete", "custom"]
FeeType = Literal["percent", "fixed"]
OperationalPayer = Literal["tenant", "owner", "agency"]
WorkflowAction = Literal["submit_review", "approve", "prepare_signature", "return_draft", "cancel"]
SignerRole = Literal["owner", "tenant", "agency", "witness", "other"]
SignerCommunication = Literal["email", "sms", "whatsapp", "none"]


class ContractSignerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: SignerRole = "owner"
    person_id: UUID | None = None
    name: str = Field(min_length=3, max_length=180)
    email: EmailStr
    document_number: str | None = Field(default=None, max_length=24)
    phone: str | None = Field(default=None, max_length=40)
    sign_order: int = Field(default=1, ge=1, le=50)
    communication: SignerCommunication = "email"


class AdministrationContractTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: AdministrationPlan = "essential"
    admin_fee_type: FeeType = "percent"
    admin_fee_percent: Decimal | None = Field(default=None, ge=0, le=100)
    admin_fee_amount: Decimal | None = Field(default=None, ge=0)
    intermediation_percent: Decimal = Field(default=Decimal("100"), ge=0, le=500)
    intermediation_installments: int = Field(default=1, ge=1, le=24)
    owner_repasse_business_days: int = Field(default=2, ge=0, le=30)
    condo_operational_payer: OperationalPayer = "tenant"
    iptu_operational_payer: OperationalPayer = "tenant"
    publication_requires_owner_approval: bool = False
    maintenance_limit_amount: Decimal | None = Field(default=None, ge=0)
    emergency_limit_amount: Decimal | None = Field(default=None, ge=0)
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    signers: list[ContractSignerPayload] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_fee_dates_and_signers(self):
        if self.admin_fee_type == "percent" and self.admin_fee_percent is None:
            raise ValueError("Informe o percentual da taxa de administração.")
        if self.admin_fee_type == "fixed" and self.admin_fee_amount is None:
            raise ValueError("Informe o valor fixo da taxa de administração.")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("A data final não pode ser anterior à data inicial.")
        normalized_emails = [str(signer.email).strip().lower() for signer in self.signers]
        if len(normalized_emails) != len(set(normalized_emails)):
            raise ValueError("Não repita o mesmo e-mail na lista de signatários.")
        return self


class AdministrationContractCreate(AdministrationContractTerms):
    property_id: UUID


class AdministrationContractUpdate(AdministrationContractTerms):
    change_summary: str = Field(min_length=3, max_length=500)


class AdministrationContractWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: WorkflowAction
    reason: str | None = Field(default=None, max_length=1000)


class AdministrationContractVersionResponse(BaseModel):
    version_number: int
    change_summary: str | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime


class SignatureEventResponse(BaseModel):
    id: UUID
    provider: str
    event_name: str
    envelope_id: str | None = None
    hmac_valid: bool
    received_at: datetime


class ContractDocumentResponse(BaseModel):
    contract_id: UUID
    code: str
    version: int
    hash_sha256: str
    reference: str | None = None
    storage_configured: bool
    message: str


class AdministrationContractResponse(BaseModel):
    id: UUID
    internal_number: int
    code: str
    property_id: UUID
    property_code: str
    property_address: dict
    owners: list[dict]
    status: AdministrationContractStatus
    plan: AdministrationPlan
    admin_fee_type: FeeType
    admin_fee_percent: Decimal | None = None
    admin_fee_amount: Decimal | None = None
    intermediation_percent: Decimal
    intermediation_installments: int
    owner_repasse_business_days: int
    condo_operational_payer: OperationalPayer
    iptu_operational_payer: OperationalPayer
    publication_requires_owner_approval: bool
    maintenance_limit_amount: Decimal | None = None
    emergency_limit_amount: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
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
    versions: list[AdministrationContractVersionResponse]
    created_at: datetime
    updated_at: datetime
