import { CalendarClock, CheckCircle2, ClipboardCheck, FileSignature, KeyRound, RefreshCw, RotateCcw, WalletCards } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './lease-lifecycle.css'

type LeaseSummary = {
  id: string
  code: string
  status: string
  rent_amount: number
  adjustment_index: string
  adjustment_period_months: number
  end_date: string
}

type ClearanceItem = {
  id: string
  code: string
  source_type: string
  direction: 'receivable' | 'payable'
  description: string
  amount: number
  remaining_amount: number
  status: string
  blocker: boolean
}

type Lifecycle = {
  id: string
  code: string
  process_type: 'renewal' | 'termination'
  status: string
  initiated_by: string | null
  requested_at: string
  effective_date: string | null
  reason: string | null
  termination_fine_amount: number
  fine_status: 'not_applicable' | 'pending' | 'waived' | 'registered'
  fine_title_id: string | null
  fine_notes: string | null
  renewal_terms: Record<string, unknown>
  renewed_lease_contract_id: string | null
  renewed_lease_code: string | null
  renewed_lease_status: string | null
  exit_inspection_id: string | null
  exit_inspection_code: string | null
  exit_inspection_status: string | null
  keys_returned_at: string | null
  keys_received_by: string | null
  returned_keys: Array<{ label: string; quantity: number; notes?: string | null }>
  meter_readings: Record<string, unknown>
  key_return_notes: string | null
  property_disposition: 'available' | 'inactive' | null
  financial_clearance: {
    blocking_count: number
    blocking_amount: number
    followup_count: number
    followup_amount: number
    items: ClearanceItem[]
  }
  can_close: boolean
  closed_at: string | null
}

type Props = {
  lease: LeaseSummary
  permissions: string[]
  onChanged?: () => void
}

const initiatedByLabels: Record<string, string> = {
  tenant: 'Locatário', owner: 'Proprietário', mutual: 'Acordo entre as partes', term_end: 'Fim do prazo', breach: 'Descumprimento', other: 'Outro',
}
const lifecycleStatusLabels: Record<string, string> = {
  renewal_proposed: 'Renovação proposta', renewal_prepared: 'Nova minuta criada', renewed: 'Renovada',
  termination_requested: 'Desocupação iniciada', exit_inspection_pending: 'Vistoria de saída', key_return_pending: 'Devolução de chaves',
  financial_clearance_pending: 'Acerto financeiro', closed: 'Encerrada', cancelled: 'Cancelada',
}
const fineLabels: Record<Lifecycle['fine_status'], string> = {
  not_applicable: 'Sem multa', pending: 'Decisão pendente', waived: 'Dispensada', registered: 'Registrada no Financeiro',
}

function money(value: number) {
  return Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}
function nextDay(value: string) {
  const date = new Date(`${value}T12:00:00`)
  date.setDate(date.getDate() + 1)
  return date.toISOString().slice(0, 10)
}
function localDateTimeNow() {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}
function iso(value: string) { return value ? new Date(value).toISOString() : null }

