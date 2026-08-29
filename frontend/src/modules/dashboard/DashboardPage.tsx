const cards = [
  { label: 'Imóveis administrados', value: '—', hint: 'Aguardando Sprint 2' },
  { label: 'Contratos ativos', value: '—', hint: 'Aguardando módulo de contratos' },
  { label: 'Pendências críticas', value: '0', hint: 'Nenhuma ocorrência crítica' },
  { label: 'Tarefas de hoje', value: '0', hint: 'Agenda integrada' },
]

export function DashboardPage() {
  return (
    <section className="workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Visão geral</span>
          <h1>Dashboard</h1>
          <p>A central operacional do ERP começa aqui. Os módulos serão ativados por sprint.</p>
        </div>
      </div>

      <div className="metric-grid">
        {cards.map((card) => (
          <article className="metric-card" key={card.label}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
            <small>{card.hint}</small>
          </article>
        ))}
      </div>

      <div className="dashboard-grid">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Fundação</span>
              <h2>Sprint 1 em construção</h2>
            </div>
          </div>
          <div className="foundation-list">
            <div><span className="status-dot status-ready" />Estrutura modular do frontend</div>
            <div><span className="status-dot status-ready" />Backend FastAPI separado</div>
            <div><span className="status-dot status-ready" />Design System por tokens</div>
            <div><span className="status-dot" />Autenticação e usuários</div>
            <div><span className="status-dot" />Permissões e auditoria</div>
            <div><span className="status-dot" />Configurações da empresa e aparência</div>
          </div>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Segurança</span>
              <h2>Princípios do sistema</h2>
            </div>
          </div>
          <ul className="plain-list">
            <li>Ações sensíveis serão auditadas.</li>
            <li>Permissões e alçadas serão administradas apenas por Administradores.</li>
            <li>Pagamentos manuais serão exceção, nunca o fluxo padrão.</li>
            <li>Configuração define o padrão; o registro operacional guarda sua própria regra.</li>
          </ul>
        </article>
      </div>
    </section>
  )
}
