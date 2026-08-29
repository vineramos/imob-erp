import { Handshake, MapPin, Plus, Search, UserRound } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { Address, Capture, CaptureCreate, Person } from '../../api/types'

const emptyAddress = (): Address => ({ street: '', number: '', complement: '', neighborhood: '', city: 'Curitiba', state: 'PR', postal_code: '' })

const statusLabels: Record<string, string> = {
  new: 'Nova', negotiation: 'Negociação', documents: 'Documentos', inspection: 'Vistoria / Cadastro', approved: 'Aprovada', available: 'Disponível', lost: 'Perdida',
}

const sourceLabels: Record<string, string> = {
  direct: 'Direta', site: 'Site', referral: 'Indicação', broker: 'Corretor', campaign: 'Campanha', other: 'Outro',
}

function money(value: number | null) {
  return value == null ? '—' : value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function addressLine(address: Address) {
  return [address.street, address.number, address.neighborhood, address.city].filter(Boolean).join(', ') || 'Endereço ainda não informado'
}

type Props = { permissions: string[] }

export function CapturesPage({ permissions }: Props) {
  const canManage = permissions.includes('captures.manage')
  const [items, setItems] = useState<Capture[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState<CaptureCreate>({
    status: 'new', source: 'direct', contact_person_id: null, responsible_user_id: null,
    property_type: 'apartment', property_address: emptyAddress(), estimated_rent: null, notes: '',
  })

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [captures, persons] = await Promise.all([apiRequest<Capture[]>('/captures'), apiRequest<Person[]>('/people')])
      setItems(captures); setPeople(persons)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar as captações.')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return items
    return items.filter((item) => `${item.contact_person_name ?? ''} ${addressLine(item.property_address)} ${sourceLabels[item.source] ?? item.source}`.toLowerCase().includes(term))
  }, [items, query])

  function updateAddress(key: keyof Address, value: string) {
    setForm((current) => ({ ...current, property_address: { ...current.property_address, [key]: value } }))
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!canManage) return
    setSaving(true); setError('')
    try {
      const created = await apiRequest<Capture>('/captures', { method: 'POST', body: JSON.stringify(form) })
      setItems((current) => [created, ...current])
      setForm({ status: 'new', source: 'direct', contact_person_id: null, responsible_user_id: null, property_type: 'apartment', property_address: emptyAddress(), estimated_rent: null, notes: '' })
      setShowForm(false)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível cadastrar a captação.')
    } finally { setSaving(false) }
  }

  const counts = useMemo(() => ({
    open: items.filter((item) => item.status !== 'lost' && item.status !== 'available').length,
    approved: items.filter((item) => item.status === 'approved' || item.status === 'available').length,
    lost: items.filter((item) => item.status === 'lost').length,
  }), [items])

  return (
    <section className="workspace portfolio-workspace">
      <div className="page-heading portfolio-heading">
        <div><span className="eyebrow">Entrada de carteira</span><h1>Captações</h1><p>Da primeira conversa até a aprovação para administração, com origem, responsável e histórico rastreáveis.</p></div>
        {canManage && <button className="button primary" type="button" onClick={() => setShowForm((value) => !value)}><Plus size={15}/> Nova captação</button>}
      </div>

      {error && <div className="form-alert danger-alert">{error}</div>}

      <div className="metric-grid capture-metrics">
        <article className="metric-card"><span>Em andamento</span><strong>{counts.open}</strong><small>Captações ativas</small></article>
        <article className="metric-card"><span>Aprovadas</span><strong>{counts.approved}</strong><small>Prontas ou já disponíveis</small></article>
        <article className="metric-card"><span>Perdidas</span><strong>{counts.lost}</strong><small>Motivo será preservado</small></article>
        <article className="metric-card"><span>Total</span><strong>{items.length}</strong><small>Histórico da operação</small></article>
      </div>

      {showForm && <form className="panel portfolio-form" onSubmit={save}><div className="panel-heading panel-heading-row"><div><span className="eyebrow">Nova oportunidade</span><h2>Cadastrar captação</h2></div><Handshake size={20}/></div><div className="form-grid three-columns"><label className="field"><span>Origem</span><select value={form.source} onChange={(e) => setForm((c) => ({ ...c, source: e.target.value as CaptureCreate['source'] }))}><option value="direct">Direta</option><option value="site">Site</option><option value="referral">Indicação</option><option value="broker">Corretor</option><option value="campaign">Campanha</option><option value="other">Outro</option></select></label><label className="field"><span>Contato / proprietário</span><select value={form.contact_person_id ?? ''} onChange={(e) => setForm((c) => ({ ...c, contact_person_id: e.target.value || null }))}><option value="">Não vinculado</option>{people.map((person) => <option value={person.id} key={person.id}>{person.name}</option>)}</select></label><label className="field"><span>Tipo de imóvel</span><select value={form.property_type ?? ''} onChange={(e) => setForm((c) => ({ ...c, property_type: e.target.value as CaptureCreate['property_type'] }))}><option value="apartment">Apartamento</option><option value="house">Casa</option><option value="commercial">Comercial</option><option value="land">Terreno</option><option value="studio">Studio</option><option value="other">Outro</option></select></label><label className="field field-span-2"><span>Rua</span><input value={form.property_address.street} onChange={(e) => updateAddress('street', e.target.value)}/></label><label className="field"><span>Número</span><input value={form.property_address.number} onChange={(e) => updateAddress('number', e.target.value)}/></label><label className="field"><span>Bairro</span><input value={form.property_address.neighborhood} onChange={(e) => updateAddress('neighborhood', e.target.value)}/></label><label className="field"><span>Cidade</span><input value={form.property_address.city} onChange={(e) => updateAddress('city', e.target.value)}/></label><label className="field"><span>Aluguel estimado</span><input min="0" step="0.01" type="number" value={form.estimated_rent ?? ''} onChange={(e) => setForm((c) => ({ ...c, estimated_rent: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field field-span-3"><span>Observações iniciais</span><textarea rows={3} value={form.notes ?? ''} onChange={(e) => setForm((c) => ({ ...c, notes: e.target.value }))}/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={() => setShowForm(false)}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : 'Cadastrar captação'}</button></div></form>}

      <article className="panel portfolio-toolbar"><label className="portfolio-search capture-search"><Search size={15}/><input placeholder="Buscar por contato, endereço ou origem..." value={query} onChange={(event) => setQuery(event.target.value)}/></label></article>

      {loading ? <article className="panel settings-loading">Carregando captações...</article> : <div className="portfolio-card-list">{filtered.map((item) => <article className="panel capture-row" key={item.id}><div className="capture-status-rail"><i className={`capture-dot ${item.status}`}/></div><div className="capture-main"><div><strong>{item.contact_person_name || 'Contato ainda não vinculado'}</strong><span className="status-badge neutral">{sourceLabels[item.source] ?? item.source}</span></div><span><MapPin size={13}/>{addressLine(item.property_address)}</span><small>{item.notes || 'Sem observações adicionais.'}</small></div><div className="capture-value"><span>Aluguel estimado</span><strong>{money(item.estimated_rent)}</strong></div><div className="capture-stage"><span>Etapa</span><strong>{statusLabels[item.status] ?? item.status}</strong><small>{new Date(item.created_at).toLocaleDateString('pt-BR')}</small></div></article>)}{filtered.length === 0 && <article className="panel portfolio-empty"><Handshake size={27}/><strong>Nenhuma captação encontrada.</strong><span>As novas oportunidades aparecerão aqui antes de virarem imóveis administrados.</span></article>}</div>}

      <article className="panel governance-note-card capture-governance"><UserRound size={21}/><div><span className="eyebrow">Regra preservada</span><h2>Captação não é imóvel ainda</h2><p>A oportunidade mantém seu próprio histórico. Somente depois da aprovação e conversão ela gera o cadastro definitivo do imóvel.</p></div></article>
    </section>
  )
}
