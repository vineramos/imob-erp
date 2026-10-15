import { AlertTriangle, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, CircleDollarSign, RefreshCw, ShieldCheck } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './finance-navigation.css'
import type { ViewMode } from '../../components/TopHeader'
import { ApiError, apiRequest } from '../../api/client'
const FinanceBankControlPanel = lazy(() => import('./FinanceBankControlPanel').then(module => ({ default: module.FinanceBankControlPanel })))
const FinanceBankSetupPanel = lazy(() => import('./FinanceBankSetupPanel').then(module => ({ default: module.FinanceBankSetupPanel })))
const FinanceBankingPanel = lazy(() => import('./FinanceBankingPanel').then(module => ({ default: module.FinanceBankingPanel })))
const FinanceBillingPanel = lazy(() => import('./FinanceBillingPanel').then(module => ({ default: module.FinanceBillingPanel })))
const FinanceReceivablesPanel = lazy(() => import('./FinanceReceivablesPanel').then(module => ({ default: module.FinanceReceivablesPanel })))
const FinanceRepassesPanel = lazy(() => import('./FinanceRepassesPanel').then(module => ({ default: module.FinanceRepassesPanel })))
const FinanceClassificationsPanel = lazy(() => import('./FinanceClassificationsPanel').then(module => ({ default: module.FinanceClassificationsPanel })))
const FinanceCommissionsPanel = lazy(() => import('./FinanceCommissionsPanel').then(module => ({ default: module.FinanceCommissionsPanel })))
const FinanceCorePanel = lazy(() => import('./FinanceCorePanel').then(module => ({ default: module.FinanceCorePanel })))
const FinanceDelinquencyPanel = lazy(() => import('./FinanceDelinquencyPanel').then(module => ({ default: module.FinanceDelinquencyPanel })))
const FinanceInterPanel = lazy(() => import('./FinanceInterPanel').then(module => ({ default: module.FinanceInterPanel })))
const FinanceMonthlyCyclePanel = lazy(() => import('./FinanceMonthlyCyclePanel').then(module => ({ default: module.FinanceMonthlyCyclePanel })))
const FinanceRentPage = lazy(() => import('./FinanceRentPage').then(module => ({ default: module.FinancePage })))
const FinancePortalsPanel = lazy(() => import('./FinancePortalsPanel').then(module => ({ default: module.FinancePortalsPanel })))
const FinanceReportsPanel = lazy(() => import('./FinanceReportsPanel').then(module => ({ default: module.FinanceReportsPanel })))
const FinanceTreasuryPanel = lazy(() => import('./FinanceTreasuryPanel').then(module => ({ default: module.FinanceTreasuryPanel })))
const MaintenanceFinancePanel = lazy(() => import('./MaintenanceFinancePanel').then(module => ({ default: module.MaintenanceFinancePanel })))

type Area = 'overview'|'ledger'|'cycle'|'billing'|'billing-batches'|'repasses'|'delinquency'|'treasury'|'banking'|'bank-setup'|'bank-control'|'inter'|'reports'|'commissions'|'classifications'|'portals'|'rent'|'maintenance'
type Dashboard = {
  competence:string
  open_amount:number
  overdue_amount:number
  critical_overdue_amount:number
  received_amount:number
  agency_revenue_amount:number
  pending_repasse_amount:number
  charges_open:number
  charges_overdue:number
  charges_critical:number
  repasses_pending:number
}
type CommissionEntry = { id:string; amount:number; status:string }

