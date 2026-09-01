import {
  ArrowDownCircle,
  ArrowUpCircle,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Plus,
  RefreshCw,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import { FinanceManualTitleModal } from './FinanceManualTitleModal'
import './finance-cashflow.css'
import './finance-cashflow-daily.css'

type Scope = 'operating'|'third_party'
type Direction = 'receivable'|'payable'
type CashFlowView = 'day'|'week'|'month'
type CashFlowMode = 'realized'|'projected'|'mixed'
type CashFlowMovement = { id:string;source_type:string;source_code:string|null;description:string;counterparty_name:string|null;category:string;direction:Direction;amount:number;state:'realized'|'projected' }
type CashFlowDay = { date:string;mode:CashFlowMode;realized_receivables:number;realized_payables:number;projected_receivables:number;projected_payables:number;receivables:number;payables:number;net:number;balance:number;receivable_count:number;payable_count:number;movements:CashFlowMovement[] }
type CashFlowPeriod = { fund_scope:Scope;view:CashFlowView;mode:CashFlowMode;anchor_date:string;start_date:string;end_date:string;today:string;current_bank_balance:number;opening_balance:number;realized_receivables:number;realized_payables:number;projected_receivables:number;projected_payables:number;total_receivables:number;total_payables:number;closing_balance:number;lowest_balance:number;lowest_balance_date:string;overdue_receivables:number;overdue_payables:number;days:CashFlowDay[] }
type DailyRow={key:string;label:string;direction:Direction;values:Record<string,number>}
type Drilldown={date:string;rowKey:string;label:string;direction:Direction}

const modeLabels:Record<CashFlowMode,string> = {realized:'Realizado',projected:'Projetado',mixed:'Realizado + projetado'}
const dayNames=['Dom','Seg','Ter','Qua','Qui','Sex','Sáb']
const sourceLabels:Record<string,string> = {bank:'Banco',rent:'Locação',owner_repasse:'Repasse',maintenance:'Manutenção',manual:'Manual',commission:'Comissão'}

function money(value:number|null|undefined){return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function dateLabel(value:string|null|undefined){if(!value)return '—';return new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString('pt-BR')}
function longDate(value:string){return new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR',{weekday:'long',day:'2-digit',month:'long',year:'numeric'})}
function monthLabel(value:string){const text=new Date(`${value.slice(0,7)}-01T12:00:00`).toLocaleDateString('pt-BR',{month:'long',year:'numeric'});return text.charAt(0).toUpperCase()+text.slice(1)}
function todayInput(){const now=new Date();const offset=now.getTimezoneOffset();return new Date(now.getTime()-offset*60000).toISOString().slice(0,10)}
function parseLocal(value:string){return new Date(`${value}T12:00:00`)}
function toInput(value:Date){const offset=value.getTimezoneOffset();return new Date(value.getTime()-offset*60000).toISOString().slice(0,10)}
function periodLabel(flow:CashFlowPeriod){if(flow.view==='day')return longDate(flow.start_date);if(flow.view==='month')return monthLabel(flow.start_date);return `${dateLabel(flow.start_date)} — ${dateLabel(flow.end_date)}`}
function stateClass(mode:CashFlowMode){return mode==='realized'?'realized':mode==='projected'?'projected':'mixed'}
function dailyCategory(item:CashFlowMovement){
  if(item.direction==='receivable'&&item.source_type==='rent')return 'Aluguéis'
  if(item.direction==='receivable'&&item.source_type==='maintenance')return 'Manutenções · recebimentos'
  if(item.direction==='payable'&&item.source_type==='owner_repasse')return 'Parte dos proprietários / repasses'
  if(item.direction==='payable'&&item.source_type==='maintenance')return 'Manutenções · parceiros'
  if(item.source_type==='commission')return item.category||'Comissões'
  if(item.source_type==='manual')return item.category||`${item.direction==='receivable'?'Outras entradas':'Outras saídas'}`
  if(item.source_type==='bank')return 'Movimentos bancários não classificados'
  return item.category||sourceLabels[item.source_type]||'Outros'
}
function categoryPriority(row:DailyRow){
  const order=['Aluguéis','Manutenções · recebimentos','Parte dos proprietários / repasses','Comissões · corretores','Comissões','Angariações','Manutenções · parceiros','Colaboradores','Aluguel da sede','Energia elétrica','Água','Internet / telefonia','Insumos','Impostos e taxas','Serviços de terceiros','Movimentos bancários não classificados']
  const index=order.indexOf(row.label)
  return index<0?100:index
}

function MovementGroup({title,items}:{title:string;items:CashFlowMovement[]}){return <div className="cashflow-movement-group"><div className="cashflow-movement-group-title"><strong>{title}</strong><span>{items.length} movimento(s)</span></div>{items.map(item=><div className="cashflow-movement" key={`${item.state}-${item.id}`}><div className={`cashflow-movement-icon ${item.direction}`}>{item.direction==='receivable'?<ArrowDownCircle size={14}/>:<ArrowUpCircle size={14}/>}</div><div className="cashflow-movement-main"><div><strong>{item.description}</strong>{item.source_code&&<span>{item.source_code}</span>}</div><small>{sourceLabels[item.source_type]||item.category}{item.counterparty_name?` · ${item.counterparty_name}`:''}</small></div><strong className={item.direction==='receivable'?'positive':'negative'}>{money(item.amount)}</strong></div>)}</div>}
function DayDetail({day}:{day:CashFlowDay|null}){
  if(!day)return <div className="panel cashflow-day-detail empty"><CalendarDays size={22}/><span>Selecione um dia para ver os movimentos.</span></div>
  const realized=day.movements.filter(item=>item.state==='realized'),projected=day.movements.filter(item=>item.state==='projected')
  return <aside className="panel cashflow-day-detail"><div className="cashflow-detail-heading"><div><span className={`cashflow-mode-badge ${stateClass(day.mode)}`}>{modeLabels[day.mode]}</span><h3>{longDate(day.date)}</h3></div><strong className={day.net<0?'negative':'positive'}>{money(day.net)}</strong></div><div className="cashflow-detail-totals"><div><span>Entradas</span><strong className="positive">{money(day.receivables)}</strong></div><div><span>Saídas</span><strong className="negative">{money(day.payables)}</strong></div><div><span>Saldo</span><strong>{money(day.balance)}</strong></div></div><div className="cashflow-movement-scroll">{realized.length>0&&<MovementGroup title="Realizado" items={realized}/>} {projected.length>0&&<MovementGroup title="Projetado" items={projected}/>} {day.movements.length===0&&<div className="cashflow-no-movements"><CheckCircle2 size={18}/><span>Nenhum movimento neste dia.</span></div>}</div></aside>
}

export function FinanceCashFlowPanel(){
  const [view,setView]=useState<CashFlowView>('week')
  const [anchor,setAnchor]=useState(todayInput())
  const [scope,setScope]=useState<Scope>('operating')
  const [flow,setFlow]=useState<CashFlowPeriod|null>(null)
  const [selectedDate,setSelectedDate]=useState(todayInput())
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [manualDirection,setManualDirection]=useState<Direction|null>(null)
  const [drilldown,setDrilldown]=useState<Drilldown|null>(null)

  const load=useCallback(async()=>{setLoading(true);setError('');try{const requestView:CashFlowView=view==='day'?'month':view;const result=await apiRequest<CashFlowPeriod>(`/finance/treasury/cash-flow-period?view=${requestView}&anchor=${anchor}&fund_scope=${scope}`);setFlow(result);setSelectedDate(current=>{if(result.days.some(day=>day.date===current))return current;if(result.days.some(day=>day.date===result.today))return result.today;return result.start_date});setDrilldown(null)}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o fluxo financeiro.')}finally{setLoading(false)}},[view,anchor,scope])
  useEffect(()=>{void load()},[load])
  const selectedDay=useMemo(()=>flow?.days.find(day=>day.date===selectedDate)||null,[flow,selectedDate])
  const calendarCells=useMemo(()=>{if(!flow||view!=='month')return [] as Array<CashFlowDay|null>;const first=parseLocal(flow.start_date).getDay();return [...Array.from({length:first},()=>null),...flow.days]},[flow,view])
  const dailyRows=useMemo(()=>{
    if(!flow||view!=='day')return [] as DailyRow[]
    const map=new Map<string,DailyRow>()
    for(const day of flow.days)for(const movement of day.movements){const label=dailyCategory(movement);const key=`${movement.direction}:${label}`;const row=map.get(key)||{key,label,direction:movement.direction,values:{}};row.values[day.date]=(row.values[day.date]||0)+movement.amount;map.set(key,row)}
    return [...map.values()].sort((a,b)=>a.direction===b.direction?(categoryPriority(a)-categoryPriority(b)||a.label.localeCompare(b.label)):a.direction==='receivable'?-1:1)
  },[flow,view])
  const dailyIncoming=dailyRows.filter(row=>row.direction==='receivable'),dailyOutgoing=dailyRows.filter(row=>row.direction==='payable')
  const drillItems=useMemo(()=>{if(!flow||!drilldown)return [] as CashFlowMovement[];const day=flow.days.find(item=>item.date===drilldown.date);return (day?.movements||[]).filter(item=>item.direction===drilldown.direction&&dailyCategory(item)===drilldown.label)},[flow,drilldown])

  function movePeriod(direction:number){const next=parseLocal(anchor);if(view==='week')next.setDate(next.getDate()+7*direction);else{next.setDate(1);next.setMonth(next.getMonth()+direction)}setAnchor(toInput(next))}
  function openDrill(day:string,row:DailyRow){if(!row.values[day])return;setDrilldown({date:day,rowKey:row.key,label:row.label,direction:row.direction})}
  function dailyValue(value:number|undefined,direction?:Direction){if(!value)return <span className="cashflow-daily-zero">—</span>;return <span className={direction==='receivable'?'positive':direction==='payable'?'negative':''}>{money(value)}</span>}

  return <div className="cashflow-workspace"><div className="panel cashflow-toolbar"><div className="cashflow-scope-switch"><button type="button" className={scope==='operating'?'active':''} onClick={()=>setScope('operating')}><WalletCards size={14}/> Operacional</button><button type="button" className={scope==='third_party'?'active':''} onClick={()=>setScope('third_party')}><ShieldCheck size={14}/> Recursos de terceiros</button></div><div className="cashflow-view-switch"><button type="button" className={view==='week'?'active':''} onClick={()=>setView('week')}>Semanal</button><button type="button" className={view==='month'?'active':''} onClick={()=>setView('month')}>Mensal</button><button type="button" className={view==='day'?'active':''} onClick={()=>setView('day')}>Diário</button></div><div className="cashflow-period-nav"><button type="button" className="icon-button" onClick={()=>movePeriod(-1)} title="Período anterior"><ChevronLeft size={16}/></button><label><CalendarDays size={14}/><input type="date" value={anchor} onChange={event=>setAnchor(event.target.value)}/></label><button type="button" className="icon-button" onClick={()=>movePeriod(1)} title="Próximo período"><ChevronRight size={16}/></button><button type="button" className="button secondary compact" onClick={()=>setAnchor(todayInput())}>Hoje</button><button type="button" className="icon-button" onClick={()=>void load()} disabled={loading} title="Atualizar"><RefreshCw size={15}/></button></div></div>

    <div className="cashflow-create-actions"><div><strong>Lançamento eventual</strong><span>Contas manuais entram na Visão Geral, no fluxo e na conciliação. Prefira sempre a origem automática quando existir.</span></div><button className="button secondary compact" type="button" onClick={()=>setManualDirection('receivable')}><Plus size={13}/> Conta a receber</button><button className="button primary compact" type="button" onClick={()=>setManualDirection('payable')}><Plus size={13}/> Conta a pagar</button></div>
    {success&&<div className="form-alert success-alert">{success}</div>}{error&&<div className="form-alert danger-alert">{error}</div>}{loading&&!flow?<article className="panel settings-loading">Carregando fluxo financeiro...</article>:flow&&<>
      <div className="cashflow-period-heading"><div><span className="eyebrow">Fluxo financeiro · {view==='week'?'Semanal':view==='month'?'Mensal':'Diário por categoria'}</span><h2>{view==='day'?monthLabel(flow.start_date):periodLabel(flow)}</h2></div><span className={`cashflow-mode-badge ${stateClass(flow.mode)}`}>{modeLabels[flow.mode]}</span></div>
      <div className="cashflow-metrics"><article className="panel cashflow-metric"><div><WalletCards size={15}/><span>Saldo inicial</span></div><strong>{money(flow.opening_balance)}</strong><small>{dateLabel(flow.start_date)}</small></article><article className="panel cashflow-metric incoming"><div><ArrowDownCircle size={15}/><span>Entradas no período</span></div><strong>{money(flow.total_receivables)}</strong><small>{money(flow.realized_receivables)} realizado · {money(flow.projected_receivables)} projetado</small></article><article className="panel cashflow-metric outgoing"><div><ArrowUpCircle size={15}/><span>Saídas no período</span></div><strong>{money(flow.total_payables)}</strong><small>{money(flow.realized_payables)} realizado · {money(flow.projected_payables)} projetado</small></article><article className={`panel cashflow-metric ${flow.closing_balance<0?'danger':''}`}><div><TrendingUp size={15}/><span>Saldo final</span></div><strong>{money(flow.closing_balance)}</strong><small>{flow.mode==='realized'?'Fechamento realizado':flow.mode==='projected'?'Fechamento projetado':'Realizado até hoje + projeção futura'}</small></article></div>
      <div className="cashflow-legend"><span><i className="dot realized"/> Realizado</span><span><i className="dot projected"/> Projetado</span><span><i className="dot mixed"/> Hoje / período misto</span>{(flow.overdue_receivables+flow.overdue_payables)>0&&<span className="warning"><Clock3 size={12}/> Vencidos trazidos para hoje: {money(flow.overdue_receivables+flow.overdue_payables)}</span>}{flow.lowest_balance<0&&<span className="danger"><TrendingDown size={12}/> Menor saldo: {money(flow.lowest_balance)} em {dateLabel(flow.lowest_balance_date)}</span>}</div>

      {view==='week'&&<div className="cashflow-week-layout"><div className="panel cashflow-table"><div className="cashflow-table-title"><div><strong>Semana</strong><span>Passado realizado; futuro projetado.</span></div></div><div className="cashflow-table-head"><span>Data</span><span>Entradas</span><span>Saídas</span><span>Saldo do dia</span><span>Saldo acumulado</span><span>Situação</span></div>{flow.days.map(day=><button type="button" className={`cashflow-table-row ${selectedDate===day.date?'selected':''}`} key={day.date} onClick={()=>setSelectedDate(day.date)}><div><strong>{dateLabel(day.date)}</strong><small>{dayNames[parseLocal(day.date).getDay()]}</small></div><strong className="positive">{money(day.receivables)}</strong><strong className="negative">{money(day.payables)}</strong><strong className={day.net<0?'negative':'positive'}>{money(day.net)}</strong><strong className={day.balance<0?'negative':''}>{money(day.balance)}</strong><span className={`cashflow-mode-badge ${stateClass(day.mode)}`}>{modeLabels[day.mode]}</span></button>)}</div><DayDetail day={selectedDay}/></div>}
      {view==='month'&&<div className="cashflow-month-layout"><div className="panel cashflow-calendar"><div className="cashflow-calendar-head">{dayNames.map(name=><span key={name}>{name}</span>)}</div><div className="cashflow-calendar-grid">{calendarCells.map((day,index)=>day?<button type="button" key={day.date} className={`cashflow-calendar-day ${selectedDate===day.date?'selected':''} ${day.balance<0?'negative-day':''} ${stateClass(day.mode)}`} onClick={()=>setSelectedDate(day.date)}><div><strong>{parseLocal(day.date).getDate()}</strong><span className={`cashflow-mode-dot ${stateClass(day.mode)}`}/></div><span className="positive">{money(day.receivables)}</span><span className="negative">{money(day.payables)}</span><span className={day.balance<0?'negative':'balance'}>{money(day.balance)}</span></button>:<div className="cashflow-calendar-day blank" key={`blank-${index}`}/>)}</div></div><DayDetail day={selectedDay}/></div>}
      {view==='day'&&<><div className="panel cashflow-daily-matrix"><div className="cashflow-daily-caption"><div><strong>Movimentação diária por origem</strong><span>Cada coluna é um dia. Clique em qualquer valor para abrir a composição daquele lançamento.</span></div><small>{scope==='operating'?'Repasses de proprietários ficam em Recursos de terceiros.':'Aqui ficam aluguéis recebidos e repasses de proprietários, separados do caixa próprio.'}</small></div><div className="cashflow-daily-scroll"><table className="cashflow-daily-table"><thead><tr><th className="daily-label">Origem / categoria</th>{flow.days.map(day=><th key={day.date} className={day.date===flow.today?'today':''}><strong>{String(parseLocal(day.date).getDate()).padStart(2,'0')}</strong><span>{dayNames[parseLocal(day.date).getDay()]}</span></th>)}</tr></thead><tbody>
        <tr className="cashflow-daily-group"><th className="daily-label">ENTRADAS</th><td colSpan={flow.days.length}/></tr>{dailyIncoming.map(row=><tr className="cashflow-daily-row" key={row.key}><th className="daily-label">{row.label}</th>{flow.days.map(day=><td key={day.date}>{row.values[day.date]?<button type="button" className={`cashflow-daily-value positive ${drilldown?.date===day.date&&drilldown.rowKey===row.key?'selected':''}`} onClick={()=>openDrill(day.date,row)}>{money(row.values[day.date])}</button>:<span className="cashflow-daily-zero">—</span>}</td>)}</tr>)}{dailyIncoming.length===0&&<tr className="cashflow-daily-row muted"><th className="daily-label">Sem categorias de entrada</th>{flow.days.map(day=><td key={day.date}>—</td>)}</tr>}
        <tr className="cashflow-daily-total incoming"><th className="daily-label">Total entradas</th>{flow.days.map(day=><td key={day.date}>{dailyValue(day.receivables,'receivable')}</td>)}</tr>
        <tr className="cashflow-daily-group"><th className="daily-label">SAÍDAS</th><td colSpan={flow.days.length}/></tr>{dailyOutgoing.map(row=><tr className="cashflow-daily-row" key={row.key}><th className="daily-label">{row.label}</th>{flow.days.map(day=><td key={day.date}>{row.values[day.date]?<button type="button" className={`cashflow-daily-value negative ${drilldown?.date===day.date&&drilldown.rowKey===row.key?'selected':''}`} onClick={()=>openDrill(day.date,row)}>{money(row.values[day.date])}</button>:<span className="cashflow-daily-zero">—</span>}</td>)}</tr>)}{dailyOutgoing.length===0&&<tr className="cashflow-daily-row muted"><th className="daily-label">Sem categorias de saída</th>{flow.days.map(day=><td key={day.date}>—</td>)}</tr>}
        <tr className="cashflow-daily-total outgoing"><th className="daily-label">Total saídas</th>{flow.days.map(day=><td key={day.date}>{dailyValue(day.payables,'payable')}</td>)}</tr><tr className="cashflow-daily-balance"><th className="daily-label">Saldo do dia</th>{flow.days.map(day=><td key={day.date} className={day.net<0?'negative':day.net>0?'positive':''}>{money(day.net)}</td>)}</tr><tr className="cashflow-daily-balance accumulated"><th className="daily-label">Saldo acumulado</th>{flow.days.map(day=><td key={day.date} className={day.balance<0?'negative':''}>{money(day.balance)}</td>)}</tr>
      </tbody></table></div></div>{drilldown&&<article className="panel cashflow-daily-drilldown"><div className="cashflow-daily-drilldown-head"><div><span className="eyebrow">Composição do valor</span><h3>{drilldown.label} · {dateLabel(drilldown.date)}</h3><p>{drillItems.length} lançamento(s) · {money(drillItems.reduce((sum,item)=>sum+item.amount,0))}</p></div><button className="button secondary compact" type="button" onClick={()=>setDrilldown(null)}>Fechar</button></div><MovementGroup title={drilldown.direction==='receivable'?'Entradas':'Saídas'} items={drillItems}/></article>}</>}
    </>}
    {manualDirection&&<FinanceManualTitleModal direction={manualDirection} onClose={()=>setManualDirection(null)} onCreated={message=>{setSuccess(message);void load()}}/>}
  </div>
}
