"""property portal publications
Revision ID: 0049_property_portal_publications
Revises: 0048_property_charge_templates
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0049_property_portal_publications"
down_revision = "0048_property_charge_templates"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("properties", sa.Column("portal_publications", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))

def downgrade() -> None:
    op.drop_column("properties", "portal_publications")
