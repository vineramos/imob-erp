import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PersonBankDetails(Base):
    """Dados bancários reutilizáveis vinculados ao cadastro canônico de Pessoa."""

    __tablename__ = "person_bank_details"
    __table_args__ = (UniqueConstraint("person_id", name="uq_person_bank_details_person"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)

    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_code: Mapped[str | None] = mapped_column(String(10))
    branch: Mapped[str | None] = mapped_column(String(30))
    account_number: Mapped[str | None] = mapped_column(String(40))
    account_digit: Mapped[str | None] = mapped_column(String(10))
    account_type: Mapped[str] = mapped_column(String(20), nullable=False, default="checking")

    pix_key_type: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    pix_key: Mapped[str | None] = mapped_column(String(180))
    account_holder_name: Mapped[str | None] = mapped_column(String(180))
    account_holder_document: Mapped[str | None] = mapped_column(String(24))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
