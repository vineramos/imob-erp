"""persist bank reconciliation exceptions

Revision ID: 0037_bank_reconciliation_exceptions
Revises: 0036_property_map_locations
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0037_bank_reconciliation_exceptions"
down_revision = "0036_property_map_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_reconciliation_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="exception"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("reason_label", sa.String(length=500), nullable=False),
        sa.Column("candidate_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("top_candidate_code", sa.String(length=80)),
        sa.Column("top_candidate_score", sa.BigInteger()),
        sa.Column("matched_identifier", sa.String(length=180)),
        sa.Column("resolution_note", sa.Text()),
        sa.Column("ignored_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bank_transaction_id"], ["bank_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ignored_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["app_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_transaction_id", name="uq_bank_reconciliation_exceptions_transaction"),
    )
    op.create_index(
        "ix_bank_reconciliation_exceptions_organization_id",
        "bank_reconciliation_exceptions",
        ["organization_id"],
    )
    op.create_index(
        "ix_bank_reconciliation_exceptions_bank_transaction_id",
        "bank_reconciliation_exceptions",
        ["bank_transaction_id"],
    )
    op.create_index(
        "ix_bank_reconciliation_exceptions_reason",
        "bank_reconciliation_exceptions",
        ["reason"],
    )
    op.create_index(
        "ix_bank_reconciliation_exceptions_severity",
        "bank_reconciliation_exceptions",
        ["severity"],
    )
    op.create_index(
        "ix_bank_reconciliation_exceptions_status",
        "bank_reconciliation_exceptions",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_bank_reconciliation_exceptions_status", table_name="bank_reconciliation_exceptions")
    op.drop_index("ix_bank_reconciliation_exceptions_severity", table_name="bank_reconciliation_exceptions")
    op.drop_index("ix_bank_reconciliation_exceptions_reason", table_name="bank_reconciliation_exceptions")
    op.drop_index("ix_bank_reconciliation_exceptions_bank_transaction_id", table_name="bank_reconciliation_exceptions")
    op.drop_index("ix_bank_reconciliation_exceptions_organization_id", table_name="bank_reconciliation_exceptions")
    op.drop_table("bank_reconciliation_exceptions")
