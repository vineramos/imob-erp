import { LockKeyhole, Plus, ShieldCheck, UserRoundCog, UsersRound } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { AppUser, Role } from '../../api/types'
import { authConfigured } from '../../auth/client'

const fallbackRoles: Role[] = [
  { id: 'admin', key: 'admin', name: 'Administrador', description: 'Governança e acesso total ao ERP.', is_system: true, is_active: true, user_count: 1, permissions: ['dashboard.view', 'properties.view', 'contracts.view', 'finance.view', 'settings.view', 'users.manage', 'permissions.manage', 'approval_rules.manage', 'audit.view'] },
  { id: 'administrative', key: 'administrative', name: 'Administrativo', description: 'Cadastros, contratos, documentos e agenda.', is_system: true, is_active: true, user_count: 0, permissions: ['dashboard.view', 'properties.view', 'captures.view', 'crm.view', 'contracts.view', 'maintenance.view', 'documents.view', 'agenda.view'] },
  { id: 'finance', key: 'finance', name: 'Financeiro', description: 'Cobranças, banco, repasses e conciliação.', is_system: true, is_active: true, user_count: 0, permissions: ['dashboard.view', 'properties.view', 'contracts.view', 'finance.view', 'finance.charge.create', 'finance.reconcile', 'finance.payment.prepare', 'finance.repasse.execute'] },
  { id: 'broker', key: 'broker', name: 'Corretor', description: 'Imóveis disponíveis, leads, visitas e propostas.', is_system: true, is_active: true, user_count: 0, permissions: ['dashboard.view', 'properties.view', 'captures.view', 'crm.view', 'crm.manage', 'contracts.view', 'agenda.view'] },
  { id: 'maintenance_inspection', key: 'maintenance_inspection', name: 'Manutenção / Vistoria', description: 'Chamados, fornecedores, vistorias e laudos.', is_system: true, is_active: true, user_count: 0, permissions: ['dashboard.view', 'properties.view', 'maintenance.view', 'maintenance.manage', 'inspections.view', 'inspections.manage', 'documents.view', 'agenda.view'] },
  { id: 'read_only', key: 'read_only', name: 'Consulta', description: 'Somente leitura conforme o escopo autorizado.', is_system: true, is_active: true, user_count: 0, permissions: ['dashboard.view', 'properties.view', 'captures.view', 'crm.view', 'contracts.view', 'finance.view', 'maintenance.view', 'inspections.view', 'documents.view', 'agenda.view', 'reports.view'] },
]

const fallbackUsers: AppUser[] = [
  { id: 'dev-admin', name: 'Administrador', email: 'dev@local', is_active: true, blocked_at: null, created_at: new Date().toISOString(), role_keys: ['admin'] },
]

const permissionNames: Record<string, string> = {
  'dashboard.view': 'Dashboard',
  'properties.view': 'Visualizar imóveis',
  'properties.create': 'Cadastrar imóveis',
  'properties.edit': 'Editar imóveis',
  'properties.publish': 'Publicar imóveis',
  'captures.view': 'Visualizar captações',
  'captures.manage': 'Gerenciar captações',
  'crm.view': 'Visualizar CRM',
  'crm.manage': 'Gerenciar CRM',
  'contracts.view': 'Visualizar contratos',
  'contracts.create': 'Criar contratos',
  'contracts.edit': 'Editar contratos',
  'contracts.approve': 'Aprovar contratos',
  'contracts.send_signature': 'Enviar para assinatura',
  'finance.view': 'Visualizar financeiro',
  'finance.charge.create': 'Gerar cobranças',
  'finance.reconcile': 'Conciliar banco',
  'finance.payment.prepare': 'Preparar pagamentos',
  'finance.payment.approve': 'Aprovar pagamentos',
  'finance.repasse.execute': 'Executar repasses',
  'maintenance.view': 'Visualizar manutenções',
  'maintenance.manage': 'Gerenciar manutenções',
  'inspections.view': 'Visualizar vistorias',
  'inspections.manage': 'Gerenciar vistorias',
  'documents.view': 'Visualizar documentos',
  'documents.manage': 'Gerenciar documentos',
  'agenda.view': 'Visualizar agenda',
  'agenda.manage': 'Gerenciar agenda',
  'reports.view': 'Visualizar relatórios',
  'settings.view': 'Visualizar configurações',
  'settings.company.manage': 'Editar empresa',
  'settings.appearance.manage': 'Editar aparência',
  'users.manage': 'Gerenciar usuários',
  'permissions.manage': 'Gerenciar permissões',
  'approval_rules.manage': 'Gerenciar alçadas',
  'audit.view': 'Visualizar auditoria',
}

function roleLabel(roleKeys: string[], roles: Role[]) {
  return roleKeys.map((key) => roles.find((role) => role.key === key)?.name ?? key).join(' · ')
}

