"""definitive finance core

Revision ID: 0015_finance_core
Revises: 0014_maint_services_finance
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_finance_core"
down_revision: str | None = "0014_maint_services_finance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_titles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("fund_scope", sa.String(length=20), nullable=False, server_default="operating"),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id"), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=False, server_default="Outros"),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.Column("counterparty_name", sa.String(length=220), nullable=False),
        sa.Column("competence", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("settled_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_method", sa.String(length=40), nullable=True),
        sa.Column("payment_reference", sa.String(length=180), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in (
        "organization_id",
        "direction",
        "fund_scope",
        "source_type",
        "source_id",
        "property_id",
        "lease_contract_id",
        "category",
        "competence",
        "due_date",
        "status",
        "settled_at",
    ):
        op.create_index(f"ix_financial_titles_{column}", "financial_titles", [column], unique=False)


def downgrade() -> None:
    op.drop_table("financial_titles")
