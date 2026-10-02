"""tenant portal temporary passwords

Revision ID: 0029_portal_temporary_passwords
Revises: 0028_portal_self_service
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0029_portal_temporary_passwords"
down_revision = "0028_portal_self_service"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_temporary_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("portal_access_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("change_token_hash", sa.String(length=64), nullable=True),
        sa.Column("change_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["portal_access_id"], ["portal_accesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portal_temporary_credentials_organization_id", "portal_temporary_credentials", ["organization_id"])
    op.create_index("ix_portal_temporary_credentials_person_id", "portal_temporary_credentials", ["person_id"])
    op.create_index("ix_portal_temporary_credentials_portal_access_id", "portal_temporary_credentials", ["portal_access_id"])
    op.create_index("ix_portal_temporary_credentials_expires_at", "portal_temporary_credentials", ["expires_at"])
    op.create_index("ix_portal_temporary_credentials_change_token_hash", "portal_temporary_credentials", ["change_token_hash"])
    op.create_index("ix_portal_temporary_credentials_change_token_expires_at", "portal_temporary_credentials", ["change_token_expires_at"])
    op.create_index("ix_portal_temporary_credentials_used_at", "portal_temporary_credentials", ["used_at"])
    op.create_index("ix_portal_temporary_credentials_created_at", "portal_temporary_credentials", ["created_at"])


def downgrade() -> None:
    op.drop_table("portal_temporary_credentials")
