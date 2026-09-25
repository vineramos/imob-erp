from dataclasses import dataclass

from app.domains.foundation.permissions import ADMIN_PERMISSION_KEYS


@dataclass(frozen=True)
class RoleTemplate:
    key: str
    name: str
    description: str
    permissions: frozenset[str]


ROLE_TEMPLATES: tuple[RoleTemplate, ...] = (
    RoleTemplate("admin", "Administrador", "Governança e acesso total ao ERP.", ADMIN_PERMISSION_KEYS),
    RoleTemplate(
        "administrative",
        "Administrativo",
        "Operação administrativa, contratos, documentos, agenda e manutenção.",
        frozenset({
            "dashboard.view", "properties.view", "properties.create", "properties.edit",
            "captures.view", "captures.manage", "crm.view", "crm.manage",
            "contracts.view", "contracts.create", "contracts.edit",
            "maintenance.view", "maintenance.manage", "inspections.view", "inspections.manage",
            "documents.view", "documents.manage", "agenda.view", "agenda.manage",
            "reports.view", "reports.export",
            "communications.view", "communications.manage", "communications.send",
        }),
    ),
    RoleTemplate(
        "finance",
        "Financeiro",
        "Operação financeira diária: cobrança, banco, conciliação e preparação de pagamentos.",
        frozenset({
            "dashboard.view", "properties.view", "contracts.view", "finance.view",
            "finance.charge.create", "finance.reconcile", "finance.payment.prepare",
            "finance.adjustment.create", "finance.repasse.execute",
            "documents.view", "agenda.view", "agenda.manage",
            "reports.view", "reports.export",
            "communications.view", "communications.manage", "communications.send",
        }),
    ),
    RoleTemplate(
        "finance_approver",
        "Aprovador financeiro",
        "Aprovação de pagamentos e fechamento de competência, separado da preparação.",
        frozenset({
            "dashboard.view", "properties.view", "contracts.view", "finance.view",
            "finance.payment.approve", "finance.period.close",
            "documents.view", "reports.view", "audit.view",
        }),
    ),
    RoleTemplate(
        "finance_executor",
        "Executor financeiro",
        "Execução de pagamentos já aprovados e consulta operacional.",
        frozenset({
            "dashboard.view", "finance.view", "finance.payment.execute",
            "documents.view", "reports.view",
        }),
    ),
    RoleTemplate(
        "finance_controller",
        "Controladoria financeira",
        "Reabertura de competências e exceções de segregação com justificativa auditada.",
        frozenset({
            "dashboard.view", "finance.view", "finance.period.reopen",
            "finance.sod.override", "reports.view", "reports.export", "audit.view",
        }),
    ),
    RoleTemplate(
        "broker",
        "Corretor",
        "Imóveis disponíveis, próprios leads, visitas e propostas.",
        frozenset({
            "dashboard.view", "properties.view", "captures.view", "crm.view", "crm.manage",
            "contracts.view", "documents.view", "agenda.view", "agenda.manage",
        }),
    ),
    RoleTemplate(
        "maintenance_inspection",
        "Manutenção / Vistoria",
        "Chamados, fornecedores, vistorias, laudos e agenda relacionados ao trabalho.",
        frozenset({
            "dashboard.view", "properties.view", "maintenance.view", "maintenance.manage",
            "inspections.view", "inspections.manage", "documents.view", "documents.manage",
            "agenda.view", "agenda.manage",
        }),
    ),
    RoleTemplate(
        "read_only",
        "Consulta",
        "Acesso somente leitura ao escopo autorizado.",
        frozenset({
            "dashboard.view", "properties.view", "captures.view", "crm.view", "contracts.view",
            "finance.view", "maintenance.view", "inspections.view", "documents.view", "agenda.view", "reports.view",
        }),
    ),
)
