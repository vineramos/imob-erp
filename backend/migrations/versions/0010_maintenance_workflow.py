"""maintenance workflow

Revision ID: 0010_maintenance_workflow
Revises: 0009_finance_rent_cycle
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_maintenance_workflow"
down_revision: str | None = "0009_finance_rent_cycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "maintenance_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id"), nullable=True),
        sa.Column("requester_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id"), nullable=True),
        sa.Column("supplier_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id"), nullable=True),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False, server_default="general"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="requested"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("responsibility", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("estimated_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("approved_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("actual_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("selected_quote_id", sa.String(length=36), nullable=True),
        sa.Column("quotes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("history", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("completed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_maintenance_org_status", "maintenance_requests", ["organization_id", "status"])
    op.create_index("ix_maintenance_property_status", "maintenance_requests", ["property_id", "status"])
    op.create_index("ix_maintenance_priority", "maintenance_requests", ["priority"])
    op.create_index("ix_maintenance_scheduled_at", "maintenance_requests", ["scheduled_at"])
    op.create_index("ix_maintenance_completed_at", "maintenance_requests", ["completed_at"])
    op.create_index("ix_maintenance_lease_contract_id", "maintenance_requests", ["lease_contract_id"])
    op.create_index("ix_maintenance_requester_person_id", "maintenance_requests", ["requester_person_id"])
    op.create_index("ix_maintenance_supplier_person_id", "maintenance_requests", ["supplier_person_id"])


def downgrade() -> None:
    op.drop_table("maintenance_requests")
