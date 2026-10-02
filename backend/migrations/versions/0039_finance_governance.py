"""finance governance permissions and segregated roles

Revision ID: 0039_fin_governance
Revises: 0038_fin_monthly_closure
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0039_fin_governance"
down_revision = "0038_fin_monthly_closure"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("finance.payment.execute", "finance", "Executar pagamentos", "Permite registrar a execução de lotes aprovados por outro usuário."),
    ("finance.period.close", "finance", "Fechar competência", "Permite confirmar o fechamento mensal quando o checklist estiver limpo."),
    ("finance.period.reopen", "finance", "Reabrir competência", "Permite reabrir competência fechada com justificativa obrigatória."),
    ("finance.adjustment.create", "finance", "Criar ajustes financeiros", "Permite classificar diferenças e ajustes financeiros manuais."),
    ("finance.sod.override", "finance", "Exceção de segregação", "Permite, em caráter excepcional e justificado, ultrapassar conflito de segregação de funções."),
)

ROLE_DEFINITIONS = {
    "finance_approver": {
        "name": "Aprovador financeiro",
        "description": "Aprovação de pagamentos e fechamento de competência, separado da preparação.",
        "permissions": {"finance.view", "finance.payment.approve", "finance.period.close", "reports.view", "audit.view"},
    },
    "finance_executor": {
        "name": "Executor financeiro",
        "description": "Execução de pagamentos já aprovados e consulta operacional.",
        "permissions": {"finance.view", "finance.payment.execute", "reports.view"},
    },
    "finance_controller": {
        "name": "Controladoria financeira",
        "description": "Reabertura de competências e exceções de segregação com justificativa auditada.",
        "permissions": {"finance.view", "finance.period.reopen", "finance.sod.override", "reports.view", "reports.export", "audit.view"},
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    meta = sa.MetaData()
    permissions = sa.Table(
        "permissions",
        meta,
        sa.Column("id", postgresql.UUID(as_uuid=True)),
        sa.Column("key", sa.String()),
        sa.Column("module", sa.String()),
        sa.Column("name", sa.String()),
        sa.Column("description", sa.Text()),
    )
    roles = sa.Table(
        "roles",
        meta,
        sa.Column("id", postgresql.UUID(as_uuid=True)),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True)),
        sa.Column("key", sa.String()),
        sa.Column("name", sa.String()),
        sa.Column("description", sa.Text()),
        sa.Column("is_system", sa.Boolean()),
        sa.Column("is_active", sa.Boolean()),
    )
    role_permissions = sa.Table(
        "role_permissions",
        meta,
        sa.Column("id", postgresql.UUID(as_uuid=True)),
        sa.Column("role_id", postgresql.UUID(as_uuid=True)),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True)),
    )

    existing = {
        row.key: row.id
        for row in bind.execute(sa.select(permissions.c.id, permissions.c.key)).all()
    }
    for key, module, name, description in PERMISSIONS:
        if key not in existing:
            permission_id = uuid.uuid4()
            bind.execute(
                permissions.insert().values(
                    id=permission_id,
                    key=key,
                    module=module,
                    name=name,
                    description=description,
                )
            )
            existing[key] = permission_id

    # Administradores existentes recebem as novas permissões para não perderem acesso.
    admin_roles = bind.execute(sa.select(roles.c.id).where(roles.c.key == "admin")).scalars().all()
    new_permission_ids = [existing[key] for key, *_ in PERMISSIONS]
    for role_id in admin_roles:
        assigned = set(
            bind.execute(
                sa.select(role_permissions.c.permission_id).where(role_permissions.c.role_id == role_id)
            ).scalars().all()
        )
        for permission_id in new_permission_ids:
            if permission_id not in assigned:
                bind.execute(
                    role_permissions.insert().values(
                        id=uuid.uuid4(),
                        role_id=role_id,
                        permission_id=permission_id,
                    )
                )

    # O perfil Financeiro mantém operação diária, mas não recebe aprovação/execução/reabertura.
    finance_roles = bind.execute(sa.select(roles.c.id).where(roles.c.key == "finance")).scalars().all()
    adjustment_permission_id = existing["finance.adjustment.create"]
    for role_id in finance_roles:
        exists = bind.execute(
            sa.select(role_permissions.c.id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == adjustment_permission_id,
            )
        ).scalar_one_or_none()
        if exists is None:
            bind.execute(
                role_permissions.insert().values(
                    id=uuid.uuid4(),
                    role_id=role_id,
                    permission_id=adjustment_permission_id,
                )
            )

    organizations = bind.execute(sa.text("SELECT id FROM organizations")).scalars().all()
    for organization_id in organizations:
        for role_key, definition in ROLE_DEFINITIONS.items():
            role_id = bind.execute(
                sa.select(roles.c.id).where(
                    roles.c.organization_id == organization_id,
                    roles.c.key == role_key,
                )
            ).scalar_one_or_none()
            if role_id is None:
                role_id = uuid.uuid4()
                bind.execute(
                    roles.insert().values(
                        id=role_id,
                        organization_id=organization_id,
                        key=role_key,
                        name=definition["name"],
                        description=definition["description"],
                        is_system=True,
                        is_active=True,
                    )
                )

            assigned = set(
                bind.execute(
                    sa.select(role_permissions.c.permission_id).where(role_permissions.c.role_id == role_id)
                ).scalars().all()
            )
            for permission_key in definition["permissions"]:
                permission_id = existing.get(permission_key)
                if permission_id is None:
                    continue
                if permission_id not in assigned:
                    bind.execute(
                        role_permissions.insert().values(
                            id=uuid.uuid4(),
                            role_id=role_id,
                            permission_id=permission_id,
                        )
                    )


def downgrade() -> None:
    bind = op.get_bind()
    role_keys = tuple(ROLE_DEFINITIONS)
    bind.execute(sa.text("DELETE FROM roles WHERE key = ANY(:keys)").bindparams(keys=list(role_keys)))
    bind.execute(
        sa.text(
            "DELETE FROM permissions WHERE key = ANY(:keys)"
        ).bindparams(keys=[item[0] for item in PERMISSIONS])
    )
