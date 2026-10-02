"""person profiles

Revision ID: 0020_person_profiles
Revises: 0019_person_bank_details
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_person_profiles"
down_revision: str | None = "0019_person_bank_details"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("secondary_phone", sa.String(40)),
        sa.Column("identity_number", sa.String(40)),
        sa.Column("identity_issuer", sa.String(40)),
        sa.Column("birth_date", sa.Date()),
        sa.Column("nationality", sa.String(80)),
        sa.Column("marital_status", sa.String(30)),
        sa.Column("occupation", sa.String(120)),
        sa.Column("trade_name", sa.String(180)),
        sa.Column("state_registration", sa.String(40)),
        sa.Column("municipal_registration", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("person_id", name="uq_person_profiles_person"),
    )
    op.create_index("ix_person_profiles_organization_id", "person_profiles", ["organization_id"], unique=False)
    op.create_index("ix_person_profiles_person_id", "person_profiles", ["person_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_person_profiles_person_id", table_name="person_profiles")
    op.drop_index("ix_person_profiles_organization_id", table_name="person_profiles")
    op.drop_table("person_profiles")
