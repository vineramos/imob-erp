"""portal integration settings
Revision ID: 0050_portal_integrations
Revises: 0049_portal_publications
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0050_portal_integrations"
down_revision = "0049_portal_publications"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("organization_settings", sa.Column("portal_integrations", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))

def downgrade() -> None:
    op.drop_column("organization_settings", "portal_integrations")
