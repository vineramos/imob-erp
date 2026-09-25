"""definitive finance suite

Revision ID: 0018_finance_definitive_suite
Revises: 0017_finance_treasury
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_finance_definitive_suite"
down_revision: str | None = "0017_finance_treasury"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)


def upgrade() -> None:
    op.create_table(
        "billing_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("competence", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="generated"),
        sa.Column("provider", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("generated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("issued_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "competence", name="uq_billing_batches_org_competence"),
    )
    _index("billing_batches", "organization_id", "competence", "status", "provider")

    op.create_table(
        "billing_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("billing_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("billing_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("charge_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("provider_charge_id", sa.String(180)),
        sa.Column("provider_status", sa.String(60)),
        sa.Column("boleto_line", sa.String(180)),
        sa.Column("barcode", sa.String(180)),
        sa.Column("pix_copy_paste", sa.Text()),
        sa.Column("pix_txid", sa.String(180)),
        sa.Column("pdf_reference", sa.String(700)),
        sa.Column("request_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("billing_batch_id", "charge_id", name="uq_billing_items_batch_charge"),
        sa.UniqueConstraint("charge_id", name="uq_billing_items_charge"),
    )
    _index("billing_items", "organization_id", "billing_batch_id", "charge_id", "provider", "provider_charge_id", "provider_status", "issued_at", "sent_at", "confirmed_at")

    op.create_table(
        "delinquency_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("charge_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("critical_after_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("critical_at", sa.DateTime(timezone=True)),
        sa.Column("last_contact_at", sa.DateTime(timezone=True)),
        sa.Column("next_action_at", sa.DateTime(timezone=True)),
        sa.Column("insurer_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("insurer_protocol", sa.String(180)),
        sa.Column("assigned_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id")),
        sa.Column("notes", sa.Text()),
        sa.Column("action_log", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    _index("delinquency_cases", "organization_id", "charge_id", "property_id", "lease_contract_id", "status", "critical_at", "next_action_at", "insurer_triggered_at", "assigned_user_id", "resolved_at")

    op.create_table(
        "commission_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False, server_default="first_rent"),
        sa.Column("basis", sa.String(40), nullable=False, server_default="agency_revenue"),
        sa.Column("calculation_type", sa.String(20), nullable=False, server_default="percent"),
        sa.Column("value", sa.Numeric(14, 4), nullable=False),
        sa.Column("beneficiary_type", sa.String(40), nullable=False, server_default="broker"),
        sa.Column("beneficiary_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("beneficiary_name", sa.String(180), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id")),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id")),
        sa.Column("due_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    _index("commission_rules", "organization_id", "event_type", "basis", "beneficiary_type", "beneficiary_person_id", "property_id", "lease_contract_id", "is_active")

    op.create_table(
        "commission_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("commission_rules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_code", sa.String(80), nullable=False),
        sa.Column("charge_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rent_charges.id", ondelete="SET NULL")),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lease_contracts.id", ondelete="SET NULL")),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("properties.id", ondelete="SET NULL")),
        sa.Column("beneficiary_type", sa.String(40), nullable=False),
        sa.Column("beneficiary_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("beneficiary_name", sa.String(180), nullable=False),
        sa.Column("competence", sa.Date(), nullable=False),
        sa.Column("basis_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("financial_title_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("financial_titles.id", ondelete="SET NULL"), unique=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("payment_reference", sa.String(180)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("rule_id", "source_type", "source_id", name="uq_commission_entry_rule_source"),
    )
    _index("commission_entries", "organization_id", "rule_id", "source_type", "source_id", "charge_id", "lease_contract_id", "property_id", "beneficiary_type", "beneficiary_person_id", "competence", "due_date", "status", "financial_title_id", "paid_at")

    op.create_table(
        "portal_accesses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portal_type", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(160)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    _index("portal_accesses", "organization_id", "person_id", "portal_type", "token_hash", "is_active", "expires_at", "revoked_at")

    op.create_table(
        "inter_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id")),
        sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("event_type", sa.String(80), nullable=False, server_default="billing"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(30), nullable=False, server_default="received"),
        sa.Column("error", sa.Text()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    _index("inter_webhook_events", "organization_id", "event_hash", "event_type", "status", "processed_at")


def downgrade() -> None:
    op.drop_table("inter_webhook_events")
    op.drop_table("portal_accesses")
    op.drop_table("commission_entries")
    op.drop_table("commission_rules")
    op.drop_table("delinquency_cases")
    op.drop_table("billing_items")
    op.drop_table("billing_batches")
