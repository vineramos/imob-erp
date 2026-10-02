"""crm manual activities

Revision ID: 0045_crm_manual_activities
Revises: 0044_crm_next_actions
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0045_crm_manual_activities"
down_revision = "0044_crm_next_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_activities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("inquiry_id", sa.UUID(), nullable=False),
        sa.Column("activity_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["inquiry_id"], ["public_site_inquiries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_commercial_activities_organization_id", "commercial_activities", ["organization_id"], unique=False)
    op.create_index("ix_commercial_activities_inquiry_id", "commercial_activities", ["inquiry_id"], unique=False)
    op.create_index("ix_commercial_activities_activity_type", "commercial_activities", ["activity_type"], unique=False)
    op.create_index("ix_commercial_activities_created_by_user_id", "commercial_activities", ["created_by_user_id"], unique=False)
    op.create_index("ix_commercial_activities_created_at", "commercial_activities", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_commercial_activities_created_at", table_name="commercial_activities")
    op.drop_index("ix_commercial_activities_created_by_user_id", table_name="commercial_activities")
    op.drop_index("ix_commercial_activities_activity_type", table_name="commercial_activities")
    op.drop_index("ix_commercial_activities_inquiry_id", table_name="commercial_activities")
    op.drop_index("ix_commercial_activities_organization_id", table_name="commercial_activities")
    op.drop_table("commercial_activities")
