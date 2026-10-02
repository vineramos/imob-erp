"""commercial funnel visits proposals and lease conversion

Revision ID: 0031_commercial_funnel
Revises: 0030_public_site_inquiries
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0031_commercial_funnel"
down_revision = "0030_public_site_inquiries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("public_site_inquiries", sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("public_site_inquiries", sa.Column("responsible_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_public_site_inquiries_person_id", "public_site_inquiries", "persons", ["person_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_public_site_inquiries_responsible_user_id", "public_site_inquiries", "app_users", ["responsible_user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_public_site_inquiries_person_id", "public_site_inquiries", ["person_id"])
    op.create_index("ix_public_site_inquiries_responsible_user_id", "public_site_inquiries", ["responsible_user_id"])

    op.create_table(
        "commercial_visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inquiry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agenda_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("responsible_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="scheduled"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inquiry_id"], ["public_site_inquiries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agenda_task_id"], ["agenda_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_number"),
        sa.UniqueConstraint("agenda_task_id"),
    )
    for column in ("organization_id", "inquiry_id", "property_id", "person_id", "agenda_task_id", "responsible_user_id", "starts_at", "status"):
        op.create_index(f"ix_commercial_visits_{column}", "commercial_visits", [column])

    op.create_table(
        "commercial_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inquiry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("responsible_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="submitted"),
        sa.Column("rent_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("guarantee_type", sa.String(length=40), nullable=False, server_default="insurance"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("closed_reason", sa.Text(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inquiry_id"], ["public_site_inquiries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lease_contract_id"], ["lease_contracts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_number"),
        sa.UniqueConstraint("lease_contract_id"),
    )
    for column in ("organization_id", "inquiry_id", "property_id", "person_id", "responsible_user_id", "lease_contract_id", "status"):
        op.create_index(f"ix_commercial_proposals_{column}", "commercial_proposals", [column])
    op.create_index("ix_commercial_proposals_property_status", "commercial_proposals", ["organization_id", "property_id", "status"])


def downgrade() -> None:
    op.drop_table("commercial_proposals")
    op.drop_table("commercial_visits")
    op.drop_index("ix_public_site_inquiries_responsible_user_id", table_name="public_site_inquiries")
    op.drop_index("ix_public_site_inquiries_person_id", table_name="public_site_inquiries")
    op.drop_constraint("fk_public_site_inquiries_responsible_user_id", "public_site_inquiries", type_="foreignkey")
    op.drop_constraint("fk_public_site_inquiries_person_id", "public_site_inquiries", type_="foreignkey")
    op.drop_column("public_site_inquiries", "responsible_user_id")
    op.drop_column("public_site_inquiries", "person_id")
