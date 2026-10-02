"""multi-bank account setup foundation

Revision ID: 0032_multibank_foundation
Revises: 0031_commercial_funnel
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0032_multibank_foundation"
down_revision = "0031_commercial_funnel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_account_setups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_key", sa.String(length=40), nullable=False),
        sa.Column("account_purpose", sa.String(length=40), nullable=False),
        sa.Column("integration_mode", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("provider_key", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("environment", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("provider_account_id", sa.String(length=180), nullable=True),
        sa.Column("credential_secret_ref", sa.String(length=300), nullable=True),
        sa.Column("certificate_secret_ref", sa.String(length=300), nullable=True),
        sa.Column("webhook_secret_ref", sa.String(length=300), nullable=True),
        sa.Column("non_secret_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled_capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="manual_ready"),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=40), nullable=True),
        sa.Column("last_test_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_account_id", name="uq_bank_account_setups_bank_account_id"),
    )
    op.create_index("ix_bank_account_setups_organization_id", "bank_account_setups", ["organization_id"])
    op.create_index("ix_bank_account_setups_bank_account_id", "bank_account_setups", ["bank_account_id"])
    op.create_index("ix_bank_account_setups_institution_key", "bank_account_setups", ["institution_key"])
    op.create_index("ix_bank_account_setups_account_purpose", "bank_account_setups", ["account_purpose"])
    op.create_index("ix_bank_account_setups_integration_mode", "bank_account_setups", ["integration_mode"])
    op.create_index("ix_bank_account_setups_provider_key", "bank_account_setups", ["provider_key"])
    op.create_index("ix_bank_account_setups_status", "bank_account_setups", ["status"])


def downgrade() -> None:
    op.drop_table("bank_account_setups")
