"""default legal representative for organization

Revision ID: 0052_company_representative
Revises: 0051_instagram_publication
"""
from alembic import op
import sqlalchemy as sa

revision = "0052_company_representative"
down_revision = "0051_instagram_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("representative_name", sa.String(length=180), nullable=True))
    op.add_column("organizations", sa.Column("representative_email", sa.String(length=180), nullable=True))
    op.add_column("organizations", sa.Column("representative_document_number", sa.String(length=24), nullable=True))
    op.add_column("organizations", sa.Column("representative_phone", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "representative_phone")
    op.drop_column("organizations", "representative_document_number")
    op.drop_column("organizations", "representative_email")
    op.drop_column("organizations", "representative_name")
