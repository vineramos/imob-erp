import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RentCharge(Base):
    __tablename__ = "rent_charges"
    __table_args__ = (
        UniqueConstraint("lease_contract_id", "competence", name="uq_rent_charges_lease_competence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    lease_contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_contracts.id"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    competence: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="generated", index=True)

    rent_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    charge_items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    tenant_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    property_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    owner_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    admin_terms_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payment_method: Mapped[str | None] = mapped_column(String(40))
    payment_reference: Mapped[str | None] = mapped_column(String(180))
    payment_notes: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    settlement: Mapped["FinancialSettlement | None"] = relationship(
        back_populates="charge", uselist=False, cascade="all, delete-orphan"
    )


class FinancialSettlement(Base):
    __tablename__ = "financial_settlements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    charge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    lease_contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_contracts.id"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    administration_contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("administration_contracts.id"), index=True)

    admin_fee_calculated: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    intermediation_fee_calculated: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    agency_fee_withheld: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    agency_reimbursement_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    owner_entitlement_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    third_party_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    charge: Mapped[RentCharge] = relationship(back_populates="settlement")
    repasses: Mapped[list["OwnerRepasse"]] = relationship(
        back_populates="settlement", cascade="all, delete-orphan", order_by="OwnerRepasse.owner_name"
    )


class OwnerRepasse(Base):
    __tablename__ = "owner_repasses"
    __table_args__ = (
        UniqueConstraint("settlement_id", "owner_person_id", name="uq_owner_repasses_settlement_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    settlement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_settlements.id", ondelete="CASCADE"), nullable=False, index=True)
    charge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_contracts.id"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    owner_person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"), nullable=False, index=True)
    owner_name: Mapped[str] = mapped_column(String(180), nullable=False)
    ownership_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    payment_reference: Mapped[str | None] = mapped_column(String(180))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    settlement: Mapped[FinancialSettlement] = relationship(back_populates="repasses")


class MaintenanceFinancialEntry(Base):
    """Conta a pagar/receber originada de uma manutenção concluída."""

    __tablename__ = "maintenance_financial_entries"
    __table_args__ = (
        UniqueConstraint("maintenance_request_id", "direction", name="uq_maintenance_financial_direction"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    maintenance_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("maintenance_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    lease_contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lease_contracts.id"), index=True)

    direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # payable / receivable
    counterparty_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    counterparty_name: Mapped[str] = mapped_column(String(220), nullable=False)
    responsibility: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    collection_method: Mapped[str | None] = mapped_column(String(40), index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    settled_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    margin_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    payment_reference: Mapped[str | None] = mapped_column(String(180))
    notes: Mapped[str | None] = mapped_column(Text)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
