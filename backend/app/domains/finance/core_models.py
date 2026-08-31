import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FinancialTitle(Base):
    """Título financeiro genérico para obrigações que não nascem de um domínio específico."""

    __tablename__ = "financial_titles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)

    direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # receivable / payable
    fund_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="operating", index=True)  # operating / third_party
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)

    property_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("properties.id"), index=True)
    lease_contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lease_contracts.id"), index=True)

    category: Mapped[str] = mapped_column(String(100), nullable=False, default="Outros", index=True)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    counterparty_name: Mapped[str] = mapped_column(String(220), nullable=False)
    competence: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    settled_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)

    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    payment_method: Mapped[str | None] = mapped_column(String(40))
    payment_reference: Mapped[str | None] = mapped_column(String(180))
    notes: Mapped[str | None] = mapped_column(Text)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
