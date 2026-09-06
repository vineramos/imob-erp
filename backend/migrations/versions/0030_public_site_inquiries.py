"""public site inquiries

Revision ID: 0030_public_site_inquiries
Revises: 0029_portal_temporary_passwords
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0030_public_site_inquiries"
down_revision = "0029_portal_temporary_passwords"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_site_inquiries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_code", sa.String(length=24), nullable=False),
        sa.Column("property_title", sa.String(length=180), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=180), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("preferred_contact", sa.String(length=24), nullable=False, server_default="whatsapp"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="public_site"),
        sa.Column("requester_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_public_site_inquiries_organization_id", "public_site_inquiries", ["organization_id"])
    op.create_index("ix_public_site_inquiries_property_id", "public_site_inquiries", ["property_id"])
    op.create_index("ix_public_site_inquiries_status", "public_site_inquiries", ["status"])
    op.create_index("ix_public_site_inquiries_requester_ip", "public_site_inquiries", ["requester_ip"])
    op.create_index("ix_public_site_inquiries_created_at", "public_site_inquiries", ["created_at"])
    op.create_index(
        "ix_public_site_inquiries_org_status_created",
        "public_site_inquiries",
        ["organization_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("public_site_inquiries")
