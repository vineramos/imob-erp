"""database document storage fallback

Revision ID: 0012_document_storage_fallback
Revises: 0011_property_photos
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_document_storage_fallback"
down_revision: str | None = "0011_property_photos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_storage_objects",
        sa.Column("object_name", sa.String(length=700), primary_key=True),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_document_storage_objects_created_at", "document_storage_objects", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_document_storage_objects_created_at", table_name="document_storage_objects")
    op.drop_table("document_storage_objects")
