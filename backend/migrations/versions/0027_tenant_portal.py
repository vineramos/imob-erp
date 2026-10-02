"""tenant portal authentication

Revision ID: 0027_tenant_portal
Revises: 0026_lease_lifecycle
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0027_tenant_portal"
down_revision = "0026_lease_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("portal_access_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=180), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["portal_access_id"], ["portal_accesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", name="uq_portal_accounts_person"),
        sa.UniqueConstraint("portal_access_id", name="uq_portal_accounts_access"),
        sa.UniqueConstraint("email", name="uq_portal_accounts_email"),
    )
    op.create_index("ix_portal_accounts_organization_id", "portal_accounts", ["organization_id"])
    op.create_index("ix_portal_accounts_email", "portal_accounts", ["email"])
    op.create_index("ix_portal_accounts_is_active", "portal_accounts", ["is_active"])
    op.create_index("ix_portal_accounts_locked_until", "portal_accounts", ["locked_until"])
    op.create_index("ix_portal_accounts_last_login_at", "portal_accounts", ["last_login_at"])

    op.create_table(
        "portal_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["account_id"], ["portal_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_portal_sessions_token_hash"),
    )
    op.create_index("ix_portal_sessions_account_id", "portal_sessions", ["account_id"])
    op.create_index("ix_portal_sessions_token_hash", "portal_sessions", ["token_hash"])
    op.create_index("ix_portal_sessions_expires_at", "portal_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("portal_sessions")
    op.drop_table("portal_accounts")
