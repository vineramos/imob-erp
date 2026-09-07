from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class GenerateChargesRequest(BaseModel):
    competence: date
    lease_contract_id: UUID | None = None

    @field_validator("competence")
    @classmethod
    def normalize_competence(cls, value: date) -> date:
        return value.replace(day=1)


class ChargePaymentRequest(BaseModel):
    paid_amount: Decimal = Field(gt=0)
    paid_at: datetime | None = None
    payment_method: Literal["pix", "boleto", "transfer", "cash", "other"] = "pix"
    payment_reference: str | None = Field(default=None, max_length=180)
    notes: str | None = Field(default=None, max_length=1000)


class ChargeCancellationRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class RepassePaymentRequest(BaseModel):
    paid_at: datetime | None = None
    payment_reference: str | None = Field(default=None, max_length=180)
    notes: str | None = Field(default=None, max_length=1000)


class ChargeItem(BaseModel):
    key: str
    kind: str = "other"
    label: str
    amount: Decimal
    payer: str = "tenant"
    beneficiary: Literal["owner", "agency", "third_party"]
    beneficiary_name: str | None = None
    frequency: Literal["monthly", "annual", "one_time"] = "monthly"
    include_in_invoice: bool = True
    agency_retention_type: Literal["none", "percent", "fixed"] = "none"
    agency_retention_value: Decimal = Decimal("0.00")
    agency_retention_amount: Decimal = Decimal("0.00")
    third_party_net_amount: Decimal = Decimal("0.00")
    source: str | None = None


class RepasseResponse(BaseModel):
    id: UUID
    charge_id: UUID
    charge_code: str
    lease_contract_id: UUID
    lease_code: str
    property_id: UUID
    property_code: str
    competence: date
    owner_person_id: UUID
    owner_name: str
    ownership_percent: Decimal
    amount: Decimal
    due_date: date
    status: str
    paid_at: datetime | None
    payment_reference: str | None


class SettlementResponse(BaseModel):
    id: UUID
    administration_contract_id: UUID | None
    admin_fee_calculated: Decimal
    intermediation_fee_calculated: Decimal
    agency_fee_withheld: Decimal
    agency_reimbursement_amount: Decimal
    agency_retention_amount: Decimal
    owner_entitlement_amount: Decimal
    third_party_amount: Decimal
    calculated_at: datetime
    repasses: list[RepasseResponse]


class ChargeResponse(BaseModel):
    id: UUID
    code: str
    lease_contract_id: UUID
    lease_code: str
    property_id: UUID
    property_code: str
    property_address: dict[str, Any]
    tenants: list[dict[str, Any]]
    owners: list[dict[str, Any]]
    competence: date
    due_date: date
    status: str
    days_overdue: int
    critical_overdue: bool
    rent_amount: Decimal
    gross_amount: Decimal
    charge_items: list[ChargeItem]
    sent_at: datetime | None
    paid_at: datetime | None
    paid_amount: Decimal | None
    payment_method: str | None
    payment_reference: str | None
    settlement: SettlementResponse | None
    created_at: datetime


class GenerateChargesResponse(BaseModel):
    competence: date
    generated: int
    skipped_existing: int
    skipped_ineligible: int
    charges: list[ChargeResponse]


class FinanceDashboardResponse(BaseModel):
    competence: date
    open_amount: Decimal
    overdue_amount: Decimal
    critical_overdue_amount: Decimal
    received_amount: Decimal
    agency_revenue_amount: Decimal
    pending_repasse_amount: Decimal
    charges_open: int
    charges_overdue: int
    charges_critical: int
    repasses_pending: int


class OwnerStatementLine(BaseModel):
    repasse_id: UUID
    charge_code: str
    lease_code: str
    property_code: str
    property_address: dict[str, Any]
    competence: date
    paid_at: datetime
    gross_charge: Decimal
    rent_amount: Decimal
    admin_fee: Decimal
    intermediation_fee: Decimal
    owner_total_before_share: Decimal
    ownership_percent: Decimal
    repasse_amount: Decimal
    repasse_due_date: date
    repasse_status: str
    repasse_paid_at: datetime | None


class OwnerStatementResponse(BaseModel):
    owner_person_id: UUID
    owner_name: str
    competence: date
    property_id: UUID | None
    total_received_from_tenants: Decimal
    total_agency_fees: Decimal
    total_owner_entitlement: Decimal
    total_repasse: Decimal
    total_repasse_paid: Decimal
    lines: list[OwnerStatementLine]

    @model_validator(mode="after")
    def apply_owner_share_to_entitlement(self):
        # A liquidação guarda o direito econômico total do imóvel antes do rateio.
        # Na prestação individual, esse total precisa respeitar a participação do
        # proprietário. O repasse pode ser menor depois de deduções operacionais,
        # por isso não deve ser usado como sinônimo do direito econômico original.
        self.total_owner_entitlement = sum(
            (
                (line.owner_total_before_share * line.ownership_percent / Decimal("100"))
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                for line in self.lines
            ),
            Decimal("0.00"),
        )
        return self


class PropertyFinanceSummary(BaseModel):
    property_id: UUID
    open_amount: Decimal
    overdue_amount: Decimal
    received_amount: Decimal
    pending_repasse_amount: Decimal
    next_due_date: date | None
    last_payment_at: datetime | None
    critical_overdue: bool
