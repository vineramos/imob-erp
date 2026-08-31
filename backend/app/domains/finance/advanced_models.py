import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Identity, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BillingBatch(Base):
    __tablename__ = "billing_batches"
    __table_args__ = (UniqueConstraint("organization_id", "competence", name="uq_billing_batches_org_competence"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    competence: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="generated", index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="manual", index=True)
    generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issued_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    items: Mapped[list["BillingItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="BillingItem.created_at"
    )


class BillingItem(Base):
    __tablename__ = "billing_items"
    __table_args__ = (
        UniqueConstraint("billing_batch_id", "charge_id", name="uq_billing_items_batch_charge"),
        UniqueConstraint("charge_id", name="uq_billing_items_charge"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    billing_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("billing_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    charge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="manual", index=True)
    provider_charge_id: Mapped[str | None] = mapped_column(String(180), index=True)
    provider_status: Mapped[str | None] = mapped_column(String(60), index=True)
    boleto_line: Mapped[str | None] = mapped_column(String(180))
    barcode: Mapped[str | None] = mapped_column(String(180))
    pix_copy_paste: Mapped[str | None] = mapped_column(Text)
    pix_txid: Mapped[str | None] = mapped_column(String(180))
    pdf_reference: Mapped[str | None] = mapped_column(String(700))
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    response_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    batch: Mapped[BillingBatch] = relationship(back_populates="items")


class DelinquencyCase(Base):
    __tablename__ = "delinquency_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    charge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    lease_contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_contracts.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open", index=True)
    critical_after_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    critical_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    insurer_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    insurer_protocol: Mapped[str | None] = mapped_column(String(180))
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"), index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    action_log: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CommissionRule(Base):
    __tablename__ = "commission_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, default="first_rent", index=True)
    basis: Mapped[str] = mapped_column(String(40), nullable=False, default="agency_revenue", index=True)
    calculation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="percent")
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    beneficiary_type: Mapped[str] = mapped_column(String(40), nullable=False, default="broker", index=True)
    beneficiary_person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"), nullable=False, index=True)
    beneficiary_name: Mapped[str] = mapped_column(String(180), nullable=False)
    property_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("properties.id"), index=True)
    lease_contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lease_contracts.id"), index=True)
    due_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CommissionEntry(Base):
    __tablename__ = "commission_entries"
    __table_args__ = (
        UniqueConstraint("rule_id", "source_type", "source_id", name="uq_commission_entry_rule_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commission_rules.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_code: Mapped[str] = mapped_column(String(80), nullable=False)
    charge_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rent_charges.id", ondelete="SET NULL"), index=True)
    lease_contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lease_contracts.id", ondelete="SET NULL"), index=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    beneficiary_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    beneficiary_person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"), nullable=False, index=True)
    beneficiary_name: Mapped[str] = mapped_column(String(180), nullable=False)
    competence: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    basis_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    financial_title_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_titles.id", ondelete="SET NULL"), unique=True, index=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    payment_reference: Mapped[str | None] = mapped_column(String(180))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PortalAccess(Base):
    __tablename__ = "portal_accesses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    portal_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InterWebhookEvent(Base):
    __tablename__ = "inter_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, default="billing", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
