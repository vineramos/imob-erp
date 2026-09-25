"""commission batches and broker billing identity

Revision ID: 0046_commission_payment_batches
Revises: 0045_crm_manual_activities
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0046_commission_payment_batches"
down_revision = "0045_crm_manual_activities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("billing_legal_name", sa.String(length=180), nullable=True))
    op.add_column("persons", sa.Column("billing_document_number", sa.String(length=24), nullable=True))
    op.create_index("ix_persons_billing_document_number", "persons", ["billing_document_number"], unique=False)

    op.create_table(
        "commission_payment_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("beneficiary_person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("beneficiary_name", sa.String(length=180), nullable=False),
        sa.Column("competence", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("broker_legal_name", sa.String(length=180), nullable=True),
        sa.Column("broker_document_number", sa.String(length=24), nullable=True),
        sa.Column("organization_legal_name", sa.String(length=180), nullable=False),
        sa.Column("organization_document_number", sa.String(length=24), nullable=True),
        sa.Column("service_description", sa.Text(), nullable=False),
        sa.Column("report_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invoice_reference", sa.String(length=700), nullable=True),
        sa.Column("invoice_filename", sa.String(length=240), nullable=True),
        sa.Column("invoice_uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finance_review_notes", sa.Text(), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_due_date", sa.Date(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(length=180), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["beneficiary_person_id"], ["persons.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_number"),
        sa.UniqueConstraint("organization_id", "beneficiary_person_id", "competence", name="uq_commission_batch_org_beneficiary_competence"),
    )
    op.create_index("ix_commission_payment_batches_organization_id", "commission_payment_batches", ["organization_id"], unique=False)
    op.create_index("ix_commission_payment_batches_beneficiary_person_id", "commission_payment_batches", ["beneficiary_person_id"], unique=False)
    op.create_index("ix_commission_payment_batches_competence", "commission_payment_batches", ["competence"], unique=False)
    op.create_index("ix_commission_payment_batches_status", "commission_payment_batches", ["status"], unique=False)
    op.create_index("ix_commission_payment_batches_payment_due_date", "commission_payment_batches", ["payment_due_date"], unique=False)
    op.create_index("ix_commission_payment_batches_paid_at", "commission_payment_batches", ["paid_at"], unique=False)

    op.create_table(
        "commission_payment_batch_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commission_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["commission_payment_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["commission_entry_id"], ["commission_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("commission_entry_id", name="uq_commission_batch_item_entry"),
    )
    op.create_index("ix_commission_payment_batch_items_organization_id", "commission_payment_batch_items", ["organization_id"], unique=False)
    op.create_index("ix_commission_payment_batch_items_batch_id", "commission_payment_batch_items", ["batch_id"], unique=False)
    op.create_index("ix_commission_payment_batch_items_commission_entry_id", "commission_payment_batch_items", ["commission_entry_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_commission_payment_batch_items_commission_entry_id", table_name="commission_payment_batch_items")
    op.drop_index("ix_commission_payment_batch_items_batch_id", table_name="commission_payment_batch_items")
    op.drop_index("ix_commission_payment_batch_items_organization_id", table_name="commission_payment_batch_items")
    op.drop_table("commission_payment_batch_items")
    op.drop_index("ix_commission_payment_batches_paid_at", table_name="commission_payment_batches")
    op.drop_index("ix_commission_payment_batches_payment_due_date", table_name="commission_payment_batches")
    op.drop_index("ix_commission_payment_batches_status", table_name="commission_payment_batches")
    op.drop_index("ix_commission_payment_batches_competence", table_name="commission_payment_batches")
    op.drop_index("ix_commission_payment_batches_beneficiary_person_id", table_name="commission_payment_batches")
    op.drop_index("ix_commission_payment_batches_organization_id", table_name="commission_payment_batches")
    op.drop_table("commission_payment_batches")
    op.drop_index("ix_persons_billing_document_number", table_name="persons")
    op.drop_column("persons", "billing_document_number")
    op.drop_column("persons", "billing_legal_name")
