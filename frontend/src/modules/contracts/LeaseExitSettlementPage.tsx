import { AlertTriangle, CheckCircle2, ClipboardCheck, KeyRound, Plus, RefreshCw, ShieldCheck, WalletCards, X } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './lease-exit-settlement.css'

type Difference = {
  environment_key: string
  environment_name: string
  item_key: string
  item_label: string
  initial_condition: string
  final_condition: string
  severity_delta: number
  initial_notes: string | null
  final_notes: string | null
}

type Adjustment = {
  id: string
  code: string
  kind: string
  description: string
  beneficiary: string
  amount: number
  due_date: string
  status: string
  financial_title_id: string | null
  financial_title_code: string | null
  financial_status: string | null
  settled_amount: number
  remaining_amount: number
  source_context: Record<string, unknown>
  notes: string | null
  cancelled_at: string | null
  created_at: string
}

type Workspace = {
  lifecycle_case_id: string
  lifecycle_code: string
  lease_contract_id: string
  lease_code: string
  lifecycle_status: string
  effective_date: string | null
  initiated_by: string | null
  property_id: string
  property_code: string
  property_address: Record<string, string>
  tenants: Array<{ name?: string; document_number?: string | null }>
  exit_inspection_id: string | null
  exit_inspection_code: string | null
  exit_inspection_status: string | null
  inspection_ready_for_adjustments: boolean
  inspection_differences: Difference[]
  keys_returned_at: string | null
  returned_keys: Array<{ label?: string; quantity?: number; notes?: string | null }>
  meter_readings: Record<string, unknown>
  adjustments: Adjustment[]
  adjustment_open_amount: number
  financial_blocking_count: number
  financial_blocking_amount: number
  financial_followup_count: number
  financial_followup_amount: number
  can_close: boolean
  closed_at: string | null
}

type Props = { permissions: string[] }
type AdjustmentKind = 'damage' | 'cleaning' | 'water' | 'energy' | 'gas' | 'condo_adjustment' | 'iptu_adjustment' | 'key_replacement' | 'other'
type Beneficiary = 'owner' | 'agency' | 'third_party'
type AdjustmentForm = {
  kind: AdjustmentKind
  description: string
  beneficiary: Beneficiary
  amount: string
  due_date: string
  notes: string
  source_context: Record<string, unknown>
}

const conditionLabels: Record<string, string> = {
  excellent: 'Excelente', good: 'Bom', regular: 'Regular', poor: 'Ruim', damaged: 'Danificado', not_applicable: 'Não avaliado',
}
const kindLabels: Record<AdjustmentKind, string> = {
  damage: 'Dano / reparo', cleaning: 'Limpeza', water: 'Água', energy: 'Energia', gas: 'Gás',
  condo_adjustment: 'Ajuste de condomínio', iptu_adjustment: 'Ajuste de IPTU', key_replacement: 'Reposição de chaves', other: 'Outro',
}
const beneficiaryLabels: Record<Beneficiary, string> = { owner: 'Proprietário', agency: 'Imobiliária', third_party: 'Terceiro' }
const statusLabels: Record<string, string> = {
  termination_requested: 'Desocupação iniciada', exit_inspection_pending: 'Vistoria de saída', key_return_pending: 'Devolução de chaves',
  financial_clearance_pending: 'Acerto financeiro', closed: 'Encerrada', cancelled: 'Cancelada',
}

function money(value: number | string | null | undefined) {
  return Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}
function dateLabel(value: string | null | undefined) {
  return value ? new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString('pt-BR') : '—'
}
function addressLine(address: Record<string, string>) {
  return [address.street, address.number, address.complement, address.neighborhood, address.city, address.state].filter(Boolean).join(', ') || 'Endereço não informado'
}
function todayIso() { return new Date().toISOString().slice(0, 10) }
function newForm(dueDate?: string | null): AdjustmentForm {
  return { kind: 'damage', description: '', beneficiary: 'owner', amount: '', due_date: dueDate || todayIso(), notes: '', source_context: {} }
}

