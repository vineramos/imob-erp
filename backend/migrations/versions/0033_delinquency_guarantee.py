"""delinquency collection ladder and guarantee workflow

Revision ID: 0033_delinquency_guarantee
Revises: 0032_multibank_foundation
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0033_delinquency_guarantee"
down_revision = "0032_multibank_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delinquency_workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delinquency_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guarantee_type", sa.String(length=40), nullable=False, server_default="none"),
        sa.Column("guarantee_provider_name", sa.String(length=180), nullable=True),
        sa.Column("guarantee_policy_number", sa.String(length=180), nullable=True),
        sa.Column("guarantee_status", sa.String(length=40), nullable=False, server_default="not_applicable"),
        sa.Column("guarantee_protocol", sa.String(length=180), nullable=True),
        sa.Column("claimed_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("approved_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("received_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("guarantee_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guarantee_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guarantee_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guarantee_rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guarantee_payment_reference", sa.String(length=180), nullable=True),
        sa.Column("promise_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("promise_due_date", sa.Date(), nullable=True),
        sa.Column("promise_status", sa.String(length=30), nullable=True),
        sa.Column("promise_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promise_broken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["delinquency_case_id"], ["delinquency_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delinquency_case_id", name="uq_delinquency_workflows_case"),
    )
    op.create_index("ix_delinquency_workflows_organization_id", "delinquency_workflows", ["organization_id"])
    op.create_index("ix_delinquency_workflows_delinquency_case_id", "delinquency_workflows", ["delinquency_case_id"])
    op.create_index("ix_delinquency_workflows_guarantee_type", "delinquency_workflows", ["guarantee_type"])
    op.create_index("ix_delinquency_workflows_guarantee_status", "delinquency_workflows", ["guarantee_status"])
    op.create_index("ix_delinquency_workflows_guarantee_submitted_at", "delinquency_workflows", ["guarantee_submitted_at"])
    op.create_index("ix_delinquency_workflows_guarantee_received_at", "delinquency_workflows", ["guarantee_received_at"])
    op.create_index("ix_delinquency_workflows_promise_due_date", "delinquency_workflows", ["promise_due_date"])
    op.create_index("ix_delinquency_workflows_promise_status", "delinquency_workflows", ["promise_status"])
    op.create_index("ix_delinquency_workflows_promise_broken_at", "delinquency_workflows", ["promise_broken_at"])


def downgrade() -> None:
    op.drop_table("delinquency_workflows")
