import { CalendarCheck2, Mail, MessageCircle, Phone, RefreshCw, Search, UserRoundCheck } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'

type InquiryStatus = 'new' | 'contacted' | 'visit_scheduled' | 'qualified' | 'lost'
type SiteInquiry = {
  id: string
  property_id: string | null
  property_code: string
  property_title: string
  name: string
  email: string | null
  phone: string | null
  preferred_contact: string
  message: string | null
  status: InquiryStatus
  source: string
  created_at: string
  updated_at: string
}

type Props = { permissions: string[] }

const statusLabels: Record<InquiryStatus, string> = {
  new: 'Novo', contacted: 'Contatado', visit_scheduled: 'Visita agendada', qualified: 'Qualificado', lost: 'Perdido',
}

function dateTime(value: string) {
  return new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

function whatsappLink(phone: string) {
  let digits = phone.replace(/\D/g, '')
  if (!digits.startsWith('55') && (digits.length === 10 || digits.length === 11)) digits = `55${digits}`
  return `https://wa.me/${digits}`
}

export function SiteInquiriesPanel({ permissions }: Props) {
  const canManage = permissions.includes('crm.manage')
  const [items, setItems] = useState<SiteInquiry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | InquiryStatus>('all')
  const [updatingId, setUpdatingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setItems(await apiRequest<SiteInquiry[]>('/crm/site-inquiries')) }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os interesses recebidos pelo site.') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  const metrics = useMemo(() => ({
    new: items.filter((item) => item.status === 'new').length,
    visits: items.filter((item) => item.status === 'visit_scheduled').length,
    active: items.filter((item) => ['contacted', 'qualified'].includes(item.status)).length,
  }), [items])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter((item) => {
      if (filter !== 'all' && item.status !== filter) return false
      if (!term) return true
      return `${item.property_code} ${item.property_title} ${item.name} ${item.email ?? ''} ${item.phone ?? ''} ${item.message ?? ''}`.toLowerCase().includes(term)
    })
  }, [filter, items, query])

  async function changeStatus(item: SiteInquiry, nextStatus: InquiryStatus) {
    if (!canManage || nextStatus === item.status) return
    setUpdatingId(item.id); setError('')
    try {
      const updated = await apiRequest<SiteInquiry>(`/crm/site-inquiries/${item.id}`, { method: 'PATCH', body: JSON.stringify({ status: nextStatus }) })
      setItems((current) => current.map((row) => row.id === item.id ? updated : row))
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível atualizar o atendimento.') }
    finally { setUpdatingId(null) }
  }

  return <section className="workspace commercial-workspace site-inquiries-workspace">
    <div className="page-heading portfolio-heading"><div><span className="eyebrow">Comercial · Site público</span><h1>Interesses recebidos</h1><p>Leads enviados pela página de cada imóvel, já vinculados ao anúncio que originou o contato.</p></div><button className="button secondary" type="button" onClick={() => void load()}><RefreshCw size={14}/> Atualizar</button></div>
    <div className="dashboard-metrics commercial-metrics"><article className="panel metric-card"><span>Novos</span><strong>{metrics.new}</strong><small>aguardando primeiro contato</small></article><article className="panel metric-card"><span>Em atendimento</span><strong>{metrics.active}</strong><small>contatados ou qualificados</small></article><article className="panel metric-card"><span>Visitas</span><strong>{metrics.visits}</strong><small>agendadas pelo comercial</small></article></div>
    {error && <div className="form-alert danger-alert" role="alert">{error}</div>}
    <div className="portfolio-toolbar panel commercial-toolbar commercial-toolbar-wide site-inquiries-toolbar"><div className="portfolio-tabs"><button className={filter === 'all' ? 'active' : ''} type="button" onClick={() => setFilter('all')}>Todos <span>{items.length}</span></button><button className={filter === 'new' ? 'active' : ''} type="button" onClick={() => setFilter('new')}>Novos <span>{metrics.new}</span></button><button className={filter === 'visit_scheduled' ? 'active' : ''} type="button" onClick={() => setFilter('visit_scheduled')}>Visitas <span>{metrics.visits}</span></button></div><label className="portfolio-search"><Search size={14}/><input placeholder="Imóvel, nome, telefone ou e-mail..." value={query} onChange={(event) => setQuery(event.target.value)}/></label></div>
    {loading ? <article className="panel settings-loading">Carregando interesses...</article> : <div className="site-inquiries-list">{filtered.map((item) => <article className={`panel site-inquiry-card status-${item.status}`} key={item.id}>
      <div className="site-inquiry-property"><span className="eyebrow">IMÓVEL #{item.property_code}</span><strong>{item.property_title}</strong><small>Recebido em {dateTime(item.created_at)}</small></div>
      <div className="site-inquiry-contact"><strong>{item.name}</strong><div>{item.phone && <><a href={whatsappLink(item.phone)} target="_blank" rel="noreferrer"><MessageCircle size={13}/> WhatsApp</a><a href={`tel:${item.phone}`}><Phone size={13}/> Ligar</a></>}{item.email && <a href={`mailto:${item.email}?subject=Interesse no imóvel ${item.property_code}`}><Mail size={13}/> E-mail</a>}</div><small>Preferência: {item.preferred_contact === 'email' ? 'e-mail' : item.preferred_contact === 'phone' ? 'ligação' : 'WhatsApp'}</small></div>
      <div className="site-inquiry-message"><span>Mensagem</span><p>{item.message || 'Sem mensagem adicional.'}</p></div>
      <div className="site-inquiry-status">{canManage ? <label><span>Status do atendimento</span><select value={item.status} disabled={updatingId === item.id} onChange={(event) => void changeStatus(item, event.target.value as InquiryStatus)}>{(Object.keys(statusLabels) as InquiryStatus[]).map((key) => <option key={key} value={key}>{statusLabels[key]}</option>)}</select></label> : <span className="status-badge neutral">{statusLabels[item.status]}</span>}{item.status === 'visit_scheduled' ? <CalendarCheck2 size={18}/> : item.status === 'qualified' ? <UserRoundCheck size={18}/> : null}</div>
    </article>)}{filtered.length === 0 && <article className="panel portfolio-empty"><Search size={26}/><strong>Nenhum interesse neste filtro.</strong><span>Novos contatos enviados pelo site aparecerão aqui.</span></article>}</div>}
  </section>
}
