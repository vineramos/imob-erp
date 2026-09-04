import {
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  FileCheck2,
  FileSignature,
  FileText,
  History,
  Plus,
  RotateCcw,
  Send,
  ShieldCheck,
  Trash2,
  UserRoundPlus,
  Users,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import type { AdjustmentIndex, ContractDocument, OperationalDefaults, Person, Property } from '../../api/types'
import { SignatureTimeline } from './SignatureTimeline'
import { EntityDocumentsPanel } from '../documents/EntityDocumentsPanel'

type LeaseStatus = 'draft' | 'review' | 'approved' | 'pending_signature' | 'signed' | 'cancelled'
type GuaranteeType = 'insurance' | 'deposit' | 'capitalization' | 'guarantor' | 'none'
type LeaseWorkflowAction = 'submit_review' | 'approve' | 'prepare_signature' | 'return_draft' | 'cancel'
type LeaseSignerRole = 'owner' | 'tenant' | 'agency' | 'witness' | 'other'
type MonthlyChargeKind = 'iptu' | 'condo' | 'guarantee_insurance' | 'fire_insurance' | 'other'
type MonthlyChargePayer = 'tenant' | 'owner' | 'agency'
type MonthlyChargeBeneficiary = 'owner' | 'agency' | 'third_party'
type MonthlyCharge = {
  key: string
  kind: MonthlyChargeKind
  label: string
  amount: number
  active: boolean
  payer: MonthlyChargePayer
  beneficiary: MonthlyChargeBeneficiary
  start_date: string | null
  end_date: string | null
}
type MonthlyChargeConfig = {
  lease_contract_id: string
  lease_code: string
  configured: boolean
  monthly_charges: Array<Omit<MonthlyCharge, 'amount'> & { amount: number | string }>
  tenant_monthly_total: number | string
}
type LeaseSigner = {
  role: LeaseSignerRole
  name: string
  email: string
  document_number: string | null
  phone: string | null
  sign_order: number
  communication: 'email' | 'sms' | 'whatsapp' | 'none'
}
type LeaseVersion = { version_number: number; change_summary: string | null; created_at: string }
type Lease = {
  id: string
  code: string
  property_id: string
  property_code: string
  property_address: Record<string, string>
  owners: Array<{ name: string; ownership_percent: string | number; email?: string | null }>
  tenants: Array<{ person_id: string; name: string; document_number: string | null; email?: string | null }>
  status: LeaseStatus
  rent_amount: number
  due_day: number
  adjustment_index: AdjustmentIndex
  adjustment_period_months: number
  adjustment_base_date: string
  next_adjustment_date: string
  term_months: number
  start_date: string
  end_date: string
  termination_fine_months: number
  inspection_contest_days: number
  guarantee_type: GuaranteeType
  guarantee_details: Record<string, unknown>
  notes: string | null
  signers: LeaseSigner[]
  current_version: number
  generated_document_reference: string | null
  generated_document_hash: string | null
  generated_document_version: number | null
  signing_provider: string
  signing_status: string
  signing_envelope_id: string | null
  signing_document_id: string | null
  approved_at: string | null
  signed_at: string | null
  archive_status: string
  archived_document_reference: string | null
  final_document_hash: string | null
  archived_at: string | null
  versions: LeaseVersion[]
}
type LeaseForm = {
  property_id: string
  tenant_ids: string[]
  rent_amount: number | null
  due_day: number
  adjustment_index: AdjustmentIndex
  adjustment_period_months: number
  adjustment_base_date: string
  next_adjustment_date: string
  term_months: number
  start_date: string
  end_date: string
  termination_fine_months: number
  inspection_contest_days: number
  guarantee_type: GuaranteeType
  guarantee_details: Record<string, unknown>
  monthly_charges: MonthlyCharge[]
  notes: string
  signers: LeaseSigner[]
}

const indexOptions: AdjustmentIndex[] = ['IPCA', 'IGP-M', 'INPC', 'IPC-FIPE', 'IGP-DI']
const guaranteeLabels: Record<GuaranteeType, string> = {
  insurance: 'Seguro fiança',
  deposit: 'Caução',
  capitalization: 'Título de capitalização',
  guarantor: 'Fiador (exceção)',
  none: 'Sem garantia (exceção)',
}
const statusLabels: Record<LeaseStatus, string> = {
  draft: 'Rascunho',
  review: 'Em revisão',
  approved: 'Aprovado',
  pending_signature: 'Assinatura',
  signed: 'Assinado',
  cancelled: 'Cancelado',
}
const signerRoleLabels: Record<LeaseSignerRole, string> = {
  owner: 'Proprietário',
  tenant: 'Locatário',
  agency: 'Imobiliária',
  witness: 'Testemunha',
  other: 'Outro',
}
const payerLabels: Record<MonthlyChargePayer, string> = { tenant: 'Locatário', owner: 'Proprietário', agency: 'Imobiliária' }
const beneficiaryLabels: Record<MonthlyChargeBeneficiary, string> = { owner: 'Proprietário', agency: 'Imobiliária', third_party: 'Terceiro' }

function isoAddMonths(value: string, months: number) {
  if (!value) return ''
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1 + months, day))
  return date.toISOString().slice(0, 10)
}
function addressLine(address: Record<string, string>) {
  return [address.street, address.number, address.neighborhood, address.city].filter(Boolean).join(', ') || 'Endereço não informado'
}
function money(value: number | null) {
  return value == null ? '—' : Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}
