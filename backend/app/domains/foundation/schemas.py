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


class MeResponse(BaseModel):
    id: UUID
    name: str
    email: str
    organization_id: UUID
    organization_name: str
    role_keys: list[str]
    permissions: list[str]


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
