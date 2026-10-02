"""maintenance partners and quote issuers

Revision ID: 0013_maintenance_partners
Revises: 0012_document_storage_fallback
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_maintenance_partners"
down_revision: str | None = "0012_document_storage_fallback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "maintenance_partners",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("legal_name", sa.String(length=220), nullable=True),
        sa.Column("document_number", sa.String(length=24), nullable=True),
        sa.Column("contact_name", sa.String(length=180), nullable=True),
        sa.Column("email", sa.String(length=180), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("whatsapp", sa.String(length=40), nullable=True),
        sa.Column("address", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("specialties", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("pix_key", sa.String(length=180), nullable=True),
        sa.Column("bank_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("logo_storage_reference", sa.String(length=700), nullable=True),
        sa.Column("logo_content_type", sa.String(length=80), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "document_number", name="uq_maintenance_partners_org_document"),
    )
    op.create_index("ix_maintenance_partners_org", "maintenance_partners", ["organization_id"])
    op.create_index("ix_maintenance_partners_name", "maintenance_partners", ["name"])
    op.create_index("ix_maintenance_partners_document", "maintenance_partners", ["document_number"])
    op.create_index("ix_maintenance_partners_active", "maintenance_partners", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_maintenance_partners_active", table_name="maintenance_partners")
    op.drop_index("ix_maintenance_partners_document", table_name="maintenance_partners")
    op.drop_index("ix_maintenance_partners_name", table_name="maintenance_partners")
    op.drop_index("ix_maintenance_partners_org", table_name="maintenance_partners")
    op.drop_table("maintenance_partners")
