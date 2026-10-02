"""crm next actions

Revision ID: 0044_crm_next_actions
Revises: 0043_property_responsible_broker
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0044_crm_next_actions"
down_revision = "0043_property_responsible_broker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("public_site_inquiries", sa.Column("next_action_title", sa.String(length=180), nullable=True))
    op.add_column("public_site_inquiries", sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("public_site_inquiries", sa.Column("next_action_notes", sa.Text(), nullable=True))
    op.create_index("ix_public_site_inquiries_next_action_at", "public_site_inquiries", ["next_action_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_public_site_inquiries_next_action_at", table_name="public_site_inquiries")
    op.drop_column("public_site_inquiries", "next_action_notes")
    op.drop_column("public_site_inquiries", "next_action_at")
    op.drop_column("public_site_inquiries", "next_action_title")
