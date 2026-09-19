import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import { shiftMonth } from './finance-period'
import './finance-monthly-cycle.css'

type CycleState = 'complete'|'pending'|'attention'|'idle'
type CycleStep = {
  key:string
  title:string
  state:CycleState
  summary:string
  detail:string
  count:number
  pending_count:number
  amount:number
  pending_amount:number
  action_label:string|null
  action_target:string|null
}
type CycleAction = { key:string; title:string; detail:string; target:string }
type ClosingReadiness = {
  competence:string
  period_end:string
  can_close:boolean
  bank_accounts_count:number
  accounts_closed_count:number
  unclosed_accounts_count:number
  unreconciled_bank_transactions_count:number
  open_bank_exceptions_count:number
  ignored_bank_exceptions_count:number
  settlement_gap_count:number
  settlement_integrity_issues_count:number
  pending_third_party_count:number
  pending_owner_repasses_count:number
  blocker_count:number
  blockers:string[]
}
type Cycle = {
  competence:string
  eligible_contracts:number
  charges_count:number
  missing_charges:number
  gross_amount:number
  open_charges:number
  overdue_charges:number
  paid_charges:number
  received_amount:number
  settlements_count:number
  agency_revenue_amount:number
  owner_entitlement_amount:number
  third_party_pending_count:number
  third_party_pending_amount:number
  owner_repasse_pending_count:number
  owner_repasse_pending_amount:number
  statement_owner_count:number
  communications_pending_count:number
  communications_sent_count:number
  communications_failed_count:number
  attention_count:number
  next_action:CycleAction|null
  steps:CycleStep[]
}

type FinanceTarget = 'overview'|'billing'|'rent'|'banking'|'bank-control'
type Props = { onNavigateArea:(target:FinanceTarget)=>void }

const stateLabels:Record<CycleState,string> = {
  complete:'Concluído',
  pending:'Pendente',
  attention:'Atenção',
  idle:'Sem movimento',
}

