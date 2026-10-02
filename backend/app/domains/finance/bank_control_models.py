import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BankDailyClose(Base):
    """Fechamento imutável de uma conta bancária em uma data."""

    __tablename__ = "bank_daily_closes"
    __table_args__ = (
        UniqueConstraint("bank_account_id", "closing_date", name="uq_bank_daily_closes_account_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    closing_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fund_scope: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")

    erp_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    bank_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    difference: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    pending_transactions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balance_source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="confirmed", index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BankPaymentInstruction(Base):
    """Ordem enviada por um provider bancário opcional.

    A obrigação financeira só é considerada liquidada quando houver conciliação
    bancária. A instrução registra a automação sem substituir o extrato.
    """

    __tablename__ = "bank_payment_instructions"
    __table_args__ = (
        UniqueConstraint("payment_batch_item_id", name="uq_bank_payment_instructions_batch_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    payment_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_batch_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_batch_items.id", ondelete="CASCADE"), nullable=False, index=True)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)

    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False, default="pix")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(220), nullable=False)
    recipient_reference: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    provider_reference: Mapped[str | None] = mapped_column(String(180), index=True)
    provider_status: Mapped[str] = mapped_column(String(60), nullable=False, default="pending", index=True)
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    response_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
