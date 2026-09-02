import {
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
  Property,
} from '../../api/types'
import { SignatureTimeline } from './SignatureTimeline'

const statusLabel: Record<AdministrationContractStatus, string> = {
  draft: 'Rascunho', review: 'Em revisão', approved: 'Aprovado', pending_signature: 'Assinatura', signed: 'Assinado', cancelled: 'Cancelado',
}
const planLabel: Record<string, string> = { essential: 'Essencial', complete: 'Completo', custom: 'Personalizado' }
const payerLabel: Record<string, string> = { tenant: 'Locatário', owner: 'Proprietário', agency: 'Imobiliária' }
const signerRoleLabel: Record<string, string> = { owner: 'Proprietário', agency: 'Imobiliária', witness: 'Testemunha', other: 'Outro' }

const defaultTerms = (defaults?: OperationalDefaults): AdministrationContractTerms => ({
  plan: 'essential', admin_fee_type: 'percent', admin_fee_percent: defaults?.default_admin_fee_percent ?? 10, admin_fee_amount: null,
  intermediation_percent: 100, intermediation_installments: 1, owner_repasse_business_days: defaults?.owner_repasse_business_days ?? 2,
  condo_operational_payer: 'tenant', iptu_operational_payer: 'tenant', publication_requires_owner_approval: false,
  maintenance_limit_amount: null, emergency_limit_amount: null, start_date: null, end_date: null, notes: '', signers: [],
})
const blankSigner = (): ContractSigner => ({ role: 'owner', name: '', email: '', document_number: null, phone: null, sign_order: 1, communication: 'email' })

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

type Props = { permissions: string[] }

