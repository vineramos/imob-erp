import {
  CheckCircle2,
  Download,
  FileCheck2,
  FileSignature,
  FileText,
  History,
  Search,
  Users,
  WalletCards,
  Plus,
  RotateCcw,
  Send,
  ShieldCheck,
  Trash2,
  UserRoundPlus,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type {
  AdministrationContract,
  AdministrationContractCreate,
  AdministrationContractStatus,
  AdministrationContractTerms,
  AdministrationContractWorkflowAction,
  ContractDocument,
  ContractSigner,
  OperationalDefaults,
  OrganizationProfile,
  Person,
  Property,
} from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { SignatureTimeline } from './SignatureTimeline'
import { EntityDocumentsPanel } from '../documents/EntityDocumentsPanel'

const statusLabel: Record<AdministrationContractStatus, string> = {
  draft: 'Rascunho', review: 'Em revisão', approved: 'Aprovado', pending_signature: 'Assinatura', signed: 'Assinado', cancelled: 'Cancelado',
}
const planLabel: Record<string, string> = { essential: 'Essencial', complete: 'Completo', custom: 'Personalizado' }
const payerLabel: Record<string, string> = { tenant: 'Locatário', owner: 'Proprietário', agency: 'Imobiliária' }
const signerRoleLabel: Record<string, string> = { owner: 'Proprietário', tenant: 'Locatário', agency: 'Imobiliária', witness: 'Testemunha', other: 'Outro' }
const signerRoleOptions: Array<{ value: 'owner' | 'tenant' | 'agency'; label: string }> = [
  { value: 'owner', label: 'Proprietário' },
  { value: 'tenant', label: 'Locatário' },
  { value: 'agency', label: 'Imobiliária' },
]

const defaultTerms = (defaults?: OperationalDefaults): AdministrationContractTerms => ({
  plan: 'essential', admin_fee_type: 'percent', admin_fee_percent: defaults?.default_admin_fee_percent ?? 10, admin_fee_amount: null,
  intermediation_percent: 100, intermediation_installments: 1, owner_repasse_business_days: defaults?.owner_repasse_business_days ?? 2,
  condo_operational_payer: 'tenant', iptu_operational_payer: 'tenant', publication_requires_owner_approval: false,
  maintenance_limit_amount: null, emergency_limit_amount: null, start_date: null, end_date: null,
  end_of_term_action: 'renew_indefinite', notes: '', signers: [],
})
const blankSigner = (): ContractSigner => ({ role: 'owner', person_id: null, name: '', email: '', document_number: null, phone: null, sign_order: 1, communication: 'email' })

function addressLine(address: Record<string, string>) {
  return [address.street, address.number, address.neighborhood, address.city].filter(Boolean).join(', ') || 'Endereço não informado'
}
function money(value: number | null) {
  if (value == null) return '—'
  return Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}
function adminFee(item: AdministrationContract) {
  return item.admin_fee_type === 'percent' ? `${Number(item.admin_fee_percent ?? 0).toLocaleString('pt-BR')}%` : money(item.admin_fee_amount)
}
function statusClass(status: AdministrationContractStatus) {
  if (status === 'signed' || status === 'approved') return 'success'
  if (status === 'cancelled') return 'danger'
  if (status === 'pending_signature' || status === 'review') return 'warning'
  return 'neutral'
}
function signingLabel(item: AdministrationContract) {
  const map: Record<string, string> = {
    not_prepared: 'Fluxo interno', ready_for_document: 'Gerar PDF', document_ready: 'PDF pronto para envio',
    provider_running: 'Assinatura em andamento', provider_signature_progress: 'Assinaturas em andamento',
    provider_closed_pending_archive: 'Concluído · arquivar PDF final', archive_failed: 'Arquivamento pendente',
    signed_archived: 'PDF final arquivado', provider_setup_failed: 'Falha ao preparar provider',
  }
  return map[item.signing_status] ?? item.signing_status.replaceAll('_', ' ')
}
function addMonthsIso(value: string | null, months: number) {
  if (!value) return null
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return null
  const totalMonths = year * 12 + (month - 1) + Math.max(1, Math.trunc(months || 1))
  const targetYear = Math.floor(totalMonths / 12)
  const targetMonthIndex = totalMonths % 12
  const lastDay = new Date(Date.UTC(targetYear, targetMonthIndex + 1, 0)).getUTCDate()
  const targetDay = Math.min(day, lastDay)
  return `${targetYear}-${String(targetMonthIndex + 1).padStart(2, '0')}-${String(targetDay).padStart(2, '0')}`
}
function monthsBetweenIso(start: string | null, end: string | null, fallback: number) {
  if (!start || !end) return fallback
  const [startYear, startMonth] = start.split('-').map(Number)
  const [endYear, endMonth] = end.split('-').map(Number)
  const diff = (endYear - startYear) * 12 + endMonth - startMonth
  return diff > 0 ? diff : fallback
}

type Props = { permissions: string[] }

export function ContractsPage({ permissions }: Props) {
  const granted = useMemo(() => new Set(permissions), [permissions])
  const canCreate = granted.has('contracts.create')
  const canEdit = granted.has('contracts.edit')
  const canApprove = granted.has('contracts.approve')
  const canSign = granted.has('contracts.send_signature')

  const [contracts, setContracts] = useState<AdministrationContract[]>([])
  const [properties, setProperties] = useState<Property[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [company, setCompany] = useState<OrganizationProfile | null>(null)
  const [defaults, setDefaults] = useState<OperationalDefaults | undefined>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [filter, setFilter] = useState<'all' | AdministrationContractStatus>('all')
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<AdministrationContract | null>(null)
  const [selectedId,setSelectedId]=useState<string|null>(null)
  const [detailTab,setDetailTab]=useState<'overview'|'parties'|'finance'|'signature'|'documents'|'history'>('overview')
  const [contractQuery,setContractQuery]=useState('')
  const [propertyId, setPropertyId] = useState('')
  const [terms, setTerms] = useState<AdministrationContractTerms>(() => defaultTerms())
  const [leaseMonths, setLeaseMonths] = useState(30)
  const [changeSummary, setChangeSummary] = useState('')
  const [cancelTarget, setCancelTarget] = useState<AdministrationContract | null>(null)
  const [cancelReason, setCancelReason] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [loadedContracts, loadedProperties, loadedDefaults, loadedPeople, loadedCompany] = await Promise.all([
        apiRequest<AdministrationContract[]>('/administration-contracts'),
        apiRequest<Property[]>('/properties'),
        apiRequest<OperationalDefaults>('/settings/operations'),
        apiRequest<Person[]>('/people'),
        apiRequest<OrganizationProfile>('/settings/company'),
      ])
      setContracts(loadedContracts); setProperties(loadedProperties); setDefaults(loadedDefaults); setPeople(loadedPeople); setCompany(loadedCompany)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os contratos de administração.')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const requestedPropertyId = new URLSearchParams(window.location.search).get('propertyId')
    if (!requestedPropertyId || !canCreate || !properties.some((item) => item.id === requestedPropertyId)) return
    const months = defaults?.residential_lease_months ?? 30
    setEditing(null)
    setPropertyId(requestedPropertyId)
    setLeaseMonths(months)
    setTerms(defaultTerms(defaults))
    setChangeSummary('')
    setShowForm(true)
    window.history.replaceState({}, '', '/app/contracts')
  }, [canCreate, defaults, properties])

  const eligibleProperties = useMemo(() => properties.filter((item) => item.owners.length > 0), [properties])
  const filtered=useMemo(()=>{
    const term=contractQuery.trim().toLocaleLowerCase('pt-BR')
    return contracts.filter(item=>{
      if(filter!=='all'&&item.status!==filter)return false
      return !term||[item.code,item.property_code,addressLine(item.property_address),item.plan,...item.owners.map(owner=>owner.name)]
        .join(' ').toLocaleLowerCase('pt-BR').includes(term)
    })
  },[contracts,filter,contractQuery])
  useEffect(()=>{
    if(!filtered.length){setSelectedId(null);return}
    if(!selectedId||!filtered.some(item=>item.id===selectedId))setSelectedId(filtered[0].id)
  },[filtered,selectedId])
  const selectedContract=useMemo(()=>filtered.find(item=>item.id===selectedId)??null,[filtered,selectedId])
  const documentCurrent=selectedContract
    ? selectedContract.generated_document_version===selectedContract.current_version&&Boolean(selectedContract.generated_document_hash)
    : false
  const metrics = useMemo(() => ({
    drafts: contracts.filter((item) => item.status === 'draft').length,
    review: contracts.filter((item) => item.status === 'review').length,
    signature: contracts.filter((item) => item.status === 'approved' || item.status === 'pending_signature').length,
    signed: contracts.filter((item) => item.status === 'signed').length,
  }), [contracts])

  function resolveSignerPersonId(signer: ContractSigner) {
    if (signer.person_id) return signer.person_id
    if (signer.role !== 'owner' && signer.role !== 'tenant') return null
    const email = signer.email.trim().toLowerCase()
    const document = (signer.document_number ?? '').replace(/\D/g, '')
    const match = people.find((person) => person.role_keys.includes(signer.role) && (
      (document && (person.document_number ?? '').replace(/\D/g, '') === document)
      || (email && (person.email ?? '').trim().toLowerCase() === email)
      || person.name.trim().toLowerCase() === signer.name.trim().toLowerCase()
    ))
    return match?.id ?? null
  }
  function openNew() {
    const months = defaults?.residential_lease_months ?? 30
    setEditing(null); setPropertyId(''); setLeaseMonths(months); setTerms(defaultTerms(defaults)); setChangeSummary(''); setShowForm(true); setError(''); setSuccess('')
  }
  function openEdit(item: AdministrationContract) {
    const fallbackMonths = defaults?.residential_lease_months ?? 30
    setEditing(item); setPropertyId(item.property_id); setLeaseMonths(monthsBetweenIso(item.start_date, item.end_date, fallbackMonths))
    setTerms({
      plan: item.plan, admin_fee_type: item.admin_fee_type,
      admin_fee_percent: item.admin_fee_percent == null ? null : Number(item.admin_fee_percent),
      admin_fee_amount: item.admin_fee_amount == null ? null : Number(item.admin_fee_amount),
      intermediation_percent: Number(item.intermediation_percent), intermediation_installments: item.intermediation_installments,
      owner_repasse_business_days: item.owner_repasse_business_days, condo_operational_payer: item.condo_operational_payer,
      iptu_operational_payer: item.iptu_operational_payer, publication_requires_owner_approval: item.publication_requires_owner_approval,
      maintenance_limit_amount: null, emergency_limit_amount: null,
      start_date: item.start_date, end_date: item.end_date,
      end_of_term_action: item.end_of_term_action ?? 'renew_indefinite', notes: item.notes ?? '',
      signers: item.signers.map((signer) => ({ ...signer, person_id: resolveSignerPersonId(signer) })),
    })
    setChangeSummary(''); setShowForm(true); setError(''); setSuccess('')
  }
  function updateSigner(index: number, patch: Partial<ContractSigner>) {
    setTerms((current) => ({ ...current, signers: current.signers.map((signer, i) => i === index ? { ...signer, ...patch } : signer) }))
  }
  function updateSignerRole(index: number, role: ContractSigner['role']) {
    if (role === 'agency') {
      updateSigner(index, {
        role,
        person_id: null,
        name: company?.display_name || company?.legal_name || 'Imobiliária',
        email: company?.contact_email || '',
        document_number: company?.document_number || null,
        phone: company?.contact_phone || null,
      })
      return
    }
    updateSigner(index, { role, person_id: null, name: '', email: '', document_number: null, phone: null })
  }
  function selectSignerPerson(index: number, personId: string) {
    const person = people.find((item) => item.id === personId)
    if (!person) {
      updateSigner(index, { person_id: null, name: '', email: '', document_number: null, phone: null })
      return
    }
    updateSigner(index, {
      person_id: person.id,
      name: person.name,
      email: person.email || '',
      document_number: person.document_number,
      phone: person.phone,
    })
  }

  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(''); setSuccess('')
    try {
      const payloadTerms = { ...terms, maintenance_limit_amount: null, emergency_limit_amount: null }
      let updated: AdministrationContract
      if (editing) {
        updated = await apiRequest<AdministrationContract>(`/administration-contracts/${editing.id}`, { method: 'PUT', body: JSON.stringify({ ...payloadTerms, change_summary: changeSummary }) })
        setSuccess(`${updated.code} ganhou a versão ${updated.current_version}. O PDF e o fluxo de assinatura da versão anterior foram invalidados.`)
      } else {
        const payload: AdministrationContractCreate = { ...payloadTerms, property_id: propertyId }
        updated = await apiRequest<AdministrationContract>('/administration-contracts', { method: 'POST', body: JSON.stringify(payload) })
        setSuccess(`${updated.code} criado como rascunho.`)
      }
      setContracts((current) => editing ? current.map((item) => item.id === updated.id ? updated : item) : [updated, ...current])
      setSelectedId(updated.id);setDetailTab('overview')
      setShowForm(false); setEditing(null); setChangeSummary('')
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar o contrato.') }
    finally { setSaving(false) }
  }

  async function workflow(item: AdministrationContract, action: AdministrationContractWorkflowAction, reason: string | null = null): Promise<boolean> {
    if (action === 'cancel' && !reason?.trim()) return false
    setSaving(true); setError(''); setSuccess('')
    try {
      const updated = await apiRequest<AdministrationContract>(`/administration-contracts/${item.id}/workflow`, { method: 'POST', body: JSON.stringify({ action, reason }) })
      setContracts((current) => current.map((contract) => contract.id === updated.id ? updated : contract))
      const message: Record<AdministrationContractWorkflowAction, string> = {
        submit_review: `${updated.code} enviado para revisão.`, approve: `${updated.code} aprovado internamente.`,
        prepare_signature: `${updated.code} entrou no fluxo de assinatura. Agora gere o PDF versionado.`, return_draft: `${updated.code} retornou para rascunho.`,
        cancel: `${updated.code} cancelado com motivo auditado.`,
      }
      setSuccess(message[action])
      return true
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível executar a ação.')
      return false
    } finally { setSaving(false) }
  }

  async function confirmCancellation() {
    if (!cancelTarget || !cancelReason.trim()) return
    const cancelled = await workflow(cancelTarget, 'cancel', cancelReason.trim())
    if (cancelled) {
      setCancelTarget(null)
      setCancelReason('')
    }
  }

  async function generateDocument(item: AdministrationContract) {
    setSaving(true); setError(''); setSuccess('')
    try {
      const result = await apiRequest<ContractDocument>(`/administration-contracts/${item.id}/document`, { method: 'POST' })
      await load()
      setSuccess(`${result.code} v${result.version}: PDF gerado. SHA-256 ${result.hash_sha256.slice(0, 12)}… ${result.storage_configured ? 'Original arquivado.' : 'Storage ainda não configurado.'}`)
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível gerar o PDF.') }
    finally { setSaving(false) }
  }

  async function sendSignature(item: AdministrationContract) {
    setSaving(true); setError(''); setSuccess('')
    try {
      const updated = await apiRequest<AdministrationContract>(`/administration-contracts/${item.id}/signature/send`, { method: 'POST' })
      setContracts((current) => current.map((contract) => contract.id === updated.id ? updated : contract))
      setSuccess(`${updated.code} enviado para ${updated.signing_provider}: documento, signatários, requisitos e envelope ativados.`)
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível enviar para assinatura.') }
    finally { setSaving(false) }
  }

  async function archiveFinal(item: AdministrationContract) {
    setSaving(true); setError(''); setSuccess('')
    try {
      const updated = await apiRequest<AdministrationContract>(`/administration-contracts/${item.id}/signature/archive`, { method: 'POST' })
      setContracts((current) => current.map((contract) => contract.id === updated.id ? updated : contract))
      setSuccess(`${updated.code}: PDF assinado arquivado e hash final registrado.`)
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível arquivar o documento final.') }
    finally { setSaving(false) }
  }

  return <section className="workspace contracts-workspace">
    <div className="page-heading portfolio-heading"><div><span className="eyebrow">Contratos · Administração</span><h1>Contratos de administração</h1><p>Versões imutáveis, PDF com hash, Clicksign e arquivamento final controlado.</p></div>{canCreate && <button className="button primary" type="button" onClick={openNew}><Plus size={15}/> Novo contrato</button>}</div>

    <div className="dashboard-metrics contract-metrics">
      <article className="panel metric-card"><span>Rascunhos</span><strong>{metrics.drafts}</strong><small>em preparação</small></article>
      <article className="panel metric-card"><span>Em revisão</span><strong>{metrics.review}</strong><small>aguardando validação</small></article>
      <article className="panel metric-card"><span>Aprovação / assinatura</span><strong>{metrics.signature}</strong><small>em fluxo</small></article>
      <article className="panel metric-card"><span>Assinados</span><strong>{metrics.signed}</strong><small>PDF final arquivado</small></article>
    </div>

    {error && <div className="form-alert danger-alert">{error}</div>}
    {success && <div className="form-alert success-alert">{success}</div>}

    {showForm && <form className="panel portfolio-form contract-form" onSubmit={save}>
      <div className="panel-heading panel-heading-row"><div><span className="eyebrow">{editing ? `Nova versão · ${editing.code}` : 'Nova minuta'}</span><h2>{editing ? 'Editar termos do contrato' : 'Contrato de administração'}</h2></div><FileSignature size={20}/></div>
      <div className="form-grid three-columns">
        <label className="field field-span-2"><span>Imóvel</span><select required disabled={Boolean(editing)} value={propertyId} onChange={(e) => setPropertyId(e.target.value)}><option value="">Selecione...</option>{eligibleProperties.map((item) => <option key={item.id} value={item.id}>#{item.code} · {addressLine(item.address)} · {item.owners.map((owner) => owner.name).join(' / ')}</option>)}</select></label>
        <label className="field"><span>Plano</span><select value={terms.plan} onChange={(e) => setTerms((current) => ({ ...current, plan: e.target.value as AdministrationContractTerms['plan'] }))}><option value="essential">Essencial</option><option value="complete">Completo</option><option value="custom">Personalizado</option></select></label>
        <label className="field"><span>Tipo da taxa</span><select value={terms.admin_fee_type} onChange={(e) => setTerms((current) => ({ ...current, admin_fee_type: e.target.value as AdministrationContractTerms['admin_fee_type'], admin_fee_percent: e.target.value === 'percent' ? (current.admin_fee_percent ?? defaults?.default_admin_fee_percent ?? 10) : null, admin_fee_amount: e.target.value === 'fixed' ? current.admin_fee_amount : null }))}><option value="percent">Percentual</option><option value="fixed">Valor fixo</option></select></label>
        {terms.admin_fee_type === 'percent' ? <label className="field"><span>Demais aluguéis · Administração (%)</span><input required type="number" min="0" max="100" step="0.01" value={terms.admin_fee_percent ?? ''} onChange={(e) => setTerms((current) => ({ ...current, admin_fee_percent: e.target.value ? Number(e.target.value) : null }))}/></label> : <label className="field"><span>Demais aluguéis · Taxa fixa</span><input required type="number" min="0" step="0.01" value={terms.admin_fee_amount ?? ''} onChange={(e) => setTerms((current) => ({ ...current, admin_fee_amount: e.target.value ? Number(e.target.value) : null }))}/></label>}
        <label className="field"><span>Repasse D+</span><input type="number" min="0" max="30" value={terms.owner_repasse_business_days} onChange={(e) => setTerms((current) => ({ ...current, owner_repasse_business_days: Number(e.target.value) }))}/></label>
        <label className="field"><span>1º aluguel · Intermediação (%)</span><input type="number" min="0" max="500" step="0.01" value={terms.intermediation_percent} onChange={(e) => setTerms((current) => ({ ...current, intermediation_percent: Number(e.target.value) }))}/></label>
        <label className="field"><span>Parcelas da intermediação</span><input type="number" min="1" max="24" value={terms.intermediation_installments} onChange={(e) => setTerms((current) => ({ ...current, intermediation_installments: Number(e.target.value) }))}/></label>
        <label className="field"><span>Início</span><input type="date" value={terms.start_date ?? ''} onChange={(e) => { const start = e.target.value || null; setTerms((current) => ({ ...current, start_date: start, end_date: addMonthsIso(start, leaseMonths) })) }}/></label>
        <label className="field"><span>Prazo da locação (meses)</span><input type="number" min="1" max="120" value={leaseMonths} onChange={(e) => { const months = Math.max(1, Number(e.target.value) || 1); setLeaseMonths(months); setTerms((current) => ({ ...current, end_date: addMonthsIso(current.start_date, months) })) }}/></label>
        <label className="field"><span>Fim previsto</span><input disabled type="date" value={terms.end_date ?? ''}/></label>
        <label className="field"><span>Condomínio · pagador</span><select value={terms.condo_operational_payer} onChange={(e) => setTerms((current) => ({ ...current, condo_operational_payer: e.target.value as AdministrationContractTerms['condo_operational_payer'] }))}>{Object.entries(payerLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="field"><span>IPTU · pagador</span><select value={terms.iptu_operational_payer} onChange={(e) => setTerms((current) => ({ ...current, iptu_operational_payer: e.target.value as AdministrationContractTerms['iptu_operational_payer'] }))}>{Object.entries(payerLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="field checkbox-field contract-checkbox"><input type="checkbox" checked={terms.publication_requires_owner_approval} onChange={(e) => setTerms((current) => ({ ...current, publication_requires_owner_approval: e.target.checked }))}/><span>Exigir aprovação para publicação</span></label>
        <fieldset className="contract-end-action field-span-3">
          <legend>Ao fim do período do contrato, o que será feito?</legend>
          <div className="contract-end-action-options">
            <label className={`contract-end-action-option ${terms.end_of_term_action === 'end_contract' ? 'active' : ''}`}>
              <input type="radio" name="end_of_term_action" value="end_contract" checked={terms.end_of_term_action === 'end_contract'} onChange={() => setTerms((current) => ({ ...current, end_of_term_action: 'end_contract' }))}/>
              <span><strong>Fim do contrato</strong><small>O contrato se encerra ao término do prazo determinado.</small></span>
            </label>
            <label className={`contract-end-action-option ${terms.end_of_term_action === 'renew_indefinite' ? 'active' : ''}`}>
              <input type="radio" name="end_of_term_action" value="renew_indefinite" checked={terms.end_of_term_action === 'renew_indefinite'} onChange={() => setTerms((current) => ({ ...current, end_of_term_action: 'renew_indefinite' }))}/>
              <span><strong>Renovação por prazo indeterminado</strong><small>Após o prazo determinado, a locação continua por prazo indeterminado.</small></span>
            </label>
          </div>
        </fieldset>
        <label className="field field-span-3"><span>Observações / condições especiais</span><textarea rows={3} value={terms.notes ?? ''} onChange={(e) => setTerms((current) => ({ ...current, notes: e.target.value }))}/></label>
        {editing && <label className="field field-span-3"><span>Resumo desta nova versão</span><input required minLength={3} value={changeSummary} onChange={(e) => setChangeSummary(e.target.value)}/></label>}
      </div>

      <div className="contract-snapshot-note"><ShieldCheck size={16}/><span><strong>Regra financeira:</strong> a intermediação substitui a administração nas parcelas iniciais definidas. Com 100% em 1 parcela, o 1º aluguel fica integralmente com a imobiliária e a administração passa a incidir a partir do 2º aluguel.</span></div>

      <div className="contract-signers-editor"><div className="contract-signers-heading"><div><span className="eyebrow">Assinatura</span><h3>Signatários desta versão</h3><p>Escolha o papel e selecione a pessoa já cadastrada no ERP. Proprietários e locatários são filtrados pelo respectivo papel no cadastro de Pessoas.</p></div><button className="button secondary" type="button" onClick={() => setTerms((current) => ({ ...current, signers: [...current.signers, blankSigner()] }))}><UserRoundPlus size={14}/> Adicionar</button></div>
        {terms.signers.length === 0 ? <div className="contract-signers-empty">Nenhum signatário selecionado. Se nenhum for informado, os proprietários com e-mail continuam sendo sugeridos automaticamente na criação.</div> : terms.signers.map((signer, index) => {
          const isPersonRole = signer.role === 'owner' || signer.role === 'tenant'
          const eligiblePeople = isPersonRole ? people.filter((person) => person.role_keys.includes(signer.role)) : []
          const isLegacyRole = !signerRoleOptions.some((option) => option.value === signer.role)
          return <div className="contract-signer-row" key={`${index}-${signer.person_id ?? signer.email}`}>
            <label className="field"><span>Papel</span><select value={signer.role} onChange={(e) => updateSignerRole(index, e.target.value as ContractSigner['role'])}>{isLegacyRole && <option value={signer.role}>{signerRoleLabel[signer.role] ?? signer.role} · legado</option>}{signerRoleOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
            <label className="field"><span>Nome</span>{isPersonRole ? <select required value={signer.person_id ?? ''} onChange={(e) => selectSignerPerson(index, e.target.value)}><option value="">Selecione...</option>{eligiblePeople.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}</select> : signer.role === 'agency' ? <input required readOnly value={signer.name}/> : <input required value={signer.name} onChange={(e) => updateSigner(index, { name: e.target.value })}/>}</label>
            <label className="field"><span>E-mail</span><input required type="email" value={signer.email} onChange={(e) => updateSigner(index, { email: e.target.value })}/></label>
            <label className="field"><span>CPF/CNPJ</span><input data-format="cpf-cnpj" value={signer.document_number ?? ''} onChange={(e) => updateSigner(index, { document_number: e.target.value || null })}/></label>
            <label className="field"><span>Comunicação</span><select value={signer.communication} onChange={(e) => updateSigner(index, { communication: e.target.value as ContractSigner['communication'] })}><option value="email">E-mail</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option><option value="none">Nenhuma</option></select></label>
            <label className="field signer-order"><span>Ordem</span><input type="number" min="1" max="50" value={signer.sign_order} onChange={(e) => updateSigner(index, { sign_order: Number(e.target.value) })}/></label>
            <button className="signer-remove" type="button" aria-label="Remover" onClick={() => setTerms((current) => ({ ...current, signers: current.signers.filter((_, i) => i !== index) }))}><Trash2 size={15}/></button>
          </div>
        })}
      </div>
      <div className="contract-snapshot-note"><ShieldCheck size={16}/><span>Nova versão invalida os artefatos de assinatura anteriores e exige novo PDF/hash.</span></div>
      <div className="form-actions"><button className="button secondary" type="button" onClick={() => { setShowForm(false); setEditing(null) }}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : editing ? 'Salvar nova versão' : 'Criar rascunho'}</button></div>
    </form>}


    {loading?<article className="panel settings-loading">Carregando contratos...</article>:
      <div className="contract-master-detail admin-master-detail">
        <aside className="panel contract-directory-v2" aria-label="Lista de contratos de administração">
          <div className="contract-directory-top">
            <label className="contract-directory-search"><Search size={15}/><input aria-label="Buscar contrato" value={contractQuery} onChange={event=>setContractQuery(event.target.value)} placeholder="Buscar contrato, imóvel ou proprietário..."/></label>
            <select aria-label="Filtrar contratos por status" value={filter} onChange={event=>setFilter(event.target.value as typeof filter)}>
              <option value="all">Todos os status</option><option value="draft">Rascunhos</option><option value="review">Em revisão</option><option value="approved">Aprovados</option><option value="pending_signature">Assinatura</option><option value="signed">Assinados</option><option value="cancelled">Cancelados</option>
            </select>
            <div className="contract-directory-count"><span>{filtered.length} contrato(s)</span><small>{contracts.length} no total</small></div>
          </div>
          <div className="contract-directory-list">
            {filtered.map(item=><button key={item.id} type="button" aria-pressed={selectedId===item.id} className={'contract-directory-row '+(selectedId===item.id?'active':'')} onClick={()=>{setSelectedId(item.id);setDetailTab('overview')}}>
              <span className="contract-directory-icon"><FileSignature size={18}/></span>
              <span className="contract-directory-copy">
                <span className="contract-directory-line"><strong>{item.code}</strong><i className={'status-badge '+statusClass(item.status)}>{statusLabel[item.status]}</i></span>
                <b>Imóvel #{item.property_code}</b>
                <small title={addressLine(item.property_address)}>{addressLine(item.property_address)}</small>
                <em>{planLabel[item.plan]||item.plan} · Administração {adminFee(item)}</em>
              </span>
            </button>)}
            {!filtered.length&&<div className="contract-directory-empty"><FileSignature size={24}/><strong>Nenhum contrato encontrado</strong><span>Experimente outro termo ou status.</span></div>}
          </div>
        </aside>
        <section className="panel contract-detail-v2 admin-contract-detail" aria-label="Ficha do contrato selecionado">
          {selectedContract?<>
            <header className="contract-detail-header">
              <div className="contract-detail-heading">
                <span className="contract-detail-icon"><FileSignature size={21}/></span>
                <div><span className="eyebrow">CONTRATO DE ADMINISTRAÇÃO · V{selectedContract.current_version}</span>
                  <div className="contract-title-row"><h2>{selectedContract.code}</h2><i className={'status-badge '+statusClass(selectedContract.status)}>{statusLabel[selectedContract.status]}</i></div>
                  <p title={addressLine(selectedContract.property_address)}>Imóvel #{selectedContract.property_code} · {addressLine(selectedContract.property_address)}</p>
                </div>
              </div>
              <div className="contract-detail-actions-v2">
                {(selectedContract.status==='draft'||selectedContract.status==='review')&&canEdit&&<button className="button secondary" type="button" onClick={()=>openEdit(selectedContract)}>Nova versão</button>}
                {selectedContract.status==='draft'&&canEdit&&<button className="button primary" type="button" disabled={saving} onClick={()=>void workflow(selectedContract,'submit_review')}><Send size={14}/> Revisão</button>}
                {selectedContract.status==='review'&&canApprove&&<button className="button primary" type="button" disabled={saving} onClick={()=>void workflow(selectedContract,'approve')}><CheckCircle2 size={14}/> Aprovar</button>}
                {selectedContract.status==='approved'&&canSign&&<button className="button primary" type="button" disabled={saving} onClick={()=>void workflow(selectedContract,'prepare_signature')}><FileSignature size={14}/> Preparar assinatura</button>}
                {selectedContract.status==='pending_signature'&&canSign&&!documentCurrent&&<button className="button secondary" type="button" disabled={saving} onClick={()=>void generateDocument(selectedContract)}><FileText size={14}/> Gerar PDF</button>}
                {selectedContract.status==='pending_signature'&&canSign&&documentCurrent&&!['provider_running','provider_signature_progress','provider_closed_pending_archive','signed_archived'].includes(selectedContract.signing_status)&&<button className="button primary" type="button" disabled={saving} onClick={()=>void sendSignature(selectedContract)}><Send size={14}/> Enviar à Clicksign</button>}
                {selectedContract.status==='pending_signature'&&canSign&&['provider_closed_pending_archive','archive_failed'].includes(selectedContract.signing_status)&&<button className="button primary" type="button" disabled={saving} onClick={()=>void archiveFinal(selectedContract)}><FileCheck2 size={14}/> Arquivar PDF final</button>}
                {(selectedContract.status==='review'||selectedContract.status==='approved'||selectedContract.status==='pending_signature')&&canEdit&&<button className="button secondary" type="button" disabled={saving} onClick={()=>void workflow(selectedContract,'return_draft')}><RotateCcw size={14}/> Rascunho</button>}
                {selectedContract.status!=='cancelled'&&selectedContract.status!=='signed'&&canEdit&&<button className="button ghost-danger" type="button" disabled={saving} onClick={()=>{setCancelTarget(selectedContract);setCancelReason('')}}>Cancelar</button>}
                {documentCurrent&&<a className="button secondary" href={'/api/administration-contracts/'+selectedContract.id+'/document/pdf'} target="_blank" rel="noreferrer"><Download size={14}/> Ver PDF</a>}
              </div>
            </header>
            <div className="contract-essential-strip admin-essential-strip">
              <div><span>Plano</span><strong>{planLabel[selectedContract.plan]||selectedContract.plan}</strong></div>
              <div><span>Administração</span><strong>{adminFee(selectedContract)}</strong></div>
              <div><span>Intermediação</span><strong>{Number(selectedContract.intermediation_percent).toLocaleString('pt-BR')}% · {selectedContract.intermediation_installments} parcela(s)</strong></div>
              <div><span>Repasse</span><strong>D+{selectedContract.owner_repasse_business_days} dias úteis</strong></div>
              <div><span>Assinatura</span><strong>{signingLabel(selectedContract)}</strong></div>
            </div>
            <nav className="contract-detail-tabs" aria-label="Abas do contrato">
              <button type="button" className={detailTab==='overview'?'active':''} onClick={()=>setDetailTab('overview')}><FileText size={14}/> Visão geral</button>
              <button type="button" className={detailTab==='parties'?'active':''} onClick={()=>setDetailTab('parties')}><Users size={14}/> Partes</button>
              <button type="button" className={detailTab==='finance'?'active':''} onClick={()=>setDetailTab('finance')}><WalletCards size={14}/> Financeiro</button>
              <button type="button" className={detailTab==='signature'?'active':''} onClick={()=>setDetailTab('signature')}><FileSignature size={14}/> Assinatura</button>
              <button type="button" className={detailTab==='documents'?'active':''} onClick={()=>setDetailTab('documents')}><FileCheck2 size={14}/> Documentos</button>
              <button type="button" className={detailTab==='history'?'active':''} onClick={()=>setDetailTab('history')}><History size={14}/> Histórico</button>
            </nav>
            <div className="contract-detail-body">
              {detailTab==='overview'&&<div className="contract-overview-v2">
                <article className="contract-surface-v2"><div className="contract-section-heading"><div><span>Resumo operacional</span><h3>Condições principais</h3></div><ShieldCheck size={16}/></div>
                  <div className="contract-facts-grid">
                    <div><span>Imóvel</span><strong>#{selectedContract.property_code}</strong><small title={addressLine(selectedContract.property_address)}>{addressLine(selectedContract.property_address)}</small></div>
                    <div><span>Proprietários</span><strong>{selectedContract.owners.length} titular(es)</strong><small>{selectedContract.owners.map(owner=>owner.name).join(' / ')||'Não informado'}</small></div>
                    <div><span>Vigência</span><strong>{selectedContract.start_date?new Date(selectedContract.start_date+'T12:00:00').toLocaleDateString('pt-BR'):'Não definida'}</strong><small>Fim {selectedContract.end_date?new Date(selectedContract.end_date+'T12:00:00').toLocaleDateString('pt-BR'):'não definido'}</small></div>
                    <div><span>Plano</span><strong>{planLabel[selectedContract.plan]||selectedContract.plan}</strong><small>Administração {adminFee(selectedContract)}</small></div>
                    <div><span>Condomínio</span><strong>{payerLabel[selectedContract.condo_operational_payer]||selectedContract.condo_operational_payer}</strong><small>Responsável operacional</small></div>
                    <div><span>IPTU</span><strong>{payerLabel[selectedContract.iptu_operational_payer]||selectedContract.iptu_operational_payer}</strong><small>Responsável operacional</small></div>
                  </div>
                </article>
                <article className="contract-surface-v2 contract-status-card"><div className="contract-section-heading"><div><span>Fluxo atual</span><h3>{statusLabel[selectedContract.status]}</h3></div><ShieldCheck size={16}/></div>
                  <div className="contract-flow-summary">
                    <div><span>Assinatura</span><strong>{signingLabel(selectedContract)}</strong></div>
                    <div><span>PDF atual</span><strong>{documentCurrent?'Gerado':'Pendente'}</strong></div>
                    <div><span>Arquivo final</span><strong>{selectedContract.archive_status==='archived'?'Arquivado':'Pendente'}</strong></div>
                    <div><span>Versão</span><strong>v{selectedContract.current_version}</strong></div>
                  </div>
                </article>
                {selectedContract.notes&&<article className="contract-surface-v2 contract-notes-v2"><div className="contract-section-heading"><div><span>Observações</span><h3>Condições adicionais</h3></div></div><p>{selectedContract.notes}</p></article>}
              </div>}
              {detailTab==='parties'&&<div className="contract-parties-v2">
                <article className="contract-surface-v2"><div className="contract-section-heading"><div><span>Partes</span><h3>Proprietários do imóvel</h3></div><Users size={16}/></div>
                  <div className="contract-party-list">{selectedContract.owners.map((owner,index)=><article key={index+'-'+owner.name}><span className="contract-party-avatar">{owner.name.trim().charAt(0).toUpperCase()}</span><div><strong>{owner.name}</strong><small>{Number(owner.ownership_percent).toLocaleString('pt-BR')}% de participação</small></div></article>)}
                    {!selectedContract.owners.length&&<div className="contract-empty-soft">Nenhum proprietário vinculado.</div>}
                  </div>
                </article>
                <article className="contract-surface-v2"><div className="contract-section-heading"><div><span>Signatários</span><h3>Participantes da assinatura</h3></div><Users size={16}/></div>
                  <div className="contract-signer-list-v2">{selectedContract.signers.map((signer,index)=><article key={index+'-'+signer.email}><b>{signer.sign_order}</b><div><strong>{signer.name}</strong><small>{signerRoleLabel[signer.role]||signer.role} · {signer.email}</small></div></article>)}
                    {!selectedContract.signers.length&&<div className="contract-empty-soft">Nenhum signatário definido nesta versão.</div>}
                  </div>
                </article>
              </div>}
              {detailTab==='finance'&&<div className="contract-finance-v2">
                <div className="contract-kpis-v2">
                  <article><span>Taxa de administração</span><strong>{adminFee(selectedContract)}</strong><small>Condição contratada</small></article>
                  <article><span>Intermediação</span><strong>{Number(selectedContract.intermediation_percent).toLocaleString('pt-BR')}%</strong><small>{selectedContract.intermediation_installments} parcela(s)</small></article>
                  <article><span>Repasse</span><strong>D+{selectedContract.owner_repasse_business_days}</strong><small>Dias úteis após recebimento</small></article>
                  <article><span>Plano</span><strong>{planLabel[selectedContract.plan]||selectedContract.plan}</strong><small>Condições contratuais</small></article>
                </div>
                <article className="contract-surface-v2"><div className="contract-section-heading"><div><span>Condições financeiras</span><h3>Regras desta versão</h3></div><WalletCards size={17}/></div>
                  <div className="contract-flow-summary">
                    <div><span>Intermediação</span><strong>{Number(selectedContract.intermediation_percent).toLocaleString('pt-BR')}% em {selectedContract.intermediation_installments} parcela(s)</strong></div>
                    <div><span>Administração após intermediação</span><strong>{adminFee(selectedContract)}</strong></div>
                    <div><span>Repasse ao proprietário</span><strong>D+{selectedContract.owner_repasse_business_days} dias úteis</strong></div>
                  </div>
                  <p className="admin-contract-finance-note">As cobranças e baixas efetivas permanecem na central Financeiro; esta aba mostra somente as condições vigentes deste contrato.</p>
                </article>
              </div>}
              {detailTab==='signature'&&<div className="contract-signature-v2">
                <article className="contract-surface-v2"><div className="contract-section-heading"><div><span>Assinatura eletrônica</span><h3>{signingLabel(selectedContract)}</h3></div><FileSignature size={17}/></div>
                  <div className="contract-document-summary-v2">
                    <div><span>Provedor</span><strong>{selectedContract.signing_provider||'Não definido'}</strong></div>
                    <div><span>Envelope</span><strong title={selectedContract.signing_envelope_id||undefined}>{selectedContract.signing_envelope_id||'Não enviado'}</strong></div>
                    <div><span>PDF atual</span><strong>{documentCurrent?'Gerado e versionado':'Pendente'}</strong></div>
                    <div><span>Arquivo final</span><strong>{selectedContract.archive_status==='archived'?'Arquivado':'Pendente'}</strong></div>
                  </div>
                  <SignatureTimeline key={selectedContract.id} contractId={selectedContract.id}/>
                </article>
              </div>}
              {detailTab==='documents'&&<div className="contract-documents-v2">
                <article className="contract-surface-v2"><div className="contract-section-heading"><div><span>Documento principal</span><h3>PDF e integridade</h3></div><FileCheck2 size={17}/></div>
                  <div className="contract-document-summary-v2">
                    <div><span>Versão documental</span><strong>{selectedContract.generated_document_version??'Não gerado'}</strong></div>
                    <div><span>SHA-256 original</span><strong title={selectedContract.generated_document_hash||undefined}>{selectedContract.generated_document_hash||'Pendente'}</strong></div>
                    <div><span>SHA-256 final</span><strong title={selectedContract.final_document_hash||undefined}>{selectedContract.final_document_hash||'Pendente'}</strong></div>
                    <div><span>Arquivo final</span><strong>{selectedContract.archive_status==='archived'?'Arquivado':selectedContract.archive_status.replaceAll('_',' ')}</strong></div>
                  </div>
                  {documentCurrent&&<a className="button secondary admin-document-link" href={'/api/administration-contracts/'+selectedContract.id+'/document/pdf'} target="_blank" rel="noreferrer"><Download size={14}/> Visualizar PDF atual</a>}
                </article>
                <EntityDocumentsPanel key={selectedContract.id} entityType="administration_contract" entityId={selectedContract.id} entityLabel={selectedContract.code} permissions={permissions} compact/>
              </div>}
              {detailTab==='history'&&<div className="contract-history-v2">
                <article className="contract-surface-v2"><div className="contract-section-heading"><div><span>Versionamento</span><h3>Histórico imutável</h3></div><History size={17}/></div>
                  <div className="contract-version-list-v2">{[...selectedContract.versions].reverse().map(version=><article key={version.version_number}><b>v{version.version_number}</b><div><strong>{version.change_summary||'Versão registrada'}</strong><small>{new Date(version.created_at).toLocaleString('pt-BR')}</small></div></article>)}
                    {!selectedContract.versions.length&&<div className="contract-empty-soft">Nenhuma versão registrada.</div>}
                  </div>
                </article>
              </div>}
            </div>
          </>:<div className="contract-detail-empty"><FileSignature size={28}/><strong>Selecione um contrato</strong><span>A ficha operacional será exibida aqui.</span></div>}
        </section>
      </div>}

    <article className="panel contract-provider-note"><ShieldCheck size={21}/><div><span className="eyebrow">Integridade documental</span><h2>O ERP não confia apenas no status da Clicksign</h2><p>Cada PDF original recebe SHA-256 antes do envio. Mesmo após a Clicksign encerrar a assinatura, o contrato só muda para “Assinado” depois que o PDF final é salvo no storage próprio e recebe um segundo hash.</p></div></article>

    <ConfirmDialog
      open={Boolean(cancelTarget)}
      title="Cancelar contrato de administração"
      description={cancelTarget ? `Informe o motivo para cancelar ${cancelTarget.code}. O motivo ficará registrado na auditoria do contrato.` : 'Informe o motivo do cancelamento.'}
      confirmLabel="Cancelar contrato"
      tone="danger"
      busy={saving}
      confirmDisabled={!cancelReason.trim()}
      onCancel={() => { if (!saving) { setCancelTarget(null); setCancelReason('') } }}
      onConfirm={() => void confirmCancellation()}
    >
      <label className="field">
        <span>Motivo do cancelamento</span>
        <textarea rows={3} value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} placeholder="Descreva o motivo..." />
      </label>
    </ConfirmDialog>
  </section>
}
