import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PersonProfile(Base):
    """Dados complementares/documentais do cadastro canônico de Pessoa."""

    __tablename__ = "person_profiles"
    __table_args__ = (UniqueConstraint("person_id", name="uq_person_profiles_person"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)

    secondary_phone: Mapped[str | None] = mapped_column(String(40))

    identity_number: Mapped[str | None] = mapped_column(String(40))
    identity_issuer: Mapped[str | None] = mapped_column(String(40))
    birth_date: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(80))
    marital_status: Mapped[str | None] = mapped_column(String(30))
    occupation: Mapped[str | None] = mapped_column(String(120))

    trade_name: Mapped[str | None] = mapped_column(String(180))
    state_registration: Mapped[str | None] = mapped_column(String(40))
    municipal_registration: Mapped[str | None] = mapped_column(String(40))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
