import { CheckCircle2, Circle, CircleAlert, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './property-lifecycle-panel.css'

type LifecyclePerson = { id: string; name: string; document_number?: string | null; role_keys?: string[] }
type LifecycleOwner = LifecyclePerson & { ownership_percent: number }
type LifecycleContract = { id: string; code: string; status: string; signing_status?: string; signed_at?: string | null; current_version?: number }
type LifecycleCapture = { id: string; code: string; status: string; source: string; contact_person_id: string | null; property_id: string | null }
type LifecycleStep = { key: string; label: string; status: string; linked: boolean }
type LifecycleResponse = {
  property: { id: string; code: string; status: string; property_type: string; publication_enabled: boolean }
  capture: LifecycleCapture | null
  contact_person: LifecyclePerson | null
  owners: LifecycleOwner[]
  administration: LifecycleContract | null
  lease: LifecycleContract | null
  publication: { enabled: boolean; slug: string | null; published_at: string | null }
  lifecycle: LifecycleStep[]
}

const statusLabel: Record<string, string> = {
  draft: 'Rascunho', available: 'Disponível', reserved: 'Reservado', leased: 'Locado', inactive: 'Inativo',
  approved: 'Aprovada', pending_signature: 'Aguardando assinatura', signed: 'Assinado', cancelled: 'Cancelado',
  active: 'Ativa', inactive_publication: 'Não publicada', not_created: 'Ainda não criada', not_started: 'Não iniciada',
  linked: 'Vinculado', pending: 'Pendente',
}

function label(value: string | null | undefined) { return !value ? '—' : statusLabel[value] ?? value.replaceAll('_', ' ') }
function dateLabel(value: string | null | undefined) { return value ? new Date(value).toLocaleDateString('pt-BR') : '' }

export function PropertyLifecyclePanel({ permissions, propertyId }: { permissions: string[]; propertyId: string }) {
  const canView = permissions.includes('properties.view')
  const [data, setData] = useState<LifecycleResponse | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

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
  if (!canView) return null

  return <article className="panel property-tab-panel property-lifecycle-panel">
    <div className="property-lifecycle-heading">
      <div><span className="eyebrow">Rastreabilidade</span><h2>Ciclo operacional</h2><p>Vínculos deste imóvel desde a captação até a publicação e locação.</p></div>
      <button className="button secondary compact" type="button" onClick={() => setRefreshKey(value => value + 1)} disabled={detailLoading}><RefreshCw size={14} /> Atualizar</button>
    </div>
    {data && <div className="property-lifecycle-progress"><span>{progress}% do ciclo rastreado</span><div><i style={{ width: `${progress}%` }} /></div></div>}
    {error && <div className="property-lifecycle-error"><CircleAlert size={15} /> {error}</div>}
    {detailLoading && <div className="property-lifecycle-loading">Carregando ciclo...</div>}
    {data && !detailLoading && <>
      <div className="property-lifecycle-grid">
        {data.lifecycle.map(step => <article className={`property-lifecycle-step ${step.linked ? 'done' : 'pending'}`} key={step.key}><div className="property-lifecycle-icon">{step.linked ? <CheckCircle2 size={18} /> : <Circle size={18} />}</div><div><strong>{step.label}</strong><span>{step.key === 'property' ? data.property.code : step.key === 'capture' ? (data.capture?.code || 'Sem captação vinculada') : step.key === 'person' ? (data.contact_person?.name || 'Sem pessoa vinculada') : step.key === 'administration' ? (data.administration?.code || 'Ainda não criada') : step.key === 'publication' ? (data.publication.enabled ? 'Publicada no site' : 'Não publicada') : (data.lease?.code || 'Ainda não criada')}</span><small>{label(step.status)}</small></div></article>)}
      </div>
      <div className="property-lifecycle-summary">
        <div><span>Captação</span><strong>{data.capture ? `${data.capture.code} · ${label(data.capture.status)}` : 'Ainda não vinculada'}</strong>{data.capture?.source && <small>Origem: {data.capture.source}</small>}</div>
        <div><span>Pessoa</span><strong>{data.contact_person?.name || 'Ainda não vinculada'}</strong>{data.contact_person?.role_keys?.length ? <small>{data.contact_person.role_keys.join(' · ')}</small> : null}</div>
        <div><span>Proprietários</span><strong>{data.owners.length ? `${data.owners.length} vinculado(s)` : 'Nenhum vinculado'}</strong>{data.owners.length > 0 && <small>{data.owners.map(owner => `${owner.name} (${owner.ownership_percent}%)`).join(' · ')}</small>}</div>
        <div><span>Administração</span><strong>{data.administration?.code || 'Ainda não criada'}</strong>{data.administration && <small>{label(data.administration.status)}{data.administration.signed_at ? ` · assinada em ${dateLabel(data.administration.signed_at)}` : ''}</small>}</div>
        <div><span>Publicação</span><strong>{data.publication.enabled ? 'Publicada no site' : 'Não publicada'}</strong>{data.publication.slug && <small>/{data.publication.slug}</small>}</div>
        <div><span>Locação</span><strong>{data.lease?.code || 'Ainda não criada'}</strong>{data.lease && <small>{label(data.lease.status)}{data.lease.signed_at ? ` · assinada em ${dateLabel(data.lease.signed_at)}` : ''}</small>}</div>
      </div>
    </>}
  </article>
}
