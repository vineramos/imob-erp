import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class LeaseContract(Base):
    __tablename__ = "lease_contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)

    rent_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    due_day: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    adjustment_index: Mapped[str] = mapped_column(String(30), nullable=False, default="IPCA")
    adjustment_period_months: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    adjustment_base_date: Mapped[date] = mapped_column(Date, nullable=False)
    next_adjustment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    term_months: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    termination_fine_months: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=3)
    inspection_contest_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    guarantee_type: Mapped[str] = mapped_column(String(40), nullable=False, default="insurance")
    guarantee_details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    property_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    owner_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    tenant_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    rules_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    signers_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text)

    generated_document_reference: Mapped[str | None] = mapped_column(String(500))
    generated_document_hash: Mapped[str | None] = mapped_column(String(64))
    generated_document_version: Mapped[int | None] = mapped_column(Integer)

    signing_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="clicksign")
    signing_envelope_id: Mapped[str | None] = mapped_column(String(180))
    signing_document_id: Mapped[str | None] = mapped_column(String(180))
    signing_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    signing_status: Mapped[str] = mapped_column(String(60), nullable=False, default="not_prepared")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    archive_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_started")
    archived_document_reference: Mapped[str | None] = mapped_column(String(500))
    final_document_hash: Mapped[str | None] = mapped_column(String(64))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    versions: Mapped[list["LeaseContractVersion"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", order_by="LeaseContractVersion.version_number"
    )


class LeaseContractVersion(Base):
    __tablename__ = "lease_contract_versions"
    __table_args__ = (UniqueConstraint("contract_id", "version_number", name="uq_lease_contract_versions_contract_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    contract: Mapped[LeaseContract] = relationship(back_populates="versions")