function money(value:number|null|undefined){
  return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
}
function currentMonth(){
  const now=new Date()
  return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`
}
function monthLabel(month:string){
  const date=new Date(`${month}-01T12:00:00`)
  return date.toLocaleDateString('pt-BR',{month:'long',year:'numeric'})
}

export function FinanceMonthlyCyclePanel({onNavigateArea}:Props){
  const [month,setMonth]=useState(currentMonth())
  const [cycle,setCycle]=useState<Cycle|null>(null)
  const [readiness,setReadiness]=useState<ClosingReadiness|null>(null)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const competence=`${month}-01`

  const load=useCallback(async()=>{
    setLoading(true)
    setError('')
    try{
      const [nextCycle,nextReadiness]=await Promise.all([
        apiRequest<Cycle>(`/finance/monthly-cycle?competence=${competence}`),
        apiRequest<ClosingReadiness>(`/finance/monthly-cycle/closing-readiness?competence=${competence}`),
      ])
      setCycle(nextCycle)
      setReadiness(nextReadiness)
    }catch(cause){
      setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o ciclo financeiro mensal.')
    }finally{
      setLoading(false)
    }
  },[competence])

  useEffect(()=>{void load()},[load])

  function navigate(target:string|null|undefined){
    if(!target)return
    if(target==='communications'||target==='contracts'){
      window.location.assign(`/app/${target}`)
      return
    }
    if(target==='overview'||target==='billing'||target==='rent'||target==='banking'||target==='bank-control')onNavigateArea(target)
  }

  return <section className="workspace finance-cycle-workspace">
    <div className="page-heading finance-heading finance-cycle-heading">
      <div>
        <span className="eyebrow">Financeiro · Ciclo mensal</span>
        <h1>Da cobrança à prestação de contas</h1>
        <p>Acompanhe a competência inteira sem misturar recursos da imobiliária, do proprietário e de terceiros.</p>
      </div>
      <div className="heading-actions">
        <button className="icon-button" type="button" onClick={()=>setMonth(value=>shiftMonth(value,-1))} aria-label="Competência anterior"><ChevronLeft size={16}/></button>
        <label className="finance-month"><CalendarDays size={15}/><input type="month" value={month} onChange={event=>setMonth(event.target.value)}/></label>
        <button className="icon-button" type="button" onClick={()=>setMonth(value=>shiftMonth(value,1))} aria-label="Próxima competência"><ChevronRight size={16}/></button>
        <button className="button secondary" type="button" onClick={()=>void load()} disabled={loading}><RefreshCw size={14}/> Atualizar</button>
      </div>
    </div>

    {error&&<div className="form-alert danger-alert">{error}</div>}
    {loading&&!cycle?<article className="panel settings-loading">Carregando ciclo financeiro...</article>:cycle&&<>
      <article className={`panel finance-cycle-next ${cycle.next_action?'has-action':'is-clear'}`}>
        <div className="finance-cycle-next-icon">{cycle.next_action?<AlertTriangle size={20}/>:<CheckCircle2 size={20}/>}</div>
        <div>
          <span className="eyebrow">{monthLabel(month)}</span>
          <strong>{cycle.next_action?.title||'Sem pendências financeiras prioritárias'}</strong>
          <p>{cycle.next_action?.detail||'As etapas financeiras registradas nesta competência estão coerentes. Comunicações continuam sob revisão humana.'}</p>
        </div>
        {cycle.next_action&&<button className="button primary" type="button" onClick={()=>navigate(cycle.next_action?.target)}>Ir para ação</button>}
      </article>

      {readiness&&<article className={`panel finance-closing-readiness ${readiness.can_close?'ready':'blocked'}`}>
        <div className="finance-closing-readiness-head">
          <div><span className="eyebrow">Fechamento mensal</span><strong>{readiness.can_close?'Competência pronta para fechamento':'Existem bloqueadores antes do fechamento'}</strong><p>{readiness.can_close?'Banco, liquidações e obrigações registradas não apresentam bloqueios no fechamento.':readiness.blocker_count+' ponto(s) precisam ser tratados antes de considerar a competência encerrada.'}</p></div>
          <div className="finance-closing-readiness-score"><b>{readiness.blocker_count}</b><span>bloqueadores</span></div>
        </div>
        <div className="finance-closing-readiness-stats">
          <span>Contas fechadas <b>{readiness.accounts_closed_count}/{readiness.bank_accounts_count}</b></span>
          <span>Movimentos bancários pendentes <b>{readiness.unreconciled_bank_transactions_count}</b></span>
          <span>Exceções bancárias <b>{readiness.open_bank_exceptions_count}</b></span>
          <span>Liquidações divergentes <b>{readiness.settlement_gap_count+readiness.settlement_integrity_issues_count}</b></span>
          <span>Terceiros pendentes <b>{readiness.pending_third_party_count}</b></span>
          <span>Repasses pendentes <b>{readiness.pending_owner_repasses_count}</b></span>
        </div>
        {!readiness.can_close&&<div className="finance-closing-blockers">{readiness.blockers.map((item,index)=><span key={index}><AlertTriangle size={13}/>{item}</span>)}</div>}
        {!readiness.can_close&&<div className="finance-closing-actions"><button className="button secondary compact" type="button" onClick={()=>navigate('banking')}>Abrir conciliação</button><button className="button secondary compact" type="button" onClick={()=>navigate('bank-control')}>Controle bancário</button></div>}
      </article>}

      <div className="finance-cycle-metrics">
        <article className="panel finance-cycle-metric"><span>Cobrado</span><strong>{money(cycle.gross_amount)}</strong><small>{cycle.charges_count} cobrança(s) · {cycle.missing_charges} faltante(s)</small></article>
        <article className="panel finance-cycle-metric"><span>Recebido</span><strong>{money(cycle.received_amount)}</strong><small>{cycle.paid_charges} recebida(s) · {cycle.open_charges} em aberto</small></article>
        <article className="panel finance-cycle-metric"><span>Receita da imobiliária</span><strong>{money(cycle.agency_revenue_amount)}</strong><small>Taxas e retenções apuradas na liquidação</small></article>
        <article className="panel finance-cycle-metric"><span>Terceiros pendentes</span><strong>{money(cycle.third_party_pending_amount)}</strong><small>{cycle.third_party_pending_count} obrigação(ões), fora do caixa operacional</small></article>
        <article className="panel finance-cycle-metric"><span>Repasses pendentes</span><strong>{money(cycle.owner_repasse_pending_amount)}</strong><small>{cycle.owner_repasse_pending_count} repasse(s) ao proprietário</small></article>
        <article className={`panel finance-cycle-metric ${cycle.attention_count?'needs-attention':''}`}><span>Pontos de atenção</span><strong>{cycle.attention_count}</strong><small>{cycle.overdue_charges} cobrança(s) vencida(s) · {cycle.communications_failed_count} falha(s) de comunicação</small></article>
      </div>

      <div className="finance-cycle-flow">
        {cycle.steps.map((step,index)=><article className={`panel finance-cycle-step ${step.state}`} key={step.key}>
          <div className="finance-cycle-step-number">{index+1}</div>
          <div className="finance-cycle-step-body">
            <div className="finance-cycle-step-title">
              <div><strong>{step.title}</strong><span className={`finance-cycle-state ${step.state}`}>{stateLabels[step.state]}</span></div>
              <p>{step.summary}</p>
            </div>
            <small>{step.detail}</small>
          </div>
          <div className="finance-cycle-step-values">
            {Number(step.amount||0)>0&&<div><span>Total</span><strong>{money(step.amount)}</strong></div>}
            {Number(step.pending_amount||0)>0&&<div><span>Pendente</span><strong>{money(step.pending_amount)}</strong></div>}
            {Number(step.amount||0)===0&&Number(step.pending_amount||0)===0&&<div><span>Registros</span><strong>{step.count}</strong></div>}
          </div>
          <div className="finance-cycle-step-action">
            {step.action_label&&step.action_target&&<button className="button secondary compact" type="button" onClick={()=>navigate(step.action_target)}>{step.action_label}</button>}
          </div>
        </article>)}
      </div>

      <article className="panel finance-cycle-guardrail">
        <ShieldCheck size={18}/>
        <div><strong>Segregação preservada</strong><span>O ciclo usa os registros financeiros existentes. Valores de terceiros e do proprietário não são tratados como caixa operacional da imobiliária, e nenhuma comunicação é disparada automaticamente.</span></div>
        <CircleDollarSign size={18}/>
      </article>
    </>}
  </section>
}
