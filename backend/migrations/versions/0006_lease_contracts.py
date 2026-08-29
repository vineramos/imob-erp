"""lease contracts

Revision ID: 0006_lease_contracts
Revises: 0005_contract_documents
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_lease_contracts"
down_revision: str | None = "0005_contract_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lease_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("rent_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column("adjustment_index", sa.String(length=30), nullable=False),
        sa.Column("adjustment_period_months", sa.Integer(), nullable=False),
        sa.Column("adjustment_base_date", sa.Date(), nullable=False),
        sa.Column("next_adjustment_date", sa.Date(), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("termination_fine_months", sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column("inspection_contest_days", sa.Integer(), nullable=False),
        sa.Column("guarantee_type", sa.String(length=40), nullable=False),
        sa.Column("guarantee_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("property_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("owner_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tenant_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rules_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["app_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_number"),
    )
    op.create_index("ix_lease_contracts_organization_id", "lease_contracts", ["organization_id"], unique=False)
    op.create_index("ix_lease_contracts_property_id", "lease_contracts", ["property_id"], unique=False)
    op.create_index("ix_lease_contracts_status", "lease_contracts", ["status"], unique=False)
    op.create_index("ix_lease_contracts_next_adjustment_date", "lease_contracts", ["next_adjustment_date"], unique=False)
    op.create_index("ix_lease_contracts_end_date", "lease_contracts", ["end_date"], unique=False)

    op.create_table(
        "lease_contract_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["lease_contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id", "version_number", name="uq_lease_contract_versions_contract_version"),
    )
    op.create_index("ix_lease_contract_versions_contract_id", "lease_contract_versions", ["contract_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_lease_contract_versions_contract_id", table_name="lease_contract_versions")
    op.drop_table("lease_contract_versions")
    op.drop_index("ix_lease_contracts_end_date", table_name="lease_contracts")
    op.drop_index("ix_lease_contracts_next_adjustment_date", table_name="lease_contracts")
    op.drop_index("ix_lease_contracts_status", table_name="lease_contracts")
    op.drop_index("ix_lease_contracts_property_id", table_name="lease_contracts")
    op.drop_index("ix_lease_contracts_organization_id", table_name="lease_contracts")
    op.drop_table("lease_contracts")
