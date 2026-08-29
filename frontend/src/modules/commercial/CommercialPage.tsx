import { CheckCircle2, CircleAlert, ExternalLink, Globe2, RefreshCw, Search, Send, XCircle } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { IntegrationsConfig, Property, PublicationReadiness } from '../../api/types'

function addressLine(address: Record<string, string>) {
  return [address.street, address.number, address.neighborhood, address.city].filter(Boolean).join(', ') || 'Endereço não informado'
}

function money(value: number | null) {
  if (value == null) return '—'
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

type Props = { permissions: string[]; organizationId: string }

export function CommercialPage({ permissions, organizationId }: Props) {
  const granted = useMemo(() => new Set(permissions), [permissions])
  const canPublish = granted.has('properties.publish')
  const [items, setItems] = useState<Property[]>([])
  const [integrations, setIntegrations] = useState<IntegrationsConfig | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [readiness, setReadiness] = useState<PublicationReadiness | null>(null)
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [saving, setSaving] = useState(false)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | 'published' | 'available'>('all')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [properties, settings] = await Promise.all([
        apiRequest<Property[]>('/properties'),
        apiRequest<IntegrationsConfig>('/settings/integrations'),
      ])
      setItems(properties); setIntegrations(settings)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar o catálogo comercial.')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter((item) => {
      if (filter === 'published' && !item.publication_enabled) return false
      if (filter === 'available' && item.status !== 'available') return false
      if (!term) return true
      return `${item.code} ${item.public_title ?? ''} ${addressLine(item.address)}`.toLowerCase().includes(term)
    })
  }, [items, query, filter])

  const metrics = useMemo(() => ({
    available: items.filter((item) => item.status === 'available').length,
    published: items.filter((item) => item.publication_enabled).length,
    withheld: items.filter((item) => item.status === 'available' && !item.publication_enabled).length,
  }), [items])

  async function inspect(propertyId: string) {
    setSelectedId(propertyId); setChecking(true); setError(''); setSuccess('')
    try { setReadiness(await apiRequest<PublicationReadiness>(`/properties/${propertyId}/publication-readiness`)) }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível validar o checklist de publicação.') }
    finally { setChecking(false) }
  }

  async function togglePublication(enabled: boolean) {
    if (!selectedId || !canPublish) return
    let reason: string | null = null
    if (!enabled) { reason = window.prompt('Informe o motivo para retirar o imóvel do site:'); if (!reason?.trim()) return }
    setSaving(true); setError(''); setSuccess('')
    try {
      const result = await apiRequest<PublicationReadiness>(`/properties/${selectedId}/publication`, {
        method: 'POST', body: JSON.stringify({ enabled, reason }),
      })
      setReadiness(result)
      setItems((current) => current.map((item) => item.id === selectedId ? { ...item, publication_enabled: result.publication_enabled, public_slug: result.public_slug } : item))
      setSuccess(enabled ? `Imóvel #${result.code} publicado no catálogo próprio.` : `Imóvel #${result.code} retirado do catálogo.`)
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível alterar a publicação.') }
    finally { setSaving(false) }
  }

  const selected = items.find((item) => item.id === selectedId) ?? null

  return (
    <section className="workspace commercial-workspace">
      <div className="page-heading portfolio-heading">
        <div><span className="eyebrow">Comercial · Catálogo próprio</span><h1>Publicação de imóveis</h1><p>O ERP é a fonte oficial do anúncio. Só imóveis aprovados pelo checklist entram na API pública do site.</p></div>
        <button className="button secondary" type="button" onClick={() => void load()}><RefreshCw size={14}/> Atualizar</button>
      </div>

      <div className="dashboard-metrics commercial-metrics">
        <article className="panel metric-card"><span>Disponíveis</span><strong>{metrics.available}</strong><small>estoque comercial</small></article>
        <article className="panel metric-card"><span>Publicados</span><strong>{metrics.published}</strong><small>visíveis no catálogo</small></article>
        <article className="panel metric-card"><span>Fora do site</span><strong>{metrics.withheld}</strong><small>disponíveis, não publicados</small></article>
      </div>

      {!integrations?.public_site_enabled && <div className="form-alert warning-alert"><CircleAlert size={16}/> O site público está desabilitado em Configurações → Integrações. O checklist funciona normalmente, mas a API pública permanece fechada.</div>}
      {error && <div className="form-alert danger-alert">{error}</div>}
      {success && <div className="form-alert success-alert">{success}</div>}

      <div className="commercial-grid">
        <div className="commercial-list-column">
          <div className="portfolio-toolbar panel commercial-toolbar">
            <div className="portfolio-tabs"><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')} type="button">Todos <span>{items.length}</span></button><button className={filter === 'available' ? 'active' : ''} onClick={() => setFilter('available')} type="button">Disponíveis <span>{metrics.available}</span></button><button className={filter === 'published' ? 'active' : ''} onClick={() => setFilter('published')} type="button">Publicados <span>{metrics.published}</span></button></div>
            <label className="portfolio-search"><Search size={14}/><input placeholder="Código, título ou endereço..." value={query} onChange={(e) => setQuery(e.target.value)}/></label>
          </div>

          {loading ? <article className="panel settings-loading">Carregando catálogo...</article> : <div className="portfolio-card-list">{filtered.map((item) => <button className={`panel commercial-property-row ${selectedId === item.id ? 'selected' : ''}`} type="button" key={item.id} onClick={() => void inspect(item.id)}><div><span className="eyebrow">IMÓVEL #{item.code}</span><strong>{item.public_title || addressLine(item.address)}</strong><small>{addressLine(item.address)}</small></div><div><span>Aluguel</span><strong>{money(item.rent_amount)}</strong></div><i className={`status-badge ${item.publication_enabled ? 'success' : item.status === 'available' ? 'warning' : 'neutral'}`}>{item.publication_enabled ? 'Publicado' : item.status === 'available' ? 'Aguardando publicação' : item.status}</i></button>)}{filtered.length === 0 && <article className="panel portfolio-empty"><Globe2 size={26}/><strong>Nenhum imóvel neste filtro.</strong></article>}</div>}
        </div>

        <aside className="panel publication-inspector">
          {!selected ? <div className="portfolio-empty"><Globe2 size={28}/><strong>Selecione um imóvel</strong><span>O checklist comercial e as ações de publicação aparecerão aqui.</span></div> : checking ? <div className="settings-loading">Validando publicação...</div> : readiness ? <>
            <div className="publication-inspector-heading"><div><span className="eyebrow">Checklist · #{readiness.code}</span><h2>{selected.public_title || 'Imóvel sem título público'}</h2><p>{addressLine(selected.address)}</p></div>{readiness.ready ? <CheckCircle2 className="publication-ok" size={26}/> : <CircleAlert className="publication-pending" size={26}/>}</div>
            <div className="publication-checklist">{readiness.checklist.map((check) => <div className={check.ok ? 'ok' : 'pending'} key={check.key}>{check.ok ? <CheckCircle2 size={16}/> : <XCircle size={16}/>}<div><strong>{check.label}</strong><span>{check.ok ? 'Pronto' : check.detail}</span></div></div>)}</div>
            <div className="publication-actions">
              {readiness.publication_enabled ? <button className="button ghost-danger" disabled={!canPublish || saving} type="button" onClick={() => void togglePublication(false)}>Retirar do site</button> : <button className="button primary" disabled={!canPublish || saving || !readiness.ready} type="button" onClick={() => void togglePublication(true)}><Send size={14}/> Publicar no site</button>}
              {readiness.public_slug && <div className="publication-slug"><ExternalLink size={13}/><span>/imoveis/{readiness.public_slug}</span></div>}
            </div>
          </> : null}
        </aside>
      </div>

      <article className="panel commercial-api-note"><Globe2 size={22}/><div><span className="eyebrow">API pública</span><h2>Catálogo desacoplado do ERP</h2><p>O backend já expõe perfil e imóveis publicados por organização em endpoints públicos próprios. O site consumirá somente esses dados sanitizados; proprietários, documentos, regras internas e auditoria nunca saem pela API comercial. Organização atual: {organizationId.slice(0, 8)}…</p></div></article>
    </section>
  )
}
