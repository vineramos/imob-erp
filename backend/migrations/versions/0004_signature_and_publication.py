"""signature audit and public publication

Revision ID: 0004_signature_and_publication
Revises: 0003_administration_contracts
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_signature_and_publication"
down_revision: str | None = "0003_administration_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administration_contracts",
        sa.Column("signers_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.alter_column("administration_contracts", "signing_status", type_=sa.String(length=60), existing_type=sa.String(length=40))

    op.create_table(
        "signature_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("event_name", sa.String(length=120), nullable=False),
        sa.Column("event_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("envelope_id", sa.String(length=180), nullable=True),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hmac_valid", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["administration_contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signature_webhook_events_provider", "signature_webhook_events", ["provider"], unique=False)
    op.create_index("ix_signature_webhook_events_event_name", "signature_webhook_events", ["event_name"], unique=False)
    op.create_index("ix_signature_webhook_events_event_fingerprint", "signature_webhook_events", ["event_fingerprint"], unique=True)
    op.create_index("ix_signature_webhook_events_envelope_id", "signature_webhook_events", ["envelope_id"], unique=False)
    op.create_index("ix_signature_webhook_events_contract_id", "signature_webhook_events", ["contract_id"], unique=False)
    op.create_index("ix_signature_webhook_events_received_at", "signature_webhook_events", ["received_at"], unique=False)

    op.add_column("properties", sa.Column("public_slug", sa.String(length=180), nullable=True))
    op.add_column("properties", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("properties", sa.Column("publication_updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_properties_publication_updated_by_user_id_app_users",
        "properties",
        "app_users",
        ["publication_updated_by_user_id"],
        ["id"],
    )
    op.create_index("ix_properties_public_slug", "properties", ["public_slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_properties_public_slug", table_name="properties")
    op.drop_constraint("fk_properties_publication_updated_by_user_id_app_users", "properties", type_="foreignkey")
    op.drop_column("properties", "publication_updated_by_user_id")
    op.drop_column("properties", "published_at")
    op.drop_column("properties", "public_slug")

    op.drop_index("ix_signature_webhook_events_received_at", table_name="signature_webhook_events")
    op.drop_index("ix_signature_webhook_events_contract_id", table_name="signature_webhook_events")
    op.drop_index("ix_signature_webhook_events_envelope_id", table_name="signature_webhook_events")
    op.drop_index("ix_signature_webhook_events_event_fingerprint", table_name="signature_webhook_events")
    op.drop_index("ix_signature_webhook_events_event_name", table_name="signature_webhook_events")
    op.drop_index("ix_signature_webhook_events_provider", table_name="signature_webhook_events")
    op.drop_table("signature_webhook_events")

    op.alter_column("administration_contracts", "signing_status", type_=sa.String(length=40), existing_type=sa.String(length=60))
    op.drop_column("administration_contracts", "signers_snapshot")
