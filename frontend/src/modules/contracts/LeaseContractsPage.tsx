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
  Search,
  Home,
  CircleDollarSign,
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
import { LeaseLifecyclePanel } from './LeaseLifecyclePanel'
import { EntityDocumentsPanel } from '../documents/EntityDocumentsPanel'

function LeasePersonPhoto({person,className}:{person:Person;className:string}){
  const [src,setSrc]=useState('')
  useEffect(()=>{
    let active=true,objectUrl=''
    if(!person.photo_content_url){setSrc('');return()=>undefined}
    void apiBlobRequest(person.photo_content_url).then(blob=>{if(!active)return;objectUrl=URL.createObjectURL(blob);setSrc(objectUrl)}).catch(()=>{if(active)setSrc('')})
    return()=>{active=false;if(objectUrl)URL.revokeObjectURL(objectUrl)}
  },[person.id,person.photo_content_url,person.photo_updated_at])
  if(src)return <img className={className} src={src} alt={person.name}/>
  return <span className={className}>{person.name.trim().split(/\s+/).slice(0,2).map(part=>part[0]?.toUpperCase()).join('')}</span>
}

type LeaseStatus = 'draft' | 'review' | 'approved' | 'pending_signature' | 'signed' | 'closed' | 'cancelled'
type ContractDetailTab = 'overview' | 'parties' | 'finance' | 'signature' | 'documents' | 'history'
type LeaseCharge = { id:string; lease_contract_id:string; code:string; competence:string; due_date:string; status:string; gross_amount:number; paid_amount:number|null; paid_at:string|null }
type GuaranteeType = 'insurance' | 'deposit' | 'capitalization' | 'guarantor' | 'none'
type LeaseWorkflowAction = 'submit_review' | 'approve' | 'prepare_signature' | 'return_draft' | 'cancel'
type LeaseSignerRole = 'owner' | 'tenant' | 'agency' | 'witness' | 'other'
type MonthlyChargeKind = 'iptu' | 'condo' | 'guarantee_insurance' | 'fire_insurance' | 'other'
type MonthlyChargePayer = 'tenant' | 'owner' | 'agency'
type MonthlyChargeBeneficiary = 'owner' | 'agency' | 'third_party'
type LatePaymentTerms = {
  fee_percent: number
  interest_percent_monthly: number
  interest_type: 'simple' | 'compound'
  compounding: 'daily' | 'monthly'
}
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
  late_payment?: {
    fee_percent: number | string
    interest_percent_monthly: number | string
    interest_type: 'simple' | 'compound'
    compounding: 'daily' | 'monthly'
  }
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
  operational_end_date: string | null
  closed_at: string | null
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
  late_payment: LatePaymentTerms
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
  closed: 'Encerrado',
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
function percent(value: number) {
  return Number(value).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}
