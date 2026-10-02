from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

FundScope = Literal["operating", "third_party"]
AccountPurpose = Literal["operating", "rent_receipts_repasses", "security_deposits", "taxes", "other"]
IntegrationMode = Literal["manual", "import", "cnab", "api"]
IntegrationEnvironment = Literal["manual", "sandbox", "production"]
AccountType = Literal["checking", "savings", "payment", "other"]


class BankInstitutionResponse(BaseModel):
    key: str
    name: str
    bank_code: str | None
    ispb: str | None = None
    provider_key: str
    api_status: str
    account_scoped_api: bool
    implemented_capabilities: list[str]
    supported_integration_modes: list[str]


class BankAccountCoreResponse(BaseModel):
    id: UUID
    code: str
    name: str
    bank_name: str
    bank_code: str | None
    branch: str | None
    account_number: str | None
    account_digit: str | None
    account_type: str
    fund_scope: FundScope
    core_provider: str
    pix_key: str | None
    opening_balance: Decimal
    current_balance: Decimal
    is_active: bool
    last_sync_at: datetime | None
    created_at: datetime


class BankAccountSetupResponse(BaseModel):
    id: UUID
    bank_account_id: UUID
    institution_key: str
    account_purpose: AccountPurpose
    integration_mode: IntegrationMode
    provider_key: str
    environment: IntegrationEnvironment
    provider_account_id: str | None
    credential_secret_ref: str | None
    certificate_secret_ref: str | None
    webhook_secret_ref: str | None
    non_secret_config: dict[str, Any]
    enabled_capabilities: list[str]
    status: str
    last_test_at: datetime | None
    last_test_status: str | None
    last_test_message: str | None
    created_at: datetime
    updated_at: datetime


class BankAccountSetupCombinedResponse(BaseModel):
    account: BankAccountCoreResponse
    setup: BankAccountSetupResponse
    institution: BankInstitutionResponse


class BankAccountProvisionRequest(BaseModel):
    institution_key: str = Field(min_length=2, max_length=40)
    custom_bank_name: str | None = Field(default=None, max_length=120)
    custom_bank_code: str | None = Field(default=None, max_length=10)
    name: str = Field(min_length=2, max_length=120)
    branch: str | None = Field(default=None, max_length=30)
    account_number: str | None = Field(default=None, max_length=40)
    account_digit: str | None = Field(default=None, max_length=10)
    account_type: AccountType = "checking"
    account_purpose: AccountPurpose = "operating"
    fund_scope: FundScope | None = None
    integration_mode: IntegrationMode = "manual"
    environment: IntegrationEnvironment = "manual"
    provider_account_id: str | None = Field(default=None, max_length=180)
    pix_key: str | None = Field(default=None, max_length=180)
    opening_balance: Decimal = Decimal("0.00")


class BankAccountSetupUpdate(BaseModel):
    account_purpose: AccountPurpose
    fund_scope: FundScope | None = None
    integration_mode: IntegrationMode
    environment: IntegrationEnvironment
    provider_account_id: str | None = Field(default=None, max_length=180)
    credential_secret_ref: str | None = Field(default=None, max_length=300)
    certificate_secret_ref: str | None = Field(default=None, max_length=300)
    webhook_secret_ref: str | None = Field(default=None, max_length=300)
    non_secret_config: dict[str, Any] = Field(default_factory=dict)
    enabled_capabilities: list[str] = Field(default_factory=list, max_length=20)
