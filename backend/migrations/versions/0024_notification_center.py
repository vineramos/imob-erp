"""notification center read state

Revision ID: 0024_notification_center
Revises: 0023_agenda_intelligence
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_notification_center"
down_revision: str | None = "0023_agenda_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_notification_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notification_key", sa.String(240), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "notification_key", name="uq_user_notification_states_user_key"),
    )
    op.create_index("ix_user_notification_states_organization_id", "user_notification_states", ["organization_id"], unique=False)
    op.create_index("ix_user_notification_states_user_id", "user_notification_states", ["user_id"], unique=False)
    op.create_index("ix_user_notification_states_read_at", "user_notification_states", ["read_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_notification_states_read_at", table_name="user_notification_states")
    op.drop_index("ix_user_notification_states_user_id", table_name="user_notification_states")
    op.drop_index("ix_user_notification_states_organization_id", table_name="user_notification_states")
    op.drop_table("user_notification_states")
