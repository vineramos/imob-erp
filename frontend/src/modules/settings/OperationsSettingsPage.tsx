import { CalendarClock, Database, History, RefreshCw, Save, ShieldCheck, TrendingUp, X } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { AdjustmentIndex, EconomicIndexSync, EconomicIndexValue, OperationalDefaults } from '../../api/types'
import { authConfigured } from '../../auth/client'

const adjustmentIndexes: { value: AdjustmentIndex; label: string }[] = [
  { value: 'IPCA', label: 'IPCA — Índice Nacional de Preços ao Consumidor Amplo' },
  { value: 'IGP-M', label: 'IGP-M — Índice Geral de Preços do Mercado' },
  { value: 'INPC', label: 'INPC — Índice Nacional de Preços ao Consumidor' },
  { value: 'IPC-FIPE', label: 'IPC-FIPE — Índice de Preços ao Consumidor' },
  { value: 'IGP-DI', label: 'IGP-DI — Índice Geral de Preços - Disponibilidade Interna' },
]
type OperationsForm = OperationalDefaults
const defaults: OperationsForm = {
  rent_due_day: 10,
  owner_repasse_business_days: 2,
  residential_lease_months: 30,
  adjustment_index: 'IPCA',
  termination_fine_months: 3,
  inspection_contest_days: 5,
  default_admin_fee_percent: 10,
  delinquency_first_contact_day: 1,
  delinquency_followup_day: 3,
  delinquency_critical_day: 5,
  late_fee_percent: 2,
  late_interest_percent_monthly: 1,
  late_interest_type: 'simple',
  late_interest_compounding: 'daily',
}
type Props = { canEdit: boolean }
type IndexHistory = { index_code:string; name:string; from_competence:string; average_12m:number|null; months_in_average:number; sync_message:string|null; values:EconomicIndexValue[] }

function competenceLabel(value: string | null | undefined) {
  if (!value) return 'Ainda sem série local'
  const [year, month] = value.slice(0,7).split('-')
  return `${month}/${year}`
}
function rate(value:number){return Number(value).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:4})+'%'}

