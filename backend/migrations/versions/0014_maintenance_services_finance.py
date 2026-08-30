"""maintenance services, dual pricing and finance integration

Revision ID: 0014_maintenance_services_finance
Revises: 0013_maintenance_partners
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_maintenance_services_finance"
down_revision: str | None = "0013_maintenance_partners"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "maintenance_requests",
        sa.Column("services", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    op.create_table(
        "maintenance_financial_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("maintenance_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maintenance_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id"), nullable=True),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("counterparty_type", sa.String(length=30), nullable=False),
        sa.Column("counterparty_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("counterparty_name", sa.String(length=220), nullable=False),
        sa.Column("responsibility", sa.String(length=20), nullable=False),
        sa.Column("collection_method", sa.String(length=40), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("settled_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("margin_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(length=180), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("maintenance_request_id", "direction", name="uq_maintenance_financial_direction"),
    )
    op.create_index("ix_maintenance_financial_org", "maintenance_financial_entries", ["organization_id"])
    op.create_index("ix_maintenance_financial_maintenance", "maintenance_financial_entries", ["maintenance_request_id"])
    op.create_index("ix_maintenance_financial_property", "maintenance_financial_entries", ["property_id"])
    op.create_index("ix_maintenance_financial_direction", "maintenance_financial_entries", ["direction"])
    op.create_index("ix_maintenance_financial_status", "maintenance_financial_entries", ["status"])
    op.create_index("ix_maintenance_financial_responsibility", "maintenance_financial_entries", ["responsibility"])


def downgrade() -> None:
    op.drop_index("ix_maintenance_financial_responsibility", table_name="maintenance_financial_entries")
    op.drop_index("ix_maintenance_financial_status", table_name="maintenance_financial_entries")
    op.drop_index("ix_maintenance_financial_direction", table_name="maintenance_financial_entries")
    op.drop_index("ix_maintenance_financial_property", table_name="maintenance_financial_entries")
    op.drop_index("ix_maintenance_financial_maintenance", table_name="maintenance_financial_entries")
    op.drop_index("ix_maintenance_financial_org", table_name="maintenance_financial_entries")
    op.drop_table("maintenance_financial_entries")
    op.drop_column("maintenance_requests", "services")
