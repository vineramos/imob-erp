"""administration contract closure lifecycle

Revision ID: 0054_admin_contract_closure
Revises: 0053_repair_first_intermediation
"""
from alembic import op
import sqlalchemy as sa

revision = "0054_admin_contract_closure"
down_revision = "0053_repair_first_intermediation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("administration_contracts", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("administration_contracts", sa.Column("closed_by_user_id", sa.UUID(), nullable=True))
    op.add_column("administration_contracts", sa.Column("closure_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_admin_contracts_closed_by_user",
        "administration_contracts",
        "app_users",
        ["closed_by_user_id"],
        ["id"],
    )
    op.create_index("ix_administration_contracts_closed_at", "administration_contracts", ["closed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_administration_contracts_closed_at", table_name="administration_contracts")
    op.drop_constraint("fk_admin_contracts_closed_by_user", "administration_contracts", type_="foreignkey")
    op.drop_column("administration_contracts", "closure_reason")
    op.drop_column("administration_contracts", "closed_by_user_id")
    op.drop_column("administration_contracts", "closed_at")
