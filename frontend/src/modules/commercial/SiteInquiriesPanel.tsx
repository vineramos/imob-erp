import {
  CalendarCheck2,
  CalendarPlus2,
  Check,
  FileCheck2,
  FilePlus2,
  Mail,
  MessageCircle,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  UserRoundCheck,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'

type InquiryStatus = 'new' | 'contacted' | 'visit_scheduled' | 'qualified' | 'proposal' | 'converted' | 'won' | 'lost'
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
type CommercialVisit = {
  id: string
  code: string
  inquiry_id: string
  property_id: string | null
  person_id: string | null
  agenda_task_id: string | null
  responsible_user_id: string | null
  responsible_name: string | null
  starts_at: string
  ends_at: string
  status: 'scheduled' | 'completed' | 'cancelled' | 'no_show'
  notes: string | null
  created_at: string
  updated_at: string
}
type CommercialProposal = {
  id: string
  code: string
  inquiry_id: string
  property_id: string | null
  person_id: string | null
  responsible_user_id: string | null
  status: 'submitted' | 'accepted' | 'rejected' | 'withdrawn' | 'converted' | 'won'
  rent_amount: number
  start_date: string
  term_months: number
  guarantee_type: 'insurance' | 'deposit' | 'capitalization' | 'guarantor' | 'none'
  notes: string | null
  closed_reason: string | null
  accepted_at: string | null
  lease_contract_id: string | null
  lease_code: string | null
  created_at: string
  updated_at: string
}
type LeaseCharge = {
  key:string
  kind:'iptu'|'condo'|'guarantee_insurance'|'fire_insurance'|'other'
  label:string
  amount:number
  active:boolean
  payer:'tenant'|'owner'|'agency'
  beneficiary:'owner'|'agency'|'third_party'
  beneficiary_name:string|null
  frequency:'monthly'|'annual'|'one_time'
  include_in_invoice:boolean
  agency_retention_type:'none'|'percent'|'fixed'
  agency_retention_value:number
  start_date:string|null
  end_date:string|null
}
type LeaseComposition = { proposal_id:string; rent_amount:number; start_date:string; end_date:string; monthly_charges:LeaseCharge[]; tenant_monthly_total:number }
type CommercialFunnel = {
  inquiry: SiteInquiry
  person: { id: string; name: string; document_number: string | null; email: string | null; phone: string | null } | null
  property_status: string | null
  property_publication_enabled: boolean
  suggested_rent_amount: number | null
  visits: CommercialVisit[]
  proposals: CommercialProposal[]
}
type ProposalConversion = {
  proposal: CommercialProposal
  lease_contract_id: string
  lease_code: string
  lease_status: string
  message: string
}

type Props = { permissions: string[] }

const statusLabels: Record<InquiryStatus, string> = {
  new: 'Novo', contacted: 'Contatado', visit_scheduled: 'Visita agendada', qualified: 'Qualificado', proposal: 'Proposta', converted: 'Contrato gerado', won: 'Locado', lost: 'Perdido',
}
const manualStatusOptions: InquiryStatus[] = ['new', 'contacted', 'qualified', 'lost']
const visitStatusLabels: Record<CommercialVisit['status'], string> = { scheduled: 'Agendada', completed: 'Realizada', cancelled: 'Cancelada', no_show: 'Não compareceu' }
const proposalStatusLabels: Record<CommercialProposal['status'], string> = { submitted: 'Enviada', accepted: 'Aceita', rejected: 'Recusada', withdrawn: 'Retirada', converted: 'Contrato gerado', won: 'Locado' }
const guaranteeLabels: Record<CommercialProposal['guarantee_type'], string> = { insurance: 'Seguro fiança', deposit: 'Caução', capitalization: 'Título de capitalização', guarantor: 'Fiador', none: 'Sem garantia' }
const frequencyLabels:Record<LeaseCharge['frequency'],string>={monthly:'Mensal',annual:'Anual',one_time:'Parcela única'}
const payerLabels:Record<LeaseCharge['payer'],string>={tenant:'Locatário',owner:'Proprietário',agency:'Imobiliária'}
const beneficiaryLabels:Record<LeaseCharge['beneficiary'],string>={owner:'Proprietário',agency:'Imobiliária',third_party:'Terceiro'}
const retentionLabels:Record<LeaseCharge['agency_retention_type'],string>={none:'Sem retenção',percent:'Percentual (%)',fixed:'Valor fixo (R$)'}

function dateTime(value: string) { return new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) }
function money(value: number | null) { return value == null ? '—' : Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) }
function whatsappLink(phone: string) { let digits = phone.replace(/\D/g, ''); if (!digits.startsWith('55') && (digits.length === 10 || digits.length === 11)) digits = `55${digits}`; return `https://wa.me/${digits}` }
function tomorrowLocal() { const value = new Date(); value.setDate(value.getDate() + 1); value.setMinutes(0, 0, 0); if (value.getHours() < 9) value.setHours(9); return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}T${String(value.getHours()).padStart(2, '0')}:00` }
function startDateDefault() { const value = new Date(); value.setDate(value.getDate() + 15); return value.toISOString().slice(0, 10) }
function isInsurance(charge:LeaseCharge){ return charge.kind==='guarantee_insurance'||charge.kind==='fire_insurance' }
function retentionAmount(charge:LeaseCharge){
  if(!isInsurance(charge)||charge.beneficiary!=='third_party')return 0
  const amount=Math.max(0,Number(charge.amount||0));const value=Math.max(0,Number(charge.agency_retention_value||0))
  const calculated=charge.agency_retention_type==='percent'?amount*value/100:charge.agency_retention_type==='fixed'?value:0
  return Math.min(amount,Math.round(calculated*100)/100)
}

export function SiteInquiriesPanel({ permissions }: Props) {
  const canManage = permissions.includes('crm.manage')
  const canCreateContract = permissions.includes('contracts.create')
  const [items, setItems] = useState<SiteInquiry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | InquiryStatus>('all')
  const [updatingId, setUpdatingId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [funnel, setFunnel] = useState<CommercialFunnel | null>(null)
  const [modalLoading, setModalLoading] = useState(false)
  const [modalError, setModalError] = useState('')
  const [modalSuccess, setModalSuccess] = useState('')
  const [visitOpen, setVisitOpen] = useState(false)
  const [visitStartsAt, setVisitStartsAt] = useState(tomorrowLocal)
  const [visitDuration, setVisitDuration] = useState(60)
  const [visitNotes, setVisitNotes] = useState('')
  const [proposalOpen, setProposalOpen] = useState(false)
  const [proposalRent, setProposalRent] = useState<number | null>(null)
  const [proposalStart, setProposalStart] = useState(startDateDefault)
  const [proposalTerm, setProposalTerm] = useState(30)
  const [proposalGuarantee, setProposalGuarantee] = useState<CommercialProposal['guarantee_type']>('insurance')
  const [proposalNotes, setProposalNotes] = useState('')
  const [compositionProposal, setCompositionProposal] = useState<CommercialProposal|null>(null)
  const [composition, setComposition] = useState<LeaseComposition|null>(null)
  const [compositionLoading,setCompositionLoading]=useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setItems(await apiRequest<SiteInquiry[]>('/crm/site-inquiries')) }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os interesses recebidos pelo site.') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!selectedId) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) { if(compositionProposal){setCompositionProposal(null);setComposition(null)} else setSelectedId(null) } }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [selectedId, busy, compositionProposal])

  const metrics = useMemo(() => ({ new: items.filter((item) => item.status === 'new').length, visits: items.filter((item) => item.status === 'visit_scheduled').length, active: items.filter((item) => ['contacted', 'qualified', 'proposal', 'converted'].includes(item.status)).length }), [items])
  const filtered = useMemo(() => { const term = query.trim().toLowerCase(); return items.filter((item) => { if (filter !== 'all' && item.status !== filter) return false; if (!term) return true; return `${item.property_code} ${item.property_title} ${item.name} ${item.email ?? ''} ${item.phone ?? ''} ${item.message ?? ''}`.toLowerCase().includes(term) }) }, [filter, items, query])

  async function loadFunnel(inquiryId: string, resetMessage = true) {
    if (resetMessage) { setModalError(''); setModalSuccess('') }
    setModalLoading(true)
    try { const next = await apiRequest<CommercialFunnel>(`/crm/site-inquiries/${inquiryId}/funnel`); setFunnel(next); setItems((current) => current.map((row) => row.id === inquiryId ? { ...row, status: next.inquiry.status } : row)); if (resetMessage) setProposalRent(next.suggested_rent_amount == null ? null : Number(next.suggested_rent_amount)) }
    catch (cause) { setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível abrir o atendimento comercial.') }
    finally { setModalLoading(false) }
  }
  async function openFunnel(inquiryId: string) { setSelectedId(inquiryId); setFunnel(null); setVisitOpen(false); setProposalOpen(false); setProposalRent(null); setCompositionProposal(null); setComposition(null); await loadFunnel(inquiryId) }
  async function changeStatus(item: SiteInquiry, nextStatus: InquiryStatus) { if (!canManage || nextStatus === item.status || !manualStatusOptions.includes(nextStatus)) return; setUpdatingId(item.id); setError(''); try { const updated = await apiRequest<SiteInquiry>(`/crm/site-inquiries/${item.id}`, { method: 'PATCH', body: JSON.stringify({ status: nextStatus }) }); setItems((current) => current.map((row) => row.id === item.id ? updated : row)) } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível atualizar o atendimento.') } finally { setUpdatingId(null) } }

  async function scheduleVisit(event: FormEvent) {
    event.preventDefault(); if (!selectedId || !visitStartsAt) return; setBusy(true); setModalError(''); setModalSuccess('')
    try { const starts = new Date(visitStartsAt); if (Number.isNaN(starts.getTime())) throw new Error('Data inválida'); await apiRequest<CommercialVisit>(`/crm/site-inquiries/${selectedId}/visits`, { method: 'POST', body: JSON.stringify({ starts_at: starts.toISOString(), duration_minutes: visitDuration, notes: visitNotes || null }) }); setVisitOpen(false); setVisitNotes(''); setVisitStartsAt(tomorrowLocal()); setModalSuccess('Visita agendada e incluída automaticamente na Agenda.'); await loadFunnel(selectedId, false) }
    catch (cause) { setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível agendar a visita.') }
    finally { setBusy(false) }
  }
  async function closeVisit(visit: CommercialVisit, nextStatus: 'completed' | 'cancelled' | 'no_show') { if (!selectedId) return; const note = nextStatus === 'completed' ? null : window.prompt(nextStatus === 'no_show' ? 'Observação sobre o não comparecimento:' : 'Motivo do cancelamento:'); if (nextStatus !== 'completed' && note === null) return; setBusy(true); setModalError(''); setModalSuccess(''); try { await apiRequest<CommercialVisit>(`/crm/visits/${visit.id}`, { method: 'PATCH', body: JSON.stringify({ status: nextStatus, notes: note }) }); setModalSuccess(nextStatus === 'completed' ? 'Visita marcada como realizada.' : 'Visita encerrada e Agenda sincronizada.'); await loadFunnel(selectedId, false) } catch (cause) { setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível atualizar a visita.') } finally { setBusy(false) } }

  async function createProposal(event: FormEvent) {
    event.preventDefault(); if (!selectedId || proposalRent == null || !proposalStart) return; setBusy(true); setModalError(''); setModalSuccess('')
    try { await apiRequest<CommercialProposal>(`/crm/site-inquiries/${selectedId}/proposals`, { method: 'POST', body: JSON.stringify({ rent_amount: proposalRent, start_date: proposalStart, term_months: proposalTerm, guarantee_type: proposalGuarantee, notes: proposalNotes || null }) }); setProposalOpen(false); setProposalNotes(''); setModalSuccess('Proposta criada com os dados do interessado e do imóvel, sem novo cadastro.'); await loadFunnel(selectedId, false) }
    catch (cause) { setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível criar a proposta.') }
    finally { setBusy(false) }
  }
  async function proposalAction(proposal: CommercialProposal, nextStatus: 'accepted' | 'rejected' | 'withdrawn') { if (!selectedId) return; let reason: string | null = null; if (nextStatus !== 'accepted') { reason = window.prompt(nextStatus === 'rejected' ? 'Motivo da recusa:' : 'Motivo da retirada:'); if (!reason?.trim()) return } setBusy(true); setModalError(''); setModalSuccess(''); try { await apiRequest<CommercialProposal>(`/crm/proposals/${proposal.id}`, { method: 'PATCH', body: JSON.stringify({ status: nextStatus, reason }) }); setModalSuccess(nextStatus === 'accepted' ? 'Proposta aceita. O imóvel continua publicado até o contrato ser assinado.' : 'Proposta encerrada.'); await loadFunnel(selectedId, false) } catch (cause) { setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível atualizar a proposta.') } finally { setBusy(false) } }

  async function openComposition(proposal:CommercialProposal){
    setCompositionProposal(proposal);setComposition(null);setCompositionLoading(true);setModalError('')
    try{const data=await apiRequest<LeaseComposition>(`/crm/proposals/${proposal.id}/lease-composition`);setComposition({...data,rent_amount:Number(data.rent_amount),tenant_monthly_total:Number(data.tenant_monthly_total),monthly_charges:data.monthly_charges.map(item=>({...item,amount:Number(item.amount),agency_retention_value:Number(item.agency_retention_value||0)}))})}
    catch(cause){setCompositionProposal(null);setModalError(cause instanceof ApiError?cause.detail:'Não foi possível preparar a composição financeira.')}
    finally{setCompositionLoading(false)}
  }
  function patchCharge(index:number,patch:Partial<LeaseCharge>){setComposition(current=>{if(!current)return current;return {...current,monthly_charges:current.monthly_charges.map((item,i)=>{if(i!==index)return item;const next={...item,...patch};if(!isInsurance(next)||next.beneficiary!=='third_party')return {...next,agency_retention_type:'none' as const,agency_retention_value:0};return next})}})}
  function addCharge(){if(!composition)return;const key=`other_${Date.now()}`;setComposition({...composition,monthly_charges:[...composition.monthly_charges,{key,kind:'other',label:'Outra cobrança',amount:0,active:true,payer:'tenant',beneficiary:'third_party',beneficiary_name:null,frequency:'monthly',include_in_invoice:true,agency_retention_type:'none',agency_retention_value:0,start_date:composition.start_date,end_date:composition.end_date}]})}
  function removeCharge(index:number){setComposition(current=>current?{...current,monthly_charges:current.monthly_charges.filter((_,i)=>i!==index)}:current)}
  const monthlyBase=composition?Number(composition.rent_amount)+composition.monthly_charges.filter(item=>item.active&&item.payer==='tenant'&&item.include_in_invoice&&item.frequency==='monthly').reduce((sum,item)=>sum+Number(item.amount||0),0):0
  async function convertToLease() {
    if (!selectedId || !compositionProposal || !composition) return
    setBusy(true); setModalError(''); setModalSuccess('')
    try { const result = await apiRequest<ProposalConversion>(`/crm/proposals/${compositionProposal.id}/convert-to-lease`, { method: 'POST', body: JSON.stringify({monthly_charges:composition.monthly_charges}) }); setCompositionProposal(null);setComposition(null);setModalSuccess(`${result.lease_code} criado em rascunho com a composição financeira definida. O imóvel só sai do estoque após a assinatura final.`); await loadFunnel(selectedId, false) }
    catch (cause) { setModalError(cause instanceof ApiError ? cause.detail : 'Não foi possível gerar o contrato.') }
    finally { setBusy(false) }
  }

  const selected = items.find((item) => item.id === selectedId) ?? null

  return <section className="workspace commercial-workspace site-inquiries-workspace">
    <div className="page-heading portfolio-heading"><div><span className="eyebrow">Comercial · Site público</span><h1>Interesses recebidos</h1><p>Do primeiro contato ao contrato, sem redigitar o interessado ou o imóvel.</p></div><button className="button secondary" type="button" onClick={() => void load()}><RefreshCw size={14}/> Atualizar</button></div>
    <div className="dashboard-metrics commercial-metrics"><article className="panel metric-card"><span>Novos</span><strong>{metrics.new}</strong><small>aguardando primeiro contato</small></article><article className="panel metric-card"><span>Em atendimento</span><strong>{metrics.active}</strong><small>contato, proposta ou contrato</small></article><article className="panel metric-card"><span>Visitas</span><strong>{metrics.visits}</strong><small>agendadas pelo comercial</small></article></div>
    {error && <div className="form-alert danger-alert" role="alert">{error}</div>}
    <div className="portfolio-toolbar panel commercial-toolbar commercial-toolbar-wide site-inquiries-toolbar"><div className="portfolio-tabs"><button className={filter === 'all' ? 'active' : ''} type="button" onClick={() => setFilter('all')}>Todos <span>{items.length}</span></button><button className={filter === 'new' ? 'active' : ''} type="button" onClick={() => setFilter('new')}>Novos <span>{metrics.new}</span></button><button className={filter === 'visit_scheduled' ? 'active' : ''} type="button" onClick={() => setFilter('visit_scheduled')}>Visitas <span>{metrics.visits}</span></button></div><label className="portfolio-search"><Search size={14}/><input placeholder="Imóvel, nome, telefone ou e-mail..." value={query} onChange={(event) => setQuery(event.target.value)}/></label></div>
    {loading ? <article className="panel settings-loading">Carregando interesses...</article> : <div className="site-inquiries-list">{filtered.map((item) => <article className={`panel site-inquiry-card status-${item.status}`} key={item.id}>
      <div className="site-inquiry-property"><span className="eyebrow">IMÓVEL #{item.property_code}</span><strong>{item.property_title}</strong><small>Recebido em {dateTime(item.created_at)}</small></div>
      <div className="site-inquiry-contact"><strong>{item.name}</strong><div>{item.phone && <><a href={whatsappLink(item.phone)} target="_blank" rel="noreferrer"><MessageCircle size={13}/> WhatsApp</a><a href={`tel:${item.phone}`}><Phone size={13}/> Ligar</a></>}{item.email && <a href={`mailto:${item.email}?subject=Interesse no imóvel ${item.property_code}`}><Mail size={13}/> E-mail</a>}</div><small>Preferência: {item.preferred_contact === 'email' ? 'e-mail' : item.preferred_contact === 'phone' ? 'ligação' : 'WhatsApp'}</small></div>
      <div className="site-inquiry-message"><span>Mensagem</span><p>{item.message || 'Sem mensagem adicional.'}</p></div>
      <div className="site-inquiry-status"><span className={`status-badge ${item.status === 'won' ? 'success' : item.status === 'lost' ? 'danger' : 'neutral'}`}>{statusLabels[item.status] ?? item.status}</span>{canManage && <label><span>Ajuste manual</span><select value={manualStatusOptions.includes(item.status) ? item.status : ''} disabled={updatingId === item.id} onChange={(event) => event.target.value && void changeStatus(item, event.target.value as InquiryStatus)}><option value="">Etapa automática</option>{manualStatusOptions.map((key) => <option key={key} value={key}>{statusLabels[key]}</option>)}</select></label>}<button className="button secondary compact-button" type="button" onClick={() => void openFunnel(item.id)}>Abrir atendimento</button>{item.status === 'visit_scheduled' ? <CalendarCheck2 size={18}/> : item.status === 'qualified' ? <UserRoundCheck size={18}/> : null}</div>
    </article>)}{filtered.length === 0 && <article className="panel portfolio-empty"><Search size={26}/><strong>Nenhum interesse neste filtro.</strong><span>Novos contatos enviados pelo site aparecerão aqui.</span></article>}</div>}

    {selectedId && <div className="portfolio-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !busy && !compositionProposal) setSelectedId(null) }}>
      <div className="panel portfolio-modal commercial-funnel-modal" role="dialog" aria-modal="true">
        <div className="portfolio-modal-header"><div><span className="eyebrow">Atendimento comercial · {selected ? `#${selected.property_code}` : ''}</span><h2>{selected?.name || 'Atendimento'}</h2><p>{selected?.property_title}</p></div><button className="portfolio-modal-close" type="button" aria-label="Fechar" disabled={busy} onClick={() => setSelectedId(null)}><X size={17}/></button></div>
        <div className="commercial-funnel-body">
          {modalError && <div className="form-alert danger-alert" role="alert">{modalError}</div>}{modalSuccess && <div className="form-alert success-alert">{modalSuccess}</div>}
          {modalLoading && !funnel ? <div className="settings-loading">Carregando atendimento...</div> : funnel && <>
            <section className="funnel-summary-grid"><article className="funnel-summary-card"><span>Interessado</span><strong>{funnel.person?.name || funnel.inquiry.name}</strong><small>{funnel.person ? 'Cadastro vinculado automaticamente' : 'Será cadastrado no próximo passo'}</small></article><article className="funnel-summary-card"><span>Imóvel</span><strong>#{funnel.inquiry.property_code}</strong><small>{funnel.property_status || 'indisponível'} · {funnel.property_publication_enabled ? 'publicado' : 'fora do site'}</small></article><article className="funnel-summary-card"><span>Aluguel de referência</span><strong>{money(funnel.suggested_rent_amount)}</strong><small>valor atual do estoque</small></article></section>

            {canManage && funnel.inquiry.status !== 'won' && funnel.inquiry.status !== 'lost' && <div className="funnel-actions"><button className="button secondary" type="button" onClick={() => { setVisitOpen((value) => !value); setProposalOpen(false) }}><CalendarPlus2 size={15}/> Agendar visita</button><button className="button secondary" type="button" onClick={() => { setProposalOpen((value) => !value); setVisitOpen(false); if (proposalRent == null && funnel.suggested_rent_amount != null) setProposalRent(Number(funnel.suggested_rent_amount)) }}><FilePlus2 size={15}/> Criar proposta</button></div>}

            {visitOpen && <form className="funnel-inline-form" onSubmit={(event) => void scheduleVisit(event)}><div className="funnel-inline-heading"><div><span className="eyebrow">Visita</span><strong>Agendar no calendário comercial</strong></div><button type="button" className="portfolio-modal-close" onClick={() => setVisitOpen(false)}><X size={15}/></button></div><div className="funnel-form-grid"><label className="field"><span>Data e hora</span><input required type="datetime-local" value={visitStartsAt} onChange={(event) => setVisitStartsAt(event.target.value)}/></label><label className="field"><span>Duração</span><select value={visitDuration} onChange={(event) => setVisitDuration(Number(event.target.value))}><option value={30}>30 min</option><option value={45}>45 min</option><option value={60}>1 hora</option><option value={90}>1h30</option><option value={120}>2 horas</option></select></label></div><label className="field"><span>Observações</span><textarea rows={2} maxLength={2000} value={visitNotes} onChange={(event) => setVisitNotes(event.target.value)} placeholder="Orientações para a visita..."/></label><div className="funnel-inline-actions"><button className="button primary" disabled={busy} type="submit"><CalendarCheck2 size={14}/> Confirmar visita</button></div></form>}

            {proposalOpen && <form className="funnel-inline-form" onSubmit={(event) => void createProposal(event)}><div className="funnel-inline-heading"><div><span className="eyebrow">Proposta</span><strong>Condições comerciais</strong></div><button type="button" className="portfolio-modal-close" onClick={() => setProposalOpen(false)}><X size={15}/></button></div><div className="funnel-form-grid proposal-grid"><label className="field"><span>Aluguel proposto</span><input required min="0.01" step="0.01" type="number" value={proposalRent ?? ''} onChange={(event) => setProposalRent(event.target.value ? Number(event.target.value) : null)}/></label><label className="field"><span>Início pretendido</span><input required type="date" value={proposalStart} onChange={(event) => setProposalStart(event.target.value)}/></label><label className="field"><span>Prazo</span><select value={proposalTerm} onChange={(event) => setProposalTerm(Number(event.target.value))}><option value={12}>12 meses</option><option value={24}>24 meses</option><option value={30}>30 meses</option><option value={36}>36 meses</option></select></label><label className="field"><span>Garantia</span><select value={proposalGuarantee} onChange={(event) => setProposalGuarantee(event.target.value as CommercialProposal['guarantee_type'])}>{Object.entries(guaranteeLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div><label className="field"><span>Observações</span><textarea rows={2} maxLength={3000} value={proposalNotes} onChange={(event) => setProposalNotes(event.target.value)} placeholder="Condições adicionais da proposta..."/></label><div className="funnel-inline-actions"><button className="button primary" disabled={busy} type="submit"><FileCheck2 size={14}/> Criar proposta</button></div></form>}

            <section className="canonical-modal-section funnel-section"><div className="funnel-section-heading"><div><span className="eyebrow">Visitas</span><h3>Histórico de visitas</h3></div><span>{funnel.visits.length}</span></div>{funnel.visits.length === 0 ? <p className="funnel-empty-copy">Nenhuma visita agendada.</p> : <div className="funnel-timeline">{funnel.visits.map((visit) => <article key={visit.id}><div><strong>{visit.code} · {dateTime(visit.starts_at)}</strong><span>{visit.responsible_name || 'Responsável comercial'} · {visitStatusLabels[visit.status]}</span>{visit.notes && <small>{visit.notes}</small>}</div>{canManage && visit.status === 'scheduled' && <div className="funnel-row-actions"><button type="button" className="mini-action success" disabled={busy} onClick={() => void closeVisit(visit, 'completed')}><Check size={13}/> Realizada</button><button type="button" className="mini-action" disabled={busy} onClick={() => void closeVisit(visit, 'no_show')}>Não compareceu</button><button type="button" className="mini-action danger" disabled={busy} onClick={() => void closeVisit(visit, 'cancelled')}>Cancelar</button></div>}</article>)}</div>}</section>

            <section className="canonical-modal-section funnel-section"><div className="funnel-section-heading"><div><span className="eyebrow">Propostas</span><h3>Negociação e conversão</h3></div><span>{funnel.proposals.length}</span></div>{funnel.proposals.length === 0 ? <p className="funnel-empty-copy">Nenhuma proposta criada.</p> : <div className="funnel-proposals">{funnel.proposals.map((proposal) => <article key={proposal.id}><div className="funnel-proposal-main"><div><strong>{proposal.code}</strong><span>{money(proposal.rent_amount)} · {proposal.term_months} meses · {guaranteeLabels[proposal.guarantee_type]}</span><small>Início {new Date(`${proposal.start_date}T12:00:00`).toLocaleDateString('pt-BR')}</small></div><span className={`status-badge ${proposal.status === 'accepted' || proposal.status === 'won' ? 'success' : proposal.status === 'rejected' || proposal.status === 'withdrawn' ? 'danger' : 'neutral'}`}>{proposalStatusLabels[proposal.status]}</span></div>{proposal.closed_reason && <p>{proposal.closed_reason}</p>}{proposal.lease_code && <div className="funnel-contract-link"><FileCheck2 size={14}/><strong>{proposal.lease_code}</strong><button type="button" onClick={() => window.location.assign('/app/contracts')}>Abrir contratos</button></div>}{canManage && proposal.status === 'submitted' && <div className="funnel-row-actions"><button type="button" className="mini-action success" disabled={busy} onClick={() => void proposalAction(proposal, 'accepted')}><Check size={13}/> Aceitar</button><button type="button" className="mini-action danger" disabled={busy} onClick={() => void proposalAction(proposal, 'rejected')}>Recusar</button><button type="button" className="mini-action" disabled={busy} onClick={() => void proposalAction(proposal, 'withdrawn')}>Retirada</button></div>}{canManage && canCreateContract && proposal.status === 'accepted' && <div className="funnel-row-actions"><button type="button" className="button primary compact-button" disabled={busy||compositionLoading} onClick={() => void openComposition(proposal)}><FilePlus2 size={14}/> Gerar contrato</button><small>Primeiro revise aluguel + condomínio + IPTU + seguros. O anúncio só sai do ar após a assinatura final.</small></div>}</article>)}</div>}</section>
          </>}
        </div>
      </div>

      {compositionProposal&&<div className="portfolio-modal-backdrop" style={{zIndex:110}} onMouseDown={event=>{if(event.currentTarget===event.target&&!busy){setCompositionProposal(null);setComposition(null)}}}><div className="panel portfolio-modal" style={{width:'min(1120px,95vw)',maxHeight:'90vh',overflow:'auto'}} role="dialog" aria-modal="true"><div className="portfolio-modal-header"><div><span className="eyebrow">Composição da locação · {compositionProposal.code}</span><h2>Aluguel e cobranças adicionais</h2><p>Defina o valor cobrado do locatário e, nos seguros, quanto fica com a imobiliária e quanto será repassado à seguradora.</p></div><button className="portfolio-modal-close" type="button" disabled={busy} onClick={()=>{setCompositionProposal(null);setComposition(null)}}><X size={17}/></button></div>{compositionLoading||!composition?<div className="settings-loading">Preparando composição...</div>:<div className="commercial-funnel-body"><section className="funnel-summary-grid"><article className="funnel-summary-card"><span>Aluguel</span><strong>{money(Number(composition.rent_amount))}</strong><small>Base contratual</small></article><article className="funnel-summary-card"><span>Base mensal prevista</span><strong>{money(monthlyBase)}</strong><small>Aluguel + encargos mensais cobrados</small></article><article className="funnel-summary-card"><span>Vigência</span><strong>{new Date(`${composition.start_date}T12:00`).toLocaleDateString('pt-BR')}</strong><small>até {new Date(`${composition.end_date}T12:00`).toLocaleDateString('pt-BR')}</small></article></section><div className="form-alert" style={{marginTop:12}}>Nos seguros, informe primeiro o <b>valor total cobrado do locatário</b>. Depois escolha a retenção da imobiliária em <b>%</b> ou <b>R$</b>. Ex.: cobra R$ 500,00, retém 30% (R$ 150,00) e repassa R$ 350,00 à seguradora.</div><div style={{display:'grid',gap:10,marginTop:14}}>{composition.monthly_charges.map((charge,index)=>{const retained=retentionAmount(charge);const thirdParty=Math.max(0,Number(charge.amount||0)-retained);return <article className="panel" key={charge.key} style={{padding:12}}><div style={{display:'grid',gridTemplateColumns:'auto minmax(150px,1.4fr) minmax(110px,.7fr) minmax(120px,.8fr) minmax(120px,.8fr) minmax(120px,.8fr) auto',gap:8,alignItems:'end'}}><label className="field"><span>Ativa</span><input type="checkbox" checked={charge.active} onChange={event=>patchCharge(index,{active:event.target.checked})}/></label><label className="field"><span>Cobrança</span><input value={charge.label} maxLength={120} onChange={event=>patchCharge(index,{label:event.target.value})}/></label><label className="field"><span>Valor cobrado</span><input type="number" min="0" step="0.01" value={charge.amount} onChange={event=>patchCharge(index,{amount:Number(event.target.value||0)})}/></label><label className="field"><span>Periodicidade</span><select value={charge.frequency} onChange={event=>patchCharge(index,{frequency:event.target.value as LeaseCharge['frequency']})}>{Object.entries(frequencyLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label className="field"><span>Responsável</span><select value={charge.payer} onChange={event=>patchCharge(index,{payer:event.target.value as LeaseCharge['payer']})}>{Object.entries(payerLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label className="field"><span>Destino</span><select value={charge.beneficiary} onChange={event=>patchCharge(index,{beneficiary:event.target.value as LeaseCharge['beneficiary']})}>{Object.entries(beneficiaryLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><button type="button" className="mini-action danger" title="Remover" onClick={()=>removeCharge(index)}><Trash2 size={14}/></button></div>{isInsurance(charge)&&charge.beneficiary==='third_party'&&<div style={{display:'grid',gridTemplateColumns:'minmax(180px,.8fr) minmax(120px,.6fr) 1.6fr',gap:8,alignItems:'end',marginTop:10,padding:'10px 12px',border:'1px solid var(--border-subtle)',borderRadius:12}}><label className="field"><span>Retenção da imobiliária</span><select value={charge.agency_retention_type} onChange={event=>patchCharge(index,{agency_retention_type:event.target.value as LeaseCharge['agency_retention_type'],agency_retention_value:event.target.value==='none'?0:charge.agency_retention_value})}>{Object.entries(retentionLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label className="field"><span>{charge.agency_retention_type==='percent'?'Percentual (%)':charge.agency_retention_type==='fixed'?'Valor retido (R$)':'Valor'}</span><input type="number" min="0" max={charge.agency_retention_type==='percent'?100:undefined} step="0.01" disabled={charge.agency_retention_type==='none'} value={charge.agency_retention_value} onChange={event=>patchCharge(index,{agency_retention_value:Number(event.target.value||0)})}/></label><div style={{display:'grid',gap:3,paddingBottom:3}}><span style={{fontSize:12,opacity:.72}}>Divisão interna do seguro</span><strong style={{fontSize:14}}>Imobiliária {money(retained)} · Seguradora {money(thirdParty)}</strong><small>O locatário continuará vendo e pagando {money(Number(charge.amount||0))}.</small></div></div>}<div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr auto',gap:8,alignItems:'end',marginTop:8}}><label className="field"><span>Beneficiário / recebedor</span><input value={charge.beneficiary_name||''} maxLength={180} placeholder={charge.beneficiary==='third_party'?'Ex.: Porto Seguro, Condomínio...':''} onChange={event=>patchCharge(index,{beneficiary_name:event.target.value||null})}/></label><label className="field"><span>Início</span><input type="date" value={charge.start_date||''} onChange={event=>patchCharge(index,{start_date:event.target.value||null})}/></label><label className="field"><span>Fim</span><input type="date" value={charge.end_date||''} onChange={event=>patchCharge(index,{end_date:event.target.value||null})}/></label><label className="field"><span>Junto no boleto</span><input type="checkbox" checked={charge.include_in_invoice} onChange={event=>patchCharge(index,{include_in_invoice:event.target.checked})}/></label></div></article>})}</div><div className="funnel-inline-actions" style={{justifyContent:'space-between',marginTop:14}}><button className="button secondary" type="button" onClick={addCharge}><Plus size={14}/> Adicionar cobrança</button><div style={{display:'flex',gap:8}}><button className="button secondary" type="button" disabled={busy} onClick={()=>{setCompositionProposal(null);setComposition(null)}}>Cancelar</button><button className="button primary" type="button" disabled={busy} onClick={()=>void convertToLease()}><FileCheck2 size={14}/> Criar contrato com esta composição</button></div></div></div>}</div></div>}
    </div>}
  </section>
}
