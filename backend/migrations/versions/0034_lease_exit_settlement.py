"""lease exit settlement adjustments

Revision ID: 0034_lease_exit_settlement
Revises: 0033_delinquency_guarantee
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0034_lease_exit_settlement"
down_revision = "0033_delinquency_guarantee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lease_exit_adjustments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lifecycle_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.Column("beneficiary", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="registered"),
        sa.Column("financial_title_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lifecycle_case_id"], ["lease_lifecycle_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lease_contract_id"], ["lease_contracts.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.ForeignKeyConstraint(["financial_title_id"], ["financial_titles.id"]),
        sa.ForeignKeyConstraint(["cancelled_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_number"),
        sa.UniqueConstraint("financial_title_id", name="uq_lease_exit_adjustments_financial_title"),
    )
    op.create_index("ix_lease_exit_adjustments_organization_id", "lease_exit_adjustments", ["organization_id"])
    op.create_index("ix_lease_exit_adjustments_lifecycle_case_id", "lease_exit_adjustments", ["lifecycle_case_id"])
    op.create_index("ix_lease_exit_adjustments_lease_contract_id", "lease_exit_adjustments", ["lease_contract_id"])
    op.create_index("ix_lease_exit_adjustments_property_id", "lease_exit_adjustments", ["property_id"])
    op.create_index("ix_lease_exit_adjustments_kind", "lease_exit_adjustments", ["kind"])
    op.create_index("ix_lease_exit_adjustments_beneficiary", "lease_exit_adjustments", ["beneficiary"])
    op.create_index("ix_lease_exit_adjustments_due_date", "lease_exit_adjustments", ["due_date"])
    op.create_index("ix_lease_exit_adjustments_status", "lease_exit_adjustments", ["status"])
    op.create_index("ix_lease_exit_adjustments_financial_title_id", "lease_exit_adjustments", ["financial_title_id"])
    op.create_index("ix_lease_exit_adjustments_cancelled_at", "lease_exit_adjustments", ["cancelled_at"])


def downgrade() -> None:
    op.drop_table("lease_exit_adjustments")
