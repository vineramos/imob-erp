import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Download,
  Landmark,
  ReceiptText,
  RefreshCw,
  Send,
  WalletCards,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import { shiftMonth } from './finance-period'

type ChargeItem = { key:string; label:string; amount:number; beneficiary:'owner'|'agency'|'third_party'; agency_retention_type:'none'|'percent'|'fixed'; agency_retention_value:number; agency_retention_amount:number; third_party_net_amount:number }
type Repasse = { id:string; charge_id:string; charge_code:string; lease_contract_id:string; lease_code:string; property_id:string; property_code:string; competence:string; owner_person_id:string; owner_name:string; ownership_percent:number; amount:number; due_date:string; status:string; paid_at:string|null; payment_reference:string|null }
type Settlement = { id:string; administration_contract_id:string|null; admin_fee_calculated:number; intermediation_fee_calculated:number; agency_fee_withheld:number; agency_reimbursement_amount:number; agency_retention_amount:number; owner_entitlement_amount:number; third_party_amount:number; calculated_at:string; repasses:Repasse[] }
type Charge = { id:string; code:string; lease_contract_id:string; lease_code:string; property_id:string; property_code:string; property_address:Record<string,string>; tenants:Array<{name?:string}>; owners:Array<{name?:string}>; competence:string; due_date:string; status:string; days_overdue:number; critical_overdue:boolean; rent_amount:number; gross_amount:number; charge_items:ChargeItem[]; sent_at:string|null; paid_at:string|null; paid_amount:number|null; payment_method:string|null; payment_reference:string|null; settlement:Settlement|null; created_at:string }
type Dashboard = { competence:string; open_amount:number; overdue_amount:number; critical_overdue_amount:number; received_amount:number; agency_revenue_amount:number; pending_repasse_amount:number; charges_open:number; charges_overdue:number; charges_critical:number; repasses_pending:number }
type Statement = { owner_person_id:string; owner_name:string; competence:string; total_received_from_tenants:number; total_agency_fees:number; total_owner_entitlement:number; total_repasse:number; total_repasse_paid:number; lines:Array<{property_code:string;charge_code:string;repasse_amount:number;repasse_status:string}> }

type Props = { permissions:string[] }
type Tab = 'charges'|'repasses'|'statements'

