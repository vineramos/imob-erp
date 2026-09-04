"""reports foundation and export permission

Revision ID: 0024_reports_foundation
Revises: 0023_agenda_intelligence
Create Date: 2026-09-04
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_reports_foundation"
down_revision: str | None = "0023_agenda_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

permission_table = sa.table(
    "permissions",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("key", sa.String()),
    sa.column("module", sa.String()),
    sa.column("name", sa.String()),
    sa.column("description", sa.Text()),
)
role_permission_table = sa.table(
    "role_permissions",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("role_id", postgresql.UUID(as_uuid=True)),
    sa.column("permission_id", postgresql.UUID(as_uuid=True)),
)


def upgrade() -> None:
    connection = op.get_bind()
    permission_id = connection.execute(
        sa.text("SELECT id FROM permissions WHERE key = 'reports.export'")
    ).scalar_one_or_none()
    if permission_id is None:
        permission_id = uuid.uuid4()
        op.bulk_insert(
            permission_table,
            [{
                "id": permission_id,
                "key": "reports.export",
                "module": "reports",
                "name": "Exportar relatórios",
                "description": "Permite exportar relatórios autorizados em PDF ou CSV.",
            }],
        )

    role_ids = connection.execute(
        sa.text(
            "SELECT id FROM roles WHERE is_active = true "
            "AND key IN ('admin', 'administrative', 'finance')"
        )
    ).scalars().all()
    for role_id in role_ids:
        exists = connection.execute(
            sa.text(
                "SELECT 1 FROM role_permissions "
                "WHERE role_id = :role_id AND permission_id = :permission_id"
            ),
            {"role_id": role_id, "permission_id": permission_id},
        ).scalar_one_or_none()
        if exists is None:
            op.bulk_insert(
                role_permission_table,
                [{"id": uuid.uuid4(), "role_id": role_id, "permission_id": permission_id}],
            )


def downgrade() -> None:
    connection = op.get_bind()
    permission_id = connection.execute(
        sa.text("SELECT id FROM permissions WHERE key = 'reports.export'")
    ).scalar_one_or_none()
    if permission_id is None:
        return
    connection.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_id = :permission_id"),
        {"permission_id": permission_id},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE id = :permission_id"),
        {"permission_id": permission_id},
    )
