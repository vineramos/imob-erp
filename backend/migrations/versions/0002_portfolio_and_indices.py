"""portfolio and economic index tables

Revision ID: 0002_portfolio_and_indices
Revises: 0001_foundation
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_portfolio_and_indices"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("document_number", sa.String(length=24), nullable=True),
        sa.Column("email", sa.String(length=180), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("address", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "document_number", name="uq_persons_org_document"),
    )
    op.create_index("ix_persons_organization_id", "persons", ["organization_id"], unique=False)
    op.create_index("ix_persons_name", "persons", ["name"], unique=False)
    op.create_index("ix_persons_document_number", "persons", ["document_number"], unique=False)

    op.create_table(
        "person_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_key", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "role_key", name="uq_person_roles_person_role"),
    )
    op.create_index("ix_person_roles_role_key", "person_roles", ["role_key"], unique=False)

    op.create_table(
        "properties",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_type", sa.String(length=50), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("address", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rent_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("condo_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("iptu_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("area_m2", sa.Numeric(12, 2), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=False),
        sa.Column("suites", sa.Integer(), nullable=False),
        sa.Column("bathrooms", sa.Integer(), nullable=False),
        sa.Column("parking_spaces", sa.Integer(), nullable=False),
        sa.Column("furnished", sa.Boolean(), nullable=False),
        sa.Column("pets_allowed", sa.Boolean(), nullable=False),
        sa.Column("public_title", sa.String(length=180), nullable=True),
        sa.Column("public_description", sa.Text(), nullable=True),
        sa.Column("publication_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_number"),
    )
    op.create_index("ix_properties_organization_id", "properties", ["organization_id"], unique=False)
    op.create_index("ix_properties_status", "properties", ["status"], unique=False)
    op.create_index("ix_properties_property_type", "properties", ["property_type"], unique=False)

    op.create_table(
        "property_owners",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ownership_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("property_id", "person_id", name="uq_property_owners_property_person"),
    )

    op.create_table(
        "captures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column("contact_person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("responsible_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("converted_property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_type", sa.String(length=50), nullable=True),
        sa.Column("property_address", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("estimated_rent", sa.Numeric(14, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("lost_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contact_person_id"], ["persons.id"]),
        sa.ForeignKeyConstraint(["converted_property_id"], ["properties.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["app_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_captures_organization_id", "captures", ["organization_id"], unique=False)
    op.create_index("ix_captures_status", "captures", ["status"], unique=False)

    op.create_table(
        "economic_index_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_code", sa.String(length=20), nullable=False),
        sa.Column("sgs_code", sa.Integer(), nullable=False),
        sa.Column("competence", sa.Date(), nullable=False),
        sa.Column("monthly_rate", sa.Numeric(12, 6), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("index_code", "competence", name="uq_economic_index_code_competence"),
    )
    op.create_index("ix_economic_index_values_index_code", "economic_index_values", ["index_code"], unique=False)
    op.create_index("ix_economic_index_values_competence", "economic_index_values", ["competence"], unique=False)

    op.create_table(
        "economic_index_sync_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_code", sa.String(length=20), nullable=False),
        sa.Column("last_success_competence", sa.Date(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("index_code"),
    )


def downgrade() -> None:
    op.drop_table("economic_index_sync_state")
    op.drop_index("ix_economic_index_values_competence", table_name="economic_index_values")
    op.drop_index("ix_economic_index_values_index_code", table_name="economic_index_values")
    op.drop_table("economic_index_values")
    op.drop_index("ix_captures_status", table_name="captures")
    op.drop_index("ix_captures_organization_id", table_name="captures")
    op.drop_table("captures")
    op.drop_table("property_owners")
    op.drop_index("ix_properties_property_type", table_name="properties")
    op.drop_index("ix_properties_status", table_name="properties")
    op.drop_index("ix_properties_organization_id", table_name="properties")
    op.drop_table("properties")
    op.drop_index("ix_person_roles_role_key", table_name="person_roles")
    op.drop_table("person_roles")
    op.drop_index("ix_persons_document_number", table_name="persons")
    op.drop_index("ix_persons_name", table_name="persons")
    op.drop_index("ix_persons_organization_id", table_name="persons")
    op.drop_table("persons")
