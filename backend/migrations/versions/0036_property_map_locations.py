"""property map locations

Revision ID: 0036_property_map_locations
Revises: 0035_communications_center
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0036_property_map_locations"
down_revision = "0035_communications_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_map_locations",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=10, scale=7), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=False),
        sa.Column("precision", sa.String(length=24), nullable=False, server_default="exact"),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="nominatim"),
        sa.Column("geocoded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("property_id"),
    )
    op.create_index(
        "ix_property_map_locations_organization_id",
        "property_map_locations",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_property_map_locations_organization_id", table_name="property_map_locations")
    op.drop_table("property_map_locations")
