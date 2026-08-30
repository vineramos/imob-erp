"""property photos

Revision ID: 0011_property_photos
Revises: 0010_maintenance_workflow
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_property_photos"
down_revision: str | None = "0010_maintenance_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "property_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("storage_reference", sa.String(length=700), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("caption", sa.String(length=300), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_cover", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_property_photos_org_property", "property_photos", ["organization_id", "property_id"])
    op.create_index("ix_property_photos_property_position", "property_photos", ["property_id", "position"])
    op.create_index(
        "uq_property_photos_single_cover",
        "property_photos",
        ["property_id"],
        unique=True,
        postgresql_where=sa.text("is_cover = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_property_photos_single_cover", table_name="property_photos")
    op.drop_index("ix_property_photos_property_position", table_name="property_photos")
    op.drop_index("ix_property_photos_org_property", table_name="property_photos")
    op.drop_table("property_photos")
