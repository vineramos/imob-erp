"""tenant portal self service access

Revision ID: 0028_portal_self_service
Revises: 0027_tenant_portal
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0028_portal_self_service"
down_revision = "0027_tenant_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_password_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=180), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False, server_default="first_access"),
        sa.Column("code_hash", sa.String(length=500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portal_password_challenges_organization_id",
        "portal_password_challenges",
        ["organization_id"],
    )
    op.create_index(
        "ix_portal_password_challenges_person_id",
        "portal_password_challenges",
        ["person_id"],
    )
    op.create_index(
        "ix_portal_password_challenges_email",
        "portal_password_challenges",
        ["email"],
    )
    op.create_index(
        "ix_portal_password_challenges_purpose",
        "portal_password_challenges",
        ["purpose"],
    )
    op.create_index(
        "ix_portal_password_challenges_expires_at",
        "portal_password_challenges",
        ["expires_at"],
    )
    op.create_index(
        "ix_portal_password_challenges_used_at",
        "portal_password_challenges",
        ["used_at"],
    )
    op.create_index(
        "ix_portal_password_challenges_created_at",
        "portal_password_challenges",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("portal_password_challenges")
