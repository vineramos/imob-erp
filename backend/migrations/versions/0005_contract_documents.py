"""contract document lifecycle

Revision ID: 0005_contract_documents
Revises: 0004_signature_and_publication
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_contract_documents"
down_revision: str | None = "0004_signature_and_publication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("administration_contracts", sa.Column("generated_document_reference", sa.String(length=500), nullable=True))
    op.add_column("administration_contracts", sa.Column("generated_document_hash", sa.String(length=64), nullable=True))
    op.add_column("administration_contracts", sa.Column("generated_document_version", sa.Integer(), nullable=True))
    op.add_column("administration_contracts", sa.Column("signing_document_id", sa.String(length=180), nullable=True))
    op.add_column(
        "administration_contracts",
        sa.Column("archive_status", sa.String(length=40), server_default="not_started", nullable=False),
    )
    op.add_column("administration_contracts", sa.Column("final_document_hash", sa.String(length=64), nullable=True))
    op.add_column("administration_contracts", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("administration_contracts", "archived_at")
    op.drop_column("administration_contracts", "final_document_hash")
    op.drop_column("administration_contracts", "archive_status")
    op.drop_column("administration_contracts", "signing_document_id")
    op.drop_column("administration_contracts", "generated_document_version")
    op.drop_column("administration_contracts", "generated_document_hash")
    op.drop_column("administration_contracts", "generated_document_reference")
