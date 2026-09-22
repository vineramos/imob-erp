import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Identity, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = (UniqueConstraint("organization_id", "document_number", name="uq_persons_org_document"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    person_type: Mapped[str] = mapped_column(String(20), nullable=False, default="individual")
    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    document_number: Mapped[str | None] = mapped_column(String(24), index=True)
    email: Mapped[str | None] = mapped_column(String(180))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    roles: Mapped[list["PersonRole"]] = relationship(back_populates="person", cascade="all, delete-orphan")


class PersonRole(Base):
    __tablename__ = "person_roles"
    __table_args__ = (UniqueConstraint("person_id", "role_key", name="uq_person_roles_person_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    role_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    person: Mapped[Person] = relationship(back_populates="roles")


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    property_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False, default="rent")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    address: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    rent_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    condo_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    iptu_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    bedrooms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    suites: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bathrooms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parking_spaces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    furnished: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pets_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    public_title: Mapped[str | None] = mapped_column(String(180))
    public_description: Mapped[str | None] = mapped_column(Text)
    public_slug: Mapped[str | None] = mapped_column(String(180), unique=True, index=True)
    publication_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    responsible_broker_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"), index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    owners: Mapped[list["PropertyOwner"]] = relationship(back_populates="property", cascade="all, delete-orphan")
    responsible_broker: Mapped[Person | None] = relationship(foreign_keys=[responsible_broker_person_id])


class PropertyOwner(Base):
    __tablename__ = "property_owners"
    __table_args__ = (UniqueConstraint("property_id", "person_id", name="uq_property_owners_property_person"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"), nullable=False)
    ownership_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    property: Mapped[Property] = relationship(back_populates="owners")
    person: Mapped[Person] = relationship()


class PropertyPhoto(Base):
    __tablename__ = "property_photos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(700), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    caption: Mapped[str | None] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    is_cover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Capture(Base):
    __tablename__ = "captures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="new", index=True)
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="direct")
    contact_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"))
    responsible_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    converted_property_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("properties.id"))
    property_type: Mapped[str | None] = mapped_column(String(50))
    property_address: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    estimated_rent: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    lost_reason: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    contact_person: Mapped[Person | None] = relationship(foreign_keys=[contact_person_id])
    converted_property: Mapped[Property | None] = relationship(foreign_keys=[converted_property_id])


class EconomicIndexValue(Base):
    __tablename__ = "economic_index_values"
    __table_args__ = (UniqueConstraint("index_code", "competence", name="uq_economic_index_code_competence"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sgs_code: Mapped[int] = mapped_column(Integer, nullable=False)
    competence: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    monthly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="BCB/SGS")
    source_reference: Mapped[str | None] = mapped_column(String(500))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EconomicIndexSyncState(Base):
    __tablename__ = "economic_index_sync_state"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    last_success_competence: Mapped[date | None] = mapped_column(Date)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="never", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
