import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Identity, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AdministrationContract(Base):
    __tablename__ = "administration_contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    plan: Mapped[str] = mapped_column(String(30), nullable=False, default="essential")

    admin_fee_type: Mapped[str] = mapped_column(String(20), nullable=False, default="percent")
    admin_fee_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    admin_fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    intermediation_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=100)
    intermediation_installments: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_repasse_business_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    condo_operational_payer: Mapped[str] = mapped_column(String(20), nullable=False, default="tenant")
    iptu_operational_payer: Mapped[str] = mapped_column(String(20), nullable=False, default="tenant")
    publication_requires_owner_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    maintenance_limit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    emergency_limit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    property_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    owner_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    rules_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text)

    signing_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="clicksign")
    signing_envelope_id: Mapped[str | None] = mapped_column(String(180))
    signing_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_prepared")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_document_reference: Mapped[str | None] = mapped_column(String(500))

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    versions: Mapped[list["AdministrationContractVersion"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", order_by="AdministrationContractVersion.version_number"
    )


class AdministrationContractVersion(Base):
    __tablename__ = "administration_contract_versions"
    __table_args__ = (UniqueConstraint("contract_id", "version_number", name="uq_admin_contract_versions_contract_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("administration_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    contract: Mapped[AdministrationContract] = relationship(back_populates="versions")
