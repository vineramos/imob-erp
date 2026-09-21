"""encrypted integration credentials

Revision ID: 0041_integration_credentials
Revises: 0040_user_invitations
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0041_integration_credentials"
down_revision = "0040_user_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_integration_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("non_secret_config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("encrypted_secret", sa.Text()),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "provider", name="uq_org_integration_credential_provider"),
    )
    op.create_index("ix_org_integration_credentials_org", "organization_integration_credentials", ["organization_id"])


def downgrade() -> None:
    op.drop_table("organization_integration_credentials")
