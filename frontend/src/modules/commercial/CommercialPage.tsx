import { ArrowUpDown, CheckCircle2, CircleAlert, ExternalLink, Globe2, RefreshCw, Save, Search, Send, X, XCircle } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { IntegrationsConfig, Property, PublicationReadiness } from '../../api/types'

function addressLine(address: Record<string, string>) {
  return [address.street, address.number, address.neighborhood, address.city].filter(Boolean).join(', ') || 'Endereço não informado'
}
function money(value: number | null) {
  return value == null ? '—' : value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

type CommercialPropertyProfile = {
  property_id: string
  status: 'draft' | 'available' | 'inactive'
  purpose: string
  public_title: string
  public_description: string
  rent_amount: number | null
  condo_amount: number | null
  iptu_amount: number | null
  publication_enabled: boolean
}
type Props = { permissions: string[]; organizationId: string }

export function CommercialPage({ permissions, organizationId }: Props) {
  const granted = useMemo(() => new Set(permissions), [permissions])
  const canEdit = granted.has('properties.edit')
  const canPublish = granted.has('properties.publish')
  const [items, setItems] = useState<Property[]>([])
  const [integrations, setIntegrations] = useState<IntegrationsConfig | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [readiness, setReadiness] = useState<PublicationReadiness | null>(null)
  const [profile, setProfile] = useState<CommercialPropertyProfile | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [saving, setSaving] = useState(false)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | 'published' | 'available'>('all')
  const [typeFilter,setTypeFilter]=useState('all')
  const [furnishedOnly,setFurnishedOnly]=useState(false)
  const [commercialSort,setCommercialSort]=useState<'recent'|'price_asc'|'price_desc'|'bedrooms_desc'>('recent')
  const [pageError, setPageError] = useState('')
  const [modalError, setModalError] = useState('')
  const [success, setSuccess] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setPageError('')
    try {
      const [properties, settings] = await Promise.all([apiRequest<Property[]>('/properties'), apiRequest<IntegrationsConfig>('/settings/integrations')])
      setItems(properties); setIntegrations(settings)
    } catch (cause) {
      setPageError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar o catálogo comercial.')
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!modalOpen) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && !saving) setModalOpen(false) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [modalOpen, saving])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    const result=items.filter((item) => {
      if (filter === 'published' && !item.publication_enabled) return false
      if (filter === 'available' && item.status !== 'available') return false
      if (typeFilter !== 'all' && item.property_type !== typeFilter) return false
      if (furnishedOnly && !item.furnished) return false
      return !term || (item.code+' '+(item.public_title ?? '')+' '+addressLine(item.address)).toLowerCase().includes(term)
    })
    return [...result].sort((a,b)=>{
      if(commercialSort==='price_asc')return Number(a.rent_amount??Number.MAX_SAFE_INTEGER)-Number(b.rent_amount??Number.MAX_SAFE_INTEGER)
      if(commercialSort==='price_desc')return Number(b.rent_amount??-1)-Number(a.rent_amount??-1)
      if(commercialSort==='bedrooms_desc')return b.bedrooms-a.bedrooms||b.suites-a.suites
      return new Date(b.updated_at).getTime()-new Date(a.updated_at).getTime()
    })
  }, [items, query, filter, typeFilter, furnishedOnly, commercialSort])
  const metrics = useMemo(() => ({
    available: items.filter((item) => item.status === 'available').length,
    published: items.filter((item) => item.publication_enabled).length,
    withheld: items.filter((item) => item.status === 'available' && !item.publication_enabled).length,
  }), [items])

  async function inspect(propertyId: string) {
    setSelectedId(propertyId); setModalOpen(true); setChecking(true); setModalError(''); setSuccess('')
    try {
      const [nextReadiness, nextProfile] = await Promise.all([
        apiRequest<PublicationReadiness>(`/properties/${propertyId}/publication-readiness`),
        apiRequest<CommercialPropertyProfile>(`/properties/${propertyId}/commercial-profile`),
      ])
      setReadiness(nextReadiness); setProfile(nextProfile)
    } catch (cause) {
      setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar o perfil comercial do imóvel.')
    } finally { setChecking(false) }
  }

  async function saveProfile() {
    if (!selectedId || !profile || !canEdit) return
    setSaving(true); setModalError('')
    try {
      const wasPublished = profile.publication_enabled
      const updated = await apiRequest<CommercialPropertyProfile>(`/properties/${selectedId}/commercial-profile`, { method: 'PUT', body: JSON.stringify({ status: profile.status, public_title: profile.public_title, public_description: profile.public_description, rent_amount: profile.rent_amount, condo_amount: profile.condo_amount, iptu_amount: profile.iptu_amount }) })
      setProfile(updated)
      const nextReadiness = await apiRequest<PublicationReadiness>(`/properties/${selectedId}/publication-readiness`)
      setReadiness(nextReadiness)
      setItems((current) => current.map((item) => item.id === selectedId ? { ...item, status: updated.status, public_title: updated.public_title || null, rent_amount: updated.rent_amount, condo_amount: updated.condo_amount, iptu_amount: updated.iptu_amount, publication_enabled: updated.publication_enabled } : item))
      setSuccess(wasPublished ? 'Perfil salvo; o anúncio foi retirado temporariamente para nova conferência.' : 'Perfil comercial salvo e checklist recalculado.')
    } catch (cause) {
      setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar o perfil comercial.')
    } finally { setSaving(false) }
  }

  async function togglePublication(enabled: boolean) {
    if (!selectedId || !canPublish) return
    let reason: string | null = null
    if (!enabled) { reason = window.prompt('Informe o motivo para retirar o imóvel do site:'); if (!reason?.trim()) return }
    setSaving(true); setModalError('')
    try {
      const result = await apiRequest<PublicationReadiness>(`/properties/${selectedId}/publication`, { method: 'POST', body: JSON.stringify({ enabled, reason }) })
      setReadiness(result)
      setProfile((current) => current ? { ...current, publication_enabled: result.publication_enabled } : current)
      setItems((current) => current.map((item) => item.id === selectedId ? { ...item, publication_enabled: result.publication_enabled, public_slug: result.public_slug } : item))
      setSuccess(enabled ? `Imóvel #${result.code} publicado no catálogo próprio.` : `Imóvel #${result.code} retirado do catálogo.`)
    } catch (cause) { setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível alterar a publicação.') }
    finally { setSaving(false) }
  }

  const selected = items.find((item) => item.id === selectedId) ?? null

  return <section className="workspace commercial-workspace commercial-refresh">
    <div className="page-heading portfolio-heading"><div><span className="eyebrow">Comercial · CRM</span><h1>Publicação de imóveis</h1><p>Estoque comercial em uma visão limpa. Clique em um imóvel para editar perfil, checklist e publicação em modal.</p></div><button className="button secondary" type="button" onClick={() => void load()}><RefreshCw size={14}/> Atualizar</button></div>
    <div className="dashboard-metrics commercial-metrics"><article className="panel metric-card"><span>Disponíveis</span><strong>{metrics.available}</strong><small>estoque comercial</small></article><article className="panel metric-card"><span>Publicados</span><strong>{metrics.published}</strong><small>visíveis no catálogo</small></article><article className="panel metric-card"><span>Fora do site</span><strong>{metrics.withheld}</strong><small>disponíveis, não publicados</small></article></div>
    {!integrations?.public_site_enabled && <div className="form-alert warning-alert"><CircleAlert size={16}/> O site público está desabilitado. O perfil e o checklist continuam funcionando normalmente.</div>}
    {pageError && <div className="form-alert danger-alert">{pageError}</div>}{success && <div className="form-alert success-alert">{success}</div>}

    <div className="portfolio-toolbar panel commercial-toolbar commercial-toolbar-wide commercial-toolbar-v82"><div className="portfolio-tabs"><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')} type="button">Todos <span>{items.length}</span></button><button className={filter === 'available' ? 'active' : ''} onClick={() => setFilter('available')} type="button">Disponíveis <span>{metrics.available}</span></button><button className={filter === 'published' ? 'active' : ''} onClick={() => setFilter('published')} type="button">Publicados <span>{metrics.published}</span></button></div><label className="portfolio-search"><Search size={14}/><input placeholder="Código, título ou endereço..." value={query} onChange={(e) => setQuery(e.target.value)}/></label><select value={typeFilter} onChange={e=>setTypeFilter(e.target.value)}><option value="all">Todos os tipos</option><option value="apartment">Apartamento</option><option value="house">Casa</option><option value="commercial">Comercial</option><option value="land">Terreno</option><option value="studio">Studio</option><option value="other">Outro</option></select><button type="button" className={'commercial-quick-filter '+(furnishedOnly?'active':'')} onClick={()=>setFurnishedOnly(value=>!value)}>Mobiliado</button><label className="commercial-sort"><ArrowUpDown size={13}/><select value={commercialSort} onChange={e=>setCommercialSort(e.target.value as 'recent'|'price_asc'|'price_desc'|'bedrooms_desc')}><option value="recent">Mais recentes</option><option value="price_asc">Menor aluguel</option><option value="price_desc">Maior aluguel</option><option value="bedrooms_desc">Mais quartos</option></select></label></div>
    {loading ? <article className="panel settings-loading">Carregando catálogo...</article> : <div className="commercial-card-grid">{filtered.map((item) => <button className="panel commercial-property-card commercial-property-card-v82" type="button" key={item.id} onClick={() => void inspect(item.id)}><div className="commercial-property-card-top"><div><span className="eyebrow">IMÓVEL #{item.code}</span><strong>{item.public_title || addressLine(item.address)}</strong><small>{addressLine(item.address)}</small></div><i className={`status-badge ${item.publication_enabled ? 'success' : item.status === 'available' ? 'warning' : 'neutral'}`}>{item.publication_enabled ? 'Publicado' : item.status === 'available' ? 'Aguardando' : item.status}</i></div><div className="commercial-property-card-facts"><span>{item.bedrooms} qtos</span>{item.suites>0&&<span>{item.suites} suítes</span>}<span>{item.parking_spaces} vagas</span>{item.furnished&&<span>Mobiliado</span>}<span>{item.address.neighborhood||item.address.city}</span></div><div className="commercial-property-card-value"><span>Aluguel</span><strong>{money(item.rent_amount)}</strong></div></button>)}{filtered.length === 0 && <article className="panel portfolio-empty"><Globe2 size={26}/><strong>Nenhum imóvel neste filtro.</strong><span>Ajuste a busca ou os filtros do catálogo comercial.</span></article>}</div>}
    <article className="panel commercial-api-note"><Globe2 size={22}/><div><span className="eyebrow">API pública</span><h2>Catálogo desacoplado do ERP</h2><p>Somente dados comerciais sanitizados saem pela API. Organização atual: {organizationId.slice(0, 8)}…</p></div></article>

    {modalOpen && <div className="portfolio-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !saving) setModalOpen(false) }}>
      <div className="panel portfolio-modal commercial-profile-modal" role="dialog" aria-modal="true">
        <div className="portfolio-modal-header"><div><span className="eyebrow">Perfil comercial{readiness ? ` · #${readiness.code}` : ''}</span><h2>{profile?.public_title || selected?.public_title || 'Perfil do imóvel'}</h2><p>{selected ? addressLine(selected.address) : 'Carregando imóvel...'}</p></div><button className="portfolio-modal-close" type="button" aria-label="Fechar" disabled={saving} onClick={() => setModalOpen(false)}><X size={17}/></button></div>
        <div className="commercial-modal-body">
          {modalError && <div className="form-alert danger-alert" role="alert">{modalError}</div>}
          {checking ? <div className="settings-loading">Carregando perfil comercial...</div> : readiness && profile ? <>
            <section className="canonical-modal-section"><div className="commercial-modal-section-heading"><div><span className="eyebrow">Anúncio</span><h3>Dados comerciais</h3></div>{readiness.ready ? <CheckCircle2 className="publication-ok" size={23}/> : <CircleAlert className="publication-pending" size={23}/>}</div><div className="commercial-profile-form"><div className="commercial-profile-grid"><label className="field"><span>Status comercial</span><select disabled={!canEdit} value={profile.status} onChange={(e) => setProfile((current) => current ? { ...current, status: e.target.value as CommercialPropertyProfile['status'] } : current)}><option value="draft">Rascunho</option><option value="available">Disponível</option><option value="inactive">Inativo</option></select></label><label className="field"><span>Aluguel</span><input disabled={!canEdit} min="0" step="0.01" type="number" value={profile.rent_amount ?? ''} onChange={(e) => setProfile((current) => current ? { ...current, rent_amount: e.target.value ? Number(e.target.value) : null } : current)}/></label><label className="field"><span>Condomínio</span><input disabled={!canEdit} min="0" step="0.01" type="number" value={profile.condo_amount ?? ''} onChange={(e) => setProfile((current) => current ? { ...current, condo_amount: e.target.value ? Number(e.target.value) : null } : current)}/></label><label className="field"><span>IPTU</span><input disabled={!canEdit} min="0" step="0.01" type="number" value={profile.iptu_amount ?? ''} onChange={(e) => setProfile((current) => current ? { ...current, iptu_amount: e.target.value ? Number(e.target.value) : null } : current)}/></label></div><label className="field"><span>Título público</span><input disabled={!canEdit} maxLength={180} value={profile.public_title} onChange={(e) => setProfile((current) => current ? { ...current, public_title: e.target.value } : current)}/></label><label className="field"><span>Descrição pública</span><textarea disabled={!canEdit} rows={5} maxLength={5000} placeholder="Descreva o imóvel, diferenciais e características relevantes..." value={profile.public_description} onChange={(e) => setProfile((current) => current ? { ...current, public_description: e.target.value } : current)}/></label><div className="commercial-profile-actions"><small>{profile.public_description.trim().length} caracteres · mínimo: 30</small><button className="button secondary" disabled={!canEdit || saving} type="button" onClick={() => void saveProfile()}><Save size={14}/> Salvar perfil</button></div></div></section>
            <section className="canonical-modal-section"><div className="publication-checklist-heading"><span className="eyebrow">Checklist de publicação</span><strong>{readiness.ready ? 'Pronto para publicar' : 'Existem pendências'}</strong></div><div className="publication-checklist commercial-checklist-grid">{readiness.checklist.map((check) => <div className={check.ok ? 'ok' : 'pending'} key={check.key}>{check.ok ? <CheckCircle2 size={16}/> : <XCircle size={16}/>}<div><strong>{check.label}</strong><span>{check.ok ? 'Pronto' : check.detail}</span></div></div>)}</div></section>
          </> : null}
        </div>
        {readiness && profile && <div className="canonical-modal-actions commercial-modal-actions"><div>{readiness.public_slug && <div className="publication-slug"><ExternalLink size={13}/><span>/imoveis/{readiness.public_slug}</span></div>}</div><div>{readiness.publication_enabled ? <button className="button ghost-danger" disabled={!canPublish || saving} type="button" onClick={() => void togglePublication(false)}>Retirar do site</button> : <button className="button primary" disabled={!canPublish || saving || !readiness.ready} type="button" onClick={() => void togglePublication(true)}><Send size={14}/> Publicar no site</button>}</div></div>}
      </div>
    </div>}
  </section>
}
