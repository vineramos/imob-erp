import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MaintenanceRequest(Base):
    __tablename__ = "maintenance_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    lease_contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lease_contracts.id"), index=True)
    requester_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"), index=True)
    supplier_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"), index=True)

    title: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="general", index=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal", index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="requested", index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsibility: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Campos legados mantidos para compatibilidade. No fluxo novo, valores só nascem dos orçamentos.
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    approved_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    # Serviços técnicos definidos pela imobiliária após a abertura do chamado.
    services: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    selected_quote_id: Mapped[str | None] = mapped_column(String(36))
    quotes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MaintenancePartner(Base):
    __tablename__ = "maintenance_partners"
    __table_args__ = (
        UniqueConstraint("organization_id", "document_number", name="uq_maintenance_partners_org_document"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(220))
    document_number: Mapped[str | None] = mapped_column(String(24), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(180))
    email: Mapped[str | None] = mapped_column(String(180))
    phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    specialties: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    pix_key: Mapped[str | None] = mapped_column(String(180))
    bank_details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    logo_storage_reference: Mapped[str | None] = mapped_column(String(700))
    logo_content_type: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
