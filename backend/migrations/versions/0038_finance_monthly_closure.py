"""finance monthly closure ledger

Revision ID: 0038_fin_monthly_closure
Revises: 0037_bank_recon_exceptions
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0038_fin_monthly_closure"
down_revision = "0037_bank_recon_exceptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_monthly_closures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competence", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("readiness_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("closing_note", sa.Text()),
        sa.Column("reopen_reason", sa.Text()),
        sa.Column("closed_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reopened_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("reopened_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["reopened_by_user_id"], ["app_users.id"]),
        sa.UniqueConstraint("organization_id", "competence", name="uq_finance_monthly_closure_org_competence"),
    )
    op.create_index("ix_fin_monthly_closure_org", "finance_monthly_closures", ["organization_id"])
    op.create_index("ix_fin_monthly_closure_comp", "finance_monthly_closures", ["competence"])
    op.create_index("ix_fin_monthly_closure_status", "finance_monthly_closures", ["status"])

    op.create_table(
        "finance_monthly_closure_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("closure_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competence", sa.Date(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("readiness_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["closure_id"], ["finance_monthly_closures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["app_users.id"]),
    )
    op.create_index("ix_fin_monthly_closure_event_org", "finance_monthly_closure_events", ["organization_id"])
    op.create_index("ix_fin_monthly_closure_event_closure", "finance_monthly_closure_events", ["closure_id"])
    op.create_index("ix_fin_monthly_closure_event_comp", "finance_monthly_closure_events", ["competence"])
    op.create_index("ix_fin_monthly_closure_event_action", "finance_monthly_closure_events", ["action"])


def downgrade() -> None:
    op.drop_table("finance_monthly_closure_events")
    op.drop_table("finance_monthly_closures")