function statusClass(value: LeaseStatus) {
  if (value === 'signed' || value === 'approved' || value === 'closed') return 'success'
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
function defaultLatePayment(defaults?: OperationalDefaults): LatePaymentTerms {
  return {
    fee_percent: Number(defaults?.late_fee_percent ?? 2),
    interest_percent_monthly: Number(defaults?.late_interest_percent_monthly ?? 1),
    interest_type: defaults?.late_interest_type ?? 'simple',
    compounding: defaults?.late_interest_compounding ?? 'daily',
  }
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
    late_payment: defaultLatePayment(defaults),
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
  const [expandedTab, setExpandedTab] = useState<'details' | 'lifecycle' | 'documents'>('details')
  const [selectedId,setSelectedId]=useState<string|null>(null)
  const [detailTab,setDetailTab]=useState<ContractDetailTab>('overview')
  const [contractQuery,setContractQuery]=useState('')
  const [contractStatus,setContractStatus]=useState<'all'|LeaseStatus>('all')
  const [contractCharges,setContractCharges]=useState<LeaseCharge[]>([])
  const [chargesLoading,setChargesLoading]=useState(false)
  const [signerLookupIndex, setSignerLookupIndex] = useState<number | null>(null)
  const [cancelTarget, setCancelTarget] = useState<Lease | null>(null)
  const [cancelReason, setCancelReason] = useState('')
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
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const propertyId = params.get('propertyId')
    if (!propertyId || !canCreate || loading) return
    const property = properties.find((item) => item.id === propertyId)
    if (!property) return
    setEditing(null)
    setForm({ ...defaultForm(defaults), property_id: property.id, rent_amount: property.rent_amount })
    setChangeSummary('')
    setSignerLookupIndex(null)
    setShowForm(true)
    window.history.replaceState({}, '', '/app/contracts')
  }, [canCreate, defaults, loading, properties])



  const tenantCandidates = useMemo(
    () => persons.filter((person) => person.is_active && (person.role_keys.includes('tenant') || person.role_keys.length === 0)),
    [persons],
  )
  const eligibleProperties = useMemo(
    () => properties.filter((property) => property.owners.length > 0 && !items.some((contract) => contract.property_id === property.id && !['cancelled', 'closed'].includes(contract.status))),
    [properties, items],
  )
  const metrics = useMemo(() => ({
    draft: items.filter((item) => item.status === 'draft').length,
    review: items.filter((item) => item.status === 'review').length,
    signature: items.filter((item) => item.status === 'approved' || item.status === 'pending_signature').length,
    signed: items.filter((item) => item.status === 'signed').length,
  }), [items])
  const tenantMonthlyTotal = useMemo(() => Number(form.rent_amount || 0) + form.monthly_charges.reduce((total, item) => total + (item.active && item.payer === 'tenant' ? Number(item.amount || 0) : 0), 0), [form.rent_amount, form.monthly_charges])

  const filteredContracts=useMemo(()=>{
    const term=contractQuery.trim().toLocaleLowerCase('pt-BR')
    return items.filter(item=>{
      if(contractStatus!=='all'&&item.status!==contractStatus)return false
      if(!term)return true
      const haystack=[item.code,item.property_code,addressLine(item.property_address),...item.tenants.map(tenant=>tenant.name),...item.owners.map(owner=>owner.name)].join(' ').toLocaleLowerCase('pt-BR')
      return haystack.includes(term)
    })
  },[items,contractQuery,contractStatus])
  useEffect(()=>{
    if(filteredContracts.length===0){setSelectedId(null);return}
    if(!selectedId||!filteredContracts.some(item=>item.id===selectedId))setSelectedId(filteredContracts[0].id)
  },[filteredContracts,selectedId])
  const selectedLease=useMemo(()=>items.find(item=>item.id===selectedId)??null,[items,selectedId])
  useEffect(()=>{
    if(!selectedLease||detailTab!=='finance'||!granted.has('finance.view'))return
    setChargesLoading(true)
    void apiRequest<LeaseCharge[]>(`/finance/charges?lease_contract_id=${selectedLease.id}`)
      .then(setContractCharges)
      .catch(cause=>setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o financeiro do contrato.'))
      .finally(()=>setChargesLoading(false))
  },[selectedLease,detailTab,granted])


  function openNew() {
    setEditing(null)
    setForm(defaultForm(defaults))
    setChangeSummary('')
    setSignerLookupIndex(null)
    setShowForm(true)
    setError('')
    setSuccess('')
  }

  async function openEdit(item: Lease) {
    setEditing(item)
    setChangeSummary('')
    setSignerLookupIndex(null)
    setError('')
    setSuccess('')
    const property = properties.find((candidate) => candidate.id === item.property_id)
    let monthlyCharges = standardMonthlyCharges(property)
    let latePayment = defaultLatePayment(defaults)
    try {
      const result = await apiRequest<MonthlyChargeConfig>(`/finance/lease-contracts/${item.id}/monthly-charges`)
      monthlyCharges = normalizeMonthlyCharges(result.monthly_charges)
      if (result.late_payment) {
        latePayment = {
          fee_percent: Number(result.late_payment.fee_percent || 0),
          interest_percent_monthly: Number(result.late_payment.interest_percent_monthly || 0),
          interest_type: result.late_payment.interest_type,
          compounding: result.late_payment.compounding,
        }
      }
    } catch {
      // Mantém sugestões do cadastro do imóvel e defaults operacionais caso a configuração financeira ainda não exista.
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
      late_payment: latePayment,
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
  function signerMatches(signer: LeaseSigner) {
    const term = signer.name.trim().toLocaleLowerCase('pt-BR')
    return persons
      .filter((person) => person.is_active)
      .filter((person) => !term || [person.name, person.document_number ?? '', person.email ?? ''].some((value) => value.toLocaleLowerCase('pt-BR').includes(term)))
      .slice(0, 8)
  }
  function chooseSigner(index: number, person: Person) {
    updateSigner(index, {
      name: person.name,
      email: person.email ?? '',
      document_number: person.document_number,
      phone: person.phone,
    })
    setSignerLookupIndex(null)
  }
  function updateMonthlyCharge(index: number, patch: Partial<MonthlyCharge>) {
    setForm((current) => ({
      ...current,
      monthly_charges: current.monthly_charges.map((charge, chargeIndex) => chargeIndex === index ? { ...charge, ...patch } : charge),
    }))
  }
  function removeMonthlyCharge(index: number) {
    setForm((current) => ({ ...current, monthly_charges: current.monthly_charges.filter((_, chargeIndex) => chargeIndex !== index) }))
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
      setSignerLookupIndex(null)
      setSuccess(
        editing
          ? `${updated.code} ganhou a versão ${updated.current_version}. PDF, assinatura e composição mensal anteriores foram invalidados.`
          : `${updated.code} criado com a composição mensal e regra de mora congeladas na versão inicial.`,
      )
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : cause instanceof Error ? cause.message : 'Não foi possível salvar a locação.')
    } finally {
      setSaving(false)
    }
  }

  async function workflow(item: Lease, action: LeaseWorkflowAction, providedReason: string | null = null) {
    const reason = action === 'cancel' ? providedReason : null
    if (action === 'cancel' && !reason?.trim()) return
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
      if (action === 'cancel') {
        setCancelTarget(null)
        setCancelReason('')
      }
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

      <div className="lease-late-payment">
        <div className="lease-late-payment-heading"><span className="eyebrow">Mora e atraso</span><h3>Multa e juros desta versão</h3><p>Esta regra fica congelada no contrato. Alterações futuras em Configurações não mudam esta locação.</p></div>
        <div className="lease-late-payment-grid">
          <label className="field"><span>Multa por atraso (%)</span><input min="0" max="100" step="0.01" type="number" value={form.late_payment.fee_percent} onChange={(event) => setForm((current) => ({ ...current, late_payment: { ...current.late_payment, fee_percent: Number(event.target.value) } }))}/></label>
          <label className="field"><span>Juros ao mês (%)</span><input min="0" max="100" step="0.01" type="number" value={form.late_payment.interest_percent_monthly} onChange={(event) => setForm((current) => ({ ...current, late_payment: { ...current.late_payment, interest_percent_monthly: Number(event.target.value) } }))}/></label>
          <label className="field"><span>Tipo de juros</span><select value={form.late_payment.interest_type} onChange={(event) => setForm((current) => ({ ...current, late_payment: { ...current.late_payment, interest_type: event.target.value as LatePaymentTerms['interest_type'] } }))}><option value="simple">Simples</option><option value="compound">Composto</option></select></label>
          <label className="field"><span>Capitalização</span><select disabled={form.late_payment.interest_type !== 'compound'} value={form.late_payment.compounding} onChange={(event) => setForm((current) => ({ ...current, late_payment: { ...current.late_payment, compounding: event.target.value as LatePaymentTerms['compounding'] } }))}><option value="daily">Diária</option><option value="monthly">Mensal</option></select></label>
        </div>
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
            <div className="lease-charge-period"><label><span>Início</span><input type="date" min={form.start_date || undefined} max={form.end_date || undefined} value={charge.start_date ?? ''} onChange={(event) => updateMonthlyCharge(index, { start_date: event.target.value || null })}/></label><label><span>Fim</span><input type="date" min={form.start_date || undefined} max={form.end_date || undefined} value={charge.end_date ?? ''} onChange={(event) => updateMonthlyCharge(index, { end_date: event.target.value || null })}/></label></div>
            <button className="signer-remove lease-charge-remove" type="button" title={`Remover ${charge.label}`} aria-label={`Remover ${charge.label}`} onClick={() => removeMonthlyCharge(index)}><Trash2 size={14}/></button>
          </div>)}
        </div>
        <div className="lease-monthly-footer"><span>Somente itens com responsável “Locatário” entram na cobrança mensal. Destino “Proprietário” compõe o repasse; “Imobiliária” vira reembolso; “Terceiro” fica separado para condomínio/seguradora.</span><button className="button secondary" type="button" onClick={addMonthlyCharge}><Plus size={14}/> Outro encargo</button></div>
      </div>

      <div className="lease-tenants">
        <div><span className="eyebrow">Locatários</span><h3>Partes da locação</h3><p>Todos os locatários selecionados ficam congelados no snapshot da versão.</p></div>
        <div className="lease-tenant-grid">
          {tenantCandidates.map((person) => <label className={form.tenant_ids.includes(person.id) ? 'selected' : ''} key={person.id}>
            <input type="checkbox" checked={form.tenant_ids.includes(person.id)} onChange={() => toggleTenant(person.id)}/>
            <LeasePersonPhoto person={person} className="lease-person-avatar"/>
            <span><strong>{person.name}</strong><small>{person.document_number || person.email || 'Cadastro sem documento'}</small></span>
          </label>)}
        </div>
      </div>

      <div className="contract-signers-editor">
        <div className="contract-signers-heading">
          <div><span className="eyebrow">Assinatura</span><h3>Signatários desta versão</h3><p>Pesquise uma pessoa já cadastrada pelo nome, documento ou e-mail. Testemunhas e outros signatários ainda podem ser preenchidos manualmente.</p></div>
          <button className="button secondary" type="button" onClick={() => setForm((current) => ({ ...current, signers: [...current.signers, blankSigner()] }))}><UserRoundPlus size={14}/> Adicionar</button>
        </div>
        {form.signers.length === 0
          ? <div className="contract-signers-empty">Signatários automáticos serão criados a partir das partes do contrato. E-mail será obrigatório antes do envio à Clicksign.</div>
          : form.signers.map((signer, index) => <div className="contract-signer-row" key={`${index}-${signer.email}`}>
            <label className="field"><span>Papel</span><select value={signer.role} onChange={(event) => updateSigner(index, { role: event.target.value as LeaseSignerRole })}>{Object.entries(signerRoleLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label className="field signer-person-field"><span>Nome</span><input required autoComplete="off" value={signer.name} onFocus={() => setSignerLookupIndex(index)} onBlur={() => window.setTimeout(() => setSignerLookupIndex((current) => current === index ? null : current), 120)} onChange={(event) => { updateSigner(index, { name: event.target.value }); setSignerLookupIndex(index) }}/>{signerLookupIndex === index && <div className="signer-person-results">{signerMatches(signer).length ? signerMatches(signer).map((person) => <button type="button" key={person.id} onMouseDown={(event) => { event.preventDefault(); chooseSigner(index, person) }}><LeasePersonPhoto person={person} className="lease-person-avatar"/><span><strong>{person.name}</strong><small>{person.document_number || person.email || 'Cadastro sem documento'}</small></span></button>) : <span>Nenhuma pessoa encontrada.</span>}</div>}</label>
            <label className="field"><span>E-mail</span><input required type="email" value={signer.email} onChange={(event) => updateSigner(index, { email: event.target.value })}/></label>
            <label className="field"><span>CPF/CNPJ</span><input value={signer.document_number ?? ''} onChange={(event) => updateSigner(index, { document_number: event.target.value || null })}/></label>
            <label className="field"><span>Comunicação</span><select value={signer.communication} onChange={(event) => updateSigner(index, { communication: event.target.value as LeaseSigner['communication'] })}><option value="email">E-mail</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option><option value="none">Nenhuma</option></select></label>
            <label className="field signer-order"><span>Ordem</span><input type="number" min="1" max="50" value={signer.sign_order} onChange={(event) => updateSigner(index, { sign_order: Number(event.target.value) })}/></label>
            <button className="signer-remove" type="button" aria-label="Remover signatário" onClick={() => setForm((current) => ({ ...current, signers: current.signers.filter((_, signerIndex) => signerIndex !== index) }))}><Trash2 size={15}/></button>
          </div>)}
      </div>

      <div className="contract-snapshot-note"><ShieldCheck size={16}/><span>Nova versão invalida PDF/hash e assinatura anteriores. A composição mensal e a regra de multa/juros também ficam versionadas para preservar o histórico das cobranças.</span></div>
      <div className="form-actions">
        <button className="button secondary" type="button" onClick={() => { setShowForm(false); setEditing(null); setSignerLookupIndex(null) }}>Cancelar</button>
        <button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : editing ? 'Salvar nova versão' : 'Criar rascunho'}</button>
      </div>
    </form>}

    {loading
      ? <article className="panel settings-loading">Carregando locações...</article>
      : <div className="contract-master-detail">
        <aside className="panel contract-directory-v2">
          <div className="contract-directory-top">
            <label className="contract-directory-search"><Search size={14}/><input value={contractQuery} onChange={event=>setContractQuery(event.target.value)} placeholder="Buscar contrato, imóvel ou pessoa..."/></label>
            <select value={contractStatus} onChange={event=>setContractStatus(event.target.value as 'all'|LeaseStatus)}>
              <option value="all">Todos os status</option>
              {Object.entries(statusLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}
            </select>
            <div className="contract-directory-count"><span>{filteredContracts.length} contrato(s)</span><small>{items.length} no total</small></div>
          </div>
          <div className="contract-directory-list">
            {filteredContracts.map(item=><button type="button" key={item.id} className={'contract-directory-row '+(selectedLease?.id===item.id?'active':'')} onClick={()=>{setSelectedId(item.id);setDetailTab('overview')}}>
              <span className="contract-directory-icon"><FileSignature size={15}/></span>
              <span className="contract-directory-copy">
                <span className="contract-directory-line"><strong>{item.code}</strong><i className={'status-badge '+statusClass(item.status)}>{statusLabels[item.status]}</i></span>
                <b>Imóvel #{item.property_code}</b>
                <small>{addressLine(item.property_address)}</small>
                <em>{item.tenants.map(tenant=>tenant.name).join(' / ')||'Sem locatário'} · {money(Number(item.rent_amount))}</em>
              </span>
            </button>)}
            {filteredContracts.length===0&&<div className="contract-directory-empty"><FileText size={22}/><strong>Nenhum contrato encontrado</strong><span>Ajuste a busca ou o filtro de status.</span></div>}
          </div>
        </aside>

        <main className="panel contract-detail-v2">
          {!selectedLease?<div className="contract-detail-empty"><FileSignature size={28}/><strong>Selecione um contrato</strong><span>A ficha operacional aparecerá aqui.</span></div>:<>
            <header className="contract-detail-header">
              <div className="contract-detail-heading">
                <span className="contract-detail-icon"><FileSignature size={20}/></span>
                <div><span className="eyebrow">Contrato de locação · v{selectedLease.current_version}</span><div className="contract-title-row"><h2>{selectedLease.code}</h2><i className={'status-badge '+statusClass(selectedLease.status)}>{statusLabels[selectedLease.status]}</i></div><p>Imóvel #{selectedLease.property_code} · {addressLine(selectedLease.property_address)}</p></div>
              </div>
              <div className="contract-detail-actions-v2">
                {(selectedLease.status==='draft'||selectedLease.status==='review')&&canEdit&&<button className="button secondary" type="button" onClick={()=>void openEdit(selectedLease)}>Nova versão</button>}
                {selectedLease.status==='draft'&&canEdit&&<button className="button primary" disabled={saving} type="button" onClick={()=>void workflow(selectedLease,'submit_review')}><Send size={14}/> Revisão</button>}
                {selectedLease.status==='review'&&canApprove&&<button className="button primary" disabled={saving} type="button" onClick={()=>void workflow(selectedLease,'approve')}><CheckCircle2 size={14}/> Aprovar</button>}
                {selectedLease.status==='approved'&&canSign&&<button className="button primary" disabled={saving} type="button" onClick={()=>void workflow(selectedLease,'prepare_signature')}><FileSignature size={14}/> Preparar assinatura</button>}
                {selectedLease.status==='pending_signature'&&selectedLease.signing_status==='ready_for_document'&&canSign&&<button className="button primary" disabled={saving} type="button" onClick={()=>void generateDocument(selectedLease)}><FileText size={14}/> Gerar PDF</button>}
                {selectedLease.status==='pending_signature'&&selectedLease.signing_status==='document_ready'&&canSign&&<button className="button primary" disabled={saving} type="button" onClick={()=>void sendSignature(selectedLease)}><Send size={14}/> Enviar Clicksign</button>}
                {selectedLease.status==='pending_signature'&&['provider_closed_pending_archive','archive_failed'].includes(selectedLease.signing_status)&&canSign&&<button className="button primary" disabled={saving} type="button" onClick={()=>void archiveFinal(selectedLease)}><FileCheck2 size={14}/> Arquivar final</button>}
              </div>
            </header>

            <div className="contract-essential-strip">
              <div><span>Aluguel</span><strong>{money(Number(selectedLease.rent_amount))}</strong></div>
              <div><span>Vencimento</span><strong>Dia {selectedLease.due_day}</strong></div>
              <div><span>Vigência</span><strong>{dateLabel(selectedLease.start_date)} — {dateLabel(selectedLease.end_date)}</strong></div>
              <div><span>Garantia</span><strong>{guaranteeLabels[selectedLease.guarantee_type]}</strong></div>
              <div><span>Reajuste</span><strong>{selectedLease.adjustment_index} · {selectedLease.adjustment_period_months}m</strong></div>
            </div>

            <nav className="contract-detail-tabs" aria-label="Seções do contrato">
              <button className={detailTab==='overview'?'active':''} type="button" onClick={()=>setDetailTab('overview')}><Home size={13}/>Visão Geral</button>
              <button className={detailTab==='parties'?'active':''} type="button" onClick={()=>setDetailTab('parties')}><Users size={13}/>Partes</button>
              <button className={detailTab==='finance'?'active':''} type="button" onClick={()=>setDetailTab('finance')}><CircleDollarSign size={13}/>Financeiro</button>
              <button className={detailTab==='signature'?'active':''} type="button" onClick={()=>setDetailTab('signature')}><FileSignature size={13}/>Assinatura</button>
              <button className={detailTab==='documents'?'active':''} type="button" onClick={()=>setDetailTab('documents')}><FileText size={13}/>Documentos</button>
              <button className={detailTab==='history'?'active':''} type="button" onClick={()=>setDetailTab('history')}><History size={13}/>Histórico</button>
            </nav>

            <div className="contract-detail-body">
              {detailTab==='overview'&&<div className="contract-overview-v2">
                <section className="contract-surface-v2 contract-overview-main">
                  <div className="contract-section-heading"><div><span>Resumo operacional</span><h3>Condições principais</h3></div><ShieldCheck size={17}/></div>
                  <div className="contract-facts-grid">
                    <div><span>Imóvel</span><strong>#{selectedLease.property_code}</strong><small>{addressLine(selectedLease.property_address)}</small></div>
                    <div><span>Locatário(s)</span><strong>{selectedLease.tenants.map(t=>t.name).join(' / ')||'Não informado'}</strong><small>{selectedLease.tenants.length} parte(s)</small></div>
                    <div><span>Prazo</span><strong>{selectedLease.term_months} meses</strong><small>{dateLabel(selectedLease.start_date)} até {dateLabel(selectedLease.end_date)}</small></div>
                    <div><span>Próximo reajuste</span><strong>{dateLabel(selectedLease.next_adjustment_date)}</strong><small>{selectedLease.adjustment_index} · a cada {selectedLease.adjustment_period_months} meses</small></div>
                    <div><span>Contestação de vistoria</span><strong>{selectedLease.inspection_contest_days} dias</strong><small>prazo contratual</small></div>
                    <div><span>Multa rescisória</span><strong>{percent(Number(selectedLease.termination_fine_months))} aluguel(is)</strong><small>conforme condições desta versão</small></div>
                  </div>
                </section>
                <aside className="contract-surface-v2 contract-status-card">
                  <div className="contract-section-heading"><div><span>Fluxo atual</span><h3>{statusLabels[selectedLease.status]}</h3></div></div>
                  <div className="contract-flow-summary"><div><span>Assinatura</span><strong>{signingLabel(selectedLease)}</strong></div><div><span>PDF atual</span><strong>{selectedLease.generated_document_version===selectedLease.current_version?'Gerado':'Pendente'}</strong></div><div><span>Arquivo final</span><strong>{selectedLease.archive_status==='archived'?'Arquivado':'Pendente'}</strong></div></div>
                  <LeaseLifecyclePanel lease={selectedLease} permissions={permissions} onChanged={()=>void load()}/>
                </aside>
                {selectedLease.notes&&<section className="contract-surface-v2 contract-notes-v2"><div className="contract-section-heading"><div><span>Observações</span><h3>Anotações contratuais</h3></div></div><p>{selectedLease.notes}</p></section>}
              </div>}

              {detailTab==='parties'&&<div className="contract-parties-v2">
                <section className="contract-surface-v2"><div className="contract-section-heading"><div><span>Locatários</span><h3>Partes ocupantes</h3></div><Users size={17}/></div><div className="contract-party-list">{selectedLease.tenants.map(tenant=><article key={tenant.person_id}><span className="contract-party-avatar">{tenant.name.split(/\s+/).slice(0,2).map(v=>v[0]?.toUpperCase()).join('')}</span><div><strong>{tenant.name}</strong><small>{tenant.document_number||tenant.email||'Cadastro sem documento'}</small></div></article>)}</div></section>
                <section className="contract-surface-v2"><div className="contract-section-heading"><div><span>Proprietários</span><h3>Titulares do imóvel</h3></div><Users size={17}/></div><div className="contract-party-list">{selectedLease.owners.map((owner,index)=><article key={owner.name+'-'+index}><span className="contract-party-avatar">{owner.name.split(/\s+/).slice(0,2).map(v=>v[0]?.toUpperCase()).join('')}</span><div><strong>{owner.name}</strong><small>{percent(Number(owner.ownership_percent))}% de participação{owner.email?' · '+owner.email:''}</small></div></article>)}</div></section>
                <section className="contract-surface-v2 contract-parties-full"><div className="contract-section-heading"><div><span>Signatários</span><h3>Ordem de assinatura</h3></div><FileSignature size={17}/></div><div className="contract-signer-list-v2">{selectedLease.signers.length?selectedLease.signers.slice().sort((a,b)=>a.sign_order-b.sign_order).map((signer,index)=><article key={index}><b>{signer.sign_order}</b><div><strong>{signer.name}</strong><small>{signerRoleLabels[signer.role]} · {signer.email||'sem e-mail'}</small></div><span>{signer.communication}</span></article>):<div className="contract-empty-soft">Nenhum signatário definido nesta versão.</div>}</div></section>
              </div>}

              {detailTab==='finance'&&(granted.has('finance.view')?<div className="contract-finance-v2">
                <div className="contract-kpis-v2">
                  <article><span>Aluguel base</span><strong>{money(Number(selectedLease.rent_amount))}</strong><small>vencimento dia {selectedLease.due_day}</small></article>
                  <article><span>Próximo reajuste</span><strong>{dateLabel(selectedLease.next_adjustment_date)}</strong><small>{selectedLease.adjustment_index}</small></article>
                  <article><span>Cobranças</span><strong>{contractCharges.length}</strong><small>lançamentos vinculados</small></article>
                  <article><span>Recebidas</span><strong>{contractCharges.filter(row=>row.status==='paid').length}</strong><small>liquidadas</small></article>
                </div>
                <section className="contract-surface-v2"><div className="contract-section-heading"><div><span>Movimentação</span><h3>Cobranças deste contrato</h3></div><CircleDollarSign size={17}/></div>{chargesLoading?<div className="contract-empty-soft">Carregando cobranças...</div>:contractCharges.length?<div className="contract-charge-list">{contractCharges.map(row=><article key={row.id}><div><strong>{row.code}</strong><small>Competência {dateLabel(row.competence)} · venc. {dateLabel(row.due_date)}</small></div><div><strong>{money(Number(row.gross_amount))}</strong><i className={'status-badge '+(row.status==='paid'?'success':row.status==='overdue'?'danger':'neutral')}>{row.status==='paid'?'Pago':row.status==='overdue'?'Em atraso':row.status==='cancelled'?'Cancelado':'Em aberto'}</i></div></article>)}</div>:<div className="contract-empty-soft">Ainda não há cobranças geradas para este contrato.</div>}</section>
              </div>:<div className="contract-empty-soft">Sem permissão para visualizar o financeiro do contrato.</div>)}

              {detailTab==='signature'&&<div className="contract-signature-v2">
                <section className="contract-surface-v2"><div className="contract-section-heading"><div><span>Assinatura eletrônica</span><h3>{signingLabel(selectedLease)}</h3></div><FileSignature size={17}/></div><div className="contract-document-summary-v2"><div><span>Provider</span><strong>{selectedLease.signing_provider}</strong></div><div><span>Envelope</span><strong>{selectedLease.signing_envelope_id||'—'}</strong></div><div><span>Assinado em</span><strong>{selectedLease.signed_at?new Date(selectedLease.signed_at).toLocaleString('pt-BR'):'—'}</strong></div><div><span>Arquivo final</span><strong>{selectedLease.archive_status==='archived'?'Arquivado':'Pendente'}</strong></div></div><SignatureTimeline contractId={selectedLease.id} contractType="lease"/></section>
              </div>}

              {detailTab==='documents'&&<div className="contract-documents-v2">
                <section className="contract-surface-v2 contract-pdf-card"><div className="contract-section-heading"><div><span>Documento principal</span><h3>PDF e integridade</h3></div><FileCheck2 size={17}/></div><div className="contract-document-summary-v2"><div><span>Versão documental</span><strong>{selectedLease.generated_document_version??'—'}</strong></div><div><span>SHA-256 original</span><strong>{selectedLease.generated_document_hash?selectedLease.generated_document_hash.slice(0,18)+'…':'—'}</strong></div><div><span>SHA-256 final</span><strong>{selectedLease.final_document_hash?selectedLease.final_document_hash.slice(0,18)+'…':'—'}</strong></div></div><div className="contract-detail-actions"><button className="button secondary" type="button" onClick={()=>void openPdf(selectedLease)}><FileText size={14}/> Prévia atual</button>{selectedLease.generated_document_reference&&<button className="button secondary" type="button" onClick={()=>void downloadStored(selectedLease,'original')}><Download size={14}/> Original</button>}{selectedLease.archived_document_reference&&<button className="button secondary" type="button" onClick={()=>void downloadStored(selectedLease,'final')}><Download size={14}/> Assinado</button>}</div></section>
                <EntityDocumentsPanel entityType="lease_contract" entityId={selectedLease.id} entityLabel={selectedLease.code} permissions={permissions} compact/>
              </div>}

              {detailTab==='history'&&<div className="contract-history-v2"><section className="contract-surface-v2"><div className="contract-section-heading"><div><span>Versionamento</span><h3>Histórico imutável</h3></div><History size={17}/></div><div className="contract-version-list-v2">{selectedLease.versions.slice().reverse().map(version=><article key={version.version_number}><b>v{version.version_number}</b><div><strong>{version.change_summary||'Versão contratual'}</strong><small>{new Date(version.created_at).toLocaleString('pt-BR')}</small></div></article>)}</div></section></div>}
            </div>
          </>}
        </main>
      </div>}

    {cancelTarget && <div className="portfolio-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !saving) { setCancelTarget(null); setCancelReason('') } }}><div className="panel portfolio-modal lease-cancel-modal" role="dialog" aria-modal="true" aria-labelledby="lease-cancel-title"><div className="portfolio-modal-header"><div><span className="eyebrow">Ação sensível</span><h2 id="lease-cancel-title">Cancelar {cancelTarget.code}</h2><p>O contrato ficará cancelado e o motivo será preservado na trilha de auditoria.</p></div></div><div className="lease-cancel-body"><label className="field"><span>Motivo do cancelamento</span><textarea autoFocus rows={4} value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} placeholder="Descreva objetivamente o motivo..."/></label></div><div className="form-actions lease-cancel-actions"><button className="button secondary" type="button" disabled={saving} onClick={() => { setCancelTarget(null); setCancelReason('') }}>Voltar</button><button className="button ghost-danger" type="button" disabled={saving || cancelReason.trim().length < 3} onClick={() => void workflow(cancelTarget, 'cancel', cancelReason.trim())}>{saving ? 'Cancelando...' : 'Confirmar cancelamento'}</button></div></div></div>}
  </section>
}
