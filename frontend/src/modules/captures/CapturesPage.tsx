import { Building2, ChevronLeft, ChevronRight, Handshake, MapPin, Plus, RotateCcw, Search, UserCheck, UserRound, X } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { Address, Capture, CaptureCreate, Person, Property } from '../../api/types'
import './captures-workflow.css'

const emptyAddress = (): Address => ({ street: '', number: '', complement: '', neighborhood: '', city: 'Curitiba', state: 'PR', postal_code: '' })
const emptyCapture = (): CaptureCreate => ({ status: 'new', source: 'direct', contact_person_id: null, responsible_user_id: null, property_type: 'apartment', property_address: emptyAddress(), estimated_rent: null, notes: '' })

const statusLabels: Record<string, string> = {
  new: 'Nova', negotiation: 'Negociação', documents: 'Documentos', inspection: 'Vistoria / Cadastro', approved: 'Aprovada', available: 'Convertida', lost: 'Perdida',
}
const sourceLabels: Record<string, string> = { direct: 'Direta', site: 'Site', referral: 'Indicação', broker: 'Corretor', campaign: 'Campanha', other: 'Outro' }
const activeStages = ['new', 'negotiation', 'documents', 'inspection', 'approved'] as const
const money = (value: number | null) => value == null ? '—' : value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const addressLine = (address: Address) => [address.street, address.number, address.neighborhood, address.city].filter(Boolean).join(', ') || 'Endereço ainda não informado'

type Props = { permissions: string[] }
type Responsible = { id: string; name: string }
type WorkflowAction = 'advance' | 'back' | 'lose' | 'reopen' | 'assign'
type ConversionResult = { capture: Capture; property: Property }

