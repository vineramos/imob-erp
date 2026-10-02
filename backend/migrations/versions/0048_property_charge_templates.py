"""property charge templates
Revision ID: 0048_property_charge_templates
Revises: 0047_person_profile_photos
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0048_property_charge_templates"
down_revision = "0047_person_profile_photos"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("properties", sa.Column("additional_charges", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))

def downgrade() -> None:
    op.drop_column("properties", "additional_charges")
