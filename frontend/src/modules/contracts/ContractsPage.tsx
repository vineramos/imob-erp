import { CheckCircle2, ChevronDown, ChevronUp, FileSignature, History, Plus, RotateCcw, Send, ShieldCheck, Trash2, UserRoundPlus } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type {
  AdministrationContract,
  AdministrationContractCreate,
  AdministrationContractStatus,
  AdministrationContractTerms,
  AdministrationContractWorkflowAction,
  ContractSigner,
  OperationalDefaults,
  Property,
} from '../../api/types'

const statusLabel: Record<AdministrationContractStatus, string> = {
  draft: 'Rascunho', review: 'Em revisão', approved: 'Aprovado', pending_signature: 'Preparando assinatura', signed: 'Assinado', cancelled: 'Cancelado',
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

type Props = { permissions: string[] }

export function ContractsPage({ permissions }: Props) {
  const granted = useMemo(() => new Set(permissions), [permissions])
  const canCreate = granted.has('contracts.create')
  const canEdit = granted.has('contracts.edit')
  const canApprove = granted.has('contracts.approve')
  const canPrepareSignature = granted.has('contracts.send_signature')

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
      setTerms((current) => current.admin_fee_percent === 10 && !showForm ? defaultTerms(loadedDefaults) : current)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os contratos de administração.')
    } finally { setLoading(false) }
  }, [showForm])

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

  function addSigner() { setTerms((current) => ({ ...current, signers: [...current.signers, blankSigner()] })) }
  function removeSigner(index: number) { setTerms((current) => ({ ...current, signers: current.signers.filter((_, i) => i !== index) })) }

  async function save(event: FormEvent) {
    event.preventDefault()
    if (editing && !canEdit) return
    if (!editing && !canCreate) return
    setSaving(true); setError(''); setSuccess('')
    try {
      let updated: AdministrationContract
      if (editing) {
        updated = await apiRequest<AdministrationContract>(`/administration-contracts/${editing.id}`, { method: 'PUT', body: JSON.stringify({ ...terms, change_summary: changeSummary }) })
        setContracts((current) => current.map((item) => item.id === updated.id ? updated : item))
        setSuccess(`${updated.code} ganhou a versão ${updated.current_version}. O histórico anterior foi preservado.`)
      } else {
        const payload: AdministrationContractCreate = { ...terms, property_id: propertyId }
        updated = await apiRequest<AdministrationContract>('/administration-contracts', { method: 'POST', body: JSON.stringify(payload) })
        setContracts((current) => [updated, ...current]); setSuccess(`${updated.code} criado como rascunho.`)
      }
      setShowForm(false); setEditing(null); setChangeSummary('')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar o contrato de administração.')
    } finally { setSaving(false) }
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
        prepare_signature: `${updated.code} preparado para o provider ${updated.signing_provider}.`, return_draft: `${updated.code} retornou para rascunho.`,
        cancel: `${updated.code} cancelado com motivo auditado.`,
      }
      setSuccess(message[action])
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível executar a ação no contrato.') }
    finally { setSaving(false) }
  }

  async function initializeEnvelope(item: AdministrationContract) {
    setSaving(true); setError(''); setSuccess('')
    try {
      const updated = await apiRequest<AdministrationContract>(`/administration-contracts/${item.id}/signature/envelope`, { method: 'POST' })
      setContracts((current) => current.map((contract) => contract.id === updated.id ? updated : contract))
      setSuccess(`${updated.code}: envelope ${updated.signing_provider} criado. O próximo passo será anexar o PDF versionado e os requisitos de assinatura.`)
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível criar o envelope de assinatura.') }
    finally { setSaving(false) }
  }

  return (
    <section className="workspace contracts-workspace">
      <div className="page-heading portfolio-heading">
        <div><span className="eyebrow">Contratos · Administração</span><h1>Contratos de administração</h1><p>Regras próprias por imóvel, signatários versionados e fluxo interno antes da assinatura eletrônica.</p></div>
        {canCreate && <button className="button primary" type="button" onClick={openNew}><Plus size={15}/> Novo contrato</button>}
      </div>

      <div className="dashboard-metrics contract-metrics">
        <article className="panel metric-card"><span>Rascunhos</span><strong>{metrics.drafts}</strong><small>em preparação</small></article>
        <article className="panel metric-card"><span>Em revisão</span><strong>{metrics.review}</strong><small>aguardando validação</small></article>
        <article className="panel metric-card"><span>Aprovação / assinatura</span><strong>{metrics.signature}</strong><small>prontos para avançar</small></article>
        <article className="panel metric-card"><span>Assinados</span><strong>{metrics.signed}</strong><small>vigentes / arquivados</small></article>
      </div>

      {error && <div className="form-alert danger-alert">{error}</div>}
      {success && <div className="form-alert success-alert">{success}</div>}

      {showForm && (
        <form className="panel portfolio-form contract-form" onSubmit={save}>
          <div className="panel-heading panel-heading-row"><div><span className="eyebrow">{editing ? `Nova versão · ${editing.code}` : 'Nova minuta'}</span><h2>{editing ? 'Editar termos do contrato' : 'Contrato de administração'}</h2></div><FileSignature size={20}/></div>
          <div className="form-grid three-columns">
            <label className="field field-span-2"><span>Imóvel</span><select required disabled={Boolean(editing)} value={propertyId} onChange={(e) => setPropertyId(e.target.value)}><option value="">Selecione o imóvel...</option>{eligibleProperties.map((item) => <option key={item.id} value={item.id}>#{item.code} · {addressLine(item.address)} · {item.owners.map((owner) => owner.name).join(' / ')}</option>)}</select></label>
            <label className="field"><span>Plano de administração</span><select value={terms.plan} onChange={(e) => setTerms((current) => ({ ...current, plan: e.target.value as AdministrationContractTerms['plan'] }))}><option value="essential">Essencial</option><option value="complete">Completo</option><option value="custom">Personalizado</option></select></label>
            <label className="field"><span>Tipo da taxa</span><select value={terms.admin_fee_type} onChange={(e) => setTerms((current) => ({ ...current, admin_fee_type: e.target.value as AdministrationContractTerms['admin_fee_type'], admin_fee_percent: e.target.value === 'percent' ? (current.admin_fee_percent ?? defaults?.default_admin_fee_percent ?? 10) : null, admin_fee_amount: e.target.value === 'fixed' ? current.admin_fee_amount : null }))}><option value="percent">Percentual</option><option value="fixed">Valor fixo</option></select></label>
            {terms.admin_fee_type === 'percent' ? <label className="field"><span>Taxa de administração (%)</span><input required min="0" max="100" step="0.01" type="number" value={terms.admin_fee_percent ?? ''} onChange={(e) => setTerms((current) => ({ ...current, admin_fee_percent: e.target.value ? Number(e.target.value) : null }))}/></label> : <label className="field"><span>Taxa fixa mensal</span><input required min="0" step="0.01" type="number" value={terms.admin_fee_amount ?? ''} onChange={(e) => setTerms((current) => ({ ...current, admin_fee_amount: e.target.value ? Number(e.target.value) : null }))}/></label>}
            <label className="field"><span>Repasse ao proprietário (D+ dias úteis)</span><input min="0" max="30" type="number" value={terms.owner_repasse_business_days} onChange={(e) => setTerms((current) => ({ ...current, owner_repasse_business_days: Number(e.target.value) }))}/></label>
            <label className="field"><span>Intermediação sobre 1º aluguel (%)</span><input min="0" max="500" step="0.01" type="number" value={terms.intermediation_percent} onChange={(e) => setTerms((current) => ({ ...current, intermediation_percent: Number(e.target.value) }))}/></label>
            <label className="field"><span>Parcelas da intermediação</span><input min="1" max="24" type="number" value={terms.intermediation_installments} onChange={(e) => setTerms((current) => ({ ...current, intermediation_installments: Number(e.target.value) }))}/></label>
            <label className="field"><span>Início da administração</span><input type="date" value={terms.start_date ?? ''} onChange={(e) => setTerms((current) => ({ ...current, start_date: e.target.value || null }))}/></label>
            <label className="field"><span>Condomínio · pagador operacional</span><select value={terms.condo_operational_payer} onChange={(e) => setTerms((current) => ({ ...current, condo_operational_payer: e.target.value as AdministrationContractTerms['condo_operational_payer'] }))}>{Object.entries(payerLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label className="field"><span>IPTU · pagador operacional</span><select value={terms.iptu_operational_payer} onChange={(e) => setTerms((current) => ({ ...current, iptu_operational_payer: e.target.value as AdministrationContractTerms['iptu_operational_payer'] }))}>{Object.entries(payerLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label className="field"><span>Fim previsto (opcional)</span><input type="date" value={terms.end_date ?? ''} onChange={(e) => setTerms((current) => ({ ...current, end_date: e.target.value || null }))}/></label>
            <label className="field"><span>Autonomia manutenção até</span><input min="0" step="0.01" type="number" value={terms.maintenance_limit_amount ?? ''} onChange={(e) => setTerms((current) => ({ ...current, maintenance_limit_amount: e.target.value ? Number(e.target.value) : null }))}/></label>
            <label className="field"><span>Limite emergencial até</span><input min="0" step="0.01" type="number" value={terms.emergency_limit_amount ?? ''} onChange={(e) => setTerms((current) => ({ ...current, emergency_limit_amount: e.target.value ? Number(e.target.value) : null }))}/></label>
            <label className="field checkbox-field contract-checkbox"><input type="checkbox" checked={terms.publication_requires_owner_approval} onChange={(e) => setTerms((current) => ({ ...current, publication_requires_owner_approval: e.target.checked }))}/><span>Exigir aprovação do proprietário para publicação</span></label>
            <label className="field field-span-3"><span>Observações e condições especiais</span><textarea rows={3} value={terms.notes ?? ''} onChange={(e) => setTerms((current) => ({ ...current, notes: e.target.value }))}/></label>
            {editing && <label className="field field-span-3"><span>Motivo / resumo desta nova versão</span><input required minLength={3} placeholder="Ex.: Ajuste da taxa de administração para 12% conforme negociação." value={changeSummary} onChange={(e) => setChangeSummary(e.target.value)}/></label>}
          </div>

          <div className="contract-signers-editor">
            <div className="contract-signers-heading"><div><span className="eyebrow">Assinatura</span><h3>Signatários desta versão</h3><p>Os signatários também ficam congelados junto com a versão do contrato.</p></div><button className="button secondary" type="button" onClick={addSigner}><UserRoundPlus size={14}/> Adicionar signatário</button></div>
            {terms.signers.length === 0 ? <div className="contract-signers-empty">Se nenhum signatário for informado, o ERP tentará sugerir proprietários que possuam e-mail cadastrado. Antes de preparar a assinatura, ao menos um signatário será obrigatório.</div> : terms.signers.map((signer, index) => (
              <div className="contract-signer-row" key={`${index}-${signer.email}`}>
                <label className="field"><span>Papel</span><select value={signer.role} onChange={(e) => updateSigner(index, { role: e.target.value as ContractSigner['role'] })}>{Object.entries(signerRoleLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
                <label className="field"><span>Nome</span><input required value={signer.name} onChange={(e) => updateSigner(index, { name: e.target.value })}/></label>
                <label className="field"><span>E-mail</span><input required type="email" value={signer.email} onChange={(e) => updateSigner(index, { email: e.target.value })}/></label>
                <label className="field"><span>CPF/CNPJ</span><input value={signer.document_number ?? ''} onChange={(e) => updateSigner(index, { document_number: e.target.value || null })}/></label>
                <label className="field"><span>Comunicação</span><select value={signer.communication} onChange={(e) => updateSigner(index, { communication: e.target.value as ContractSigner['communication'] })}><option value="email">E-mail</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option><option value="none">Sem comunicação</option></select></label>
                <label className="field signer-order"><span>Ordem</span><input min="1" max="50" type="number" value={signer.sign_order} onChange={(e) => updateSigner(index, { sign_order: Number(e.target.value) })}/></label>
                <button className="signer-remove" aria-label="Remover signatário" type="button" onClick={() => removeSigner(index)}><Trash2 size={15}/></button>
              </div>
            ))}
          </div>

          <div className="contract-snapshot-note"><ShieldCheck size={16}/><span>Ao salvar, proprietários, regras e signatários desta versão ficam congelados no histórico. Alterar Configurações depois não muda este contrato.</span></div>
          <div className="form-actions"><button className="button secondary" type="button" onClick={() => { setShowForm(false); setEditing(null) }}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : editing ? 'Salvar nova versão' : 'Criar rascunho'}</button></div>
        </form>
      )}

      <div className="portfolio-toolbar panel contract-filter-bar"><div className="portfolio-tabs">
        <button className={filter === 'all' ? 'active' : ''} type="button" onClick={() => setFilter('all')}>Todos <span>{contracts.length}</span></button>
        <button className={filter === 'draft' ? 'active' : ''} type="button" onClick={() => setFilter('draft')}>Rascunhos <span>{metrics.drafts}</span></button>
        <button className={filter === 'review' ? 'active' : ''} type="button" onClick={() => setFilter('review')}>Revisão <span>{metrics.review}</span></button>
        <button className={filter === 'pending_signature' ? 'active' : ''} type="button" onClick={() => setFilter('pending_signature')}>Assinatura <span>{contracts.filter((item) => item.status === 'pending_signature').length}</span></button>
        <button className={filter === 'signed' ? 'active' : ''} type="button" onClick={() => setFilter('signed')}>Assinados <span>{metrics.signed}</span></button>
      </div></div>

      {loading ? <article className="panel settings-loading">Carregando contratos...</article> : (
        <div className="portfolio-card-list contract-list">
          {filtered.map((item) => {
            const isExpanded = expanded === item.id
            return <article className="panel contract-card" key={item.id}>
              <div className="contract-row">
                <div className="contract-code"><FileSignature size={18}/><span>ADMINISTRAÇÃO</span><strong>{item.code}</strong><small>v{item.current_version}</small></div>
                <div className="contract-property"><strong>Imóvel #{item.property_code}</strong><span>{addressLine(item.property_address)}</span><small>{item.owners.map((owner) => `${owner.name} · ${Number(owner.ownership_percent).toLocaleString('pt-BR')}%`).join(' / ')}</small></div>
                <div className="contract-commercial"><span>Plano / administração</span><strong>{planLabel[item.plan]} · {adminFee(item)}</strong><small>Intermediação {Number(item.intermediation_percent).toLocaleString('pt-BR')}% em {item.intermediation_installments}x · Repasse D+{item.owner_repasse_business_days}</small></div>
                <div className="contract-state"><i className={`status-badge ${statusClass(item.status)}`}>{statusLabel[item.status]}</i><span>{item.signers.length} signatário(s) · {item.signing_status.replaceAll('_', ' ')}</span></div>
              </div>

              <div className="contract-actions">
                <button className="contract-history-toggle" type="button" onClick={() => setExpanded(isExpanded ? null : item.id)}><History size={14}/> Histórico ({item.versions.length}) {isExpanded ? <ChevronUp size={13}/> : <ChevronDown size={13}/>}</button>
                <div>
                  {(item.status === 'draft' || item.status === 'review') && canEdit && <button className="button secondary" type="button" onClick={() => openEdit(item)}>Nova versão</button>}
                  {item.status === 'draft' && canEdit && <button className="button primary" disabled={saving} type="button" onClick={() => void workflow(item, 'submit_review')}><Send size={14}/> Enviar à revisão</button>}
                  {item.status === 'review' && canApprove && <button className="button primary" disabled={saving} type="button" onClick={() => void workflow(item, 'approve')}><CheckCircle2 size={14}/> Aprovar</button>}
                  {item.status === 'approved' && canPrepareSignature && <button className="button primary" disabled={saving} type="button" onClick={() => void workflow(item, 'prepare_signature')}><FileSignature size={14}/> Preparar assinatura</button>}
                  {item.status === 'pending_signature' && item.signing_status === 'ready_for_provider' && canPrepareSignature && <button className="button primary" disabled={saving} type="button" onClick={() => void initializeEnvelope(item)}><FileSignature size={14}/> Criar envelope Clicksign</button>}
                  {(item.status === 'review' || item.status === 'approved' || item.status === 'pending_signature') && canEdit && <button className="button secondary" disabled={saving} type="button" onClick={() => void workflow(item, 'return_draft')}><RotateCcw size={14}/> Voltar ao rascunho</button>}
                  {!['signed','cancelled'].includes(item.status) && canEdit && <button className="button ghost-danger" disabled={saving} type="button" onClick={() => void workflow(item, 'cancel')}>Cancelar</button>}
                </div>
              </div>

              {isExpanded && <div className="contract-expanded-detail">
                <div className="contract-signers-summary"><span className="eyebrow">Signatários atuais</span>{item.signers.length ? item.signers.map((signer) => <div key={signer.email}><strong>{signer.name}</strong><span>{signerRoleLabel[signer.role] ?? signer.role} · {signer.email} · ordem {signer.sign_order}</span></div>) : <small>Nenhum signatário registrado nesta versão.</small>}</div>
                <div className="contract-version-history">{[...item.versions].reverse().map((version) => <div key={version.version_number}><span>v{version.version_number}</span><strong>{version.change_summary || 'Versão registrada'}</strong><small>{new Date(version.created_at).toLocaleString('pt-BR')}</small></div>)}</div>
              </div>}
            </article>
          })}
          {filtered.length === 0 && <article className="panel portfolio-empty"><FileSignature size={27}/><strong>Nenhum contrato nesta etapa.</strong><span>Os contratos de administração aparecerão aqui conforme o fluxo avançar.</span></article>}
        </div>
      )}

      <article className="panel contract-provider-note"><FileSignature size={21}/><div><span className="eyebrow">Clicksign API 3.0</span><h2>Provider real preparado com proteção por etapas</h2><p>O ERP agora testa autenticação, versiona signatários, pode inicializar o envelope e recebe webhooks com HMAC. Documento, requisitos e ativação serão enviados apenas quando o PDF final versionado estiver disponível. Mesmo um evento de conclusão não marca o contrato como assinado antes do arquivamento final.</p></div></article>
    </section>
  )
}
