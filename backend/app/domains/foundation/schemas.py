from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ThemeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    companyName: str = Field(min_length=1, max_length=120)
    companyShortName: str = Field(min_length=1, max_length=40)
    logoUrl: str = ""
    faviconUrl: str = ""
    primary: str
    primaryStrong: str
    primarySoft: str
    sidebarBg: str
    appBg: str
    surface: str
    text: str
    textMuted: str
    border: str
    success: str
    warning: str
    danger: str
    fontFamily: str = Field(min_length=1, max_length=300)
    radius: int = Field(ge=0, le=24)
    fieldHeight: int = Field(ge=36, le=52)
    sidebarWidth: int = Field(ge=210, le=320)
    tableDensity: Literal["compact", "normal", "comfortable"] = "normal"


class AddressPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    street: str = ""
    number: str = ""
    complement: str = ""
    neighborhood: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""


class OrganizationProfile(BaseModel):
    id: UUID
    legal_name: str
    display_name: str
    document_number: str | None = None
    creci_pj: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: dict = Field(default_factory=dict)


class OrganizationProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str = Field(min_length=1, max_length=180)
    display_name: str = Field(min_length=1, max_length=120)
    document_number: str | None = Field(default=None, max_length=20)
    creci_pj: str | None = Field(default=None, max_length=40)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=30)
    address: AddressPayload = Field(default_factory=AddressPayload)


class OperationalDefaultsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rent_due_day: int = Field(default=10, ge=1, le=28)
    owner_repasse_business_days: int = Field(default=2, ge=0, le=20)
    residential_lease_months: int = Field(default=30, ge=1, le=120)
    adjustment_index: Literal["IPCA", "IGP-M", "INPC", "IPC-FIPE", "IGP-DI"] = "IPCA"
    termination_fine_months: float = Field(default=3, ge=0, le=12)
    inspection_contest_days: int = Field(default=5, ge=1, le=30)
    default_admin_fee_percent: float = Field(default=10, ge=0, le=100)
    delinquency_critical_day: int = Field(default=5, ge=1, le=90)


class IntegrationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_provider: Literal["none", "inter"] = "inter"
    signature_provider: Literal["none", "clicksign"] = "clicksign"
    email_provider: Literal["none", "smtp"] = "smtp"
    public_site_enabled: bool = False
    webhook_base_url: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=1000)


class ApprovalRulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    scope: str = Field(min_length=2, max_length=80)
    priority: int = Field(default=100, ge=1, le=999)
    min_amount: float | None = Field(default=None, ge=0)
    max_amount: float | None = Field(default=None, ge=0)
    required_approvals: int = Field(default=1, ge=1, le=5)
    approver_permission: str = Field(min_length=2, max_length=140)
    is_active: bool = True
    reason: str | None = Field(default=None, max_length=500)


class ApprovalRuleResponse(BaseModel):
    id: UUID
    name: str
    scope: str
    priority: int
    min_amount: float | None = None
    max_amount: float | None = None
    required_approvals: int
    approver_permission: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MeResponse(BaseModel):
    id: UUID
    name: str
    email: str
    organization_id: UUID
    organization_name: str
    role_keys: list[str]
    permissions: list[str]


class RoleResponse(BaseModel):
    id: UUID
    key: str
    name: str
    description: str | None = None
    is_system: bool
    is_active: bool
    permissions: list[str]
    user_count: int = 0


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: str
    is_active: bool
    blocked_at: datetime | None = None
    created_at: datetime
    role_keys: list[str]


class UserStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool
    reason: str | None = Field(default=None, max_length=500)


class UserRolesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_keys: list[str] = Field(min_length=1, max_length=20)
    reason: str | None = Field(default=None, max_length=500)


class AuditEventResponse(BaseModel):
    id: UUID
    actor_user_id: UUID | None = None
    actor_name: str | None = None
    action: str
    module: str
    entity_type: str
    entity_id: str | None = None
    before_data: dict[str, Any] | None = None
    after_data: dict[str, Any] | None = None
    reason: str | None = None
    ip_address: str | None = None
    created_at: datetime