export function OperationsSettingsPage({ canEdit }: Props) {
  const [form, setForm] = useState<OperationsForm>(defaults)
  const [indices, setIndices] = useState<EconomicIndexValue[]>([])
  const [syncing, setSyncing] = useState<AdjustmentIndex | null>(null)
  const [syncInfo, setSyncInfo] = useState<Partial<Record<AdjustmentIndex, EconomicIndexSync>>>({})
  const [loading, setLoading] = useState(authConfigured)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [historyCode,setHistoryCode]=useState<AdjustmentIndex|null>(null)
  const [history,setHistory]=useState<IndexHistory|null>(null)
  const [historyLoading,setHistoryLoading]=useState(false)
  const [historyError,setHistoryError]=useState('')

  useEffect(() => {
    if (!authConfigured) return
    let active = true
    void Promise.all([apiRequest<OperationsForm>('/settings/operations'), apiRequest<EconomicIndexValue[]>('/economic-indices/latest')])
      .then(([data, latest]) => { if (active) { setForm(data); setIndices(latest) } })
      .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os padrões operacionais.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  useEffect(()=>{if(!historyCode)return;const close=(event:KeyboardEvent)=>{if(event.key==='Escape')setHistoryCode(null)};window.addEventListener('keydown',close);return()=>window.removeEventListener('keydown',close)},[historyCode])

  function numberField<K extends keyof OperationsForm>(key: K, value: string) {
    setForm((current) => ({ ...current, [key]: Number(value) })); setSuccess('')
  }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!canEdit) return
    setSaving(true); setError(''); setSuccess('')
    try {
      const updated = authConfigured ? await apiRequest<OperationsForm>('/settings/operations', { method: 'PUT', body: JSON.stringify(form) }) : form
      setForm(updated); setSuccess('Padrões operacionais salvos. Novos contratos passam a copiar estas condições; contratos já versionados permanecem intactos.')
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar os padrões operacionais.') }
    finally { setSaving(false) }
  }
  async function syncIndex(index: AdjustmentIndex) {
    if (!canEdit || !authConfigured) return
    setSyncing(index); setError(''); setSuccess('')
    try {
      const result = await apiRequest<EconomicIndexSync>(`/economic-indices/sync/${encodeURIComponent(index)}`, { method: 'POST' })
      setSyncInfo((current) => ({ ...current, [index]: result })); setIndices(await apiRequest<EconomicIndexValue[]>('/economic-indices/latest')); setSuccess(result.message)
    } catch (cause) { setError(cause instanceof ApiError?cause.detail:`Não foi possível atualizar ${index}.`) }
    finally { setSyncing(null) }
  }
  async function openHistory(index:AdjustmentIndex){
    setHistoryCode(index);setHistory(null);setHistoryError('');setHistoryLoading(true)
    try{setHistory(await apiRequest<IndexHistory>(`/economic-indices/${encodeURIComponent(index)}/history`))}
    catch(cause){setHistoryError(cause instanceof ApiError?cause.detail:`Não foi possível carregar o histórico de ${index}.`)}
    finally{setHistoryLoading(false)}
  }

  if (loading) return <section className="workspace settings-workspace"><article className="panel settings-loading">Carregando padrões operacionais...</article></section>

  return <section className="workspace settings-workspace operations-settings-refresh">
    <div className="page-heading settings-heading"><div><span className="eyebrow">Configurações · Operação</span><h1>Padrões operacionais</h1><p>Defina os padrões do dia a dia em uma visão simples. O histórico dos contratos continua imutável.</p></div>{canEdit&&<button className="button primary" type="button" disabled={saving} onClick={()=>document.getElementById('operations-settings-form')?.requestSubmit()}><Save size={15}/>{saving?'Salvando...':'Salvar padrões'}</button>}</div>
    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}

    <form id="operations-settings-form" onSubmit={save} className="operations-settings-grid">
      <div className="operations-settings-main">
        <article className="panel settings-card-refined"><div className="settings-card-title"><div className="settings-card-icon"><CalendarClock size={18}/></div><div><span className="eyebrow">Locação</span><h2>Contrato e cobrança</h2><p>Padrões aplicados somente aos novos registros.</p></div></div><div className="form-grid two-columns refined-form-grid"><label className="field"><span>Vencimento padrão do aluguel</span><input disabled={!canEdit} min={1} max={28} type="number" value={form.rent_due_day} onChange={(e)=>numberField('rent_due_day',e.target.value)}/></label><label className="field"><span>Prazo residencial (meses)</span><input disabled={!canEdit} min={1} max={120} type="number" value={form.residential_lease_months} onChange={(e)=>numberField('residential_lease_months',e.target.value)}/></label><label className="field"><span>Índice de reajuste</span><select disabled={!canEdit} value={form.adjustment_index} onChange={(e)=>setForm((current)=>({...current,adjustment_index:e.target.value as AdjustmentIndex}))}>{adjustmentIndexes.map((index)=><option key={index.value} value={index.value}>{index.label}</option>)}</select></label><label className="field"><span>Multa rescisória (aluguéis)</span><input disabled={!canEdit} min={0} max={12} step="0.5" type="number" value={form.termination_fine_months} onChange={(e)=>numberField('termination_fine_months',e.target.value)}/></label><label className="field"><span>Administração padrão (%)</span><input disabled={!canEdit} min={0} max={100} step="0.1" type="number" value={form.default_admin_fee_percent} onChange={(e)=>numberField('default_admin_fee_percent',e.target.value)}/></label><label className="field"><span>Repasse ao proprietário (dias úteis)</span><input disabled={!canEdit} min={0} max={20} type="number" value={form.owner_repasse_business_days} onChange={(e)=>numberField('owner_repasse_business_days',e.target.value)}/></label></div></article>

        <article className="panel settings-card-refined"><div className="settings-card-title"><div className="settings-card-icon"><ShieldCheck size={18}/></div><div><span className="eyebrow">Inadimplência</span><h2>Multa e juros de mora</h2><p>Condições copiadas para novos contratos e congeladas em cada versão. A mora começa em D+1.</p></div></div><div className="form-grid two-columns refined-form-grid"><label className="field"><span>Multa padrão por atraso (%)</span><input disabled={!canEdit} min={0} max={100} step="0.01" type="number" value={form.late_fee_percent} onChange={(e)=>numberField('late_fee_percent',e.target.value)}/><small>Aplicada uma única vez a partir do dia seguinte ao vencimento.</small></label><label className="field"><span>Juros de mora (% ao mês)</span><input disabled={!canEdit} min={0} max={100} step="0.01" type="number" value={form.late_interest_percent_monthly} onChange={(e)=>numberField('late_interest_percent_monthly',e.target.value)}/><small>Cálculo proporcional desde D+1 até a data da liquidação.</small></label><label className="field"><span>Tipo de juros</span><select disabled={!canEdit} value={form.late_interest_type} onChange={(e)=>setForm((current)=>({...current,late_interest_type:e.target.value as OperationsForm['late_interest_type']}))}><option value="simple">Simples</option><option value="compound">Composto</option></select></label><label className="field"><span>Capitalização</span><select disabled={!canEdit||form.late_interest_type!=='compound'} value={form.late_interest_compounding} onChange={(e)=>setForm((current)=>({...current,late_interest_compounding:e.target.value as OperationsForm['late_interest_compounding']}))}><option value="daily">Diária</option><option value="monthly">Mensal</option></select><small>{form.late_interest_type==='simple'?'Não se aplica a juros simples.':'Define a periodicidade de capitalização no cálculo interno.'}</small></label></div>{form.late_interest_type==='compound'&&<div className="form-alert warning-alert">Juros compostos ficam disponíveis no ERP e precisam estar expressamente previstos no contrato. O Banco Inter não oferece um parâmetro de capitalização composta equivalente; a emissão via Inter será bloqueada para evitar divergência entre boleto e contrato.</div>}</article>

        <article className="panel settings-card-refined"><div className="settings-card-title"><div className="settings-card-icon"><ShieldCheck size={18}/></div><div><span className="eyebrow">Controle</span><h2>Prazos críticos e régua de cobrança</h2><p>Marcos automáticos da inadimplência. A ordem deve respeitar primeiro contato ≤ acompanhamento ≤ garantia.</p></div></div><div className="form-grid two-columns refined-form-grid"><label className="field"><span>Contestação de vistoria (dias)</span><input disabled={!canEdit} min={1} max={30} type="number" value={form.inspection_contest_days} onChange={(e)=>numberField('inspection_contest_days',e.target.value)}/></label><label className="field"><span>Primeiro contato após vencimento (D+)</span><input disabled={!canEdit} min={1} max={90} type="number" value={form.delinquency_first_contact_day} onChange={(e)=>numberField('delinquency_first_contact_day',e.target.value)}/></label><label className="field"><span>Acompanhamento da cobrança (D+)</span><input disabled={!canEdit} min={1} max={90} type="number" value={form.delinquency_followup_day} onChange={(e)=>numberField('delinquency_followup_day',e.target.value)}/></label><label className="field"><span>Marco crítico / garantia (D+)</span><input disabled={!canEdit} min={1} max={90} type="number" value={form.delinquency_critical_day} onChange={(e)=>numberField('delinquency_critical_day',e.target.value)}/></label></div></article>
      </div>
      <aside className="operations-settings-side"><article className="panel settings-principle-card"><ShieldCheck size={20}/><div><span className="eyebrow">Princípio estrutural</span><h2>Configuração não reescreve histórico</h2><p>Cada contrato guarda sua própria regra na data da contratação. Alterar multa, juros ou régua aqui muda apenas o padrão usado em novos contratos.</p></div></article></aside>
    </form>

    <article className="panel economic-indices-card"><div className="settings-card-title"><div className="settings-card-icon"><Database size={18}/></div><div><span className="eyebrow">Séries oficiais</span><h2>Índices econômicos</h2><p>Histórico oficial desde janeiro/2025, com média móvel dos últimos 12 meses.</p></div></div><div className="economic-index-grid">{adjustmentIndexes.map(({value,label})=>{const current=indices.find((item)=>item.index_code===value);const state=syncInfo[value];return <div className="economic-index-item" key={value}><div className="economic-index-name"><strong>{value}</strong><span>{label.split(' — ')[1]}</span></div><div className="economic-index-current"><span>Última competência</span><strong>{current?competenceLabel(current.competence):'—'}</strong><small>{current?rate(Number(current.monthly_rate)):'Sem valor local'}{state?.status==='awaiting_publication'?' · aguardando publicação':''}</small></div><div className="economic-index-actions"><button className="button secondary compact" type="button" onClick={()=>void openHistory(value)}><History size={13}/> Histórico</button><button className="button secondary compact" type="button" disabled={!canEdit||syncing!==null} onClick={()=>void syncIndex(value)}><RefreshCw size={13}/>{syncing===value?'Consultando...':'Atualizar'}</button></div></div>})}</div></article>

    {historyCode&&<div className="portfolio-modal-backdrop" onMouseDown={(event)=>{if(event.currentTarget===event.target)setHistoryCode(null)}}><div className="panel portfolio-modal economic-history-modal" role="dialog" aria-modal="true"><div className="portfolio-modal-header"><div><span className="eyebrow">Série histórica · Banco Central</span><h2>{historyCode}</h2><p>{history?.name||'Histórico mensal desde janeiro de 2025.'}</p></div><button className="portfolio-modal-close" type="button" aria-label="Fechar" onClick={()=>setHistoryCode(null)}><X size={17}/></button></div><div className="economic-history-body">{historyError&&<div className="form-alert danger-alert" role="alert">{historyError}</div>}{historyLoading?<div className="settings-loading">Carregando e completando a série histórica...</div>:history&&<><div className="economic-history-summary"><TrendingUp size={19}/><div><span>Média dos últimos {history.months_in_average} meses</span><strong>{history.average_12m==null?'—':rate(history.average_12m)}</strong></div><small>Histórico disponível desde 01/2025</small></div>{history.sync_message&&<div className="economic-history-note">{history.sync_message}</div>}<div className="economic-history-table"><div className="economic-history-table-head"><span>Competência</span><span>Variação mensal</span><span>Fonte</span></div>{[...history.values].reverse().map((item)=><div className="economic-history-row" key={`${item.index_code}-${item.competence}`}><strong>{competenceLabel(item.competence)}</strong><span className={Number(item.monthly_rate)<0?'negative':'positive'}>{rate(Number(item.monthly_rate))}</span><small>{item.source}</small></div>)}</div></>}</div><div className="canonical-modal-actions"><button className="button secondary" type="button" onClick={()=>setHistoryCode(null)}>Fechar</button></div></div></div>}
  </section>
}
