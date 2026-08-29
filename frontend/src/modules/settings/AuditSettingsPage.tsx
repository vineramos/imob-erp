import { FileClock, Search, ShieldCheck } from 'lucide-react'

const events = [
  { time: 'Agora', action: 'Fundação do sistema iniciada', module: 'Sistema', actor: 'Administrador', status: 'Registrado' },
  { time: '—', action: 'Alterações de aparência', module: 'Configurações', actor: '—', status: 'Aguardando uso' },
  { time: '—', action: 'Alterações de permissões', module: 'Segurança', actor: '—', status: 'Aguardando uso' },
]

export function AuditSettingsPage() {
  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Governança</span>
          <h1>Auditoria</h1>
          <p>Histórico imutável das ações importantes do ERP, com origem, usuário e contexto da alteração.</p>
        </div>
      </div>

      <div className="audit-summary-grid">
        <article className="panel audit-summary"><ShieldCheck size={20} /><div><strong>Imutável</strong><span>Eventos não são editados nem apagados pelo usuário.</span></div></article>
        <article className="panel audit-summary"><FileClock size={20} /><div><strong>Rastreável</strong><span>Antes/depois e justificativa quando a ação exigir.</span></div></article>
      </div>

      <article className="panel audit-panel">
        <div className="audit-toolbar">
          <div><span className="eyebrow">Histórico</span><h2>Eventos do sistema</h2></div>
          <label className="audit-search"><Search size={16} /><input placeholder="Buscar usuário, módulo ou ação..." /></label>
        </div>
        <div className="data-table">
          <div className="data-row data-header"><span>Data / hora</span><span>Ação</span><span>Módulo</span><span>Usuário</span><span>Status</span></div>
          {events.map((event) => (
            <div className="data-row" key={`${event.action}-${event.module}`}>
              <span>{event.time}</span><strong>{event.action}</strong><span>{event.module}</span><span>{event.actor}</span><span><i className="status-badge neutral">{event.status}</i></span>
            </div>
          ))}
        </div>
      </article>
    </section>
  )
}