export function LeaseLifecyclePanel({ lease, permissions, onChanged }: Props) {
  const canManage = permissions.includes('contracts.edit')
  const [item, setItem] = useState<Lifecycle | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [modal, setModal] = useState<'renewal' | 'termination' | null>(null)
  const [renewal, setRenewal] = useState({ start_date: nextDay(lease.end_date), term_months: 30, rent_amount: Number(lease.rent_amount), adjustment_index: lease.adjustment_index, adjustment_period_months: lease.adjustment_period_months || 12, notes: '' })
  const [termination, setTermination] = useState({ effective_date: lease.end_date, initiated_by: 'term_end', reason: '' })
  const [inspection, setInspection] = useState({ scheduled_at: '', inspector_name: '', notes: '' })
  const [keyReturn, setKeyReturn] = useState({ returned_at: localDateTimeNow(), received_by: '', received_document: '', key_label: 'Chaves do imóvel', quantity: 1, notes: '' })
  const [fineBeneficiary, setFineBeneficiary] = useState<'owner' | 'agency'>('owner')
  const [fineAmount, setFineAmount] = useState<number | null>(null)
  const [disposition, setDisposition] = useState<'available' | 'inactive'>('available')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await apiRequest<Lifecycle | null>(`/lease-contracts/${lease.id}/lifecycle`)
      setItem(result)
      if (result?.termination_fine_amount != null) setFineAmount(Number(result.termination_fine_amount))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar o ciclo da locação.')
    } finally { setLoading(false) }
  }, [lease.id])
  useEffect(() => { void load() }, [load])

  const step = useMemo(() => {
    if (!item) return 0
    if (item.status === 'closed' || item.status === 'renewed') return 5
    if (item.keys_returned_at) return 4
    if (item.exit_inspection_id) return item.exit_inspection_status === 'ready' || item.exit_inspection_status === 'finalized' ? 3 : 2
    if (item.process_type === 'termination') return 1
    return 1
  }, [item])

  async function mutate(path: string, body?: unknown, message?: string) {
    setSaving(true); setError(''); setSuccess('')
    try {
      const result = await apiRequest<Lifecycle>(`/lease-contracts/${lease.id}/lifecycle${path}`, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
      setItem(result)
      if (result.termination_fine_amount != null) setFineAmount(Number(result.termination_fine_amount))
      if (message) setSuccess(message)
      onChanged?.()
      return result
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível atualizar o ciclo da locação.')
      return null
    } finally { setSaving(false) }
  }

  async function submitRenewal(event: FormEvent) {
    event.preventDefault()
    const result = await mutate('/renewal', renewal, 'Proposta de renovação registrada.')
    if (result) setModal(null)
  }
  async function submitTermination(event: FormEvent) {
    event.preventDefault()
    const result = await mutate('/termination', termination, 'Desocupação iniciada com cálculo da multa proporcional.')
    if (result) setModal(null)
  }
  async function createInspection(event: FormEvent) {
    event.preventDefault()
    await mutate('/exit-inspection', { scheduled_at: iso(inspection.scheduled_at), inspector_name: inspection.inspector_name || null, notes: inspection.notes || null }, 'Vistoria de saída criada. Conclua o laudo no módulo Vistorias.')
  }
  async function submitKeys(event: FormEvent) {
    event.preventDefault()
    await mutate('/keys-return', {
      returned_at: iso(keyReturn.returned_at), received_by: keyReturn.received_by, received_document: keyReturn.received_document || null,
      keys: [{ label: keyReturn.key_label, quantity: keyReturn.quantity, notes: null }], meter_readings: {}, notes: keyReturn.notes || null,
    }, 'Devolução das chaves registrada. Vistoria de saída finalizada.')
  }

  if (loading) return <div className="lease-lifecycle-loading">Carregando ciclo da locação...</div>

  return <div className="lease-lifecycle-panel">
    <div className="lease-lifecycle-heading">
      <div><span className="eyebrow">Ciclo da locação</span><h3>Renovação, desocupação e encerramento</h3><p>O contrato assinado permanece imutável. O encerramento só libera o imóvel depois de vistoria, chaves e acerto financeiro.</p></div>
      <button className="button secondary compact" type="button" onClick={() => void load()}><RefreshCw size={13}/> Atualizar</button>
    </div>
    {error && <div className="form-alert danger-alert">{error}</div>}
    {success && <div className="form-alert success-alert">{success}</div>}

    {!item && <div className="lease-lifecycle-start">
      {lease.status === 'signed' ? <>
        <article><FileSignature size={20}/><div><strong>Renovar sem apagar histórico</strong><span>Gera uma nova minuta com os termos propostos; o contrato atual só fecha quando a renovação estiver assinada.</span></div>{canManage&&<button className="button primary" type="button" onClick={() => setModal('renewal')}>Iniciar renovação</button>}</article>
        <article><KeyRound size={20}/><div><strong>Rescisão / desocupação</strong><span>Registra data efetiva, multa proporcional, vistoria de saída, devolução das chaves e acerto final.</span></div>{canManage&&<button className="button secondary" type="button" onClick={() => setModal('termination')}>Iniciar desocupação</button>}</article>
      </> : <div className="lease-lifecycle-empty">O ciclo final fica disponível quando a locação estiver assinada e arquivada.</div>}
    </div>}

    {item && <>
      <div className="lease-lifecycle-summary">
        <div><span>Processo</span><strong>{item.process_type === 'renewal' ? 'Renovação' : 'Desocupação'}</strong><small>{item.code}</small></div>
        <div><span>Situação</span><strong>{lifecycleStatusLabels[item.status] || item.status}</strong><small>{new Date(item.requested_at).toLocaleString('pt-BR')}</small></div>
        <div><span>Data efetiva</span><strong>{item.effective_date ? new Date(`${item.effective_date}T12:00:00`).toLocaleDateString('pt-BR') : '—'}</strong><small>{item.initiated_by ? initiatedByLabels[item.initiated_by] || item.initiated_by : 'renovação'}</small></div>
        <div><span>Financeiro</span><strong>{item.financial_clearance.blocking_count ? `${item.financial_clearance.blocking_count} bloqueio(s)` : 'Sem bloqueios'}</strong><small>{money(item.financial_clearance.blocking_amount)}</small></div>
      </div>

      {item.process_type === 'termination' && <div className="lease-lifecycle-steps">
        {['Solicitação','Vistoria de saída','Chaves','Acerto final','Encerramento'].map((label,index)=><div className={step>index?'done':step===index?'active':''} key={label}><i>{step>index?<CheckCircle2 size={13}/>:index+1}</i><span>{label}</span></div>)}
      </div>}

      {item.process_type === 'renewal' && <div className="lease-lifecycle-section">
        <div className="lease-lifecycle-section-title"><FileSignature size={17}/><div><strong>Renovação</strong><span>A nova locação segue todo o fluxo normal de revisão, assinatura e arquivamento.</span></div></div>
        <div className="lease-lifecycle-data-grid">
          <div><span>Início proposto</span><strong>{String(item.renewal_terms.start_date || '—')}</strong></div>
          <div><span>Novo aluguel</span><strong>{money(Number(item.renewal_terms.rent_amount || 0))}</strong></div>
          <div><span>Prazo</span><strong>{String(item.renewal_terms.term_months || '—')} meses</strong></div>
          <div><span>Nova minuta</span><strong>{item.renewed_lease_code || 'Ainda não criada'}</strong></div>
        </div>
        <div className="lease-lifecycle-actions">
          {item.status === 'renewal_proposed' && canManage && <button className="button primary" disabled={saving} type="button" onClick={() => void mutate('/renewal/prepare', undefined, 'Nova minuta de renovação criada nos contratos de locação.')}>Gerar nova minuta</button>}
          {item.status === 'renewal_prepared' && <span className="lease-lifecycle-hint">{item.renewed_lease_code} está <strong>{item.renewed_lease_status}</strong>. Revise e assine normalmente na lista de contratos.</span>}
          {item.status === 'renewal_prepared' && item.renewed_lease_status === 'signed' && canManage && <button className="button primary" disabled={saving} type="button" onClick={() => void mutate('/renewal/complete', undefined, 'Renovação concluída. O contrato anterior foi encerrado e o imóvel permanece locado.')}>Concluir renovação</button>}
          {item.status === 'renewed' && <span className="lease-lifecycle-complete"><CheckCircle2 size={16}/> Renovação concluída em {item.closed_at ? new Date(item.closed_at).toLocaleString('pt-BR') : '—'}.</span>}
          {!['renewed','cancelled'].includes(item.status) && canManage && <button className="button ghost-danger" disabled={saving} type="button" onClick={() => void mutate('/cancel', undefined, 'Processo de renovação cancelado.')}>Cancelar ciclo</button>}
        </div>
      </div>}

      {item.process_type === 'termination' && <>
        <div className="lease-lifecycle-section">
          <div className="lease-lifecycle-section-title"><WalletCards size={17}/><div><strong>Multa rescisória</strong><span>Estimativa proporcional ao período restante. A decisão fica auditada antes do encerramento.</span></div></div>
          <div className="lease-lifecycle-fine"><strong>{money(Number(item.termination_fine_amount))}</strong><span className={`status-badge ${item.fine_status==='pending'?'warning':'success'}`}>{fineLabels[item.fine_status]}</span></div>
          {item.fine_status === 'pending' && canManage && <div className="lease-lifecycle-fine-actions">
            <label className="field"><span>Valor a registrar</span><input type="number" step="0.01" min="0" value={fineAmount ?? ''} onChange={e=>setFineAmount(e.target.value?Number(e.target.value):null)}/></label>
            <label className="field"><span>Beneficiário</span><select value={fineBeneficiary} onChange={e=>setFineBeneficiary(e.target.value as 'owner'|'agency')}><option value="owner">Proprietário</option><option value="agency">Imobiliária</option></select></label>
            <button className="button primary" disabled={saving} type="button" onClick={() => void mutate('/fine', { action:'register', beneficiary:fineBeneficiary, amount:fineAmount, due_date:item.effective_date, notes:null }, 'Multa registrada no Financeiro. O título precisa ser liquidado para liberar o encerramento.')}>Registrar no Financeiro</button>
            <button className="button secondary" disabled={saving} type="button" onClick={() => void mutate('/fine', { action:'waive', beneficiary:null, amount:null, due_date:null, notes:'Multa dispensada no processo de desocupação.' }, 'Multa dispensada com registro no histórico.')}>Dispensar multa</button>
          </div>}
        </div>

        <div className="lease-lifecycle-section">
          <div className="lease-lifecycle-section-title"><ClipboardCheck size={17}/><div><strong>Vistoria de saída</strong><span>Nasce separada da vistoria inicial e preserva o laudo de entrada como histórico.</span></div></div>
          {!item.exit_inspection_id && canManage && <form className="lease-lifecycle-inline-form" onSubmit={createInspection}>
            <label className="field"><span>Agendamento</span><input type="datetime-local" value={inspection.scheduled_at} onChange={e=>setInspection(c=>({...c,scheduled_at:e.target.value}))}/></label>
            <label className="field"><span>Vistoriador</span><input value={inspection.inspector_name} onChange={e=>setInspection(c=>({...c,inspector_name:e.target.value}))}/></label>
            <button className="button primary" disabled={saving} type="submit">Criar vistoria de saída</button>
          </form>}
          {item.exit_inspection_id && <div className="lease-lifecycle-row"><div><strong>{item.exit_inspection_code}</strong><span>Situação: {item.exit_inspection_status}</span></div>{item.exit_inspection_status === 'draft' && <small>Abra o módulo Vistorias, registre condições/fotos e clique em “Concluir laudo”.</small>}{['ready','finalized'].includes(item.exit_inspection_status || '') && <span className="lease-lifecycle-complete"><CheckCircle2 size={15}/> Laudo concluído</span>}</div>}
        </div>

        <div className="lease-lifecycle-section">
          <div className="lease-lifecycle-section-title"><KeyRound size={17}/><div><strong>Devolução das chaves</strong><span>Só fica disponível depois que o laudo de saída estiver concluído.</span></div></div>
          {!item.keys_returned_at && ['ready','finalized'].includes(item.exit_inspection_status || '') && canManage && <form className="lease-lifecycle-inline-form keys" onSubmit={submitKeys}>
            <label className="field"><span>Data/hora</span><input required type="datetime-local" value={keyReturn.returned_at} onChange={e=>setKeyReturn(c=>({...c,returned_at:e.target.value}))}/></label>
            <label className="field"><span>Recebido por</span><input required value={keyReturn.received_by} onChange={e=>setKeyReturn(c=>({...c,received_by:e.target.value}))}/></label>
            <label className="field"><span>Chave / conjunto</span><input required value={keyReturn.key_label} onChange={e=>setKeyReturn(c=>({...c,key_label:e.target.value}))}/></label>
            <label className="field"><span>Quantidade</span><input required min="1" max="50" type="number" value={keyReturn.quantity} onChange={e=>setKeyReturn(c=>({...c,quantity:Number(e.target.value)}))}/></label>
            <button className="button primary" disabled={saving} type="submit">Registrar devolução</button>
          </form>}
          {item.keys_returned_at && <div className="lease-lifecycle-row"><div><strong>Chaves devolvidas</strong><span>{new Date(item.keys_returned_at).toLocaleString('pt-BR')} · recebido por {item.keys_received_by}</span></div><span className="lease-lifecycle-complete"><CheckCircle2 size={15}/> Registrado</span></div>}
        </div>

        <div className="lease-lifecycle-section">
          <div className="lease-lifecycle-section-title"><WalletCards size={17}/><div><strong>Acerto financeiro final</strong><span>Recebíveis em aberto bloqueiam o encerramento. Repasses e contas a pagar permanecem como acompanhamento da imobiliária.</span></div></div>
          <div className="lease-lifecycle-clearance"><div><span>Bloqueios do locatário</span><strong>{item.financial_clearance.blocking_count}</strong><small>{money(item.financial_clearance.blocking_amount)}</small></div><div><span>Acompanhamentos da imobiliária</span><strong>{item.financial_clearance.followup_count}</strong><small>{money(item.financial_clearance.followup_amount)}</small></div></div>
          {item.financial_clearance.items.length>0 && <div className="lease-lifecycle-finance-list">{item.financial_clearance.items.map(entry=><div key={`${entry.source_type}-${entry.id}`} className={entry.blocker?'blocker':''}><span><strong>{entry.code}</strong><small>{entry.description}</small></span><span>{entry.direction==='receivable'?'A receber':'A pagar'}</span><strong>{money(entry.remaining_amount)}</strong></div>)}</div>}
        </div>

        <div className="lease-lifecycle-section close-section">
          <div className="lease-lifecycle-section-title"><CheckCircle2 size={17}/><div><strong>Encerramento</strong><span>Ao concluir, o contrato fecha e o imóvel volta como Disponível ou sai da carteira.</span></div></div>
          {item.status === 'closed' ? <div className="lease-lifecycle-complete"><CheckCircle2 size={16}/> Locação encerrada. Destino do imóvel: {item.property_disposition === 'available' ? 'Disponível' : 'Inativo'}.</div> : <div className="lease-lifecycle-close-actions">
            <label className="field"><span>Destino do imóvel</span><select value={disposition} onChange={e=>setDisposition(e.target.value as 'available'|'inactive')}><option value="available">Voltar para Disponível</option><option value="inactive">Retirar da carteira</option></select></label>
            <button className="button primary" disabled={saving || !item.can_close} type="button" onClick={() => void mutate('/close', { property_disposition: disposition, notes: null }, 'Locação encerrada e imóvel atualizado.')}>Encerrar locação</button>
            {!item.can_close && <small>O botão libera quando vistoria, chaves, multa e recebíveis estiverem resolvidos.</small>}
          </div>}
          {!['closed','cancelled'].includes(item.status) && !item.keys_returned_at && canManage && <button className="button ghost-danger" disabled={saving} type="button" onClick={() => void mutate('/cancel', undefined, 'Processo de desocupação cancelado.')}>Cancelar desocupação</button>}
        </div>
      </>}
    </>}

    {modal && <div className="lease-lifecycle-modal-backdrop" role="presentation"><div className="lease-lifecycle-modal" role="dialog" aria-modal="true">
      {modal === 'renewal' ? <form onSubmit={submitRenewal}><div className="lease-lifecycle-modal-heading"><div><span className="eyebrow">Renovação</span><h3>Propor novos termos</h3></div><CalendarClock size={20}/></div><div className="form-grid two-columns"><label className="field"><span>Início da renovação</span><input required type="date" min={lease.end_date} value={renewal.start_date} onChange={e=>setRenewal(c=>({...c,start_date:e.target.value}))}/></label><label className="field"><span>Prazo (meses)</span><input required min="1" max="240" type="number" value={renewal.term_months} onChange={e=>setRenewal(c=>({...c,term_months:Number(e.target.value)}))}/></label><label className="field"><span>Novo aluguel</span><input required min="0.01" step="0.01" type="number" value={renewal.rent_amount} onChange={e=>setRenewal(c=>({...c,rent_amount:Number(e.target.value)}))}/></label><label className="field"><span>Índice</span><select value={renewal.adjustment_index} onChange={e=>setRenewal(c=>({...c,adjustment_index:e.target.value}))}><option>IPCA</option><option>IGP-M</option><option>INPC</option><option>IPC-FIPE</option><option>IGP-DI</option></select></label><label className="field field-span-2"><span>Observações</span><textarea rows={3} value={renewal.notes} onChange={e=>setRenewal(c=>({...c,notes:e.target.value}))}/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={()=>setModal(null)}>Cancelar</button><button className="button primary" disabled={saving} type="submit">Registrar proposta</button></div></form> : <form onSubmit={submitTermination}><div className="lease-lifecycle-modal-heading"><div><span className="eyebrow">Rescisão / desocupação</span><h3>Iniciar encerramento</h3></div><KeyRound size={20}/></div><div className="form-grid two-columns"><label className="field"><span>Data efetiva</span><input required type="date" value={termination.effective_date} onChange={e=>setTermination(c=>({...c,effective_date:e.target.value}))}/></label><label className="field"><span>Origem</span><select value={termination.initiated_by} onChange={e=>setTermination(c=>({...c,initiated_by:e.target.value}))}>{Object.entries(initiatedByLabels).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></label><label className="field field-span-2"><span>Motivo / observações</span><textarea required minLength={3} rows={4} value={termination.reason} onChange={e=>setTermination(c=>({...c,reason:e.target.value}))}/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={()=>setModal(null)}>Cancelar</button><button className="button primary" disabled={saving} type="submit">Iniciar desocupação</button></div></form>}
    </div></div>}
  </div>
}
