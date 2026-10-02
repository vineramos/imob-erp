"""administration contracts

Revision ID: 0003_administration_contracts
Revises: 0002_portfolio_and_indices
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_administration_contracts"
down_revision: str | None = "0002_portfolio_and_indices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administration_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("plan", sa.String(length=30), nullable=False),
        sa.Column("admin_fee_type", sa.String(length=20), nullable=False),
        sa.Column("admin_fee_percent", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("admin_fee_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("intermediation_percent", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("intermediation_installments", sa.Integer(), nullable=False),
        sa.Column("owner_repasse_business_days", sa.Integer(), nullable=False),
        sa.Column("condo_operational_payer", sa.String(length=20), nullable=False),
        sa.Column("iptu_operational_payer", sa.String(length=20), nullable=False),
        sa.Column("publication_requires_owner_approval", sa.Boolean(), nullable=False),
        sa.Column("maintenance_limit_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("emergency_limit_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("property_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("owner_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rules_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("signing_provider", sa.String(length=30), nullable=False),
        sa.Column("signing_envelope_id", sa.String(length=180), nullable=True),
        sa.Column("signing_status", sa.String(length=40), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_document_reference", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_number"),
    )
    op.create_index("ix_administration_contracts_organization_id", "administration_contracts", ["organization_id"], unique=False)
    op.create_index("ix_administration_contracts_property_id", "administration_contracts", ["property_id"], unique=False)
    op.create_index("ix_administration_contracts_status", "administration_contracts", ["status"], unique=False)

    op.create_table(
        "administration_contract_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["administration_contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id", "version_number", name="uq_admin_contract_versions_contract_version"),
    )
    op.create_index("ix_administration_contract_versions_contract_id", "administration_contract_versions", ["contract_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_administration_contract_versions_contract_id", table_name="administration_contract_versions")
    op.drop_table("administration_contract_versions")
    op.drop_index("ix_administration_contracts_status", table_name="administration_contracts")
    op.drop_index("ix_administration_contracts_property_id", table_name="administration_contracts")
    op.drop_index("ix_administration_contracts_organization_id", table_name="administration_contracts")
    op.drop_table("administration_contracts")
