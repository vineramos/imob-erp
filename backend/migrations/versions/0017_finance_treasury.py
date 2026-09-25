"""cash flow and payment batches

Revision ID: 0017_finance_treasury
Revises: 0016_finance_banking
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_finance_treasury"
down_revision: str | None = "0016_finance_banking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "bank_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("fund_scope", sa.String(length=20), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False, server_default="pix"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("item_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("provider_batch_id", sa.String(length=180), nullable=True),
        sa.Column("provider_status", sa.String(length=60), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("prepared_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("executed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("cancelled_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_reference", sa.String(length=180), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in (
        "organization_id",
        "bank_account_id",
        "scheduled_date",
        "fund_scope",
        "status",
        "provider_batch_id",
    ):
        op.create_index(f"ix_payment_batches_{column}", "payment_batches", [column], unique=False)

    op.create_table(
        "payment_batch_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "payment_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_code", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=260), nullable=False),
        sa.Column("counterparty_name", sa.String(length=220), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("fund_scope", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column(
            "bank_transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "payment_batch_id", "target_type", "target_id", name="uq_payment_batch_item_target"
        ),
    )
    for column in (
        "organization_id",
        "payment_batch_id",
        "target_type",
        "target_id",
        "due_date",
        "fund_scope",
        "status",
        "bank_transaction_id",
    ):
        op.create_index(f"ix_payment_batch_items_{column}", "payment_batch_items", [column], unique=False)


def downgrade() -> None:
    op.drop_table("payment_batch_items")
    op.drop_table("payment_batches")
