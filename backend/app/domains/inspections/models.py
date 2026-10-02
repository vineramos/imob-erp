import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (UniqueConstraint("lease_contract_id", "inspection_type", name="uq_inspections_lease_type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    lease_contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_contracts.id"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    inspection_type: Mapped[str] = mapped_column(String(30), nullable=False, default="initial", index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)

    lease_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    environments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    contestations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    inspector_name: Mapped[str | None] = mapped_column(String(180))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contest_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    report_reference: Mapped[str | None] = mapped_column(String(500))
    report_hash: Mapped[str | None] = mapped_column(String(64))
    report_version: Mapped[int | None] = mapped_column(Integer)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    finalized_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    versions: Mapped[list["InspectionVersion"]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan", order_by="InspectionVersion.version_number"
    )
    key_handover: Mapped[Optional["KeyHandover"]] = relationship(back_populates="inspection", uselist=False)


class InspectionVersion(Base):
    __tablename__ = "inspection_versions"
    __table_args__ = (UniqueConstraint("inspection_id", "version_number", name="uq_inspection_versions_inspection_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inspection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    inspection: Mapped[Inspection] = relationship(back_populates="versions")


class KeyHandover(Base):
    __tablename__ = "key_handovers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    lease_contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_contracts.id"), nullable=False, unique=True, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    inspection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inspections.id"), nullable=False, unique=True, index=True)
    handed_over_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    recipient_name: Mapped[str] = mapped_column(String(180), nullable=False)
    recipient_document: Mapped[str | None] = mapped_column(String(30))
    keys: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    meter_readings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    inspection: Mapped[Inspection] = relationship(back_populates="key_handover")
