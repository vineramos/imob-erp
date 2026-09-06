import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LeaseLifecycleCase(Base):
    __tablename__ = "lease_lifecycle_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    lease_contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_contracts.id"), nullable=False, unique=True, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)

    process_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    initiated_by: Mapped[str | None] = mapped_column(String(30), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, index=True)
    reason: Mapped[str | None] = mapped_column(Text)

    termination_fine_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    fine_status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_applicable", index=True)
    fine_title_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_titles.id"), index=True)
    fine_notes: Mapped[str | None] = mapped_column(Text)

    renewal_terms: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    renewed_lease_contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lease_contracts.id"), index=True)

    exit_inspection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inspections.id"), index=True)
    keys_returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    keys_received_by: Mapped[str | None] = mapped_column(String(180))
    keys_received_document: Mapped[str | None] = mapped_column(String(30))
    returned_keys: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    meter_readings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    key_return_notes: Mapped[str | None] = mapped_column(Text)

    property_disposition: Mapped[str | None] = mapped_column(String(30), index=True)
    financial_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class LeaseExitAdjustment(Base):
    """Ajuste humano do acerto final de uma desocupação.

    A vistoria apenas sugere divergências. A cobrança nasce somente quando um
    usuário registra explicitamente este ajuste, que por sua vez cria um título
    financeiro rastreável e bloqueia o encerramento enquanto estiver em aberto.
    """

    __tablename__ = "lease_exit_adjustments"
    __table_args__ = (
        UniqueConstraint("financial_title_id", name="uq_lease_exit_adjustments_financial_title"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lifecycle_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_lifecycle_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_contracts.id"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    beneficiary: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="registered", index=True)
    financial_title_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_titles.id"), index=True)

    source_context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
