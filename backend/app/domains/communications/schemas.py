from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


Channel = Literal["email", "whatsapp"]
RecipientRole = Literal["tenant", "owner", "other"]


class CommunicationMessageCreate(BaseModel):
    person_id: UUID | None = None
    recipient_name: str = Field(default="", max_length=180)
    recipient_email: EmailStr | None = None
    recipient_phone: str | None = Field(default=None, max_length=50)
    recipient_role: RecipientRole = "other"
    channel: Channel = "email"
    category: str = Field(default="manual", max_length=80)
    subject: str = Field(default="", max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    source_module: str | None = Field(default=None, max_length=80)
    source_type: str | None = Field(default=None, max_length=80)
    source_id: str | None = Field(default=None, max_length=180)
    attachment_manifest: list[dict[str, Any]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_recipient(self):
        if self.person_id is None and not self.recipient_name.strip():
            raise ValueError("Informe a pessoa ou o nome do destinatário.")
        return self


class CommunicationMessageUpdate(BaseModel):
    recipient_name: str | None = Field(default=None, max_length=180)
    recipient_email: EmailStr | None = None
    recipient_phone: str | None = Field(default=None, max_length=50)
    channel: Channel | None = None
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    attachment_manifest: list[dict[str, Any]] | None = Field(default=None, max_length=20)


class CommunicationTemplateUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    subject_template: str = Field(default="", max_length=300)
    body_template: str = Field(min_length=1, max_length=20000)
    is_active: bool = True


class CommunicationPreferenceUpdate(BaseModel):
    email_enabled: bool = True
    whatsapp_enabled: bool = False
    transactional_enabled: bool = True
    preferred_channel: Channel = "email"
    notes: str | None = Field(default=None, max_length=1000)


class CommunicationSuggestionRefresh(BaseModel):
    include_overdue_charges: bool = True
    include_contracts: bool = True
    include_owner_repasses: bool = True


class CommunicationCapabilities(BaseModel):
    email: dict[str, Any]
    whatsapp: dict[str, Any]


class CommunicationEventResponse(BaseModel):
    id: UUID
    event_type: str
    event_data: dict[str, Any]
    created_by_user_id: UUID | None
    created_at: datetime


class CommunicationMessageResponse(BaseModel):
    id: UUID
    internal_number: int
    person_id: UUID | None
    recipient_name: str
    recipient_email: str | None
    recipient_phone: str | None
    recipient_role: str
    channel: str
    category: str
    origin: str
    subject: str
    body: str
    status: str
    source_module: str | None
    source_type: str | None
    source_id: str | None
    attachment_manifest: list[dict[str, Any]]
    provider_name: str | None
    provider_message_id: str | None
    error_message: str | None
    attempt_count: int
    suggested_at: datetime | None
    queued_at: datetime | None
    sent_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None
    created_by_user_id: UUID | None
    sent_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    send_allowed: bool
    blocked_reason: str | None = None
    events: list[CommunicationEventResponse] = Field(default_factory=list)