function statusClass(value: LeaseStatus) {
  if (value === 'signed' || value === 'approved') return 'success'
  if (value === 'cancelled') return 'danger'
  if (value === 'review' || value === 'pending_signature') return 'warning'
  return 'neutral'
}
function signingLabel(item: Lease) {
  const labels: Record<string, string> = {
    not_prepared: 'Fluxo interno',
    ready_for_document: 'Gerar PDF',
    document_ready: 'PDF pronto para envio',
    provider_running: 'Assinatura em andamento',
    provider_signature_progress: 'Assinaturas em andamento',
    provider_closed_pending_archive: 'Concluído · arquivar PDF final',
    archive_failed: 'Arquivamento pendente',
    signed_archived: 'PDF final arquivado',
    provider_setup_failed: 'Falha ao preparar provider',
    storage_not_configured: 'Storage pendente',
    provider_not_configured: 'Provider pendente',
  }
  return labels[item.signing_status] ?? item.signing_status.replaceAll('_', ' ')
}
function blankSigner(): LeaseSigner {
  return { role: 'tenant', name: '', email: '', document_number: null, phone: null, sign_order: 1, communication: 'email' }
}
function standardMonthlyCharges(property?: Property): MonthlyCharge[] {
  const iptu = Number(property?.iptu_amount ?? 0)
  const condo = Number(property?.condo_amount ?? 0)
  return [
    { key: 'iptu', kind: 'iptu', label: 'IPTU', amount: iptu, active: iptu > 0, payer: 'tenant', beneficiary: 'owner', start_date: null, end_date: null },
    { key: 'condo', kind: 'condo', label: 'Condomínio', amount: condo, active: condo > 0, payer: 'tenant', beneficiary: 'third_party', start_date: null, end_date: null },
    { key: 'guarantee_insurance', kind: 'guarantee_insurance', label: 'Seguro fiança', amount: 0, active: false, payer: 'tenant', beneficiary: 'third_party', start_date: null, end_date: null },
    { key: 'fire_insurance', kind: 'fire_insurance', label: 'Seguro incêndio', amount: 0, active: false, payer: 'tenant', beneficiary: 'third_party', start_date: null, end_date: null },
  ]
}
function normalizeMonthlyCharges(items: MonthlyChargeConfig['monthly_charges']): MonthlyCharge[] {
  return items.map((item) => ({ ...item, amount: Number(item.amount || 0) }))
}
function defaultForm(defaults?: OperationalDefaults): LeaseForm {
  return {
    property_id: '',
    tenant_ids: [],
    rent_amount: null,
    due_day: defaults?.rent_due_day ?? 10,
    adjustment_index: defaults?.adjustment_index ?? 'IPCA',
    adjustment_period_months: 12,
    adjustment_base_date: '',
    next_adjustment_date: '',
    term_months: defaults?.residential_lease_months ?? 30,
    start_date: '',
    end_date: '',
    termination_fine_months: defaults?.termination_fine_months ?? 3,
    inspection_contest_days: defaults?.inspection_contest_days ?? 5,
    guarantee_type: 'insurance',
    guarantee_details: {},
    monthly_charges: standardMonthlyCharges(),
    notes: '',
    signers: [],
  }
}
function dateLabel(value: string | null) {
  if (!value) return '—'
  return new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString('pt-BR')
}

type Props = { permissions: string[] }

