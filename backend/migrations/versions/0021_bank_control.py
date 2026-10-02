"""bank agnostic daily close and provider payments

Revision ID: 0021_bank_control
Revises: 0020_person_profiles
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_bank_control"
down_revision: str | None = "0020_person_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)


def upgrade() -> None:
    op.create_table(
        "bank_daily_closes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bank_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("closing_date", sa.Date(), nullable=False),
        sa.Column("fund_scope", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("erp_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("bank_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("difference", sa.Numeric(14, 2), nullable=False),
        sa.Column("pending_transactions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="confirmed"),
        sa.Column("notes", sa.Text()),
        sa.Column("closed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("bank_account_id", "closing_date", name="uq_bank_daily_closes_account_date"),
    )
    _index("bank_daily_closes", "organization_id", "bank_account_id", "closing_date", "fund_scope", "status")

    op.create_table(
        "bank_payment_instructions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("payment_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_batch_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_batch_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bank_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("payment_method", sa.String(30), nullable=False, server_default="pix"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("recipient_name", sa.String(220), nullable=False),
        sa.Column("recipient_reference", sa.String(120)),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("provider_reference", sa.String(180)),
        sa.Column("provider_status", sa.String(60), nullable=False, server_default="pending"),
        sa.Column("request_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_error", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("payment_batch_item_id", name="uq_bank_payment_instructions_batch_item"),
    )
    _index(
        "bank_payment_instructions",
        "organization_id",
        "payment_batch_id",
        "payment_batch_item_id",
        "bank_account_id",
        "provider",
        "provider_reference",
        "provider_status",
        "submitted_at",
        "confirmed_at",
    )


def downgrade() -> None:
    op.drop_table("bank_payment_instructions")
    op.drop_table("bank_daily_closes")
