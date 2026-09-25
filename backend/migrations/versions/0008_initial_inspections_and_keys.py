"""initial inspections and key handover

Revision ID: 0008_initial_inspections_keys
Revises: 0007_lease_documents_and_signing
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_initial_inspections_keys"
down_revision: str | None = "0007_lease_documents_and_signing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inspections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("inspection_type", sa.String(length=30), nullable=False, server_default="initial"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("lease_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("environments", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("contestations", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("inspector_name", sa.String(length=180), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contest_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("report_reference", sa.String(length=500), nullable=True),
        sa.Column("report_hash", sa.String(length=64), nullable=True),
        sa.Column("report_version", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("finalized_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("lease_contract_id", "inspection_type", name="uq_inspections_lease_type"),
    )
    for column in ("organization_id", "lease_contract_id", "property_id", "inspection_type", "status", "scheduled_at", "contest_deadline"):
        op.create_index(f"ix_inspections_{column}", "inspections", [column], unique=False)

    op.create_table(
        "inspection_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("inspection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("inspection_id", "version_number", name="uq_inspection_versions_inspection_version"),
    )
    op.create_index("ix_inspection_versions_inspection_id", "inspection_versions", ["inspection_id"], unique=False)

    op.create_table(
        "key_handovers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id"), nullable=False, unique=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("inspection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inspections.id"), nullable=False, unique=True),
        sa.Column("handed_over_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipient_name", sa.String(length=180), nullable=False),
        sa.Column("recipient_document", sa.String(length=30), nullable=True),
        sa.Column("keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("meter_readings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("organization_id", "lease_contract_id", "property_id", "inspection_id", "handed_over_at"):
        op.create_index(f"ix_key_handovers_{column}", "key_handovers", [column], unique=column in {"lease_contract_id", "inspection_id"})


def downgrade() -> None:
    op.drop_table("key_handovers")
    op.drop_table("inspection_versions")
    op.drop_table("inspections")