export function ContractsPage({ permissions }: Props) {
  const granted = useMemo(() => new Set(permissions), [permissions])
  const canCreate = granted.has('contracts.create')
  const canEdit = granted.has('contracts.edit')
  const canApprove = granted.has('contracts.approve')
  const canSign = granted.has('contracts.send_signature')

  const [contracts, setContracts] = useState<AdministrationContract[]>([])
  const [properties, setProperties] = useState<Property[]>([])
  const [defaults, setDefaults] = useState<OperationalDefaults | undefined>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [filter, setFilter] = useState<'all' | AdministrationContractStatus>('all')
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<AdministrationContract | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [propertyId, setPropertyId] = useState('')
  const [terms, setTerms] = useState<AdministrationContractTerms>(() => defaultTerms())
  const [changeSummary, setChangeSummary] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [loadedContracts, loadedProperties, loadedDefaults] = await Promise.all([
        apiRequest<AdministrationContract[]>('/administration-contracts'),
        apiRequest<Property[]>('/properties'),
        apiRequest<OperationalDefaults>('/settings/operations'),
      ])
      setContracts(loadedContracts); setProperties(loadedProperties); setDefaults(loadedDefaults)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os contratos de administração.')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  const eligibleProperties = useMemo(() => properties.filter((item) => item.owners.length > 0), [properties])
  const filtered = useMemo(() => filter === 'all' ? contracts : contracts.filter((item) => item.status === filter), [contracts, filter])
  const metrics = useMemo(() => ({
    drafts: contracts.filter((item) => item.status === 'draft').length,
    review: contracts.filter((item) => item.status === 'review').length,
    signature: contracts.filter((item) => item.status === 'approved' || item.status === 'pending_signature').length,
    signed: contracts.filter((item) => item.status === 'signed').length,
  }), [contracts])

  function openNew() {
    setEditing(null); setPropertyId(''); setTerms(defaultTerms(defaults)); setChangeSummary(''); setShowForm(true); setError(''); setSuccess('')
  }
  function openEdit(item: AdministrationContract) {
    setEditing(item); setPropertyId(item.property_id)
    setTerms({
      plan: item.plan, admin_fee_type: item.admin_fee_type,
      admin_fee_percent: item.admin_fee_percent == null ? null : Number(item.admin_fee_percent),
      admin_fee_amount: item.admin_fee_amount == null ? null : Number(item.admin_fee_amount),
      intermediation_percent: Number(item.intermediation_percent), intermediation_installments: item.intermediation_installments,
      owner_repasse_business_days: item.owner_repasse_business_days, condo_operational_payer: item.condo_operational_payer,
      iptu_operational_payer: item.iptu_operational_payer, publication_requires_owner_approval: item.publication_requires_owner_approval,
      maintenance_limit_amount: item.maintenance_limit_amount == null ? null : Number(item.maintenance_limit_amount),
      emergency_limit_amount: item.emergency_limit_amount == null ? null : Number(item.emergency_limit_amount),
      start_date: item.start_date, end_date: item.end_date, notes: item.notes ?? '', signers: item.signers.map((signer) => ({ ...signer })),
    })
    setChangeSummary(''); setShowForm(true); setError(''); setSuccess('')
  }
  function updateSigner(index: number, patch: Partial<ContractSigner>) {
    setTerms((current) => ({ ...current, signers: current.signers.map((signer, i) => i === index ? { ...signer, ...patch } : signer) }))
  }

  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(''); setSuccess('')
    try {
      let updated: AdministrationContract
      if (editing) {
        updated = await apiRequest<AdministrationContract>(`/administration-contracts/${editing.id}`, { method: 'PUT', body: JSON.stringify({ ...terms, change_summary: changeSummary }) })
        setSuccess(`${updated.code} ganhou a versão ${updated.current_version}. O PDF e o fluxo de assinatura da versão anterior foram invalidados.`)
      } else {
        const payload: AdministrationContractCreate = { ...terms, property_id: propertyId }
        updated = await apiRequest<AdministrationContract>('/administration-contracts', { method: 'POST', body: JSON.stringify(payload) })
        setSuccess(`${updated.code} criado como rascunho.`)
      }
      setContracts((current) => editing ? current.map((item) => item.id === updated.id ? updated : item) : [updated, ...current])
      setShowForm(false); setEditing(null); setChangeSummary('')
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar o contrato.') }
    finally { setSaving(false) }
  }

  async function workflow(item: AdministrationContract, action: AdministrationContractWorkflowAction) {
    let reason: string | null = null
    if (action === 'cancel') { reason = window.prompt('Informe o motivo do cancelamento:'); if (!reason?.trim()) return }
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
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível executar a ação.') }
    finally { setSaving(false) }
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
        <label className="field"><span>Início</span><input type="date" value={terms.start_date ?? ''} onChange={(e) => setTerms((current) => ({ ...current, start_date: e.target.value || null }))}/></label>
        <label className="field"><span>Condomínio · pagador</span><select value={terms.condo_operational_payer} onChange={(e) => setTerms((current) => ({ ...current, condo_operational_payer: e.target.value as AdministrationContractTerms['condo_operational_payer'] }))}>{Object.entries(payerLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="field"><span>IPTU · pagador</span><select value={terms.iptu_operational_payer} onChange={(e) => setTerms((current) => ({ ...current, iptu_operational_payer: e.target.value as AdministrationContractTerms['iptu_operational_payer'] }))}>{Object.entries(payerLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="field"><span>Fim previsto</span><input type="date" value={terms.end_date ?? ''} onChange={(e) => setTerms((current) => ({ ...current, end_date: e.target.value || null }))}/></label>
        <label className="field"><span>Autonomia manutenção</span><input type="number" min="0" step="0.01" value={terms.maintenance_limit_amount ?? ''} onChange={(e) => setTerms((current) => ({ ...current, maintenance_limit_amount: e.target.value ? Number(e.target.value) : null }))}/></label>
        <label className="field"><span>Limite emergencial</span><input type="number" min="0" step="0.01" value={terms.emergency_limit_amount ?? ''} onChange={(e) => setTerms((current) => ({ ...current, emergency_limit_amount: e.target.value ? Number(e.target.value) : null }))}/></label>
        <label className="field checkbox-field contract-checkbox"><input type="checkbox" checked={terms.publication_requires_owner_approval} onChange={(e) => setTerms((current) => ({ ...current, publication_requires_owner_approval: e.target.checked }))}/><span>Exigir aprovação para publicação</span></label>
        <label className="field field-span-3"><span>Observações / condições especiais</span><textarea rows={3} value={terms.notes ?? ''} onChange={(e) => setTerms((current) => ({ ...current, notes: e.target.value }))}/></label>
        {editing && <label className="field field-span-3"><span>Resumo desta nova versão</span><input required minLength={3} value={changeSummary} onChange={(e) => setChangeSummary(e.target.value)}/></label>}
      </div>

      <div className="contract-snapshot-note"><ShieldCheck size={16}/><span><strong>Regra financeira:</strong> a intermediação substitui a administração nas parcelas iniciais definidas. Com 100% em 1 parcela, o 1º aluguel fica integralmente com a imobiliária e a administração passa a incidir a partir do 2º aluguel.</span></div>

      <div className="contract-signers-editor"><div className="contract-signers-heading"><div><span className="eyebrow">Assinatura</span><h3>Signatários desta versão</h3><p>Os signatários também ficam congelados com a versão.</p></div><button className="button secondary" type="button" onClick={() => setTerms((current) => ({ ...current, signers: [...current.signers, blankSigner()] }))}><UserRoundPlus size={14}/> Adicionar</button></div>
        {terms.signers.length === 0 ? <div className="contract-signers-empty">Sem signatários manuais. Proprietários com e-mail serão sugeridos automaticamente na criação.</div> : terms.signers.map((signer, index) => <div className="contract-signer-row" key={`${index}-${signer.email}`}>
          <label className="field"><span>Papel</span><select value={signer.role} onChange={(e) => updateSigner(index, { role: e.target.value as ContractSigner['role'] })}>{Object.entries(signerRoleLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label className="field"><span>Nome</span><input required value={signer.name} onChange={(e) => updateSigner(index, { name: e.target.value })}/></label>
          <label className="field"><span>E-mail</span><input required type="email" value={signer.email} onChange={(e) => updateSigner(index, { email: e.target.value })}/></label>
          <label className="field"><span>CPF/CNPJ</span><input value={signer.document_number ?? ''} onChange={(e) => updateSigner(index, { document_number: e.target.value || null })}/></label>
          <label className="field"><span>Comunicação</span><select value={signer.communication} onChange={(e) => updateSigner(index, { communication: e.target.value as ContractSigner['communication'] })}><option value="email">E-mail</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option><option value="none">Nenhuma</option></select></label>
          <label className="field signer-order"><span>Ordem</span><input type="number" min="1" max="50" value={signer.sign_order} onChange={(e) => updateSigner(index, { sign_order: Number(e.target.value) })}/></label>
          <button className="signer-remove" type="button" aria-label="Remover" onClick={() => setTerms((current) => ({ ...current, signers: current.signers.filter((_, i) => i !== index) }))}><Trash2 size={15}/></button>
        </div>)}
      </div>
      <div className="contract-snapshot-note"><ShieldCheck size={16}/><span>Nova versão invalida os artefatos de assinatura anteriores e exige novo PDF/hash.</span></div>
      <div className="form-actions"><button className="button secondary" type="button" onClick={() => { setShowForm(false); setEditing(null) }}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : editing ? 'Salvar nova versão' : 'Criar rascunho'}</button></div>
    </form>}

    <div className="portfolio-toolbar panel contract-filter-bar"><div className="portfolio-tabs"><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')} type="button">Todos <span>{contracts.length}</span></button><button className={filter === 'draft' ? 'active' : ''} onClick={() => setFilter('draft')} type="button">Rascunhos <span>{metrics.drafts}</span></button><button className={filter === 'review' ? 'active' : ''} onClick={() => setFilter('review')} type="button">Revisão <span>{metrics.review}</span></button><button className={filter === 'pending_signature' ? 'active' : ''} onClick={() => setFilter('pending_signature')} type="button">Assinatura</button><button className={filter === 'signed' ? 'active' : ''} onClick={() => setFilter('signed')} type="button">Assinados <span>{metrics.signed}</span></button></div></div>

    {loading ? <article className="panel settings-loading">Carregando contratos...</article> : <div className="portfolio-card-list contract-list">{filtered.map((item) => {
      const isExpanded = expanded === item.id
      const documentCurrent = item.generated_document_version === item.current_version && Boolean(item.generated_document_hash)
      return <article className="panel contract-card" key={item.id}>
        <div className="contract-row"><div className="contract-code"><FileSignature size={18}/><span>ADMINISTRAÇÃO</span><strong>{item.code}</strong><small>v{item.current_version}</small></div><div className="contract-property"><strong>Imóvel #{item.property_code}</strong><span>{addressLine(item.property_address)}</span><small>{item.owners.map((owner) => `${owner.name} · ${Number(owner.ownership_percent).toLocaleString('pt-BR')}%`).join(' / ')}</small></div><div className="contract-commercial"><span>Plano / condições comerciais</span><strong>{planLabel[item.plan]} · administração {adminFee(item)}</strong><small>Intermediação {Number(item.intermediation_percent).toLocaleString('pt-BR')}% em {item.intermediation_installments} parcela(s) · administração após a intermediação · Repasse D+{item.owner_repasse_business_days}</small></div><div className="contract-state"><i className={`status-badge ${statusClass(item.status)}`}>{statusLabel[item.status]}</i><span>{signingLabel(item)}</span></div></div>
        <div className="contract-document-strip"><div><FileText size={15}/><span>PDF</span><strong>{documentCurrent ? `v${item.generated_document_version} · ${item.generated_document_hash?.slice(0, 10)}…` : 'não gerado'}</strong></div><div><FileSignature size={15}/><span>Clicksign</span><strong>{item.signing_envelope_id ? `envelope ${item.signing_envelope_id.slice(0, 8)}…` : 'não enviado'}</strong></div><div><FileCheck2 size={15}/><span>Arquivo final</span><strong>{item.archive_status === 'archived' ? `${item.final_document_hash?.slice(0, 10)}…` : item.archive_status.replaceAll('_', ' ')}</strong></div></div>
        <div className="contract-actions"><button className="contract-history-toggle" type="button" onClick={() => setExpanded(isExpanded ? null : item.id)}><History size={14}/> Detalhes {isExpanded ? <ChevronUp size={13}/> : <ChevronDown size={13}/>}</button><div>
          {(item.status === 'draft' || item.status === 'review') && canEdit && <button className="button secondary" type="button" onClick={() => openEdit(item)}>Nova versão</button>}
          {item.status === 'draft' && canEdit && <button className="button primary" disabled={saving} type="button" onClick={() => void workflow(item, 'submit_review')}><Send size={14}/> Revisão</button>}
          {item.status === 'review' && canApprove && <button className="button primary" disabled={saving} type="button" onClick={() => void workflow(item, 'approve')}><CheckCircle2 size={14}/> Aprovar</button>}
          {item.status === 'approved' && canSign && <button className="button primary" disabled={saving} type="button" onClick={() => void workflow(item, 'prepare_signature')}><FileSignature size={14}/> Preparar assinatura</button>}
          {item.status === 'pending_signature' && canSign && !documentCurrent && <button className="button secondary" disabled={saving} type="button" onClick={() => void generateDocument(item)}><FileText size={14}/> Gerar PDF</button>}
          {item.status === 'pending_signature' && canSign && documentCurrent && !['provider_running','provider_signature_progress','provider_closed_pending_archive','signed_archived'].includes(item.signing_status) && <button className="button primary" disabled={saving} type="button" onClick={() => void sendSignature(item)}><Send size={14}/> Enviar à Clicksign</button>}
          {item.status === 'pending_signature' && canSign && ['provider_closed_pending_archive','archive_failed'].includes(item.signing_status) && <button className="button primary" disabled={saving} type="button" onClick={() => void archiveFinal(item)}><FileCheck2 size={14}/> Arquivar PDF final</button>}
          {(item.status === 'review' || item.status === 'approved' || item.status === 'pending_signature') && canEdit && <button className="button secondary" disabled={saving} type="button" onClick={() => void workflow(item, 'return_draft')}><RotateCcw size={14}/> Rascunho</button>}
          {item.status !== 'cancelled' && item.status !== 'signed' && canEdit && <button className="button ghost-danger" disabled={saving} type="button" onClick={() => void workflow(item, 'cancel')}>Cancelar</button>}
          <a className="button secondary" href={`/api/administration-contracts/${item.id}/document/pdf`} target="_blank" rel="noreferrer"><Download size={14}/> Ver PDF</a>
        </div></div>
        {isExpanded && <div className="contract-expanded-detail contract-expanded-three"><div className="contract-signers-summary"><span className="eyebrow">Signatários</span>{item.signers.length ? item.signers.map((signer) => <div key={signer.email}><strong>{signer.name}</strong><span>{signerRoleLabel[signer.role] ?? signer.role} · {signer.email} · ordem {signer.sign_order}</span></div>) : <small>Nenhum signatário.</small>}</div><div className="contract-version-history"><span className="eyebrow">Versões</span>{[...item.versions].reverse().map((version) => <div key={version.version_number}><span>v{version.version_number}</span><strong>{version.change_summary || 'Versão registrada'}</strong><small>{new Date(version.created_at).toLocaleString('pt-BR')}</small></div>)}</div><SignatureTimeline contractId={item.id}/></div>}
      </article>
    })}{filtered.length === 0 && <article className="panel portfolio-empty"><FileSignature size={27}/><strong>Nenhum contrato nesta etapa.</strong></article>}</div>}

    <article className="panel contract-provider-note"><ShieldCheck size={21}/><div><span className="eyebrow">Integridade documental</span><h2>O ERP não confia apenas no status da Clicksign</h2><p>Cada PDF original recebe SHA-256 antes do envio. Mesmo após a Clicksign encerrar a assinatura, o contrato só muda para “Assinado” depois que o PDF final é salvo no storage próprio e recebe um segundo hash.</p></div></article>
  </section>
}
