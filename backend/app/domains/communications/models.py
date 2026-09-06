import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CommunicationTemplate(Base):
    __tablename__ = "communication_templates"
    __table_args__ = (
        UniqueConstraint("organization_id", "key", "channel", name="uq_communication_templates_org_key_channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, default="email", index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    subject_template: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CommunicationPreference(Base):
    __tablename__ = "communication_preferences"
    __table_args__ = (
        UniqueConstraint("organization_id", "person_id", name="uq_communication_preferences_org_person"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transactional_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preferred_channel: Mapped[str] = mapped_column(String(30), nullable=False, default="email")
    notes: Mapped[str | None] = mapped_column(Text)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CommunicationMessage(Base):
    __tablename__ = "communication_messages"
    __table_args__ = (
        UniqueConstraint("organization_id", "dedupe_key", name="uq_communication_messages_org_dedupe"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), index=True)
    recipient_name: Mapped[str] = mapped_column(String(180), nullable=False)
    recipient_email: Mapped[str | None] = mapped_column(String(180), index=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(50))
    recipient_role: Mapped[str] = mapped_column(String(30), nullable=False, default="other", index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, default="email", index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="manual", index=True)
    origin: Mapped[str] = mapped_column(String(30), nullable=False, default="manual", index=True)
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    source_module: Mapped[str | None] = mapped_column(String(80), index=True)
    source_type: Mapped[str | None] = mapped_column(String(80), index=True)
    source_id: Mapped[str | None] = mapped_column(String(180), index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(300))
    attachment_manifest: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    provider_name: Mapped[str | None] = mapped_column(String(80))
    provider_message_id: Mapped[str | None] = mapped_column(String(220))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suggested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CommunicationEvent(Base):
    __tablename__ = "communication_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("communication_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    event_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
