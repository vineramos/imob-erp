"""lease renewal and termination lifecycle

Revision ID: 0026_lease_lifecycle
Revises: 0025_documents_catalog
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_lease_lifecycle"
down_revision: str | None = "0025_documents_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("lease_contracts", sa.Column("operational_end_date", sa.Date(), nullable=True))
    op.add_column("lease_contracts", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_lease_contracts_operational_end_date", "lease_contracts", ["operational_end_date"])
    op.create_index("ix_lease_contracts_closed_at", "lease_contracts", ["closed_at"])

    op.create_table(
        "lease_lifecycle_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("process_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("initiated_by", sa.String(length=30), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("termination_fine_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("fine_status", sa.String(length=30), server_default="not_applicable", nullable=False),
        sa.Column("fine_title_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fine_notes", sa.Text(), nullable=True),
        sa.Column("renewal_terms", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("renewed_lease_contract_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exit_inspection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("keys_returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("keys_received_by", sa.String(length=180), nullable=True),
        sa.Column("keys_received_document", sa.String(length=30), nullable=True),
        sa.Column("returned_keys", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("meter_readings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("key_return_notes", sa.Text(), nullable=True),
        sa.Column("property_disposition", sa.String(length=30), nullable=True),
        sa.Column("financial_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["lease_contract_id"], ["lease_contracts.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.ForeignKeyConstraint(["fine_title_id"], ["financial_titles.id"]),
        sa.ForeignKeyConstraint(["renewed_lease_contract_id"], ["lease_contracts.id"]),
        sa.ForeignKeyConstraint(["exit_inspection_id"], ["inspections.id"]),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_number"),
        sa.UniqueConstraint("lease_contract_id"),
    )
    op.create_index("ix_lease_lifecycle_cases_organization_id", "lease_lifecycle_cases", ["organization_id"])
    op.create_index("ix_lease_lifecycle_cases_lease_contract_id", "lease_lifecycle_cases", ["lease_contract_id"])
    op.create_index("ix_lease_lifecycle_cases_property_id", "lease_lifecycle_cases", ["property_id"])
    op.create_index("ix_lease_lifecycle_cases_process_type", "lease_lifecycle_cases", ["process_type"])
    op.create_index("ix_lease_lifecycle_cases_status", "lease_lifecycle_cases", ["status"])
    op.create_index("ix_lease_lifecycle_cases_initiated_by", "lease_lifecycle_cases", ["initiated_by"])
    op.create_index("ix_lease_lifecycle_cases_effective_date", "lease_lifecycle_cases", ["effective_date"])
    op.create_index("ix_lease_lifecycle_cases_fine_status", "lease_lifecycle_cases", ["fine_status"])
    op.create_index("ix_lease_lifecycle_cases_fine_title_id", "lease_lifecycle_cases", ["fine_title_id"])
    op.create_index("ix_lease_lifecycle_cases_renewed_lease_contract_id", "lease_lifecycle_cases", ["renewed_lease_contract_id"])
    op.create_index("ix_lease_lifecycle_cases_exit_inspection_id", "lease_lifecycle_cases", ["exit_inspection_id"])
    op.create_index("ix_lease_lifecycle_cases_keys_returned_at", "lease_lifecycle_cases", ["keys_returned_at"])
    op.create_index("ix_lease_lifecycle_cases_property_disposition", "lease_lifecycle_cases", ["property_disposition"])
    op.create_index("ix_lease_lifecycle_cases_closed_at", "lease_lifecycle_cases", ["closed_at"])


def downgrade() -> None:
    op.drop_index("ix_lease_lifecycle_cases_closed_at", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_property_disposition", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_keys_returned_at", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_exit_inspection_id", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_renewed_lease_contract_id", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_fine_title_id", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_fine_status", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_effective_date", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_initiated_by", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_status", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_process_type", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_property_id", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_lease_contract_id", table_name="lease_lifecycle_cases")
    op.drop_index("ix_lease_lifecycle_cases_organization_id", table_name="lease_lifecycle_cases")
    op.drop_table("lease_lifecycle_cases")
    op.drop_index("ix_lease_contracts_closed_at", table_name="lease_contracts")
    op.drop_index("ix_lease_contracts_operational_end_date", table_name="lease_contracts")
    op.drop_column("lease_contracts", "closed_at")
    op.drop_column("lease_contracts", "operational_end_date")
