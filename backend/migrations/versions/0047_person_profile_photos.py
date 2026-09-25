"""person profile photos

Revision ID: 0047_person_profile_photos
Revises: 0046_commission_payment_batches
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0047_person_profile_photos"
down_revision = "0046_commission_payment_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("photo_filename", sa.String(length=255), nullable=True))
    op.add_column("persons", sa.Column("photo_content_type", sa.String(length=80), nullable=True))
    op.add_column("persons", sa.Column("photo_storage_reference", sa.String(length=700), nullable=True))
    op.add_column("persons", sa.Column("photo_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("persons", sa.Column("photo_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("persons", "photo_updated_at")
    op.drop_column("persons", "photo_size_bytes")
    op.drop_column("persons", "photo_storage_reference")
    op.drop_column("persons", "photo_content_type")
    op.drop_column("persons", "photo_filename")
