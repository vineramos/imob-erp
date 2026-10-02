"""lease documents and signing

Revision ID: 0007_lease_documents_and_signing
Revises: 0006_lease_contracts
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_lease_documents_and_signing"
down_revision: str | None = "0006_lease_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lease_contracts",
        sa.Column(
            "signers_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("lease_contracts", sa.Column("generated_document_reference", sa.String(length=500), nullable=True))
    op.add_column("lease_contracts", sa.Column("generated_document_hash", sa.String(length=64), nullable=True))
    op.add_column("lease_contracts", sa.Column("generated_document_version", sa.Integer(), nullable=True))
    op.add_column(
        "lease_contracts",
        sa.Column("signing_provider", sa.String(length=30), nullable=False, server_default="clicksign"),
    )
    op.add_column("lease_contracts", sa.Column("signing_envelope_id", sa.String(length=180), nullable=True))
    op.add_column("lease_contracts", sa.Column("signing_document_id", sa.String(length=180), nullable=True))
    op.add_column(
        "lease_contracts",
        sa.Column(
            "signing_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "lease_contracts",
        sa.Column("signing_status", sa.String(length=60), nullable=False, server_default="not_prepared"),
    )
    op.add_column("lease_contracts", sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "lease_contracts",
        sa.Column("archive_status", sa.String(length=40), nullable=False, server_default="not_started"),
    )
    op.add_column("lease_contracts", sa.Column("archived_document_reference", sa.String(length=500), nullable=True))
    op.add_column("lease_contracts", sa.Column("final_document_hash", sa.String(length=64), nullable=True))
    op.add_column("lease_contracts", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "signature_webhook_events",
        sa.Column("lease_contract_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_signature_webhook_events_lease_contract_id",
        "signature_webhook_events",
        "lease_contracts",
        ["lease_contract_id"],
        ["id"],
    )
    op.create_index(
        "ix_signature_webhook_events_lease_contract_id",
        "signature_webhook_events",
        ["lease_contract_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_signature_webhook_events_lease_contract_id", table_name="signature_webhook_events")
    op.drop_constraint(
        "fk_signature_webhook_events_lease_contract_id",
        "signature_webhook_events",
        type_="foreignkey",
    )
    op.drop_column("signature_webhook_events", "lease_contract_id")

    op.drop_column("lease_contracts", "archived_at")
    op.drop_column("lease_contracts", "final_document_hash")
    op.drop_column("lease_contracts", "archived_document_reference")
    op.drop_column("lease_contracts", "archive_status")
    op.drop_column("lease_contracts", "signed_at")
    op.drop_column("lease_contracts", "signing_status")
    op.drop_column("lease_contracts", "signing_metadata")
    op.drop_column("lease_contracts", "signing_document_id")
    op.drop_column("lease_contracts", "signing_envelope_id")
    op.drop_column("lease_contracts", "signing_provider")
    op.drop_column("lease_contracts", "generated_document_version")
    op.drop_column("lease_contracts", "generated_document_hash")
    op.drop_column("lease_contracts", "generated_document_reference")
    op.drop_column("lease_contracts", "signers_snapshot")