const money=(value:number)=>Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
const currentMonth=()=>{const now=new Date();return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`}
const monthLabel=(month:string)=>new Date(`${month}-01T12:00:00`).toLocaleDateString('pt-BR',{month:'long',year:'numeric'})

function FinanceDashboardPanel({onNavigate,month,setMonth}:{onNavigate:(area:Area)=>void;month:string;setMonth:(next:string|((month:string)=>string))=>void}){
  const requestId=useRef(0)
  const [dashboard,setDashboard]=useState<Dashboard|null>(null)
  const [commissions,setCommissions]=useState<CommissionEntry[]>([])
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const competence=`${month}-01`

  const load=useCallback(async()=>{
    const request=++requestId.current
    setLoading(true);setError('')
    try{
      const [summary,commissionRows]=await Promise.all([
        apiRequest<Dashboard>(`/finance/dashboard?competence=${competence}`),
        apiRequest<CommissionEntry[]>(`/finance/advanced/commissions?competence=${competence}`),
      ])
      if(request!==requestId.current)return
      setDashboard(summary)
      setCommissions(commissionRows)
    }catch(cause){
      if(request===requestId.current)setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o dashboard financeiro.')
    }finally{if(request===requestId.current)setLoading(false)}
  },[competence])
  useEffect(()=>{void load();return()=>{requestId.current+=1}},[load])

  const pendingCommissions=useMemo(()=>commissions.filter(item=>!['paid','cancelled'].includes(item.status)),[commissions])
  const pendingCommissionAmount=useMemo(()=>pendingCommissions.reduce((total,item)=>total+Number(item.amount||0),0),[pendingCommissions])
  function moveMonth(step:number){const [year,monthNumber]=month.split('-').map(Number);const next=new Date(year,monthNumber-1+step,1);setMonth(`${next.getFullYear()}-${String(next.getMonth()+1).padStart(2,'0')}`)}

  const alerts=dashboard?[
    dashboard.charges_critical>0?{key:'critical',title:`${dashboard.charges_critical} cobrança(s) em atraso crítico`,detail:`${money(dashboard.critical_overdue_amount)} exigem atuação prioritária.`,target:'delinquency' as Area,tone:'danger'}:null,
    dashboard.repasses_pending>0?{key:'repasses',title:`${dashboard.repasses_pending} repasse(s) pendente(s)`,detail:`${money(dashboard.pending_repasse_amount)} aguardam processamento ou baixa.`,target:'repasses' as Area,tone:'warning'}:null,
    pendingCommissions.length>0?{key:'commissions',title:`${pendingCommissions.length} comissão(ões) pendente(s)`,detail:`${money(pendingCommissionAmount)} ainda não concluídos no fluxo financeiro.`,target:'commissions' as Area,tone:'warning'}:null,
  ].filter(Boolean) as {key:string;title:string;detail:string;target:Area;tone:string}[]:[]

  return <section className="workspace finance-workspace finance-dashboard">
    <div className="page-heading finance-heading finance-dashboard-heading">
      <div className="finance-dashboard-copy"><span className="eyebrow">Financeiro · Visão geral</span><h1>Dashboard financeiro</h1><p>Caixa, inadimplência, repasses e comissões em uma leitura operacional da competência.</p></div>
      <div className="heading-actions finance-dashboard-controls">
        <div className="finance-competence-control">
          <button className="icon-button" type="button" onClick={()=>moveMonth(-1)} aria-label="Competência anterior"><ChevronLeft size={15}/></button>
          <label className="finance-month"><CalendarDays size={14}/><span>Competência</span><input type="month" value={month} onChange={event=>setMonth(event.target.value)}/></label>
          <button className="icon-button" type="button" onClick={()=>moveMonth(1)} aria-label="Próxima competência"><ChevronRight size={15}/></button>
        </div>
        <button className="button secondary finance-refresh" type="button" onClick={()=>void load()} disabled={loading}><RefreshCw size={14}/> Atualizar</button>
      </div>
    </div>

    {error&&<div className="form-alert danger-alert">{error}</div>}
    {loading&&!dashboard?<article className="panel settings-loading">Carregando dashboard financeiro...</article>:dashboard&&<>
      <div className="finance-metrics finance-dashboard-metrics">
        <article className="panel finance-metric"><span>Recebimentos do mês</span><strong>{money(dashboard.received_amount)}</strong><small>{monthLabel(month)}</small></article>
        <article className="panel finance-metric"><span>Valores em aberto</span><strong>{money(dashboard.open_amount)}</strong><small>{dashboard.charges_open} cobrança(s)</small></article>
        <article className={`panel finance-metric ${dashboard.charges_overdue?'critical':''}`}><span>Inadimplência</span><strong>{money(dashboard.overdue_amount)}</strong><small>{dashboard.charges_overdue} cobrança(s) vencida(s)</small></article>
        <article className="panel finance-metric"><span>Repasses pendentes</span><strong>{money(dashboard.pending_repasse_amount)}</strong><small>{dashboard.repasses_pending} repasse(s)</small></article>
        <article className="panel finance-metric"><span>Receita da imobiliária</span><strong>{money(dashboard.agency_revenue_amount)}</strong><small>Taxas e retenções da competência</small></article>
        <article className="panel finance-metric"><span>Comissões pendentes</span><strong>{money(pendingCommissionAmount)}</strong><small>{pendingCommissions.length} comissão(ões)</small></article>
      </div>

      <div className="finance-core-master-detail finance-dashboard-lower">
        <article className="panel finance-advanced-card finance-dashboard-alerts">
          <div className="finance-advanced-card-head"><div><span className="eyebrow">Atenção operacional</span><h2>Alertas críticos</h2><p>Somente pendências que exigem ação financeira ou acompanhamento.</p></div><AlertTriangle size={20}/></div>
          <div className="finance-compact-list">
            {alerts.map(alert=><button type="button" className="finance-compact-row" key={alert.key} onClick={()=>onNavigate(alert.target)} style={{width:'100%',border:0,textAlign:'left',cursor:'pointer'}}>
              <div><strong>{alert.title}</strong><span>{alert.detail}</span><small>Abrir área responsável</small></div><i className={`status-badge ${alert.tone}`}>{alert.tone==='danger'?'Crítico':'Pendente'}</i>
            </button>)}
            {alerts.length===0&&<div className="finance-empty compact"><ShieldCheck size={23}/><strong>Nenhum alerta crítico agora.</strong><span>Não há cobranças críticas, repasses ou comissões pendentes para esta leitura.</span></div>}
          </div>
        </article>

        <aside className="panel finance-core-detail finance-dashboard-summary">
          <div className="finance-core-detail-head"><div><span className="eyebrow">Competência</span><h2>{monthLabel(month)}</h2><p>Resumo operacional consolidado</p></div><CircleDollarSign size={19}/></div>
          <div className="finance-core-detail-grid">
            <div><span>Cobranças abertas</span><strong>{dashboard.charges_open}</strong></div>
            <div><span>Vencidas</span><strong>{dashboard.charges_overdue}</strong></div>
            <div><span>Atraso crítico</span><strong>{dashboard.charges_critical}</strong></div>
            <div><span>Repasses pendentes</span><strong>{dashboard.repasses_pending}</strong></div>
            <div><span>Valor crítico</span><strong>{money(dashboard.critical_overdue_amount)}</strong></div>
            <div><span>Comissões pendentes</span><strong>{pendingCommissions.length}</strong></div>
          </div>
          <div className="finance-core-detail-actions"><button className="button secondary" type="button" onClick={()=>onNavigate('ledger')}>Ver lançamentos</button><button className="button primary" type="button" onClick={()=>onNavigate('billing')}>Abrir cobranças</button><button className="button secondary" type="button" onClick={()=>onNavigate('commissions')}>Ver comissões</button></div>
        </aside>
      </div>
    </>}
  </section>
}

export function FinancePage({permissions,viewMode}:{permissions:string[];viewMode:ViewMode}){
  const [area,setArea]=useState<Area>(()=>viewMode==='essential'?'billing':viewMode==='managerial'?'ledger':'overview')
  const [month,setMonth]=useState(currentMonth())
  const moreRef=useRef<HTMLDetailsElement>(null)
  const choose=(next:Area)=>{ setArea(next); if(moreRef.current)moreRef.current.open=false }
  const primaryAreas: {key:Area;label:string}[]=[
    {key:'billing',label:'Contas a receber'},
    {key:'ledger',label:'Lançamentos'},
    {key:'repasses',label:'Repasses'},
    {key:'delinquency',label:'Inadimplência'},
  ]
  const groups: {label:string;items:{key:Area;label:string}[]}[]=[
    {label:'Operação',items:[
      {key:'cycle',label:'Ciclo mensal'},{key:'billing-batches',label:'Emissão em lote'},
      {key:'commissions',label:'Comissões'},{key:'treasury',label:'Tesouraria'},
      {key:'rent',label:'Locações'},{key:'maintenance',label:'Manutenções'},
    ]},
    {label:'Bancos',items:[
      {key:'banking',label:'Bancos'},{key:'inter',label:'Banco Inter'},
      {key:'bank-setup',label:'Contas e APIs'},{key:'bank-control',label:'Controle bancário'},
    ]},
    {label:'Análise e configuração',items:[
      {key:'overview',label:'Visão geral'},...(permissions.includes('reports.view')?[{key:'reports' as Area,label:'Relatórios'}]:[]),
      {key:'classifications',label:'Classificações'},{key:'portals',label:'Portais'},
    ]},
  ]
  const allSecondary=groups.flatMap(group=>group.items)
  const secondaryActive=allSecondary.find(item=>item.key===area)
  return <><div className={`workspace finance-area-switch finance-nav-workspace finance-view-${viewMode}`}>
    <nav className="panel finance-nav-shell" aria-label="Navegação do Financeiro">
      <div className="finance-primary-tabs" role="group" aria-label="Operações financeiras frequentes">
        {primaryAreas.map(item=><button key={item.key} type="button" className={area===item.key?'active':''} onClick={()=>choose(item.key)}>{item.label}</button>)}
      </div>
      <details className={'finance-more'+(secondaryActive?' active':'')} ref={moreRef}>
        <summary aria-label="Outras funções do Financeiro">
          {secondaryActive?.label||'Outras funções'} <ChevronDown size={14}/>
        </summary>
        <div className="finance-more-menu" role="group" aria-label="Outras funções do Financeiro">
          {groups.map(group=><div key={group.label}>
            <span className="finance-more-heading">{group.label}</span>
            {group.items.map(item=><button key={item.key} type="button" className={area===item.key?'active':''} onClick={()=>choose(item.key)}>{item.label}</button>)}
          </div>)}
        </div>
      </details>
    </nav>
  </div>
  <Suspense fallback={<section className="workspace"><div className="panel settings-loading">Carregando área financeira...</div></section>}>
  {area==='overview'?<FinanceDashboardPanel onNavigate={setArea} month={month} setMonth={setMonth}/>:area==='ledger'?<FinanceCorePanel permissions={permissions} onNavigateSource={source=>setArea(source==='maintenance'?'maintenance':'rent')}/>:area==='cycle'?<FinanceMonthlyCyclePanel permissions={permissions} onNavigateArea={target=>setArea(target)}/>:area==='billing'?<FinanceReceivablesPanel permissions={permissions} month={month} setMonth={setMonth}/>:area==='billing-batches'?<FinanceBillingPanel permissions={permissions}/>:area==='repasses'?<FinanceRepassesPanel permissions={permissions} month={month} setMonth={setMonth}/>:area==='delinquency'?<FinanceDelinquencyPanel permissions={permissions}/>:area==='treasury'?<FinanceTreasuryPanel permissions={permissions}/>:area==='banking'?<FinanceBankingPanel permissions={permissions}/>:area==='bank-setup'?<FinanceBankSetupPanel permissions={permissions}/>:area==='bank-control'?<FinanceBankControlPanel permissions={permissions}/>:area==='inter'?<FinanceInterPanel permissions={permissions}/>:area==='reports'?<FinanceReportsPanel permissions={permissions}/>:area==='commissions'?<FinanceCommissionsPanel permissions={permissions} month={month} setMonth={setMonth}/>:area==='classifications'?<FinanceClassificationsPanel permissions={permissions}/>:area==='portals'?<FinancePortalsPanel permissions={permissions}/>:area==='rent'?<FinanceRentPage permissions={permissions}/>:<MaintenanceFinancePanel permissions={permissions}/>}</Suspense></>
}
