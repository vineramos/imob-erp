import { FileClock, Search, ShieldCheck } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { AuditEvent } from '../../api/types'
import { authConfigured } from '../../auth/client'

const actionLabels: Record<string, string> = {
  'settings.company.updated': 'Dados da empresa alterados',
  'settings.appearance.erp.updated': 'Identidade visual do ERP alterada',
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function AuditSettingsPage() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(authConfigured)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!authConfigured) return

    let active = true
    void apiRequest<AuditEvent[]>('/settings/audit?limit=100')
      .then((data) => {
        if (active) setEvents(data)
      })
      .catch((cause) => {
        if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar a auditoria.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => { active = false }
  }, [])

  const filteredEvents = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase('pt-BR')
    if (!normalized) return events
    return events.filter((event) => {
      const haystack = [
        actionLabels[event.action] ?? event.action,
        event.module,
        event.actor_name ?? '',
        event.entity_type,
        event.reason ?? '',
      ].join(' ').toLocaleLowerCase('pt-BR')
      return haystack.includes(normalized)
    })
  }, [events, query])

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

      {error && <div className="form-alert danger-alert">{error}</div>}

      <article className="panel audit-panel">
        <div className="audit-toolbar">
          <div><span className="eyebrow">Histórico</span><h2>Eventos do sistema</h2></div>
          <label className="audit-search"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar usuário, módulo ou ação..." /></label>
        </div>

        {loading ? (
          <div className="settings-loading">Carregando eventos...</div>
        ) : !authConfigured ? (
          <div className="audit-empty"><strong>Auditoria pronta para conexão.</strong><span>No modo de desenvolvimento sem Auth, nenhum evento permanente é gravado.</span></div>
        ) : filteredEvents.length === 0 ? (
          <div className="audit-empty"><strong>Nenhum evento encontrado.</strong><span>As primeiras alterações auditáveis aparecerão aqui automaticamente.</span></div>
        ) : (
          <div className="data-table">
            <div className="data-row data-header"><span>Data / hora</span><span>Ação</span><span>Módulo</span><span>Usuário</span><span>Status</span></div>
            {filteredEvents.map((event) => (
              <div className="data-row" key={event.id} title={event.reason ?? undefined}>
                <span>{formatDate(event.created_at)}</span>
                <strong>{actionLabels[event.action] ?? event.action}</strong>
                <span>{event.module}</span>
                <span>{event.actor_name ?? 'Sistema'}</span>
                <span><i className="status-badge neutral">Registrado</i></span>
              </div>
            ))}
          </div>
        )}
      </article>
    </section>
  )
}
