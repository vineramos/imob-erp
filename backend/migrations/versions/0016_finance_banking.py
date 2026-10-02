"""bank accounts, statements and reconciliation

Revision ID: 0016_finance_banking
Revises: 0015_finance_core
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_finance_banking"
down_revision: str | None = "0015_finance_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bank_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("bank_code", sa.String(length=10), nullable=True),
        sa.Column("bank_name", sa.String(length=120), nullable=False),
        sa.Column("branch", sa.String(length=30), nullable=True),
        sa.Column("account_number", sa.String(length=40), nullable=True),
        sa.Column("account_digit", sa.String(length=10), nullable=True),
        sa.Column("account_type", sa.String(length=30), nullable=False, server_default="checking"),
        sa.Column("fund_scope", sa.String(length=20), nullable=False, server_default="operating"),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("provider_account_id", sa.String(length=120), nullable=True),
        sa.Column("pix_key", sa.String(length=180), nullable=True),
        sa.Column("opening_balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("organization_id", "fund_scope", "provider", "is_active"):
        op.create_index(f"ix_bank_accounts_{column}", "bank_accounts", [column], unique=False)

    op.create_table(
        "bank_statement_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bank_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("filename", sa.String(length=220), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("total_rows", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_rows", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("duplicate_rows", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("imported_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("organization_id", "bank_account_id", "file_hash"):
        op.create_index(f"ix_bank_statement_imports_{column}", "bank_statement_imports", [column], unique=False)

    op.create_table(
        "bank_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bank_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("statement_import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bank_statement_imports.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_id", sa.String(length=180), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("document", sa.String(length=120), nullable=True),
        sa.Column("counterparty_name", sa.String(length=220), nullable=True),
        sa.Column("bank_reference", sa.String(length=180), nullable=True),
        sa.Column("balance_after", sa.Numeric(14, 2), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("bank_account_id", "fingerprint", name="uq_bank_transactions_account_fingerprint"),
    )
    for column in (
        "organization_id",
        "bank_account_id",
        "statement_import_id",
        "external_id",
        "transaction_date",
        "posted_at",
        "direction",
        "source",
        "status",
    ):
        op.create_index(f"ix_bank_transactions_{column}", "bank_transactions", [column], unique=False)

    op.create_table(
        "bank_reconciliations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bank_transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_code", sa.String(length=80), nullable=False),
        sa.Column("target_direction", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reconciled_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("organization_id", "bank_transaction_id", "target_type", "target_id"):
        op.create_index(f"ix_bank_reconciliations_{column}", "bank_reconciliations", [column], unique=False)


def downgrade() -> None:
    op.drop_table("bank_reconciliations")
    op.drop_table("bank_transactions")
    op.drop_table("bank_statement_imports")
    op.drop_table("bank_accounts")
