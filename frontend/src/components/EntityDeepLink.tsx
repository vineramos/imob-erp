import { ArrowRight, Copy, LoaderCircle, UserRound, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../api/client'
import './entity-deep-link.css'

type DeepLinkTarget = { kind: string; id: string; overlayBaseRoute?: string }
type DeepLinkDetail = { label: string; value: string }
type DeepLinkRecord = {
  kind: string
  module: string
  module_label: string
  code: string
  title: string
  status: string | null
  status_label: string
  subtitle: string
  details: DeepLinkDetail[]
  root_route: string
}
type Props = { route: string }

const patterns: Array<[RegExp, string]> = [
  [/^\/app\/people\/([^/?#]+)\/?$/, 'person'],
  [/^\/app\/properties\/([^/?#]+)\/?$/, 'property'],
  [/^\/app\/contracts\/administration\/([^/?#]+)\/?$/, 'administration_contract'],
  [/^\/app\/contracts\/lease\/([^/?#]+)\/?$/, 'lease_contract'],
  [/^\/app\/inspections\/([^/?#]+)\/?$/, 'inspection'],
  [/^\/app\/maintenance\/partners\/([^/?#]+)\/?$/, 'maintenance_partner'],
  [/^\/app\/maintenance\/([^/?#]+)\/?$/, 'maintenance'],
  [/^\/app\/finance\/charge\/([^/?#]+)\/?$/, 'charge'],
  [/^\/app\/agenda\/task\/([^/?#]+)\/?$/, 'agenda_task'],
]

function parseTarget(route: string): DeepLinkTarget | null {
  const [pathAndQuery] = route.split('#')
  const [path, rawQuery = ''] = pathAndQuery.split('?')
  const params = new URLSearchParams(rawQuery)
  const personId = params.get('person')
  if (personId) {
    params.delete('person')
    const baseQuery = params.toString()
    return { kind:'person', id:personId, overlayBaseRoute: path + (baseQuery ? `?${baseQuery}` : '') }
  }
  for (const [pattern, kind] of patterns) {
    const match = path.match(pattern)
    if (match) return { kind, id: decodeURIComponent(match[1]) }
  }
  return null
}

function statusClass(status: string | null) {
  if (!status) return 'neutral'
  if (['active', 'available', 'approved', 'signed', 'paid', 'completed', 'finalized'].includes(status)) return 'success'
  if (['cancelled', 'inactive', 'overdue', 'missed'].includes(status)) return 'danger'
  if (['reserved', 'review', 'pending_signature', 'awaiting_approval', 'contested', 'pending'].includes(status)) return 'warning'
  return 'neutral'
}

export function EntityDeepLink({ route }: Props) {
  const target = useMemo(() => parseTarget(route), [route])
  const [record, setRecord] = useState<DeepLinkRecord | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!target) {
      setRecord(null); setError(''); setLoading(false); setCopied(false)
      return
    }
    let active = true
    setLoading(true); setError(''); setRecord(null); setCopied(false)
    void apiRequest<DeepLinkRecord>(`/deep-links/${encodeURIComponent(target.kind)}/${encodeURIComponent(target.id)}`)
      .then(value => { if (active) setRecord(value) })
      .catch(cause => { if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível abrir este registro.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [target])

  useEffect(() => {
    if (!target) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') closePanel() }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  })

  if (!target) return null

  function closePanel() {
    if (target.overlayBaseRoute) {
      window.history.replaceState({}, '', target.overlayBaseRoute)
      window.dispatchEvent(new PopStateEvent('popstate'))
      return
    }
    if (record) {
      window.history.replaceState({}, '', record.root_route)
      window.dispatchEvent(new PopStateEvent('popstate'))
      return
    }
    window.history.back()
  }

  function openFullModule() {
    if (!record) return
    window.history.pushState({}, '', record.root_route)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopied(false)
    }
  }

  return <div className="entity-deep-link-layer" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) closePanel() }}>
    <aside className={`entity-deep-link panel ${record?.kind==='person'?'entity-deep-link-person':''}`} role="dialog" aria-modal="true" aria-label="Detalhes do registro">
      <header className="entity-deep-link-header">
        <div className="entity-deep-link-identity">
          {record?.kind==='person'&&<div className="entity-deep-link-avatar" aria-hidden="true"><UserRound size={18}/></div>}
          <div>
            <span className="eyebrow">{record ? `Registro vinculado · ${record.module_label}` : 'Abrindo registro'}</span>
            <h2>{record?.title || 'Carregando...'}</h2>
            {record?.subtitle && <p>{record.subtitle}</p>}
          </div>
        </div>
        <button className="entity-deep-link-close" type="button" onClick={closePanel} aria-label="Fechar detalhe"><X size={18}/></button>
      </header>

      {loading && <div className="entity-deep-link-state"><LoaderCircle className="entity-deep-link-spinner" size={22}/><strong>Localizando o registro...</strong><span>Acesso e permissões estão sendo validados.</span></div>}
      {!loading && error && <div className="entity-deep-link-state error"><strong>Não foi possível abrir o registro.</strong><span>{error}</span><button className="button secondary" type="button" onClick={closePanel}>Voltar ao módulo</button></div>}

      {!loading && record && <>
        <div className="entity-deep-link-summary">
          <div><span>Código</span><strong>{record.code}</strong></div>
          {record.status_label && <i className={`status-badge ${statusClass(record.status)}`}>{record.status_label}</i>}
        </div>
        <div className="entity-deep-link-details">
          {record.details.map((detail, index) => <div className={`entity-deep-link-detail ${detail.label==='Papéis'?'entity-deep-link-detail-tags':''}`} key={`${detail.label}-${index}`}>
            <span>{detail.label}</span>
            {detail.label==='Papéis'
              ? <div className="entity-deep-link-tags">{detail.value.split(',').map(value=><i key={value.trim()}>{value.trim()}</i>)}</div>
              : <strong>{detail.value}</strong>}
          </div>)}
        </div>
        <footer className="entity-deep-link-actions">
          <button className="button secondary" type="button" onClick={() => void copyLink()}><Copy size={14}/>{copied ? 'Link copiado' : 'Copiar link'}</button>
          <button className="button primary" type="button" onClick={openFullModule}>Abrir módulo completo <ArrowRight size={14}/></button>
        </footer>
      </>}
    </aside>
  </div>
}
