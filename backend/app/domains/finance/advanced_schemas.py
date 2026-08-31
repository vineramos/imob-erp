from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

FundScope = Literal["operating", "third_party"]
PortalType = Literal["owner", "tenant"]


class BillingRunRequest(BaseModel):
    competence: date


class BillingIssueRequest(BaseModel):
    bank_account_id: UUID


class BillingItemResponse(BaseModel):
    id: UUID
    charge_id: UUID
    charge_code: str
    lease_code: str
    property_code: str
    tenant_name: str
    due_date: date
    amount: float
    charge_status: str
    provider: str
    provider_charge_id: str | None
    provider_status: str | None
    boleto_line: str | None
    pix_copy_paste: str | None
    issued_at: datetime | None
    sent_at: datetime | None
    confirmed_at: datetime | None
    last_error: str | None


class BillingBatchResponse(BaseModel):
    id: UUID
    code: str
    competence: date
    status: str
    provider: str
    generated_count: int
    issued_count: int
    sent_count: int
    confirmed_count: int
    error_count: int
    started_at: datetime
    completed_at: datetime | None
    items: list[BillingItemResponse]


class BillingRunResponse(BaseModel):
    generated: int
    skipped_existing: int
    skipped_ineligible: int
    batch: BillingBatchResponse


class DelinquencyActionRequest(BaseModel):
    status: Literal["open", "contacted", "insurer_triggered", "negotiating", "resolved"]
    notes: str | None = Field(default=None, max_length=4000)
    insurer_protocol: str | None = Field(default=None, max_length=180)
    next_action_at: datetime | None = None


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
    due_date: date
    amount: float
    days_overdue: int
    critical: bool
    status: str
    insurer_protocol: str | None
    opened_at: datetime
    critical_at: datetime | None
    last_contact_at: datetime | None
    next_action_at: datetime | None
    insurer_triggered_at: datetime | None
    resolved_at: datetime | None
    notes: str | None
    action_log: list[dict[str, Any]]


class CommissionRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    event_type: Literal["first_rent", "recurring", "intermediation"] = "first_rent"
    basis: Literal["rent", "administration_fee", "intermediation_fee", "agency_revenue"] = "agency_revenue"
    calculation_type: Literal["percent", "fixed"] = "percent"
    value: float = Field(gt=0)
    beneficiary_type: Literal["broker", "referrer", "supplier", "other"] = "broker"
    beneficiary_person_id: UUID
    property_id: UUID | None = None
    lease_contract_id: UUID | None = None
    due_days: int = Field(default=0, ge=0, le=180)
    priority: int = Field(default=100, ge=0, le=9999)
    notes: str | None = Field(default=None, max_length=2000)


class CommissionRuleUpdate(CommissionRuleCreate):
    is_active: bool = True


class CommissionRuleResponse(BaseModel):
    id: UUID
    code: str
    name: str
    event_type: str
    basis: str
    calculation_type: str
    value: float
    beneficiary_type: str
    beneficiary_person_id: UUID
    beneficiary_name: str
    property_id: UUID | None
    lease_contract_id: UUID | None
    due_days: int
    priority: int
    is_active: bool
    notes: str | None
    created_at: datetime


class CommissionEntryResponse(BaseModel):
    id: UUID
    code: str
    rule_id: UUID
    source_type: str
    source_id: UUID
    source_code: str
    beneficiary_type: str
    beneficiary_person_id: UUID
    beneficiary_name: str
    competence: date
    basis_amount: float
    amount: float
    due_date: date
    status: str
    financial_title_id: UUID | None
    paid_at: datetime | None
    payment_reference: str | None
    created_at: datetime


class DreLine(BaseModel):
    key: str
    label: str
    kind: Literal["revenue", "expense"]
    amount: float


class DreReport(BaseModel):
    start_date: date
    end_date: date
    regime: Literal["cash", "competence"]
    total_revenue: float
    total_expenses: float
    result: float
    margin_percent: float
    lines: list[DreLine]


class FinanceReportOverview(BaseModel):
    start_date: date
    end_date: date
    tenant_collections: float
    agency_revenue: float
    owner_repasses: float
    maintenance_revenue: float
    maintenance_cost: float
    commissions: float
    overdue_amount: float
    overdue_count: int
    paid_charges: int
    open_charges: int


class AnnualIncomeLine(BaseModel):
    competence: date
    payment_date: date | None
    property_code: str
    charge_code: str
    rent_amount: float
    additional_charges: float
    total_amount: float
    administration_fee: float
    owner_net_amount: float


class AnnualIncomeReport(BaseModel):
    year: int
    party_type: PortalType
    person_id: UUID
    person_name: str
    allocation_method: str
    total_rent: float
    total_additional_charges: float
    total_paid: float
    total_administration_fee: float
    total_owner_net: float
    lines: list[AnnualIncomeLine]


class PortalAccessCreate(BaseModel):
    person_id: UUID
    portal_type: PortalType
    label: str | None = Field(default=None, max_length=160)
    expires_days: int = Field(default=90, ge=1, le=730)


class PortalAccessResponse(BaseModel):
    id: UUID
    person_id: UUID
    person_name: str
    portal_type: PortalType
    label: str | None
    is_active: bool
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class PortalAccessCreated(PortalAccessResponse):
    token: str
    path: str


class PortalCharge(BaseModel):
    id: UUID
    code: str
    competence: date
    due_date: date
    property_code: str
    amount: float
    status: str
    paid_at: datetime | None
    boleto_line: str | None
    pix_copy_paste: str | None


class PortalRepasse(BaseModel):
    id: UUID
    competence: date
    property_code: str
    amount: float
    due_date: date
    status: str
    paid_at: datetime | None


class PortalProperty(BaseModel):
    id: UUID
    code: str
    address: dict[str, Any]
    ownership_percent: float | None = None


class PortalPayload(BaseModel):
    organization_name: str
    portal_type: PortalType
    person_id: UUID
    person_name: str
    expires_at: datetime
    properties: list[PortalProperty]
    charges: list[PortalCharge]
    repasses: list[PortalRepasse]
    current_year_total: float
    open_amount: float


class InterStatusResponse(BaseModel):
    configured: bool
    environment: str
    client_id_configured: bool
    certificate_configured: bool
    account_header_configured: bool
    billing_api: str
    banking_api: str


class InterSyncResponse(BaseModel):
    account_id: UUID
    start_date: date
    end_date: date
    created: int
    duplicates: int
    external_balance: float | None
    synced_at: datetime
