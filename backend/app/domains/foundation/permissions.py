from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDefinition:
    key: str
    module: str
    name: str
    description: str


PERMISSIONS: tuple[PermissionDefinition, ...] = (
    PermissionDefinition("dashboard.view", "dashboard", "Visualizar dashboard", "Permite acessar a visão geral do ERP."),
    PermissionDefinition("properties.view", "properties", "Visualizar imóveis", "Permite consultar imóveis e seus dados operacionais."),
    PermissionDefinition("properties.create", "properties", "Cadastrar imóveis", "Permite criar novos imóveis."),
    PermissionDefinition("properties.edit", "properties", "Editar imóveis", "Permite alterar dados do imóvel."),
    PermissionDefinition("properties.publish", "properties", "Publicar imóveis", "Permite alterar a publicação do imóvel nos canais autorizados."),
    PermissionDefinition("captures.view", "captures", "Visualizar captações", "Permite consultar captações e suas etapas."),
    PermissionDefinition("captures.manage", "captures", "Gerenciar captações", "Permite avançar, editar e converter captações."),
    PermissionDefinition("crm.view", "crm", "Visualizar CRM", "Permite consultar leads, visitas e propostas conforme escopo."),
    PermissionDefinition("crm.manage", "crm", "Gerenciar CRM", "Permite atuar sobre leads, visitas e propostas."),
    PermissionDefinition("contracts.view", "contracts", "Visualizar contratos", "Permite consultar contratos e documentos relacionados."),
    PermissionDefinition("contracts.create", "contracts", "Criar contratos", "Permite preparar minutas e novos contratos."),
    PermissionDefinition("contracts.edit", "contracts", "Editar contratos", "Permite alterar contratos ainda não finalizados."),
    PermissionDefinition("contracts.approve", "contracts", "Aprovar contratos", "Permite conceder aprovação interna de contrato."),
    PermissionDefinition("contracts.send_signature", "contracts", "Enviar para assinatura", "Permite encaminhar documentos para o provedor de assinatura."),
    PermissionDefinition("finance.view", "finance", "Visualizar financeiro", "Permite consultar dados financeiros conforme escopo."),
    PermissionDefinition("finance.charge.create", "finance", "Gerar cobranças", "Permite gerar cobranças e lotes previstos."),
    PermissionDefinition("finance.reconcile", "finance", "Conciliar banco", "Permite efetuar e corrigir conciliações bancárias."),
    PermissionDefinition("finance.payment.prepare", "finance", "Preparar pagamentos", "Permite criar e preparar lotes de pagamento para aprovação."),
    PermissionDefinition("finance.payment.approve", "finance", "Aprovar pagamentos", "Permite aprovar lotes preparados por outro usuário conforme alçada."),
    PermissionDefinition("finance.payment.execute", "finance", "Executar pagamentos", "Permite registrar a execução de lotes aprovados por outro usuário."),
    PermissionDefinition("finance.period.close", "finance", "Fechar competência", "Permite confirmar o fechamento mensal quando o checklist estiver limpo."),
    PermissionDefinition("finance.period.reopen", "finance", "Reabrir competência", "Permite reabrir competência fechada com justificativa obrigatória."),
    PermissionDefinition("finance.adjustment.create", "finance", "Criar ajustes financeiros", "Permite classificar diferenças e ajustes financeiros manuais."),
    PermissionDefinition("finance.sod.override", "finance", "Exceção de segregação", "Permite, em caráter excepcional e justificado, ultrapassar conflito de segregação de funções."),
    PermissionDefinition("finance.repasse.execute", "finance", "Executar repasses", "Permite encaminhar repasses aprovados ao banco."),
    PermissionDefinition("maintenance.view", "maintenance", "Visualizar manutenções", "Permite consultar chamados de manutenção."),
    PermissionDefinition("maintenance.manage", "maintenance", "Gerenciar manutenções", "Permite triar, orçar, aprovar quando autorizado e concluir chamados."),
    PermissionDefinition("inspections.view", "inspections", "Visualizar vistorias", "Permite consultar vistorias e laudos."),
    PermissionDefinition("inspections.manage", "inspections", "Gerenciar vistorias", "Permite executar e revisar vistorias."),
    PermissionDefinition("documents.view", "documents", "Visualizar documentos", "Permite consultar documentos conforme escopo."),
    PermissionDefinition("documents.manage", "documents", "Gerenciar documentos", "Permite anexar e versionar documentos."),
    PermissionDefinition("agenda.view", "agenda", "Visualizar agenda", "Permite consultar agenda, tarefas e alertas."),
    PermissionDefinition("agenda.manage", "agenda", "Gerenciar agenda", "Permite criar e alterar tarefas e compromissos."),
    PermissionDefinition("reports.view", "reports", "Visualizar relatórios", "Permite acessar relatórios autorizados."),
    PermissionDefinition("reports.export", "reports", "Exportar relatórios", "Permite exportar relatórios autorizados em PDF ou CSV."),
    PermissionDefinition("communications.view", "communications", "Visualizar comunicações", "Permite consultar fila, histórico, modelos e preferências de comunicação."),
    PermissionDefinition("communications.manage", "communications", "Gerenciar comunicações", "Permite criar, editar, cancelar e preparar comunicações e modelos."),
    PermissionDefinition("communications.send", "communications", "Enviar comunicações", "Permite confirmar envio e reenvio por provedores externos configurados."),
    PermissionDefinition("settings.view", "settings", "Visualizar configurações", "Permite consultar configurações permitidas."),
    PermissionDefinition("settings.company.manage", "settings", "Editar empresa", "Permite alterar dados institucionais da empresa."),
    PermissionDefinition("settings.appearance.manage", "settings", "Editar aparência", "Permite alterar temas, marca e identidade visual."),
    PermissionDefinition("users.manage", "security", "Gerenciar usuários", "Permite criar, bloquear e alterar usuários."),
    PermissionDefinition("permissions.manage", "security", "Gerenciar permissões", "Permite conceder e revogar permissões e perfis."),
    PermissionDefinition("approval_rules.manage", "security", "Gerenciar alçadas", "Permite criar e alterar regras de aprovação."),
    PermissionDefinition("audit.view", "audit", "Visualizar auditoria", "Permite consultar eventos de auditoria."),
)

ADMIN_PERMISSION_KEYS = frozenset(permission.key for permission in PERMISSIONS)
