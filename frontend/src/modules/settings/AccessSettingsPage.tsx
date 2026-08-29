import { LockKeyhole, Plus, ShieldCheck, UserRoundCog } from 'lucide-react'

const profiles = [
  { name: 'Administrador', scope: 'Acesso total e governança', users: 1, locked: true },
  { name: 'Administrativo', scope: 'Cadastros, contratos, documentos e agenda', users: 0 },
  { name: 'Financeiro', scope: 'Cobranças, banco, repasses e conciliação', users: 0 },
  { name: 'Corretor', scope: 'CRM, imóveis disponíveis, visitas e propostas', users: 0 },
  { name: 'Manutenção / Vistoria', scope: 'Chamados, fornecedores, laudos e agenda', users: 0 },
  { name: 'Consulta', scope: 'Somente leitura conforme escopo', users: 0 },
]

const permissionGroups = [
  ['Contratos', 'Visualizar', 'Criar', 'Editar', 'Aprovar', 'Enviar para assinatura'],
  ['Financeiro', 'Visualizar', 'Gerar cobrança', 'Conciliar', 'Aprovar pagamento', 'Executar repasse'],
  ['Imóveis', 'Visualizar', 'Editar', 'Publicar', 'Alterar proprietário'],
  ['Configurações', 'Visualizar', 'Editar aparência', 'Gerenciar usuários', 'Gerenciar alçadas'],
]

export function AccessSettingsPage() {
  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Administrador</span>
          <h1>Usuários e permissões</h1>
          <p>Perfis são atalhos. A autorização real será feita por permissões granulares e auditáveis.</p>
        </div>
        <button className="button primary" type="button"><Plus size={16} /> Novo usuário</button>
      </div>

      <div className="metric-grid access-metrics">
        <article className="metric-card"><span>Usuários ativos</span><strong>1</strong><small>Administrador inicial</small></article>
        <article className="metric-card"><span>Perfis disponíveis</span><strong>6</strong><small>Base da Sprint 1</small></article>
        <article className="metric-card"><span>Acessos bloqueados</span><strong>0</strong><small>Bloqueio preserva histórico</small></article>
        <article className="metric-card"><span>Alterações críticas</span><strong>0</strong><small>Auditadas automaticamente</small></article>
      </div>

      <div className="dashboard-grid access-grid">
        <article className="panel">
          <div className="panel-heading panel-heading-row">
            <div><span className="eyebrow">Perfis-base</span><h2>Estrutura de acesso</h2></div>
            <ShieldCheck size={20} />
          </div>
          <div className="profile-list">
            {profiles.map((profile) => (
              <button className="profile-row" type="button" key={profile.name}>
                <div className="profile-icon"><UserRoundCog size={17} /></div>
                <div><strong>{profile.name}</strong><span>{profile.scope}</span></div>
                <div className="profile-meta"><span>{profile.users} usuário(s)</span>{profile.locked && <LockKeyhole size={14} />}</div>
              </button>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <span className="eyebrow">Regra estrutural</span>
            <h2>Segregação de funções</h2>
          </div>
          <div className="security-callout">
            <ShieldCheck size={22} />
            <div>
              <strong>Administrador governa permissões</strong>
              <p>Financeiro e Administrativo operam o sistema, mas não podem conceder a si mesmos novos poderes.</p>
            </div>
          </div>
          <ul className="plain-list permission-rules">
            <li>Quem altera dados bancários não aprova sozinho o pagamento seguinte.</li>
            <li>Alçadas de pagamento são configuradas exclusivamente por Administradores.</li>
            <li>Bloquear um usuário encerra acesso sem apagar seu histórico.</li>
            <li>Ações críticas registram usuário, data/hora, antes, depois e justificativa.</li>
          </ul>
        </article>
      </div>

      <article className="panel permission-panel">
        <div className="panel-heading">
          <span className="eyebrow">Permissões granulares</span>
          <h2>Matriz por ação</h2>
        </div>
        <div className="permission-table">
          {permissionGroups.map(([group, ...permissions]) => (
            <div className="permission-group" key={group}>
              <strong>{group}</strong>
              <div>{permissions.map((permission) => <span className="permission-chip" key={permission}>{permission}</span>)}</div>
            </div>
          ))}
        </div>
      </article>
    </section>
  )
}