export function CapturesPage({ permissions }: Props) {
  const canManage = permissions.includes('captures.manage')
  const [items, setItems] = useState<Capture[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [responsibles, setResponsibles] = useState<Responsible[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [managed, setManaged] = useState<Capture | null>(null)
  const [lostReason, setLostReason] = useState('')
  const [reopenReason, setReopenReason] = useState('')
  const [pageError, setPageError] = useState('')
  const [modalError, setModalError] = useState('')
  const [success, setSuccess] = useState('')
  const [form, setForm] = useState<CaptureCreate>(emptyCapture)

  const load = useCallback(async () => {
    setLoading(true); setPageError('')
    try {
      const [captures, persons, responsibleRows] = await Promise.all([
        apiRequest<Capture[]>('/captures'),
        apiRequest<Person[]>('/people'),
        canManage ? apiRequest<Responsible[]>('/captures/responsibles') : Promise.resolve([] as Responsible[]),
      ])
      setItems(captures); setPeople(persons); setResponsibles(responsibleRows)
      setManaged((current) => current ? captures.find((item) => item.id === current.id) ?? null : null)
    } catch (cause) {
      setPageError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar as captações.')
    } finally { setLoading(false) }
  }, [canManage])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!showForm && !managed) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const close = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || saving) return
      if (showForm) setShowForm(false)
      else setManaged(null)
      setModalError('')
    }
    window.addEventListener('keydown', close)
    return () => { document.body.style.overflow = previous; window.removeEventListener('keydown', close) }
  }, [showForm, managed, saving])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return items
    return items.filter((item) => `${item.contact_person_name ?? ''} ${addressLine(item.property_address)} ${sourceLabels[item.source] ?? item.source}`.toLowerCase().includes(term))
  }, [items, query])

  const counts = useMemo(() => ({
    open: items.filter((item) => item.status !== 'lost' && item.status !== 'available').length,
    approved: items.filter((item) => item.status === 'approved' || item.status === 'available').length,
    lost: items.filter((item) => item.status === 'lost').length,
  }), [items])

  function openCreate() {
    setForm(emptyCapture()); setModalError(''); setSuccess(''); setShowForm(true)
  }
  function openManage(item: Capture) {
    setManaged(item); setLostReason(''); setReopenReason(''); setModalError(''); setSuccess('')
  }
  function closeManage() {
    if (!saving) { setManaged(null); setModalError(''); setLostReason(''); setReopenReason('') }
  }
  function updateAddress(key: keyof Address, value: string) {
    setForm((current) => ({ ...current, property_address: { ...current.property_address, [key]: value } }))
  }
  function replaceCapture(updated: Capture) {
    setItems((current) => current.map((item) => item.id === updated.id ? updated : item))
    setManaged(updated)
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (!canManage) return
    setSaving(true); setModalError('')
    try {
      const created = await apiRequest<Capture>('/captures', { method: 'POST', body: JSON.stringify(form) })
      setItems((current) => [created, ...current]); setShowForm(false); setForm(emptyCapture()); setSuccess('Captação cadastrada com sucesso.')
    } catch (cause) {
      setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível cadastrar a captação.')
    } finally { setSaving(false) }
  }
  async function workflow(action: WorkflowAction, extra: Record<string, unknown> = {}) {
    if (!managed || !canManage) return
    setSaving(true); setModalError(''); setSuccess('')
    try {
      const updated = await apiRequest<Capture>(`/captures/${managed.id}/workflow`, { method: 'POST', body: JSON.stringify({ action, ...extra }) })
      replaceCapture(updated)
      if (action === 'advance') setSuccess(`Captação avançou para ${statusLabels[updated.status] ?? updated.status}.`)
      else if (action === 'back') setSuccess(`Captação retornou para ${statusLabels[updated.status] ?? updated.status}.`)
      else if (action === 'lose') { setLostReason(''); setSuccess('Captação encerrada como perdida, com motivo preservado.') }
      else if (action === 'reopen') { setReopenReason(''); setSuccess('Captação reaberta em Negociação.') }
      else setSuccess('Responsável da captação atualizado.')
    } catch (cause) {
      setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível atualizar a captação.')
    } finally { setSaving(false) }
  }
  async function convert() {
    if (!managed || !canManage) return
    setSaving(true); setModalError(''); setSuccess('')
    try {
      const result = await apiRequest<ConversionResult>(`/captures/${managed.id}/convert`, { method: 'POST' })
      replaceCapture(result.capture)
      setSuccess(`Captação convertida no imóvel ${result.property.code}. O cadastro definitivo já está disponível em Imóveis.`)
    } catch (cause) {
      setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível converter a captação em imóvel.')
    } finally { setSaving(false) }
  }

  const managedStageIndex = managed ? activeStages.indexOf(managed.status as (typeof activeStages)[number]) : -1
  const managedResponsible = managed?.responsible_user_id ? responsibles.find((item) => item.id === managed.responsible_user_id)?.name : null

  return <section className="workspace portfolio-workspace capture-workspace">
    <div className="page-heading portfolio-heading"><div><span className="eyebrow">Entrada de carteira</span><h1>Captações</h1><p>Da primeira conversa até a aprovação para administração, com origem, responsável e histórico rastreáveis.</p></div>{canManage && <button className="button primary" type="button" onClick={openCreate}><Plus size={15}/> Nova captação</button>}</div>
    {pageError && <div className="form-alert danger-alert">{pageError}</div>}{success && <div className="form-alert success-alert">{success}</div>}

    <div className="metric-grid capture-metrics"><article className="metric-card"><span>Em andamento</span><strong>{counts.open}</strong><small>Captações ativas</small></article><article className="metric-card"><span>Aprovadas</span><strong>{counts.approved}</strong><small>Prontas ou já convertidas</small></article><article className="metric-card"><span>Perdidas</span><strong>{counts.lost}</strong><small>Motivo preservado</small></article><article className="metric-card"><span>Total</span><strong>{items.length}</strong><small>Histórico da operação</small></article></div>

    <article className="panel portfolio-toolbar"><label className="portfolio-search capture-search"><Search size={15}/><input placeholder="Buscar por contato, endereço ou origem..." value={query} onChange={(event) => setQuery(event.target.value)}/></label></article>
    {loading ? <article className="panel settings-loading">Carregando captações...</article> : <div className="portfolio-card-list">{filtered.map((item) => <article className="panel capture-row" key={item.id}><div className="capture-status-rail"><i className={`capture-dot ${item.status}`}/></div><div className="capture-main"><div><strong>{item.contact_person_name || 'Contato ainda não vinculado'}</strong><span className="status-badge neutral">{sourceLabels[item.source] ?? item.source}</span></div><span><MapPin size={13}/>{addressLine(item.property_address)}</span><small>{item.notes || 'Sem observações adicionais.'}</small></div><div className="capture-value"><span>Aluguel estimado</span><strong>{money(item.estimated_rent)}</strong></div><div className="capture-stage"><span>Etapa</span><strong>{statusLabels[item.status] ?? item.status}</strong><small>{new Date(item.created_at).toLocaleDateString('pt-BR')}</small>{canManage && <button className="button secondary capture-manage-button" type="button" onClick={() => openManage(item)}>Gerenciar</button>}</div></article>)}{filtered.length === 0 && <article className="panel portfolio-empty"><Handshake size={27}/><strong>Nenhuma captação encontrada.</strong><span>As novas oportunidades aparecerão aqui antes de virarem imóveis administrados.</span></article>}</div>}

    <article className="panel governance-note-card capture-governance"><UserRound size={21}/><div><span className="eyebrow">Regra preservada</span><h2>Captação não é imóvel ainda</h2><p>A oportunidade mantém seu próprio histórico. Somente depois da aprovação e conversão ela gera o cadastro definitivo do imóvel.</p></div></article>

    {showForm && <div className="portfolio-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !saving) setShowForm(false) }}>
      <form className="panel portfolio-modal capture-form-modal" onSubmit={save} role="dialog" aria-modal="true" aria-label="Nova captação">
        <div className="portfolio-modal-header"><div><span className="eyebrow">Nova oportunidade</span><h2>Cadastrar captação</h2><p>Inclua os dados iniciais sem sair da carteira de captações.</p></div><button className="portfolio-modal-close" type="button" aria-label="Fechar" disabled={saving} onClick={() => setShowForm(false)}><X size={17}/></button></div>
        <div className="capture-modal-body">
          {modalError && <div className="form-alert danger-alert" role="alert">{modalError}</div>}
          <section className="canonical-modal-section"><div className="canonical-modal-section-title"><Handshake size={16}/><div><strong>Oportunidade</strong><span>Origem, contato e perfil inicial do imóvel.</span></div></div><div className="form-grid three-columns"><label className="field"><span>Origem</span><select value={form.source} onChange={(e) => setForm((c) => ({ ...c, source: e.target.value as CaptureCreate['source'] }))}><option value="direct">Direta</option><option value="site">Site</option><option value="referral">Indicação</option><option value="broker">Corretor</option><option value="campaign">Campanha</option><option value="other">Outro</option></select></label><label className="field"><span>Contato / proprietário</span><select value={form.contact_person_id ?? ''} onChange={(e) => setForm((c) => ({ ...c, contact_person_id: e.target.value || null }))}><option value="">Não vinculado</option>{people.map((person) => <option value={person.id} key={person.id}>{person.name}</option>)}</select></label><label className="field"><span>Tipo de imóvel</span><select value={form.property_type ?? ''} onChange={(e) => setForm((c) => ({ ...c, property_type: e.target.value as CaptureCreate['property_type'] }))}><option value="apartment">Apartamento</option><option value="house">Casa</option><option value="commercial">Comercial</option><option value="land">Terreno</option><option value="studio">Studio</option><option value="other">Outro</option></select></label></div></section>
          <section className="canonical-modal-section"><div className="canonical-modal-section-title"><MapPin size={16}/><div><strong>Localização</strong><span>Endereço preliminar da oportunidade.</span></div></div><div className="form-grid three-columns"><label className="field"><span>CEP</span><input data-format="cep" value={form.property_address.postal_code} onChange={(e) => updateAddress('postal_code', e.target.value)} placeholder="00000-000"/></label><label className="field field-span-2"><span>Rua</span><input value={form.property_address.street} onChange={(e) => updateAddress('street', e.target.value)}/></label><label className="field"><span>Número</span><input value={form.property_address.number} onChange={(e) => updateAddress('number', e.target.value)}/></label><label className="field"><span>Bairro</span><input value={form.property_address.neighborhood} onChange={(e) => updateAddress('neighborhood', e.target.value)}/></label><label className="field"><span>Cidade</span><input value={form.property_address.city} onChange={(e) => updateAddress('city', e.target.value)}/></label><label className="field"><span>Aluguel estimado</span><input min="0" step="0.01" type="number" value={form.estimated_rent ?? ''} onChange={(e) => setForm((c) => ({ ...c, estimated_rent: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field field-span-3"><span>Observações iniciais</span><textarea rows={3} value={form.notes ?? ''} onChange={(e) => setForm((c) => ({ ...c, notes: e.target.value }))}/></label></div></section>
        </div>
        <div className="form-actions canonical-modal-actions"><button className="button secondary" type="button" disabled={saving} onClick={() => setShowForm(false)}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : 'Cadastrar captação'}</button></div>
      </form>
    </div>}

    {managed && <div className="portfolio-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) closeManage() }}>
      <div className="panel portfolio-modal capture-form-modal capture-workflow-modal" role="dialog" aria-modal="true" aria-label="Gerenciar captação">
        <div className="portfolio-modal-header"><div><span className="eyebrow">Jornada da captação</span><h2>{managed.contact_person_name || 'Oportunidade sem contato vinculado'}</h2><p>{addressLine(managed.property_address)} · {money(managed.estimated_rent)}</p></div><button className="portfolio-modal-close" type="button" aria-label="Fechar" disabled={saving} onClick={closeManage}><X size={17}/></button></div>
        <div className="capture-modal-body">
          {modalError && <div className="form-alert danger-alert" role="alert">{modalError}</div>}
          <section className="canonical-modal-section">
            <div className="canonical-modal-section-title"><UserCheck size={16}/><div><strong>Controle da oportunidade</strong><span>A etapa e o responsável ficam rastreáveis até a conversão definitiva.</span></div></div>
            <div className="capture-workflow-summary">
              <div className="capture-workflow-card"><span>Etapa atual</span><strong>{statusLabels[managed.status] ?? managed.status}</strong><small>{managed.status === 'lost' && managed.lost_reason ? managed.lost_reason : managed.status === 'available' ? 'Fluxo comercial concluído.' : 'Siga a próxima ação quando o marco real estiver concluído.'}</small></div>
              <label className="field"><span>Responsável</span><select disabled={saving} value={managed.responsible_user_id ?? ''} onChange={(event) => void workflow('assign', { responsible_user_id: event.target.value || null, reason: 'Distribuição operacional da captação' })}><option value="">Fila compartilhada</option>{responsibles.map((user) => <option value={user.id} key={user.id}>{user.name}</option>)}</select><small>{managedResponsible ? `Responsável atual: ${managedResponsible}` : 'Ainda sem responsável individual.'}</small></label>
            </div>
          </section>

          {managedStageIndex >= 0 && <section className="canonical-modal-section">
            <div className="canonical-modal-section-title"><Handshake size={16}/><div><strong>Próximo marco</strong><span>Avance somente quando a etapa comercial correspondente realmente estiver concluída.</span></div></div>
            <div className="capture-workflow-actions">
              {managedStageIndex > 0 && <button className="button secondary" type="button" disabled={saving} onClick={() => void workflow('back')}><ChevronLeft size={14}/> Voltar para {statusLabels[activeStages[managedStageIndex - 1]]}</button>}
              {managedStageIndex < activeStages.length - 1 && <button className="button primary" type="button" disabled={saving} onClick={() => void workflow('advance')}>Avançar para {statusLabels[activeStages[managedStageIndex + 1]]} <ChevronRight size={14}/></button>}
              {managed.status === 'approved' && <button className="button primary" type="button" disabled={saving} onClick={() => void convert()}><Building2 size={14}/> Converter em imóvel</button>}
            </div>
            {managed.status === 'approved' && !managed.contact_person_id && <div className="form-alert danger-alert">Vincule o proprietário à captação antes da conversão.</div>}
          </section>}

          {managedStageIndex >= 0 && <section className="canonical-modal-section capture-workflow-loss">
            <div className="canonical-modal-section-title"><X size={16}/><div><strong>Encerrar oportunidade</strong><span>Uma captação perdida exige motivo e permanece no histórico.</span></div></div>
            <label className="field"><span>Motivo da perda</span><textarea rows={3} value={lostReason} onChange={(event) => setLostReason(event.target.value)} placeholder="Ex.: proprietário decidiu não seguir com a administração..."/></label>
            <div className="capture-workflow-actions"><button className="button secondary" type="button" disabled={saving || !lostReason.trim()} onClick={() => void workflow('lose', { lost_reason: lostReason })}>Marcar como perdida</button></div>
          </section>}

          {managed.status === 'lost' && <section className="canonical-modal-section capture-workflow-loss">
            <div className="canonical-modal-section-title"><RotateCcw size={16}/><div><strong>Retomar negociação</strong><span>A reabertura exige justificativa e retorna a oportunidade para Negociação.</span></div></div>
            <label className="field"><span>Motivo da reabertura</span><textarea rows={3} value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} placeholder="Ex.: proprietário retomou o contato e deseja prosseguir..."/></label>
            <div className="capture-workflow-actions"><button className="button primary" type="button" disabled={saving || !reopenReason.trim()} onClick={() => void workflow('reopen', { reason: reopenReason })}><RotateCcw size={14}/> Reabrir em Negociação</button></div>
          </section>}

          {managed.status === 'available' && <div className="capture-converted-note"><strong>Captação convertida</strong>O cadastro definitivo do imóvel já foi criado sem publicação automática. A partir daqui, dados técnicos, contrato de administração e publicação são tratados no módulo Imóveis.</div>}
        </div>
        <div className="form-actions canonical-modal-actions"><button className="button secondary" type="button" disabled={saving} onClick={closeManage}>Fechar</button></div>
      </div>
    </div>}
  </section>
}