const statusLabels:Record<string,string> = { generated:'Gerada', sent:'Enviada', overdue:'Inadimplente', paid:'Recebida', cancelled:'Cancelada', pending:'A repassar', settled_zero:'Sem repasse' }
function money(value:number|null|undefined){ return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'}) }
function dateLabel(value:string|null|undefined){ if(!value)return '—'; return new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString('pt-BR') }
function dateTimeLabel(value:string|null|undefined){ if(!value)return '—'; return new Date(value).toLocaleString('pt-BR') }
function addressLine(address:Record<string,string>){ return [address.street,address.number,address.neighborhood,address.city].filter(Boolean).join(', ') || 'Endereço não informado' }
function currentMonth(){ const now=new Date(); return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}` }
function localDateTime(){ const now=new Date(); const offset=now.getTimezoneOffset(); return new Date(now.getTime()-offset*60000).toISOString().slice(0,16) }

export function FinancePage({permissions}:Props){
  const canGenerate=permissions.includes('finance.charge.create')
  const canReconcile=permissions.includes('finance.reconcile')
  const canRepasse=permissions.includes('finance.repasse.execute')
  const [month,setMonth]=useState(currentMonth())
  const [tab,setTab]=useState<Tab>('charges')
  const [dashboard,setDashboard]=useState<Dashboard|null>(null)
  const [charges,setCharges]=useState<Charge[]>([])
  const [repasses,setRepasses]=useState<Repasse[]>([])
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [statusFilter,setStatusFilter]=useState('all')
  const [paymentCharge,setPaymentCharge]=useState<Charge|null>(null)
  const [paymentMethod,setPaymentMethod]=useState('pix')
  const [paymentReference,setPaymentReference]=useState('')
  const [paymentAt,setPaymentAt]=useState(localDateTime())
  const [repasseModal,setRepasseModal]=useState<Repasse|null>(null)
  const [repasseReference,setRepasseReference]=useState('')
  const [repasseAt,setRepasseAt]=useState(localDateTime())
  const [statements,setStatements]=useState<Record<string,Statement>>({})

  const competence=`${month}-01`
  const load=useCallback(async()=>{
    setLoading(true);setError('')
    try{
      const [metrics,nextCharges,nextRepasses]=await Promise.all([
        apiRequest<Dashboard>(`/finance/dashboard?competence=${competence}`),
        apiRequest<Charge[]>(`/finance/charges?competence=${competence}`),
        apiRequest<Repasse[]>(`/finance/repasses?competence=${competence}`),
      ])
      setDashboard(metrics);setCharges(nextCharges);setRepasses(nextRepasses)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o financeiro.')}
    finally{setLoading(false)}
  },[competence])
  useEffect(()=>{void load()},[load])

  const filtered=useMemo(()=>statusFilter==='all'?charges:charges.filter(item=>item.status===statusFilter),[charges,statusFilter])
  const owners=useMemo(()=>{
    const map=new Map<string,string>()
    repasses.forEach(item=>map.set(item.owner_person_id,item.owner_name))
    return [...map.entries()].map(([id,name])=>({id,name}))
  },[repasses])

  async function generate(){
    setSaving(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<{generated:number;skipped_existing:number;skipped_ineligible:number}>('/finance/charges/generate',{method:'POST',body:JSON.stringify({competence})})
      await load();setSuccess(`${result.generated} cobrança(s) gerada(s). ${result.skipped_existing} já existiam e ${result.skipped_ineligible} contrato(s) não estavam elegíveis.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível gerar as cobranças.')}
    finally{setSaving(false)}
  }
  async function markSent(item:Charge){
    setSaving(true);setError('');setSuccess('')
    try{await apiRequest(`/finance/charges/${item.id}/mark-sent`,{method:'POST'});await load();setSuccess(`${item.code} marcada como enviada.`)}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível atualizar a cobrança.')}
    finally{setSaving(false)}
  }
  async function receive(event:FormEvent){
    event.preventDefault();if(!paymentCharge)return
    setSaving(true);setError('');setSuccess('')
    try{
      await apiRequest(`/finance/charges/${paymentCharge.id}/payment`,{method:'POST',body:JSON.stringify({paid_amount:paymentCharge.gross_amount,paid_at:new Date(paymentAt).toISOString(),payment_method:paymentMethod,payment_reference:paymentReference||null})})
      const code=paymentCharge.code;setPaymentCharge(null);setPaymentReference('');await load();setSuccess(`${code} recebida integralmente. Taxas, retenções e repasses foram calculados automaticamente.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível registrar o recebimento.')}
    finally{setSaving(false)}
  }
  async function payRepasse(event:FormEvent){
    event.preventDefault();if(!repasseModal)return
    setSaving(true);setError('');setSuccess('')
    try{
      await apiRequest(`/finance/repasses/${repasseModal.id}/payment`,{method:'POST',body:JSON.stringify({paid_at:new Date(repasseAt).toISOString(),payment_reference:repasseReference||null})})
      const owner=repasseModal.owner_name;setRepasseModal(null);setRepasseReference('');await load();setSuccess(`Repasse de ${owner} marcado como pago.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível registrar o repasse.')}
    finally{setSaving(false)}
  }
  async function loadStatement(ownerId:string){
    try{const item=await apiRequest<Statement>(`/finance/statements/${ownerId}?competence=${competence}`);setStatements(current=>({...current,[ownerId]:item}))}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar a prestação de contas.')}
  }
  async function pdf(ownerId:string,ownerName:string){
    try{const blob=await apiBlobRequest(`/finance/statements/${ownerId}/pdf?competence=${competence}`);const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`prestacao-contas-${ownerName}-${month}.pdf`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível gerar o PDF.')}
  }

  return <section className="workspace finance-workspace">
    <div className="page-heading finance-heading"><div><span className="eyebrow">Financeiro · Locação</span><h1>Financeiro</h1><p>Cobrança, recebimento, taxas da imobiliária e dinheiro do proprietário separados no mesmo fluxo.</p></div><div className="heading-actions"><button className="icon-button" type="button" onClick={()=>setMonth(current=>shiftMonth(current,-1))} aria-label="Competência anterior" title="Competência anterior"><ChevronLeft size={16}/></button><label className="finance-month"><CalendarDays size={15}/><input type="month" value={month} onChange={e=>setMonth(e.target.value)}/></label><button className="icon-button" type="button" onClick={()=>setMonth(current=>shiftMonth(current,1))} aria-label="Próxima competência" title="Próxima competência"><ChevronRight size={16}/></button><button className="button secondary" type="button" onClick={()=>void load()} disabled={loading}><RefreshCw size={14}/> Atualizar</button>{canGenerate&&<button className="button primary" type="button" onClick={()=>void generate()} disabled={saving}><ReceiptText size={14}/> Gerar cobranças</button>}</div></div>

    {dashboard&&<div className="finance-metrics">
      <article className="panel finance-metric"><span>Recebido na competência</span><strong>{money(dashboard.received_amount)}</strong><small>{money(dashboard.agency_revenue_amount)} de receita da imobiliária, incluindo retenções</small></article>
      <article className="panel finance-metric"><span>Em aberto</span><strong>{money(dashboard.open_amount)}</strong><small>{dashboard.charges_open} cobrança(s)</small></article>
      <article className={`panel finance-metric ${dashboard.charges_critical?'critical':''}`}><span>Inadimplência</span><strong>{money(dashboard.overdue_amount)}</strong><small>{dashboard.charges_critical?`${dashboard.charges_critical} caso(s) crítico(s)`:`${dashboard.charges_overdue} em atraso`}</small></article>
      <article className="panel finance-metric"><span>Repasses pendentes</span><strong>{money(dashboard.pending_repasse_amount)}</strong><small>{dashboard.repasses_pending} repasse(s)</small></article>
    </div>}

    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}
    <div className="finance-tabs panel"><button className={tab==='charges'?'active':''} onClick={()=>setTab('charges')} type="button"><ReceiptText size={15}/> Cobranças <span>{charges.length}</span></button><button className={tab==='repasses'?'active':''} onClick={()=>setTab('repasses')} type="button"><Landmark size={15}/> Repasses <span>{repasses.filter(item=>item.status==='pending').length}</span></button><button className={tab==='statements'?'active':''} onClick={()=>setTab('statements')} type="button"><WalletCards size={15}/> Prestação de contas <span>{owners.length}</span></button></div>

    {loading?<article className="panel settings-loading">Carregando financeiro...</article>:tab==='charges'?<>
      <div className="finance-filter"><button className={statusFilter==='all'?'active':''} onClick={()=>setStatusFilter('all')}>Todas</button>{['generated','sent','overdue','paid','cancelled'].map(key=><button key={key} className={statusFilter===key?'active':''} onClick={()=>setStatusFilter(key)}>{statusLabels[key]}</button>)}</div>
      <div className="finance-charge-list">{filtered.map(item=><article className={`panel finance-charge ${item.critical_overdue?'critical':''}`} key={item.id}>
        <div className="finance-charge-top"><div className="finance-charge-code"><CircleDollarSign size={18}/><div><span>{item.code}</span><strong>{item.lease_code} · Imóvel #{item.property_code}</strong><small>{addressLine(item.property_address)}</small></div></div><div className="finance-charge-tenant"><span>Locatário(s)</span><strong>{item.tenants.map(t=>t.name).filter(Boolean).join(' / ')||'—'}</strong><small>Competência {item.competence.slice(0,7).split('-').reverse().join('/')}</small></div><div className="finance-charge-due"><span>Vencimento</span><strong>{dateLabel(item.due_date)}</strong>{item.days_overdue>0&&<small>{item.days_overdue} dia(s) em atraso</small>}</div><div className="finance-charge-total"><span>Total</span><strong>{money(item.gross_amount)}</strong><i className={`status-badge ${item.status==='paid'?'success':item.status==='overdue'?'danger':item.status==='cancelled'?'neutral':'warning'}`}>{statusLabels[item.status]||item.status}</i></div></div>
        <div className="finance-charge-bottom"><div className="finance-components">{item.charge_items.map(component=><span key={component.key}>{component.label} <b>{money(component.amount)}</b>{Number(component.agency_retention_amount||0)>0&&<small> · retém {money(component.agency_retention_amount)} · repassa {money(component.third_party_net_amount)}</small>}</span>)}</div>{item.settlement&&<div className="finance-settlement-mini"><span>Taxa adm. <b>{money(item.settlement.admin_fee_calculated)}</b></span><span>Intermediação <b>{money(item.settlement.intermediation_fee_calculated)}</b></span>{Number(item.settlement.agency_retention_amount||0)>0&&<span>Retenção seguros <b>{money(item.settlement.agency_retention_amount)}</b></span>}<span>Terceiros <b>{money(item.settlement.third_party_amount)}</b></span><span>Direito proprietário <b>{money(item.settlement.owner_entitlement_amount)}</b></span></div>}<div className="finance-actions">{canGenerate&&['generated','overdue'].includes(item.status)&&<button className="button secondary compact" type="button" disabled={saving} onClick={()=>void markSent(item)}><Send size={13}/> Marcar enviada</button>}{canReconcile&&['generated','sent','overdue'].includes(item.status)&&<button className="button primary compact" type="button" disabled={saving} onClick={()=>{setPaymentCharge(item);setPaymentAt(localDateTime());setPaymentMethod('pix');setPaymentReference('')}}><CheckCircle2 size={13}/> Receber</button>}</div></div>
        {item.critical_overdue&&<div className="finance-critical"><AlertTriangle size={14}/><strong>Alerta crítico:</strong> atraso atingiu o limite operacional para acionamento da garantia/seguradora.</div>}
      </article>)}{filtered.length===0&&<article className="panel finance-empty"><ReceiptText size={26}/><strong>Nenhuma cobrança neste filtro.</strong><span>Use “Gerar cobranças” para criar a competência dos contratos elegíveis.</span></article>}</div>
    </>:tab==='repasses'?<div className="finance-repasses">{repasses.map(item=><article className="panel finance-repasse" key={item.id}><div><span className="eyebrow">{item.charge_code} · Imóvel #{item.property_code}</span><strong>{item.owner_name}</strong><small>{Number(item.ownership_percent).toLocaleString('pt-BR')}% · {item.lease_code}</small></div><div><span>Valor</span><strong>{money(item.amount)}</strong></div><div><span>Previsto</span><strong>{dateLabel(item.due_date)}</strong></div><div><i className={`status-badge ${item.status==='paid'?'success':'warning'}`}>{item.status==='paid'?'Pago':'A repassar'}</i>{item.paid_at&&<small>{dateTimeLabel(item.paid_at)}</small>}</div>{canRepasse&&item.status==='pending'&&<button className="button primary compact" type="button" onClick={()=>{setRepasseModal(item);setRepasseAt(localDateTime());setRepasseReference('')}}>Registrar repasse</button>}</article>)}{repasses.length===0&&<article className="panel finance-empty"><Landmark size={26}/><strong>Nenhum repasse nesta competência.</strong><span>Os repasses nascem automaticamente quando uma cobrança é recebida.</span></article>}</div>:<div className="finance-statements">{owners.map(owner=>{const statement=statements[owner.id];return <article className="panel finance-statement" key={owner.id}><div className="finance-statement-heading"><div><span className="eyebrow">Proprietário</span><h2>{owner.name}</h2><p>Prestação de contas da competência {month.split('-').reverse().join('/')}.</p></div><div className="heading-actions"><button className="button secondary" onClick={()=>void loadStatement(owner.id)}>Carregar resumo</button><button className="button primary" onClick={()=>void pdf(owner.id,owner.name)}><Download size={14}/> PDF</button></div></div>{statement&&<div className="finance-statement-metrics"><div><span>Recebido</span><strong>{money(statement.total_received_from_tenants)}</strong></div><div><span>Taxas</span><strong>{money(statement.total_agency_fees)}</strong></div><div><span>Direito proprietário</span><strong>{money(statement.total_owner_entitlement)}</strong></div><div><span>Repasses</span><strong>{money(statement.total_repasse)}</strong><small>{money(statement.total_repasse_paid)} pagos</small></div></div>}</article>})}{owners.length===0&&<article className="panel finance-empty"><WalletCards size={26}/><strong>Ainda não há prestação de contas nesta competência.</strong><span>Ela passa a existir após o primeiro recebimento e cálculo de repasse.</span></article>}</div>}

    {paymentCharge&&<div className="finance-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget&&!saving)setPaymentCharge(null)}}><form className="panel finance-modal" onSubmit={receive}><div className="finance-modal-header"><div><span className="eyebrow">Recebimento integral</span><h2>{paymentCharge.code}</h2><p>{paymentCharge.lease_code} · Imóvel #{paymentCharge.property_code}</p></div><button type="button" onClick={()=>setPaymentCharge(null)} disabled={saving}><X size={18}/></button></div><div className="finance-modal-amount"><span>Valor da cobrança</span><strong>{money(paymentCharge.gross_amount)}</strong><small>O ERP não aceita pagamento parcial neste fluxo.</small></div><div className="form-grid two-columns"><label className="field"><span>Data do recebimento</span><input required type="datetime-local" value={paymentAt} onChange={e=>setPaymentAt(e.target.value)}/></label><label className="field"><span>Forma</span><select value={paymentMethod} onChange={e=>setPaymentMethod(e.target.value)}><option value="pix">Pix</option><option value="boleto">Boleto</option><option value="transfer">Transferência</option><option value="cash">Dinheiro</option><option value="other">Outro</option></select></label><label className="field field-span-2"><span>Referência / comprovante</span><input value={paymentReference} onChange={e=>setPaymentReference(e.target.value)} placeholder="ID da transação, autenticação ou observação curta"/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={()=>setPaymentCharge(null)}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving?'Processando...':'Confirmar recebimento'}</button></div></form></div>}
    {repasseModal&&<div className="finance-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget&&!saving)setRepasseModal(null)}}><form className="panel finance-modal" onSubmit={payRepasse}><div className="finance-modal-header"><div><span className="eyebrow">Repasse ao proprietário</span><h2>{repasseModal.owner_name}</h2><p>{repasseModal.charge_code} · Imóvel #{repasseModal.property_code}</p></div><button type="button" onClick={()=>setRepasseModal(null)} disabled={saving}><X size={18}/></button></div><div className="finance-modal-amount"><span>Valor do repasse</span><strong>{money(repasseModal.amount)}</strong><small>Previsão contratual: {dateLabel(repasseModal.due_date)}</small></div><div className="form-grid two-columns"><label className="field"><span>Data do pagamento</span><input required type="datetime-local" value={repasseAt} onChange={e=>setRepasseAt(e.target.value)}/></label><label className="field"><span>Referência</span><input value={repasseReference} onChange={e=>setRepasseReference(e.target.value)} placeholder="Pix, TED ou autenticação"/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={()=>setRepasseModal(null)}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving?'Salvando...':'Confirmar repasse'}</button></div></form></div>}
  </section>
}