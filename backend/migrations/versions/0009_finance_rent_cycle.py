"""finance rent cycle

Revision ID: 0009_finance_rent_cycle
Revises: 0008_initial_inspections_keys
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_finance_rent_cycle"
down_revision: str | None = "0008_initial_inspections_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rent_charges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("competence", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="generated"),
        sa.Column("rent_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("gross_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("charge_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("tenant_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("property_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("owner_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("admin_terms_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("payment_method", sa.String(length=40), nullable=True),
        sa.Column("payment_reference", sa.String(length=180), nullable=True),
        sa.Column("payment_notes", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("lease_contract_id", "competence", name="uq_rent_charges_lease_competence"),
    )
    for column in ("organization_id", "lease_contract_id", "property_id", "competence", "due_date", "status", "paid_at"):
        op.create_index(f"ix_rent_charges_{column}", "rent_charges", [column], unique=False)

    op.create_table(
        "financial_settlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("charge_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("administration_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("administration_contracts.id"), nullable=True),
        sa.Column("admin_fee_calculated", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("intermediation_fee_calculated", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("agency_fee_withheld", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("agency_reimbursement_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("owner_entitlement_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("third_party_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("organization_id", "charge_id", "lease_contract_id", "property_id", "administration_contract_id"):
        op.create_index(f"ix_financial_settlements_{column}", "financial_settlements", [column], unique=column == "charge_id")

    op.create_table(
        "owner_repasses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("settlement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("financial_settlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("charge_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("owner_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("owner_name", sa.String(length=180), nullable=False),
        sa.Column("ownership_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(length=180), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("settlement_id", "owner_person_id", name="uq_owner_repasses_settlement_owner"),
    )
    for column in ("organization_id", "settlement_id", "charge_id", "lease_contract_id", "property_id", "owner_person_id", "due_date", "status", "paid_at"):
        op.create_index(f"ix_owner_repasses_{column}", "owner_repasses", [column], unique=False)


def downgrade() -> None:
    op.drop_table("owner_repasses")
    op.drop_table("financial_settlements")
    op.drop_table("rent_charges")
