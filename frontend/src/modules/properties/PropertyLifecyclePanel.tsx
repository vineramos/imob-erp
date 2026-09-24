import {
  Building2, CheckCircle2, Circle, CircleAlert, CircleDollarSign, ClipboardCheck,
  ExternalLink, FileText, History, Home, RefreshCw, Users, Wrench,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './property-lifecycle-panel.css'

type LifecyclePerson = { id: string; name: string; document_number?: string | null; role_keys?: string[] }
type LifecycleOwner = LifecyclePerson & { ownership_percent: number }
type LifecycleContract = { id: string; code: string; status: string; signing_status?: string; signed_at?: string | null; current_version?: number }
type LifecycleCapture = { id: string; code: string; status: string; source: string; contact_person_id: string | null; property_id: string | null }
type LifecycleStep = { key: string; label: string; status: string; linked: boolean }
type TimelineStage = 'acquisition' | 'commercial' | 'contract' | 'operation' | 'finance' | 'maintenance'
type TimelineEvent = {
  id: string
  kind: string
  stage: TimelineStage
  title: string
  detail: string
  occurred_at: string
  status: string | null
  code: string | null
  route: string | null
}
type LifecycleResponse = {
  property: { id: string; code: string; status: string; property_type: string; publication_enabled: boolean }
  capture: LifecycleCapture | null
  contact_person: LifecyclePerson | null
  owners: LifecycleOwner[]
  administration: LifecycleContract | null
  lease: LifecycleContract | null
  publication: { enabled: boolean; slug: string | null; published_at: string | null }
  timeline: TimelineEvent[]
  lifecycle: LifecycleStep[]
}

const statusLabel: Record<string, string> = {
  draft: 'Rascunho', available: 'Disponível', reserved: 'Reservado', leased: 'Locado', inactive: 'Inativo',
  approved: 'Aprovada', pending_signature: 'Aguardando assinatura', signed: 'Assinado', cancelled: 'Cancelado',
  active: 'Ativa', inactive_publication: 'Não publicada', not_created: 'Ainda não criada', not_started: 'Não iniciada',
  linked: 'Vinculado', pending: 'Pendente', new: 'Novo', contacted: 'Contato', visit_scheduled: 'Visita agendada',
  qualified: 'Qualificado', proposal: 'Proposta', won: 'Fechado', lost: 'Perdido', scheduled: 'Agendada',
  completed: 'Concluída', no_show: 'Não compareceu', submitted: 'Enviada', accepted: 'Aceita', rejected: 'Recusada',
  withdrawn: 'Retirada', ready: 'Laudo concluído', contested: 'Contestada', finalized: 'Finalizada',
  generated: 'Gerada', sent: 'Enviada', overdue: 'Em atraso', paid: 'Pago', requested: 'Aberta',
  awaiting_approval: 'Aguardando aprovação', approved_execution: 'Execução aprovada', in_progress: 'Em execução',
  closed: 'Encerrado',
}

const stageLabel: Record<TimelineStage, string> = {
  acquisition: 'Captação',
  commercial: 'Comercial',
  contract: 'Contratos',
  operation: 'Operação',
  finance: 'Financeiro',
  maintenance: 'Manutenção',
}

function label(value: string | null | undefined) { return !value ? '—' : statusLabel[value] ?? value.replaceAll('_', ' ') }
function dateLabel(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}
function navigate(path: string) {
  window.history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}
function EventIcon({ kind }: { kind: string }) {
  if (kind === 'capture' || kind === 'property') return <Building2 size={15}/>
  if (kind === 'lead' || kind === 'visit' || kind === 'proposal' || kind === 'publication') return <Users size={15}/>
  if (kind === 'administration' || kind === 'lease') return <FileText size={15}/>
  if (kind === 'inspection') return <ClipboardCheck size={15}/>
  if (kind === 'finance') return <CircleDollarSign size={15}/>
  if (kind === 'maintenance') return <Wrench size={15}/>
  return <History size={15}/>
}

export function PropertyLifecyclePanel({ permissions, propertyId }: { permissions: string[]; propertyId: string }) {
  const canView = permissions.includes('properties.view')
  const [data, setData] = useState<LifecycleResponse | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [stage, setStage] = useState<'all' | TimelineStage>('all')

  useEffect(() => {
    if (!canView || !propertyId) { setData(null); return }
    void (async () => {
      setDetailLoading(true); setError('')
      try { setData(await apiRequest<LifecycleResponse>(`/properties/${propertyId}/lifecycle`)) }
      catch (cause) { setData(null); setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar a rastreabilidade.') }
      finally { setDetailLoading(false) }
    })()
  }, [canView, propertyId, refreshKey])

  const progress = useMemo(() => data?.lifecycle.length ? Math.round((data.lifecycle.filter(step => step.linked).length / data.lifecycle.length) * 100) : 0, [data])
  const visibleEvents = useMemo(() => (data?.timeline || []).filter(event => stage === 'all' || event.stage === stage), [data, stage])
  const stageCounts = useMemo(() => {
    const counts = { acquisition: 0, commercial: 0, contract: 0, operation: 0, finance: 0, maintenance: 0 }
    for (const event of data?.timeline || []) counts[event.stage] += 1
    return counts
  }, [data])
  const openOperational = useMemo(() => (data?.timeline || []).filter(event =>
    ['maintenance', 'inspection'].includes(event.kind) && !['completed', 'finalized', 'cancelled'].includes(event.status || '')
  ).length, [data])
  const latestEvent = data?.timeline?.[0] || null

  if (!canView) return null

  return <article className="panel property-tab-panel property-lifecycle-panel property-lifecycle-v82">
    <div className="property-lifecycle-heading">
      <div><span className="eyebrow">Rastreabilidade unificada</span><h2>Histórico completo do imóvel</h2><p>Captação, comercial, contratos, vistorias, financeiro e manutenções em uma única linha do tempo.</p></div>
      <button className="button secondary compact" type="button" onClick={() => setRefreshKey(value => value + 1)} disabled={detailLoading}><RefreshCw size={14}/> Atualizar</button>
    </div>

    {data && <div className="property-lifecycle-kpis">
      <article><span>Ciclo rastreado</span><strong>{progress}%</strong><small>{data.lifecycle.filter(step => step.linked).length} de {data.lifecycle.length} etapas-base</small></article>
      <article><span>Eventos</span><strong>{data.timeline.length}</strong><small>registros vinculados ao imóvel</small></article>
      <article><span>Comercial</span><strong>{stageCounts.commercial}</strong><small>lead, visita, proposta e publicação</small></article>
      <article className={openOperational ? 'attention' : ''}><span>Pendências operacionais</span><strong>{openOperational}</strong><small>vistorias/manutenções em andamento</small></article>
      <article><span>Última movimentação</span><strong>{latestEvent ? dateLabel(latestEvent.occurred_at).split(' ')[0] : '—'}</strong><small>{latestEvent?.title || 'Sem movimentações'}</small></article>
    </div>}

    {error && <div className="property-lifecycle-error"><CircleAlert size={15}/> {error}</div>}
    {detailLoading && <div className="property-lifecycle-loading">Carregando histórico operacional...</div>}

    {data && !detailLoading && <>
      <div className="property-lifecycle-flow" aria-label="Etapas-base do ciclo do imóvel">
        {data.lifecycle.map((step, index) => <div className={step.linked ? 'done' : 'pending'} key={step.key}>
          <span>{step.linked ? <CheckCircle2 size={12}/> : <Circle size={12}/>}</span>
          <div><strong>{step.label}</strong><small>{label(step.status)}</small></div>
          {index < data.lifecycle.length - 1 && <i/>}
        </div>)}
      </div>

      <div className="property-lifecycle-layout">
        <section className="property-lifecycle-timeline">
          <header className="property-lifecycle-timeline-head">
            <div><span className="eyebrow">Linha do tempo</span><h3>Movimentações do ativo</h3></div>
            <div className="property-lifecycle-filters">
              <button type="button" className={stage === 'all' ? 'active' : ''} onClick={() => setStage('all')}>Tudo</button>
              {(Object.keys(stageLabel) as TimelineStage[]).map(key => <button type="button" key={key} className={stage === key ? 'active' : ''} onClick={() => setStage(key)}>{stageLabel[key]} <b>{stageCounts[key]}</b></button>)}
            </div>
          </header>
          <div className="property-lifecycle-events">
            {visibleEvents.map(event => <article key={event.id} className="property-lifecycle-event">
              <div className={'property-lifecycle-event-icon ' + event.stage}><EventIcon kind={event.kind}/></div>
              <div className="property-lifecycle-event-copy">
                <div><span>{stageLabel[event.stage]}</span>{event.code && <b>{event.code}</b>}</div>
                <strong>{event.title}</strong>
                <small>{event.detail}</small>
              </div>
              <div className="property-lifecycle-event-meta">
                <time>{dateLabel(event.occurred_at)}</time>
                {event.status && <i className={'status-badge ' + (['paid','signed','accepted','completed','finalized','won','active','available'].includes(event.status) ? 'success' : ['cancelled','rejected','lost','overdue'].includes(event.status) ? 'danger' : 'neutral')}>{label(event.status)}</i>}
                {event.route && <button type="button" onClick={() => navigate(event.route)} title="Abrir registro"><ExternalLink size={13}/></button>}
              </div>
            </article>)}
            {visibleEvents.length === 0 && <div className="property-lifecycle-empty"><History size={20}/><strong>Nenhum evento nesta categoria.</strong><span>Os próximos registros vinculados ao imóvel aparecerão automaticamente aqui.</span></div>}
          </div>
        </section>

        <aside className="property-lifecycle-context">
          <section>
            <div className="property-lifecycle-context-title"><Home size={15}/><div><span>Base do ativo</span><strong>Vínculos principais</strong></div></div>
            <div className="property-lifecycle-context-list">
              <div><span>Captação</span><strong>{data.capture?.code || 'Não vinculada'}</strong><small>{data.capture ? label(data.capture.status) : 'Sem origem cadastrada'}</small></div>
              <div><span>Proprietários</span><strong>{data.owners.length || 0}</strong><small>{data.owners.length ? data.owners.map(owner => `${owner.name} (${owner.ownership_percent}%)`).join(' · ') : 'Nenhum vínculo'}</small></div>
              <div><span>Administração</span><strong>{data.administration?.code || 'Não criada'}</strong><small>{data.administration ? label(data.administration.status) : 'Sem contrato'}</small></div>
              <div><span>Locação</span><strong>{data.lease?.code || 'Não criada'}</strong><small>{data.lease ? label(data.lease.status) : 'Sem contrato'}</small></div>
              <div><span>Publicação</span><strong>{data.publication.enabled ? 'Ativa' : 'Inativa'}</strong><small>{data.publication.published_at ? dateLabel(data.publication.published_at) : 'Ainda não publicada'}</small></div>
            </div>
          </section>
          <section>
            <div className="property-lifecycle-context-title"><CircleDollarSign size={15}/><div><span>Leitura operacional</span><strong>Eventos por área</strong></div></div>
            <div className="property-lifecycle-stage-summary">
              {(Object.keys(stageLabel) as TimelineStage[]).map(key => <button type="button" key={key} onClick={() => setStage(key)}><span>{stageLabel[key]}</span><strong>{stageCounts[key]}</strong></button>)}
            </div>
          </section>
        </aside>
      </div>
    </>}
  </article>
}
