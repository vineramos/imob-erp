import {
  ArrowDownCircle,
  ArrowUpCircle,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  RefreshCw,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './finance-cashflow.css'

type Scope = 'operating'|'third_party'
type CashFlowView = 'day'|'week'|'month'
type CashFlowMode = 'realized'|'projected'|'mixed'
type CashFlowMovement = {
  id:string
  source_type:string
  source_code:string|null
  description:string
  counterparty_name:string|null
  category:string
  direction:'receivable'|'payable'
  amount:number
  state:'realized'|'projected'
}
type CashFlowDay = {
  date:string
  mode:CashFlowMode
  realized_receivables:number
  realized_payables:number
  projected_receivables:number
  projected_payables:number
  receivables:number
  payables:number
  net:number
  balance:number
  receivable_count:number
  payable_count:number
  movements:CashFlowMovement[]
}
type CashFlowPeriod = {
  fund_scope:Scope
  view:CashFlowView
  mode:CashFlowMode
  anchor_date:string
  start_date:string
  end_date:string
  today:string
  current_bank_balance:number
  opening_balance:number
  realized_receivables:number
  realized_payables:number
  projected_receivables:number
  projected_payables:number
  total_receivables:number
  total_payables:number
  closing_balance:number
  lowest_balance:number
  lowest_balance_date:string
  overdue_receivables:number
  overdue_payables:number
  days:CashFlowDay[]
}

const modeLabels:Record<CashFlowMode,string> = {realized:'Realizado',projected:'Projetado',mixed:'Realizado + projetado'}
const dayNames=['Dom','Seg','Ter','Qua','Qui','Sex','Sáb']
const sourceLabels:Record<string,string> = {bank:'Banco',rent:'Locação',owner_repasse:'Repasse',maintenance:'Manutenção',manual:'Manual'}

function money(value:number|null|undefined){return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function dateLabel(value:string|null|undefined){if(!value)return '—';return new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString('pt-BR')}
function longDate(value:string){return new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR',{weekday:'long',day:'2-digit',month:'long',year:'numeric'})}
function monthLabel(value:string){const text=new Date(`${value.slice(0,7)}-01T12:00:00`).toLocaleDateString('pt-BR',{month:'long',year:'numeric'});return text.charAt(0).toUpperCase()+text.slice(1)}
function todayInput(){const now=new Date();const offset=now.getTimezoneOffset();return new Date(now.getTime()-offset*60000).toISOString().slice(0,10)}
function parseLocal(value:string){return new Date(`${value}T12:00:00`)}
function toInput(value:Date){const offset=value.getTimezoneOffset();return new Date(value.getTime()-offset*60000).toISOString().slice(0,10)}
function periodLabel(flow:CashFlowPeriod){if(flow.view==='day')return longDate(flow.start_date);if(flow.view==='month')return monthLabel(flow.start_date);return `${dateLabel(flow.start_date)} — ${dateLabel(flow.end_date)}`}
function stateClass(mode:CashFlowMode){return mode==='realized'?'realized':mode==='projected'?'projected':'mixed'}

function DayDetail({day}:{day:CashFlowDay|null}){
  if(!day)return <div className="panel cashflow-day-detail empty"><CalendarDays size={22}/><span>Selecione um dia para ver os movimentos.</span></div>
  const realized=day.movements.filter(item=>item.state==='realized')
  const projected=day.movements.filter(item=>item.state==='projected')
  return <aside className="panel cashflow-day-detail">
    <div className="cashflow-detail-heading"><div><span className={`cashflow-mode-badge ${stateClass(day.mode)}`}>{modeLabels[day.mode]}</span><h3>{longDate(day.date)}</h3></div><strong className={day.net<0?'negative':'positive'}>{money(day.net)}</strong></div>
    <div className="cashflow-detail-totals"><div><span>Entradas</span><strong className="positive">{money(day.receivables)}</strong></div><div><span>Saídas</span><strong className="negative">{money(day.payables)}</strong></div><div><span>Saldo</span><strong>{money(day.balance)}</strong></div></div>
    <div className="cashflow-movement-scroll">
      {realized.length>0&&<MovementGroup title="Realizado" items={realized}/>} {projected.length>0&&<MovementGroup title="Projetado" items={projected}/>} {day.movements.length===0&&<div className="cashflow-no-movements"><CheckCircle2 size={18}/><span>Nenhum movimento neste dia.</span></div>}
    </div>
  </aside>
}

function MovementGroup({title,items}:{title:string;items:CashFlowMovement[]}){
  return <div className="cashflow-movement-group"><div className="cashflow-movement-group-title"><strong>{title}</strong><span>{items.length} movimento(s)</span></div>{items.map(item=><div className="cashflow-movement" key={`${item.state}-${item.id}`}><div className={`cashflow-movement-icon ${item.direction}`}>{item.direction==='receivable'?<ArrowDownCircle size={14}/>:<ArrowUpCircle size={14}/>}</div><div className="cashflow-movement-main"><div><strong>{item.description}</strong>{item.source_code&&<span>{item.source_code}</span>}</div><small>{sourceLabels[item.source_type]||item.category}{item.counterparty_name?` · ${item.counterparty_name}`:''}</small></div><strong className={item.direction==='receivable'?'positive':'negative'}>{money(item.amount)}</strong></div>)}</div>
}

export function FinanceCashFlowPanel(){
  const [view,setView]=useState<CashFlowView>('week')
  const [anchor,setAnchor]=useState(todayInput())
  const [scope,setScope]=useState<Scope>('operating')
  const [flow,setFlow]=useState<CashFlowPeriod|null>(null)
  const [selectedDate,setSelectedDate]=useState(todayInput())
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')

  const load=useCallback(async()=>{setLoading(true);setError('');try{const result=await apiRequest<CashFlowPeriod>(`/finance/treasury/cash-flow-period?view=${view}&anchor=${anchor}&fund_scope=${scope}`);setFlow(result);setSelectedDate(current=>{if(result.days.some(day=>day.date===current))return current;if(result.days.some(day=>day.date===result.today))return result.today;return result.start_date})}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o fluxo financeiro.')}finally{setLoading(false)}},[view,anchor,scope])
  useEffect(()=>{void load()},[load])

  const selectedDay=useMemo(()=>flow?.days.find(day=>day.date===selectedDate)||null,[flow,selectedDate])
  const calendarCells=useMemo(()=>{if(!flow||view!=='month')return [] as Array<CashFlowDay|null>;const first=parseLocal(flow.start_date).getDay();return [...Array.from({length:first},()=>null),...flow.days]},[flow,view])

  function movePeriod(direction:number){const next=parseLocal(anchor);if(view==='day')next.setDate(next.getDate()+direction);else if(view==='week')next.setDate(next.getDate()+7*direction);else{next.setDate(1);next.setMonth(next.getMonth()+direction)}setAnchor(toInput(next))}

  return <div className="cashflow-workspace">
    <div className="panel cashflow-toolbar">
      <div className="cashflow-scope-switch"><button type="button" className={scope==='operating'?'active':''} onClick={()=>setScope('operating')}><WalletCards size={14}/> Operacional</button><button type="button" className={scope==='third_party'?'active':''} onClick={()=>setScope('third_party')}><ShieldCheck size={14}/> Recursos de terceiros</button></div>
      <div className="cashflow-view-switch"><button type="button" className={view==='week'?'active':''} onClick={()=>setView('week')}>Semanal</button><button type="button" className={view==='month'?'active':''} onClick={()=>setView('month')}>Mensal</button><button type="button" className={view==='day'?'active':''} onClick={()=>setView('day')}>Diário</button></div>
      <div className="cashflow-period-nav"><button type="button" className="icon-button" onClick={()=>movePeriod(-1)} title="Período anterior"><ChevronLeft size={16}/></button><label><CalendarDays size={14}/><input type="date" value={anchor} onChange={event=>setAnchor(event.target.value)}/></label><button type="button" className="icon-button" onClick={()=>movePeriod(1)} title="Próximo período"><ChevronRight size={16}/></button><button type="button" className="button secondary compact" onClick={()=>setAnchor(todayInput())}>Hoje</button><button type="button" className="icon-button" onClick={()=>void load()} disabled={loading} title="Atualizar"><RefreshCw size={15}/></button></div>
    </div>

    {error&&<div className="form-alert danger-alert">{error}</div>}
    {loading&&!flow?<article className="panel settings-loading">Carregando fluxo financeiro...</article>:flow&&<>
      <div className="cashflow-period-heading"><div><span className="eyebrow">Fluxo financeiro · {view==='week'?'Semanal':view==='month'?'Mensal':'Diário'}</span><h2>{periodLabel(flow)}</h2></div><span className={`cashflow-mode-badge ${stateClass(flow.mode)}`}>{modeLabels[flow.mode]}</span></div>
      <div className="cashflow-metrics">
        <article className="panel cashflow-metric"><div><WalletCards size={15}/><span>Saldo inicial</span></div><strong>{money(flow.opening_balance)}</strong><small>{dateLabel(flow.start_date)}</small></article>
        <article className="panel cashflow-metric incoming"><div><ArrowDownCircle size={15}/><span>Entradas no período</span></div><strong>{money(flow.total_receivables)}</strong><small>{money(flow.realized_receivables)} realizado · {money(flow.projected_receivables)} projetado</small></article>
        <article className="panel cashflow-metric outgoing"><div><ArrowUpCircle size={15}/><span>Saídas no período</span></div><strong>{money(flow.total_payables)}</strong><small>{money(flow.realized_payables)} realizado · {money(flow.projected_payables)} projetado</small></article>
        <article className={`panel cashflow-metric ${flow.closing_balance<0?'danger':''}`}><div><TrendingUp size={15}/><span>Saldo final</span></div><strong>{money(flow.closing_balance)}</strong><small>{flow.mode==='realized'?'Fechamento realizado':flow.mode==='projected'?'Fechamento projetado':'Realizado até hoje + projeção futura'}</small></article>
      </div>
      <div className="cashflow-legend"><span><i className="dot realized"/> Realizado</span><span><i className="dot projected"/> Projetado</span><span><i className="dot mixed"/> Hoje / período misto</span>{(flow.overdue_receivables+flow.overdue_payables)>0&&<span className="warning"><Clock3 size={12}/> Vencidos trazidos para hoje: {money(flow.overdue_receivables+flow.overdue_payables)}</span>}{flow.lowest_balance<0&&<span className="danger"><TrendingDown size={12}/> Menor saldo: {money(flow.lowest_balance)} em {dateLabel(flow.lowest_balance_date)}</span>}</div>

      {view==='week'&&<div className="cashflow-week-layout"><div className="panel cashflow-table"><div className="cashflow-table-title"><div><strong>Semana</strong><span>Passado realizado; futuro projetado.</span></div></div><div className="cashflow-table-head"><span>Data</span><span>Entradas</span><span>Saídas</span><span>Saldo do dia</span><span>Saldo acumulado</span><span>Situação</span></div>{flow.days.map(day=><button type="button" className={`cashflow-table-row ${selectedDate===day.date?'selected':''}`} key={day.date} onClick={()=>setSelectedDate(day.date)}><div><strong>{dateLabel(day.date)}</strong><small>{dayNames[parseLocal(day.date).getDay()]}</small></div><strong className="positive">{money(day.receivables)}</strong><strong className="negative">{money(day.payables)}</strong><strong className={day.net<0?'negative':'positive'}>{money(day.net)}</strong><strong className={day.balance<0?'negative':''}>{money(day.balance)}</strong><span className={`cashflow-mode-badge ${stateClass(day.mode)}`}>{modeLabels[day.mode]}</span></button>)}</div><DayDetail day={selectedDay}/></div>}

      {view==='month'&&<div className="cashflow-month-layout"><div className="panel cashflow-calendar"><div className="cashflow-calendar-head">{dayNames.map(name=><span key={name}>{name}</span>)}</div><div className="cashflow-calendar-grid">{calendarCells.map((day,index)=>day?<button type="button" key={day.date} className={`cashflow-calendar-day ${selectedDate===day.date?'selected':''} ${day.balance<0?'negative-day':''} ${stateClass(day.mode)}`} onClick={()=>setSelectedDate(day.date)}><div><strong>{parseLocal(day.date).getDate()}</strong><span className={`cashflow-mode-dot ${stateClass(day.mode)}`}/></div><span className="positive">{money(day.receivables)}</span><span className="negative">{money(day.payables)}</span><span className={day.balance<0?'negative':'balance'}>{money(day.balance)}</span></button>:<div className="cashflow-calendar-day blank" key={`blank-${index}`}/>)}</div></div><DayDetail day={selectedDay}/></div>}

      {view==='day'&&<div className="cashflow-day-layout"><div className="panel cashflow-day-summary"><div className="cashflow-day-summary-top"><div><span className={`cashflow-mode-badge ${stateClass(selectedDay?.mode||flow.mode)}`}>{modeLabels[selectedDay?.mode||flow.mode]}</span><h3>{selectedDay?longDate(selectedDay.date):periodLabel(flow)}</h3></div><strong className={(selectedDay?.net||0)<0?'negative':'positive'}>{money(selectedDay?.net||0)}</strong></div><div className="cashflow-day-equation"><div><span>Saldo inicial</span><strong>{money(flow.opening_balance)}</strong></div><i>+</i><div><span>Entradas</span><strong className="positive">{money(selectedDay?.receivables||0)}</strong></div><i>−</i><div><span>Saídas</span><strong className="negative">{money(selectedDay?.payables||0)}</strong></div><i>=</i><div><span>Saldo final</span><strong>{money(selectedDay?.balance||flow.closing_balance)}</strong></div></div></div><DayDetail day={selectedDay}/></div>}
    </>}
  </div>
}