export function LeaseContractsPage({ permissions }: Props) {
  const granted = useMemo(() => new Set(permissions), [permissions])
  const canCreate = granted.has('contracts.create')
  const canEdit = granted.has('contracts.edit')
  const canApprove = granted.has('contracts.approve')
  const canSign = granted.has('contracts.send_signature')

  const [items, setItems] = useState<Lease[]>([])
  const [properties, setProperties] = useState<Property[]>([])
  const [persons, setPersons] = useState<Person[]>([])
  const [defaults, setDefaults] = useState<OperationalDefaults>()
  const [form, setForm] = useState<LeaseForm>(() => defaultForm())
  const [editing, setEditing] = useState<Lease | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [changeSummary, setChangeSummary] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [expandedTab, setExpandedTab] = useState<'details' | 'documents'>('details')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [contracts, props, people, operations] = await Promise.all([
        apiRequest<Lease[]>('/lease-contracts'),
        apiRequest<Property[]>('/properties'),
        apiRequest<Person[]>('/people'),
        apiRequest<OperationalDefaults>('/settings/operations'),
      ])
      setItems(contracts)
      setProperties(props)
      setPersons(people)
      setDefaults(operations)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os contratos de locação.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const tenantCandidates = useMemo(
    () => persons.filter((person) => person.is_active && (person.role_keys.includes('tenant') || person.role_keys.length === 0)),
    [persons],
  )
  const eligibleProperties = useMemo(
    () => properties.filter((property) => property.owners.length > 0 && !items.some((contract) => contract.property_id === property.id && contract.status !== 'cancelled')),
    [properties, items],
  )
  const metrics = useMemo(() => ({
    draft: items.filter((item) => item.status === 'draft').length,
    review: items.filter((item) => item.status === 'review').length,
    signature: items.filter((item) => item.status === 'approved' || item.status === 'pending_signature').length,
    signed: items.filter((item) => item.status === 'signed').length,
  }), [items])
  const tenantMonthlyTotal = useMemo(() => Number(form.rent_amount || 0) + form.monthly_charges.reduce((total, item) => total + (item.active && item.payer === 'tenant' ? Number(item.amount || 0) : 0), 0), [form.rent_amount, form.monthly_charges])

  function openNew() {
    setEditing(null)
    setForm(defaultForm(defaults))
    setChangeSummary('')
    setShowForm(true)
    setError('')
    setSuccess('')
  }

  async function openEdit(item: Lease) {
    setEditing(item)
    setChangeSummary('')
    setError('')
    setSuccess('')
    const property = properties.find((candidate) => candidate.id === item.property_id)
    let monthlyCharges = standardMonthlyCharges(property)
    try {
      const result = await apiRequest<MonthlyChargeConfig>(`/finance/lease-contracts/${item.id}/monthly-charges`)
      monthlyCharges = normalizeMonthlyCharges(result.monthly_charges)
    } catch {
      // Mantém sugestões do cadastro do imóvel caso a configuração financeira ainda não exista.
    }
    setForm({
      property_id: item.property_id,
      tenant_ids: item.tenants.map((tenant) => tenant.person_id),
      rent_amount: Number(item.rent_amount),
      due_day: item.due_day,
      adjustment_index: item.adjustment_index,
      adjustment_period_months: item.adjustment_period_months,
      adjustment_base_date: item.adjustment_base_date,
      next_adjustment_date: item.next_adjustment_date,
      term_months: item.term_months,
      start_date: item.start_date,
      end_date: item.end_date,
      termination_fine_months: Number(item.termination_fine_months),
      inspection_contest_days: item.inspection_contest_days,
      guarantee_type: item.guarantee_type,
      guarantee_details: item.guarantee_details,
      monthly_charges: monthlyCharges,
      notes: item.notes ?? '',
      signers: item.signers.map((signer) => ({ ...signer })),
    })
    setShowForm(true)
  }

  function changeStart(value: string) {
    setForm((current) => ({
      ...current,
      start_date: value,
      adjustment_base_date: value,
      next_adjustment_date: isoAddMonths(value, current.adjustment_period_months),
      end_date: isoAddMonths(value, current.term_months),
    }))
  }
  function changeTerm(value: number) {
    setForm((current) => ({ ...current, term_months: value, end_date: isoAddMonths(current.start_date, value) }))
  }
  function toggleTenant(id: string) {
    setForm((current) => ({
      ...current,
      tenant_ids: current.tenant_ids.includes(id) ? current.tenant_ids.filter((value) => value !== id) : [...current.tenant_ids, id],
    }))
  }
  function updateSigner(index: number, patch: Partial<LeaseSigner>) {
    setForm((current) => ({
      ...current,
      signers: current.signers.map((signer, signerIndex) => signerIndex === index ? { ...signer, ...patch } : signer),
    }))
  }
  function updateMonthlyCharge(index: number, patch: Partial<MonthlyCharge>) {
    setForm((current) => ({
      ...current,
      monthly_charges: current.monthly_charges.map((charge, chargeIndex) => chargeIndex === index ? { ...charge, ...patch } : charge),
    }))
  }
  function addMonthlyCharge() {
    const suffix = Date.now().toString(36)
    setForm((current) => ({
      ...current,
      monthly_charges: [...current.monthly_charges, { key: `other_${suffix}`, kind: 'other', label: 'Outro encargo', amount: 0, active: true, payer: 'tenant', beneficiary: 'third_party', start_date: null, end_date: null }],
    }))
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      if (!form.rent_amount || form.tenant_ids.length === 0) throw new Error('Informe o aluguel e ao menos um locatário.')
      const body = editing ? { ...form, change_summary: changeSummary } : form
      const updated = await apiRequest<Lease>(
        editing ? `/lease-contracts/${editing.id}` : '/lease-contracts',
        { method: editing ? 'PUT' : 'POST', body: JSON.stringify(body) },
      )
      setItems((current) => editing
        ? current.map((item) => item.id === updated.id ? updated : item)
        : [updated, ...current])
      setShowForm(false)
      setEditing(null)
      setSuccess(
        editing
          ? `${updated.code} ganhou a versão ${updated.current_version}. PDF, assinatura e composição mensal anteriores foram invalidados.`
          : `${updated.code} criado com a composição mensal congelada na versão inicial.`,
      )
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : cause instanceof Error ? cause.message : 'Não foi possível salvar a locação.')
    } finally {
      setSaving(false)
    }
  }

  async function workflow(item: Lease, action: LeaseWorkflowAction) {
    let reason: string | null = null
    if (action === 'cancel') {
      reason = window.prompt('Motivo do cancelamento:')
      if (!reason?.trim()) return
    }
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const updated = await apiRequest<Lease>(`/lease-contracts/${item.id}/workflow`, {
        method: 'POST',
        body: JSON.stringify({ action, reason }),
      })
      setItems((current) => current.map((contract) => contract.id === updated.id ? updated : contract))
      const message: Record<LeaseWorkflowAction, string> = {
        submit_review: `${updated.code} enviado para revisão.`,
        approve: `${updated.code} aprovado internamente.`,
        prepare_signature: `${updated.code} entrou no fluxo de assinatura. Gere o PDF versionado antes do envio.`,
        return_draft: `${updated.code} retornou para rascunho.`,
        cancel: `${updated.code} cancelado com motivo auditado.`,
      }
      setSuccess(message[action])
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível avançar o contrato.')
    } finally {
      setSaving(false)
    }
  }

  async function generateDocument(item: Lease) {
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const result = await apiRequest<ContractDocument>(`/lease-contracts/${item.id}/document`, { method: 'POST' })
      await load()
      setSuccess(
        `${result.code} v${result.version}: PDF gerado. SHA-256 ${result.hash_sha256.slice(0, 12)}… `
        + (result.storage_configured ? 'Original arquivado.' : 'Storage ainda não configurado.'),
      )
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível gerar o PDF.')
    } finally {
      setSaving(false)
    }
  }

  async function sendSignature(item: Lease) {
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const updated = await apiRequest<Lease>(`/lease-contracts/${item.id}/signature/send`, { method: 'POST' })
      setItems((current) => current.map((contract) => contract.id === updated.id ? updated : contract))
      setSuccess(`${updated.code} enviado para ${updated.signing_provider}: envelope ativado com os signatários desta versão.`)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível enviar para assinatura.')
    } finally {
      setSaving(false)
    }
  }

  async function archiveFinal(item: Lease) {
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const updated = await apiRequest<Lease>(`/lease-contracts/${item.id}/signature/archive`, { method: 'POST' })
      setItems((current) => current.map((contract) => contract.id === updated.id ? updated : contract))
      setProperties((current) => current.map((property) => property.id === updated.property_id
        ? { ...property, status: 'leased', publication_enabled: false }
        : property))
      setSuccess(`${updated.code}: PDF final arquivado. O imóvel agora está Locado e foi retirado das vitrines.`)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível arquivar o documento final.')
    } finally {
      setSaving(false)
    }
  }

  async function openPdf(item: Lease) {
    setError('')
    try {
      const blob = await apiBlobRequest(`/lease-contracts/${item.id}/document/pdf`)
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener,noreferrer')
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível abrir o PDF.')
    }
  }

  async function downloadStored(item: Lease, kind: 'original' | 'final') {
    setError('')
    try {
      const blob = await apiBlobRequest(`/lease-contracts/${item.id}/document/${kind}`)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${item.code}-v${item.current_version}-${kind === 'final' ? 'ASSINADO' : 'original'}.pdf`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível baixar o documento.')
    }
  }

  return <section className="workspace lease-workspace">
    <div className="page-heading portfolio-heading">
      <div>
        <span className="eyebrow">Contratos · Locação</span>
        <h1>Contratos de locação</h1>
        <p>Versão congelada, composição mensal, PDF com hash e assinatura eletrônica.</p>
      </div>
      {canCreate && <button className="button primary" type="button" onClick={openNew}><Plus size={15}/> Nova locação</button>}
    </div>

    <div className="dashboard-metrics contract-metrics">
      <article className="panel metric-card"><span>Rascunhos</span><strong>{metrics.draft}</strong><small>em preparação</small></article>
      <article className="panel metric-card"><span>Em revisão</span><strong>{metrics.review}</strong><small>aguardando validação</small></article>
      <article className="panel metric-card"><span>Aprovação / assinatura</span><strong>{metrics.signature}</strong><small>em fluxo documental</small></article>
      <article className="panel metric-card"><span>Assinados</span><strong>{metrics.signed}</strong><small>PDF final arquivado</small></article>
    </div>

    {error && <div className="form-alert danger-alert">{error}</div>}
    {success && <div className="form-alert success-alert">{success}</div>}

    {showForm && <form className="panel portfolio-form lease-form" onSubmit={save}>
      <div className="panel-heading panel-heading-row">
        <div><span className="eyebrow">{editing ? `Nova versão · ${editing.code}` : 'Nova minuta'}</span><h2>Condições da locação</h2></div>
        <FileSignature size={20}/>
      </div>
      <div className="form-grid three-columns">
        <label className="field field-span-2">
          <span>Imóvel</span>
          <select
            required
            disabled={Boolean(editing)}
            value={form.property_id}
            onChange={(event) => {
              const id = event.target.value
              const property = properties.find((value) => value.id === id)
              setForm((current) => ({ ...current, property_id: id, rent_amount: property?.rent_amount ?? current.rent_amount, monthly_charges: standardMonthlyCharges(property) }))
            }}
          >
            <option value="">Selecione...</option>
            {(editing ? properties : eligibleProperties).map((property) => <option value={property.id} key={property.id}>#{property.code} · {addressLine(property.address)}</option>)}
          </select>
        </label>
        <label className="field"><span>Aluguel</span><input required min="0.01" step="0.01" type="number" value={form.rent_amount ?? ''} onChange={(event) => setForm((current) => ({ ...current, rent_amount: event.target.value ? Number(event.target.value) : null }))}/></label>
        <label className="field"><span>Início</span><input required type="date" value={form.start_date} onChange={(event) => changeStart(event.target.value)}/></label>
        <label className="field"><span>Prazo (meses)</span><input min="1" max="240" type="number" value={form.term_months} onChange={(event) => changeTerm(Number(event.target.value))}/></label>
        <label className="field"><span>Término</span><input required type="date" value={form.end_date} onChange={(event) => setForm((current) => ({ ...current, end_date: event.target.value }))}/></label>
        <label className="field"><span>Vencimento</span><input min="1" max="28" type="number" value={form.due_day} onChange={(event) => setForm((current) => ({ ...current, due_day: Number(event.target.value) }))}/></label>
        <label className="field"><span>Índice de reajuste</span><select value={form.adjustment_index} onChange={(event) => setForm((current) => ({ ...current, adjustment_index: event.target.value as AdjustmentIndex }))}>{indexOptions.map((index) => <option value={index} key={index}>{index}</option>)}</select></label>
        <label className="field"><span>Periodicidade (meses)</span><input min="1" max="36" type="number" value={form.adjustment_period_months} onChange={(event) => { const months = Number(event.target.value); setForm((current) => ({ ...current, adjustment_period_months: months, next_adjustment_date: isoAddMonths(current.adjustment_base_date, months) })) }}/></label>
        <label className="field"><span>Data-base</span><input required type="date" value={form.adjustment_base_date} onChange={(event) => setForm((current) => ({ ...current, adjustment_base_date: event.target.value, next_adjustment_date: isoAddMonths(event.target.value, current.adjustment_period_months) }))}/></label>
        <label className="field"><span>Próximo reajuste</span><input required type="date" value={form.next_adjustment_date} onChange={(event) => setForm((current) => ({ ...current, next_adjustment_date: event.target.value }))}/></label>
        <label className="field"><span>Multa rescisória (aluguéis)</span><input min="0" max="12" step="0.1" type="number" value={form.termination_fine_months} onChange={(event) => setForm((current) => ({ ...current, termination_fine_months: Number(event.target.value) }))}/></label>
        <label className="field"><span>Contestação vistoria (dias)</span><input min="1" max="30" type="number" value={form.inspection_contest_days} onChange={(event) => setForm((current) => ({ ...current, inspection_contest_days: Number(event.target.value) }))}/></label>
        <label className="field"><span>Garantia</span><select value={form.guarantee_type} onChange={(event) => setForm((current) => ({ ...current, guarantee_type: event.target.value as GuaranteeType }))}>{Object.entries(guaranteeLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="field field-span-3"><span>Observações</span><textarea rows={3} value={form.notes} onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}/></label>
        {editing && <label className="field field-span-3"><span>Resumo desta nova versão</span><input required minLength={3} value={changeSummary} onChange={(event) => setChangeSummary(event.target.value)}/></label>}
      </div>

      <div className="lease-monthly-charges">
        <div className="lease-monthly-heading">
          <div><span className="eyebrow">Composição mensal</span><h3>Aluguel + encargos recorrentes</h3><p>IPTU, condomínio, seguro fiança, seguro incêndio e outros itens ficam congelados nesta versão do contrato.</p></div>
          <div className="lease-monthly-total"><span>Cobrança mensal do locatário</span><strong>{money(tenantMonthlyTotal)}</strong><small>considerando itens ativos cobrados do locatário</small></div>
        </div>
        <div className="lease-monthly-table">
          <div className="lease-monthly-table-head"><span>Ativo</span><span>Encargo</span><span>Valor</span><span>Responsável</span><span>Destino</span><span>Vigência</span><span/></div>
          {form.monthly_charges.map((charge, index) => <div className={`lease-monthly-row ${charge.active ? '' : 'inactive'}`} key={charge.key}>
            <label className="lease-charge-toggle"><input type="checkbox" checked={charge.active} onChange={(event) => updateMonthlyCharge(index, { active: event.target.checked })}/><span>{charge.active ? 'Sim' : 'Não'}</span></label>
            <label className="field"><span>Descrição</span><input required value={charge.label} onChange={(event) => updateMonthlyCharge(index, { label: event.target.value })}/></label>
            <label className="field"><span>Valor mensal</span><input min="0" step="0.01" type="number" value={charge.amount || ''} onChange={(event) => { const amount = event.target.value ? Number(event.target.value) : 0; updateMonthlyCharge(index, { amount, active: amount > 0 ? true : charge.active }) }}/></label>
            <label className="field"><span>Responsável</span><select value={charge.payer} onChange={(event) => updateMonthlyCharge(index, { payer: event.target.value as MonthlyChargePayer })}>{Object.entries(payerLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
            <label className="field"><span>Destino</span><select value={charge.beneficiary} onChange={(event) => updateMonthlyCharge(index, { beneficiary: event.target.value as MonthlyChargeBeneficiary })}>{Object.entries(beneficiaryLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
            <div className="lease-charge-period"><label><span>De</span><input type="date" min={form.start_date || undefined} max={form.end_date || undefined} value={charge.start_date ?? ''} onChange={(event) => updateMonthlyCharge(index, { start_date: event.target.value || null })}/></label><label><span>Até</span><input type="date" min={form.start_date || undefined} max={form.end_date || undefined} value={charge.end_date ?? ''} onChange={(event) => updateMonthlyCharge(index, { end_date: event.target.value || null })}/></label></div>
            {charge.kind === 'other' ? <button className="signer-remove" type="button" aria-label="Remover encargo" onClick={() => setForm((current) => ({ ...current, monthly_charges: current.monthly_charges.filter((_, chargeIndex) => chargeIndex !== index) }))}><Trash2 size={15}/></button> : <span className="lease-charge-fixed">padrão</span>}
          </div>)}
        </div>
        <div className="lease-monthly-footer"><span>Somente itens com responsável “Locatário” entram na cobrança mensal. Destino “Proprietário” compõe o repasse; “Imobiliária” vira reembolso; “Terceiro” fica separado para condomínio/seguradora.</span><button className="button secondary" type="button" onClick={addMonthlyCharge}><Plus size={14}/> Outro encargo</button></div>
      </div>

      <div className="lease-tenants">
        <div><span className="eyebrow">Locatários</span><h3>Partes da locação</h3><p>Todos os locatários selecionados ficam congelados no snapshot da versão.</p></div>
        <div className="lease-tenant-grid">
          {tenantCandidates.map((person) => <label className={form.tenant_ids.includes(person.id) ? 'selected' : ''} key={person.id}>
            <input type="checkbox" checked={form.tenant_ids.includes(person.id)} onChange={() => toggleTenant(person.id)}/>
            <Users size={15}/>
            <span><strong>{person.name}</strong><small>{person.document_number || person.email || 'Cadastro sem documento'}</small></span>
          </label>)}
        </div>
      </div>

      <div className="contract-signers-editor">
        <div className="contract-signers-heading">
          <div><span className="eyebrow">Assinatura</span><h3>Signatários desta versão</h3><p>Se a lista ficar vazia, o ERP monta automaticamente proprietários + locatários ao salvar.</p></div>
          <button className="button secondary" type="button" onClick={() => setForm((current) => ({ ...current, signers: [...current.signers, blankSigner()] }))}><UserRoundPlus size={14}/> Adicionar</button>
        </div>
        {form.signers.length === 0
          ? <div className="contract-signers-empty">Signatários automáticos serão criados a partir das partes do contrato. E-mail será obrigatório antes do envio à Clicksign.</div>
          : form.signers.map((signer, index) => <div className="contract-signer-row" key={`${index}-${signer.email}`}>
            <label className="field"><span>Papel</span><select value={signer.role} onChange={(event) => updateSigner(index, { role: event.target.value as LeaseSignerRole })}>{Object.entries(signerRoleLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label className="field"><span>Nome</span><input required value={signer.name} onChange={(event) => updateSigner(index, { name: event.target.value })}/></label>
            <label className="field"><span>E-mail</span><input required type="email" value={signer.email} onChange={(event) => updateSigner(index, { email: event.target.value })}/></label>
            <label className="field"><span>CPF/CNPJ</span><input value={signer.document_number ?? ''} onChange={(event) => updateSigner(index, { document_number: event.target.value || null })}/></label>
            <label className="field"><span>Comunicação</span><select value={signer.communication} onChange={(event) => updateSigner(index, { communication: event.target.value as LeaseSigner['communication'] })}><option value="email">E-mail</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option><option value="none">Nenhuma</option></select></label>
            <label className="field signer-order"><span>Ordem</span><input type="number" min="1" max="50" value={signer.sign_order} onChange={(event) => updateSigner(index, { sign_order: Number(event.target.value) })}/></label>
            <button className="signer-remove" type="button" aria-label="Remover signatário" onClick={() => setForm((current) => ({ ...current, signers: current.signers.filter((_, signerIndex) => signerIndex !== index) }))}><Trash2 size={15}/></button>
          </div>)}
      </div>

      <div className="contract-snapshot-note"><ShieldCheck size={16}/><span>Nova versão invalida PDF/hash e assinatura anteriores. A composição mensal também fica versionada para preservar o histórico das cobranças.</span></div>
      <div className="form-actions">
        <button className="button secondary" type="button" onClick={() => { setShowForm(false); setEditing(null) }}>Cancelar</button>
        <button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : editing ? 'Salvar nova versão' : 'Criar rascunho'}</button>
      </div>
    </form>}

    {loading
      ? <article className="panel settings-loading">Carregando locações...</article>
      : <div className="portfolio-card-list contract-list lease-list">
        {items.map((item) => {
          const isExpanded = expanded === item.id
          const documentCurrent = item.generated_document_version === item.current_version && Boolean(item.generated_document_hash)
          return <article className="panel contract-card lease-card" key={item.id}>
            <div className="contract-row">
              <div className="contract-code"><FileSignature size={18}/><span>LOCAÇÃO</span><strong>{item.code}</strong><small>v{item.current_version}</small></div>
              <div className="contract-property"><strong>Imóvel #{item.property_code}</strong><span>{addressLine(item.property_address)}</span><small>{item.tenants.map((tenant) => tenant.name).join(' / ')}</small></div>
              <div className="contract-commercial"><span>Aluguel / vencimento</span><strong>{money(Number(item.rent_amount))} · dia {item.due_day}</strong><small>{item.adjustment_index} · {item.term_months} meses · garantia {guaranteeLabels[item.guarantee_type]}</small></div>
              <div className="contract-state"><i className={`status-badge ${statusClass(item.status)}`}>{statusLabels[item.status]}</i><span>{signingLabel(item)}</span></div>
            </div>

            <div className="contract-document-strip">
              <div><FileText size={15}/><span>PDF</span><strong>{documentCurrent ? `v${item.generated_document_version} · ${item.generated_document_hash?.slice(0, 10)}…` : 'não gerado'}</strong></div>
              <div><FileSignature size={15}/><span>Clicksign</span><strong>{item.signing_envelope_id ? `envelope ${item.signing_envelope_id.slice(0, 8)}…` : 'não enviado'}</strong></div>
              <div><FileCheck2 size={15}/><span>Arquivo final</span><strong>{item.archive_status === 'archived' ? `${item.final_document_hash?.slice(0, 10)}…` : item.archive_status.replaceAll('_', ' ')}</strong></div>
            </div>

            <div className="contract-actions">
              <button className="contract-history-toggle" type="button" onClick={() => { setExpanded(isExpanded ? null : item.id); setExpandedTab('details') }}><History size={14}/> Detalhes {isExpanded ? <ChevronUp size={13}/> : <ChevronDown size={13}/>}</button>
              <div>
                {(item.status === 'draft' || item.status === 'review') && canEdit && <button className="button secondary" type="button" onClick={() => void openEdit(item)}>Nova versão</button>}
                {item.status === 'draft' && canEdit && <button className="button primary" disabled={saving} type="button" onClick={() => void workflow(item, 'submit_review')}><Send size={14}/> Revisão</button>}
                {item.status === 'review' && canApprove && <button className="button primary" disabled={saving} type="button" onClick={() => void workflow(item, 'approve')}><CheckCircle2 size={14}/> Aprovar</button>}
                {item.status === 'approved' && canSign && <button className="button primary" disabled={saving} type="button" onClick={() => void workflow(item, 'prepare_signature')}><FileSignature size={14}/> Preparar assinatura</button>}
                {item.status === 'pending_signature' && item.signing_status === 'ready_for_document' && canSign && <button className="button primary" disabled={saving} type="button" onClick={() => void generateDocument(item)}><FileText size={14}/> Gerar PDF</button>}
                {item.status === 'pending_signature' && item.signing_status === 'document_ready' && canSign && <button className="button primary" disabled={saving} type="button" onClick={() => void sendSignature(item)}><Send size={14}/> Enviar Clicksign</button>}
                {item.status === 'pending_signature' && ['provider_closed_pending_archive', 'archive_failed'].includes(item.signing_status) && canSign && <button className="button primary" disabled={saving} type="button" onClick={() => void archiveFinal(item)}><FileCheck2 size={14}/> Arquivar final</button>}
                {['review', 'approved', 'pending_signature'].includes(item.status) && canEdit && <button className="button secondary" type="button" onClick={() => void workflow(item, 'return_draft')}><RotateCcw size={14}/> Rascunho</button>}
                {!['signed', 'cancelled'].includes(item.status) && canEdit && <button className="button ghost-danger" type="button" onClick={() => void workflow(item, 'cancel')}>Cancelar</button>}
              </div>
            </div>

            {isExpanded && <><div className="entity-document-tabs"><button type="button" className={expandedTab==='details'?'active':''} onClick={()=>setExpandedTab('details')}>Detalhes</button><button type="button" className={expandedTab==='documents'?'active':''} onClick={()=>setExpandedTab('documents')}>Documentos</button></div>{expandedTab==='details'&&<div className="contract-expanded">
              <div className="contract-version-panel">
                <div className="panel-heading-row"><div><span className="eyebrow">Versões</span><h3>Histórico imutável</h3></div><CalendarClock size={17}/></div>
                {item.versions.slice().reverse().map((version) => <div className="contract-version-row" key={version.version_number}><strong>v{version.version_number}</strong><span>{version.change_summary || 'Sem resumo'}</span><small>{new Date(version.created_at).toLocaleString('pt-BR')}</small></div>)}
              </div>
              <div className="contract-version-panel">
                <div className="panel-heading-row"><div><span className="eyebrow">Documento</span><h3>PDF e hashes</h3></div><FileCheck2 size={17}/></div>
                <div className="contract-document-detail"><span>Versão documental</span><strong>{item.generated_document_version ?? '—'}</strong></div>
                <div className="contract-document-detail"><span>SHA-256 original</span><strong>{item.generated_document_hash ?? '—'}</strong></div>
                <div className="contract-document-detail"><span>SHA-256 final</span><strong>{item.final_document_hash ?? '—'}</strong></div>
                <div className="contract-document-detail"><span>Assinado em</span><strong>{item.signed_at ? new Date(item.signed_at).toLocaleString('pt-BR') : '—'}</strong></div>
                <div className="contract-detail-actions">
                  <button className="button secondary" type="button" onClick={() => void openPdf(item)}><FileText size={14}/> Prévia atual</button>
                  {item.generated_document_reference && <button className="button secondary" type="button" onClick={() => void downloadStored(item, 'original')}><Download size={14}/> Original</button>}
                  {item.archived_document_reference && <button className="button secondary" type="button" onClick={() => void downloadStored(item, 'final')}><Download size={14}/> Assinado</button>}
                </div>
              </div>
              <div className="contract-version-panel">
                <div className="panel-heading-row"><div><span className="eyebrow">Regras</span><h3>Resumo operacional</h3></div><ShieldCheck size={17}/></div>
                <div className="contract-document-detail"><span>Início / término</span><strong>{dateLabel(item.start_date)} · {dateLabel(item.end_date)}</strong></div>
                <div className="contract-document-detail"><span>Reajuste</span><strong>{item.adjustment_index} · próximo {dateLabel(item.next_adjustment_date)}</strong></div>
                <div className="contract-document-detail"><span>Vistoria</span><strong>{item.inspection_contest_days} dias para contestação</strong></div>
                <div className="contract-document-detail"><span>Composição mensal</span><strong>Versionada junto ao contrato e aplicada na geração financeira</strong></div>
                <div className="contract-document-detail"><span>Signatários</span><strong>{item.signers.map((signer) => signer.name).join(' / ') || 'não definidos'}</strong></div>
              </div>
              <SignatureTimeline contractId={item.id} contractType="lease"/>
            </div>}{expandedTab==='documents'&&<EntityDocumentsPanel entityType="lease_contract" entityId={item.id} entityLabel={item.code} permissions={permissions} compact/>}</>}
          </article>
        })}
        {items.length === 0 && <article className="panel portfolio-empty"><FileText size={26}/><strong>Nenhum contrato de locação ainda.</strong><span>Crie a primeira minuta usando as regras-padrão da imobiliária.</span></article>}
      </div>}
  </section>
}
