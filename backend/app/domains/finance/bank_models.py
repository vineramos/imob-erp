import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Identity, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    bank_code: Mapped[str | None] = mapped_column(String(10))
    bank_name: Mapped[str] = mapped_column(String(120), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(30))
    account_number: Mapped[str | None] = mapped_column(String(40))
    account_digit: Mapped[str | None] = mapped_column(String(10))
    account_type: Mapped[str] = mapped_column(String(30), nullable=False, default="checking")
    fund_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="operating", index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", index=True)
    provider_account_id: Mapped[str | None] = mapped_column(String(120))
    pix_key: Mapped[str | None] = mapped_column(String(180))

    opening_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    transactions: Mapped[list["BankTransaction"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class BankStatementImport(Base):
    __tablename__ = "bank_statement_imports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    filename: Mapped[str] = mapped_column(String(220), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    imported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint("bank_account_id", "fingerprint", name="uq_bank_transactions_account_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    statement_import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_statement_imports.id", ondelete="SET NULL"), index=True)

    external_id: Mapped[str | None] = mapped_column(String(180), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    description: Mapped[str] = mapped_column(String(300), nullable=False)
    document: Mapped[str | None] = mapped_column(String(120))
    counterparty_name: Mapped[str | None] = mapped_column(String(220))
    bank_reference: Mapped[str | None] = mapped_column(String(180))
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual", index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    account: Mapped[BankAccount] = relationship(back_populates="transactions")
    reconciliations: Mapped[list["BankReconciliation"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", order_by="BankReconciliation.reconciled_at"
    )
    exception: Mapped["BankReconciliationExceptionRecord | None"] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", uselist=False
    )


class BankReconciliation(Base):
    __tablename__ = "bank_reconciliations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    bank_transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False, index=True)

    target_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    target_code: Mapped[str] = mapped_column(String(80), nullable=False)
    target_direction: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    reconciled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    reconciled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    transaction: Mapped[BankTransaction] = relationship(back_populates="reconciliations")


class BankReconciliationExceptionRecord(Base):
    __tablename__ = "bank_reconciliation_exceptions"
    __table_args__ = (
        UniqueConstraint("bank_transaction_id", name="uq_bank_reconciliation_exceptions_transaction"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    bank_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    reason: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="exception", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    reason_label: Mapped[str] = mapped_column(String(500), nullable=False)
    candidate_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    top_candidate_code: Mapped[str | None] = mapped_column(String(80))
    top_candidate_score: Mapped[int | None] = mapped_column(BigInteger)
    matched_identifier: Mapped[str | None] = mapped_column(String(180))
    resolution_note: Mapped[str | None] = mapped_column(Text)

    ignored_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    transaction: Mapped[BankTransaction] = relationship(back_populates="exception")