export function LeaseExitSettlementPage({ permissions }: Props) {
  const canEdit = permissions.includes('contracts.edit')
  const [items, setItems] = useState<Workspace[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [showClosed, setShowClosed] = useState(false)
  const [modalLeaseId, setModalLeaseId] = useState<string | null>(null)
  const [form, setForm] = useState<AdjustmentForm>(newForm())

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setItems(await apiRequest<Workspace[]>('/lease-lifecycle/terminations')) }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os encerramentos de locação.') }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  const visible = useMemo(() => items.filter(item => showClosed || !['closed', 'cancelled'].includes(item.lifecycle_status)), [items, showClosed])
  const active = items.filter(item => !['closed', 'cancelled'].includes(item.lifecycle_status))
  const blocking = active.filter(item => item.financial_blocking_count > 0)
  const ready = active.filter(item => item.can_close)

  function openAdjustment(workspace: Workspace, difference?: Difference) {
    setModalLeaseId(workspace.lease_contract_id)
    setError(''); setSuccess('')
    setForm({
      ...newForm(workspace.effective_date || todayIso()),
      kind: difference ? 'damage' : 'other',
      description: difference ? `${difference.item_label} · ${difference.environment_name}` : '',
      source_context: difference ? {
        source: 'inspection_difference',
        environment_key: difference.environment_key,
        environment_name: difference.environment_name,
        item_key: difference.item_key,
        item_label: difference.item_label,
        initial_condition: difference.initial_condition,
        final_condition: difference.final_condition,
        severity_delta: difference.severity_delta,
      } : { source: 'manual_exit_adjustment' },
    })
  }

  async function submitAdjustment(event: FormEvent) {
    event.preventDefault()
    if (!modalLeaseId) return
    setSaving(true); setError(''); setSuccess('')
    try {
      const updated = await apiRequest<Workspace>(`/lease-contracts/${modalLeaseId}/lifecycle/exit-adjustments`, {
        method: 'POST',
        body: JSON.stringify({ ...form, amount: Number(form.amount), notes: form.notes || null }),
      })
      setItems(current => current.map(item => item.lease_contract_id === updated.lease_contract_id ? updated : item))
      setModalLeaseId(null)
      setSuccess('Ajuste registrado no Financeiro. A locação ficará bloqueada até a resolução deste recebível.')
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível registrar o ajuste final.') }
    finally { setSaving(false) }
  }

  async function cancelAdjustment(workspace: Workspace, adjustment: Adjustment) {
    if (!window.confirm(`Cancelar ${adjustment.code} e o título financeiro vinculado?`)) return
    setSaving(true); setError(''); setSuccess('')
    try {
      const updated = await apiRequest<Workspace>(`/lease-contracts/${workspace.lease_contract_id}/lifecycle/exit-adjustments/${adjustment.id}/cancel`, { method: 'POST' })
      setItems(current => current.map(item => item.lease_contract_id === updated.lease_contract_id ? updated : item))
      setSuccess(`${adjustment.code} cancelado. Nenhum valor liquidado foi apagado.`)
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível cancelar o ajuste.') }
    finally { setSaving(false) }
  }

  return <section className="workspace lease-exit-workspace">
    <div className="page-heading lease-exit-heading">
      <div><span className="eyebrow">Contratos · Encerramentos</span><h1>Acerto final da locação</h1><p>Compare a vistoria de entrada com a saída, registre somente os ajustes aprovados por uma pessoa e acompanhe o que ainda bloqueia a devolução definitiva do imóvel.</p></div>
      <button className="button secondary" type="button" onClick={() => void load()}><RefreshCw size={14}/> Atualizar</button>
    </div>

    {error && <div className="form-alert danger-alert">{error}</div>}
    {success && <div className="form-alert success-alert">{success}</div>}

    <div className="lease-exit-metrics">
      <article className="panel"><KeyRound size={18}/><span>Desocupações ativas</span><strong>{active.length}</strong></article>
      <article className="panel"><WalletCards size={18}/><span>Com bloqueio financeiro</span><strong>{blocking.length}</strong><small>{money(blocking.reduce((sum, item) => sum + Number(item.financial_blocking_amount || 0), 0))}</small></article>
      <article className="panel"><CheckCircle2 size={18}/><span>Prontas para encerrar</span><strong>{ready.length}</strong></article>
    </div>

    <div className="lease-exit-toolbar panel">
      <div><ShieldCheck size={16}/><span><strong>Controle humano obrigatório.</strong> Uma piora na vistoria nunca gera cobrança sozinha; ela apenas sugere revisão.</span></div>
      <label><input type="checkbox" checked={showClosed} onChange={event => setShowClosed(event.target.checked)}/> Mostrar encerradas/canceladas</label>
    </div>

    {loading ? <article className="panel lease-exit-empty">Carregando encerramentos...</article> : <div className="lease-exit-list">
      {visible.map(workspace => {
        const isClosed = ['closed', 'cancelled'].includes(workspace.lifecycle_status)
        const tenantNames = workspace.tenants.map(item => item.name).filter(Boolean).join(' / ') || 'Locatário'
        return <article className={`panel lease-exit-card ${isClosed ? 'is-closed' : ''}`} key={workspace.lifecycle_case_id}>
          <div className="lease-exit-card-head">
            <div><span className="eyebrow">{workspace.lifecycle_code} · {workspace.lease_code}</span><h2>{workspace.property_code} · {tenantNames}</h2><p>{addressLine(workspace.property_address)}</p></div>
            <div className="lease-exit-card-status"><span className={`status-badge ${workspace.can_close ? 'success' : workspace.financial_blocking_count ? 'warning' : 'neutral'}`}>{statusLabels[workspace.lifecycle_status] || workspace.lifecycle_status}</span><small>Saída prevista: {dateLabel(workspace.effective_date)}</small></div>
          </div>

          <div className="lease-exit-progress">
            <div className={workspace.exit_inspection_id ? 'done' : ''}><ClipboardCheck size={14}/><span>Vistoria</span><strong>{workspace.exit_inspection_code || 'Pendente'}</strong></div>
            <div className={workspace.keys_returned_at ? 'done' : ''}><KeyRound size={14}/><span>Chaves</span><strong>{workspace.keys_returned_at ? new Date(workspace.keys_returned_at).toLocaleDateString('pt-BR') : 'Pendentes'}</strong></div>
            <div className={workspace.financial_blocking_count === 0 ? 'done' : 'warning'}><WalletCards size={14}/><span>Recebíveis bloqueadores</span><strong>{workspace.financial_blocking_count} · {money(workspace.financial_blocking_amount)}</strong></div>
            <div className={workspace.can_close ? 'done' : ''}><CheckCircle2 size={14}/><span>Encerramento</span><strong>{workspace.can_close ? 'Liberado' : workspace.closed_at ? 'Concluído' : 'Aguardando'}</strong></div>
          </div>

          {workspace.inspection_differences.length > 0 && <section className="lease-exit-section">
            <div className="lease-exit-section-title"><AlertTriangle size={16}/><div><strong>Divergências Entrada × Saída</strong><span>{workspace.inspection_differences.length} item(ns) pioraram em relação ao laudo inicial.</span></div></div>
            <div className="lease-exit-differences">{workspace.inspection_differences.map(diff => <div className="lease-exit-difference" key={`${diff.environment_key}-${diff.item_key}`}>
              <div><strong>{diff.environment_name} · {diff.item_label}</strong><span>{conditionLabels[diff.initial_condition] || diff.initial_condition} → <b>{conditionLabels[diff.final_condition] || diff.final_condition}</b></span>{diff.final_notes && <small>{diff.final_notes}</small>}</div>
              <span className="lease-exit-severity">nível {diff.severity_delta}</span>
              {canEdit && workspace.inspection_ready_for_adjustments && !isClosed && <button className="button secondary compact" type="button" onClick={() => openAdjustment(workspace, diff)}><Plus size={13}/> Registrar ajuste</button>}
            </div>)}</div>
          </section>}

          {workspace.exit_inspection_id && workspace.inspection_differences.length === 0 && <div className="lease-exit-no-difference"><CheckCircle2 size={15}/><span>Nenhuma deterioração objetiva foi identificada pela comparação dos itens avaliados.</span></div>}

          <section className="lease-exit-section">
            <div className="lease-exit-section-title"><WalletCards size={16}/><div><strong>Ajustes do acerto final</strong><span>Cada ajuste cria um título financeiro rastreável. Cancelamento só é permitido antes de qualquer liquidação.</span></div>{canEdit && workspace.inspection_ready_for_adjustments && !isClosed && <button className="button primary compact" type="button" onClick={() => openAdjustment(workspace)}><Plus size={13}/> Novo ajuste</button>}</div>
            {workspace.adjustments.length ? <div className="lease-exit-adjustments">{workspace.adjustments.map(adjustment => <div className={`lease-exit-adjustment ${adjustment.status === 'cancelled' ? 'cancelled' : ''}`} key={adjustment.id}>
              <span><strong>{adjustment.code}</strong><small>{kindLabels[adjustment.kind as AdjustmentKind] || adjustment.kind} · {beneficiaryLabels[adjustment.beneficiary as Beneficiary] || adjustment.beneficiary}</small></span>
              <span className="lease-exit-adjustment-description">{adjustment.description}<small>{adjustment.financial_title_code ? `${adjustment.financial_title_code} · ${adjustment.financial_status}` : 'Título pendente'}</small></span>
              <strong>{money(adjustment.amount)}</strong>
              <span className={`status-badge ${adjustment.status === 'cancelled' ? 'neutral' : adjustment.remaining_amount > 0 ? 'warning' : 'success'}`}>{adjustment.status === 'cancelled' ? 'Cancelado' : adjustment.remaining_amount > 0 ? `Em aberto ${money(adjustment.remaining_amount)}` : 'Resolvido'}</span>
              {canEdit && adjustment.status !== 'cancelled' && adjustment.settled_amount === 0 && !isClosed && <button className="button ghost-danger compact" disabled={saving} type="button" onClick={() => void cancelAdjustment(workspace, adjustment)}>Cancelar</button>}
            </div>)}</div> : <div className="lease-exit-empty-inline">Nenhum ajuste financeiro registrado. Divergências da vistoria não são cobradas automaticamente.</div>}
          </section>

          {workspace.keys_returned_at && Object.keys(workspace.meter_readings || {}).length > 0 && <section className="lease-exit-section compact-section"><div className="lease-exit-section-title"><KeyRound size={16}/><div><strong>Leituras na devolução</strong><span>{Object.entries(workspace.meter_readings).map(([key, value]) => `${key}: ${String(value)}`).join(' · ')}</span></div></div></section>}

          <div className={`lease-exit-final-state ${workspace.can_close ? 'ready' : ''}`}>
            {workspace.lifecycle_status === 'closed' ? <><CheckCircle2 size={17}/><span>Locação encerrada em {workspace.closed_at ? new Date(workspace.closed_at).toLocaleString('pt-BR') : '—'}.</span></> : workspace.can_close ? <><CheckCircle2 size={17}/><span><strong>Acerto liberado.</strong> Vistoria, chaves e recebíveis estão resolvidos. Conclua o encerramento na aba “Ciclo da locação” do contrato.</span></> : <><ShieldCheck size={17}/><span>O contrato continua aberto até que todos os bloqueios obrigatórios sejam resolvidos.</span></>}
          </div>
        </article>
      })}
      {visible.length === 0 && <article className="panel lease-exit-empty"><CheckCircle2 size={24}/><strong>Nenhuma desocupação neste filtro.</strong><span>Quando um encerramento for iniciado em uma locação, ele aparecerá aqui automaticamente.</span></article>}
    </div>}

    {modalLeaseId && <div className="portfolio-modal-backdrop" onMouseDown={event => { if (event.currentTarget === event.target && !saving) setModalLeaseId(null) }}><form className="panel portfolio-modal lease-exit-modal" onSubmit={submitAdjustment}>
      <div className="portfolio-modal-header"><div><span className="eyebrow">Acerto final</span><h2>Registrar ajuste financeiro</h2><p>O valor só entra no Financeiro após esta confirmação humana.</p></div><button className="portfolio-modal-close" type="button" aria-label="Fechar" disabled={saving} onClick={() => setModalLeaseId(null)}><X size={17}/></button></div>
      <div className="form-grid two-columns">
        <label className="field"><span>Tipo</span><select value={form.kind} onChange={event => setForm(current => ({ ...current, kind: event.target.value as AdjustmentKind }))}>{Object.entries(kindLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label className="field"><span>Beneficiário</span><select value={form.beneficiary} onChange={event => setForm(current => ({ ...current, beneficiary: event.target.value as Beneficiary }))}>{Object.entries(beneficiaryLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label className="field field-span-2"><span>Descrição</span><input required minLength={3} maxLength={240} value={form.description} onChange={event => setForm(current => ({ ...current, description: event.target.value }))}/></label>
        <label className="field"><span>Valor</span><input required type="number" min="0.01" step="0.01" value={form.amount} onChange={event => setForm(current => ({ ...current, amount: event.target.value }))}/></label>
        <label className="field"><span>Vencimento</span><input required type="date" value={form.due_date} onChange={event => setForm(current => ({ ...current, due_date: event.target.value }))}/></label>
        <label className="field field-span-2"><span>Observações</span><textarea rows={3} maxLength={2000} value={form.notes} onChange={event => setForm(current => ({ ...current, notes: event.target.value }))}/></label>
      </div>
      <div className="lease-exit-human-note"><ShieldCheck size={15}/><span>Ao salvar, o sistema cria um recebível vinculado à locação. O fechamento fica bloqueado até esse título ser liquidado ou o ajuste ser cancelado.</span></div>
      <div className="canonical-modal-actions"><button className="button secondary" type="button" disabled={saving} onClick={() => setModalLeaseId(null)}>Cancelar</button><button className="button primary" type="submit" disabled={saving}>{saving ? 'Registrando...' : 'Registrar no Financeiro'}</button></div>
    </form></div>}
  </section>
}