export function AccessSettingsPage() {
  const [roles, setRoles] = useState<Role[]>(authConfigured ? [] : fallbackRoles)
  const [users, setUsers] = useState<AppUser[]>(authConfigured ? [] : fallbackUsers)
  const [selectedRoleKey, setSelectedRoleKey] = useState('admin')
  const [loading, setLoading] = useState(authConfigured)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!authConfigured) return

    let active = true
    void Promise.all([
      apiRequest<Role[]>('/settings/roles'),
      apiRequest<AppUser[]>('/settings/users'),
    ])
      .then(([loadedRoles, loadedUsers]) => {
        if (!active) return
        setRoles(loadedRoles)
        setUsers(loadedUsers)
        if (loadedRoles.length && !loadedRoles.some((role) => role.key === selectedRoleKey)) {
          setSelectedRoleKey(loadedRoles[0].key)
        }
      })
      .catch((cause) => {
        if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar usuários e perfis.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => { active = false }
  }, [selectedRoleKey])

  const selectedRole = useMemo(
    () => roles.find((role) => role.key === selectedRoleKey) ?? roles[0],
    [roles, selectedRoleKey],
  )
  const activeUsers = users.filter((user) => user.is_active).length
  const blockedUsers = users.length - activeUsers

  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Administrador</span>
          <h1>Usuários e permissões</h1>
          <p>Perfis facilitam a configuração, mas a autorização real é feita por permissões granulares e auditáveis.</p>
        </div>
        <button className="button primary" type="button" disabled title="Será ativado junto ao fluxo seguro de convite do Neon Auth">
          <Plus size={16} /> Novo usuário
        </button>
      </div>

      {error && <div className="form-alert danger-alert">{error}</div>}
      {!authConfigured && <div className="form-alert dev-info-alert">Pré-visualização local. Os usuários reais serão carregados quando o Neon Auth for ativado.</div>}

      <div className="metric-grid access-metrics">
        <article className="metric-card"><span>Usuários ativos</span><strong>{activeUsers}</strong><small>Acesso liberado ao ERP</small></article>
        <article className="metric-card"><span>Perfis disponíveis</span><strong>{roles.filter((role) => role.is_active).length}</strong><small>Perfis-base da fundação</small></article>
        <article className="metric-card"><span>Acessos bloqueados</span><strong>{blockedUsers}</strong><small>Bloqueio preserva histórico</small></article>
        <article className="metric-card"><span>Permissões catalogadas</span><strong>{new Set(roles.flatMap((role) => role.permissions)).size}</strong><small>Controle por ação</small></article>
      </div>

      {loading ? (
        <article className="panel settings-loading">Carregando estrutura de acesso...</article>
      ) : (
        <>
          <div className="dashboard-grid access-grid">
            <article className="panel">
              <div className="panel-heading panel-heading-row">
                <div><span className="eyebrow">Perfis-base</span><h2>Estrutura de acesso</h2></div>
                <ShieldCheck size={20} />
              </div>
              <div className="profile-list">
                {roles.map((role) => (
                  <button
                    className={`profile-row ${selectedRole?.key === role.key ? 'selected' : ''}`}
                    type="button"
                    key={role.key}
                    onClick={() => setSelectedRoleKey(role.key)}
                  >
                    <div className="profile-icon"><UserRoundCog size={17} /></div>
                    <div><strong>{role.name}</strong><span>{role.description ?? 'Perfil de acesso'}</span></div>
                    <div className="profile-meta"><span>{role.user_count} usuário(s)</span>{role.key === 'admin' && <LockKeyhole size={14} />}</div>
                  </button>
                ))}
              </div>
            </article>

            <article className="panel role-detail-panel">
              <div className="panel-heading">
                <span className="eyebrow">Permissões do perfil</span>
                <h2>{selectedRole?.name ?? 'Perfil'}</h2>
              </div>
              {selectedRole ? (
                <div className="role-permission-list">
                  {selectedRole.permissions.map((permission) => (
                    <span className="permission-chip" key={permission} title={permission}>{permissionNames[permission] ?? permission}</span>
                  ))}
                </div>
              ) : (
                <div className="audit-empty"><span>Nenhum perfil disponível.</span></div>
              )}
              <div className="security-callout role-security-callout">
                <ShieldCheck size={20} />
                <div>
                  <strong>Segregação de funções</strong>
                  <p>O perfil Financeiro prepara pagamentos, mas aprovação sensível depende de permissão e alçada próprias.</p>
                </div>
              </div>
            </article>
          </div>

          <article className="panel users-panel">
            <div className="panel-heading panel-heading-row">
              <div><span className="eyebrow">Equipe</span><h2>Usuários do ERP</h2></div>
              <UsersRound size={20} />
            </div>
            <div className="user-table">
              <div className="user-row user-header"><span>Usuário</span><span>Perfil</span><span>Status</span></div>
              {users.map((user) => (
                <div className="user-row" key={user.id}>
                  <div className="user-cell">
                    <div className="avatar avatar-user">{user.name.trim().slice(0, 2).toUpperCase()}</div>
                    <div><strong>{user.name}</strong><span>{user.email}</span></div>
                  </div>
                  <span>{roleLabel(user.role_keys, roles) || 'Sem perfil'}</span>
                  <span><i className={`status-badge ${user.is_active ? 'success' : 'danger'}`}>{user.is_active ? 'Ativo' : 'Bloqueado'}</i></span>
                </div>
              ))}
              {users.length === 0 && <div className="audit-empty"><strong>Nenhum usuário habilitado.</strong><span>O primeiro Administrador será criado no bootstrap seguro.</span></div>}
            </div>
          </article>

          <article className="panel permission-panel">
            <div className="panel-heading">
              <span className="eyebrow">Governança</span>
              <h2>Regras estruturais</h2>
            </div>
            <ul className="plain-list permission-rules">
              <li>Somente Administradores podem gerenciar usuários, permissões e alçadas.</li>
              <li>Quem altera dados bancários não aprova sozinho o pagamento seguinte.</li>
              <li>Bloquear um usuário encerra o acesso sem apagar seu histórico.</li>
              <li>Alterações de perfil e bloqueios exigem justificativa e entram na auditoria.</li>
            </ul>
          </article>
        </>
      )}
    </section>
  )
}
