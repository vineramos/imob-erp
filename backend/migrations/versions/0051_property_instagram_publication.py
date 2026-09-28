"""instagram property publication workspace

Revision ID: 0051_property_instagram_publication
Revises: 0050_portal_integrations
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0051_property_instagram_publication"
down_revision = "0050_portal_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column(
            "instagram_publication",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("properties", "instagram_publication")
