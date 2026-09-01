"""person bank details

Revision ID: 0019_person_bank_details
Revises: 0018_finance_definitive_suite
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_person_bank_details"
down_revision: str | None = "0018_finance_definitive_suite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person_bank_details",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bank_name", sa.String(120)),
        sa.Column("bank_code", sa.String(10)),
        sa.Column("branch", sa.String(30)),
        sa.Column("account_number", sa.String(40)),
        sa.Column("account_digit", sa.String(10)),
        sa.Column("account_type", sa.String(20), nullable=False, server_default="checking"),
        sa.Column("pix_key_type", sa.String(20), nullable=False, server_default="none"),
        sa.Column("pix_key", sa.String(180)),
        sa.Column("account_holder_name", sa.String(180)),
        sa.Column("account_holder_document", sa.String(24)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("person_id", name="uq_person_bank_details_person"),
    )
    op.create_index("ix_person_bank_details_organization_id", "person_bank_details", ["organization_id"], unique=False)
    op.create_index("ix_person_bank_details_person_id", "person_bank_details", ["person_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_person_bank_details_person_id", table_name="person_bank_details")
    op.drop_index("ix_person_bank_details_organization_id", table_name="person_bank_details")
    op.drop_table("person_bank_details")
