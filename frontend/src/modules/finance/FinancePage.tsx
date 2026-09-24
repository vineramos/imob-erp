import { AlertTriangle, BarChart3, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, CircleDollarSign, ExternalLink, Landmark, LayoutDashboard, ListTree, LockKeyhole, Percent, PlugZap, ReceiptText, RefreshCw, Send, ShieldCheck, Tags, TrendingUp, WalletCards } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './finance-navigation.css'
import { ApiError, apiRequest } from '../../api/client'
import { FinanceBankControlPanel } from './FinanceBankControlPanel'
import { FinanceBankSetupPanel } from './FinanceBankSetupPanel'
import { FinanceBankingPanel } from './FinanceBankingPanel'
import { FinanceBillingPanel } from './FinanceBillingPanel'
import { FinanceReceivablesPanel } from './FinanceReceivablesPanel'
import { FinanceRepassesPanel } from './FinanceRepassesPanel'
import { FinanceClassificationsPanel } from './FinanceClassificationsPanel'
import { FinanceCommissionsPanel } from './FinanceCommissionsPanel'
import { FinanceCorePanel } from './FinanceCorePanel'
import { FinanceDelinquencyPanel } from './FinanceDelinquencyPanel'
import { FinanceInterPanel } from './FinanceInterPanel'
import { FinanceMonthlyCyclePanel } from './FinanceMonthlyCyclePanel'
import { FinancePage as FinanceRentPage } from './FinanceRentPage'
import { FinancePortalsPanel } from './FinancePortalsPanel'
import { FinanceReportsPanel } from './FinanceReportsPanel'
import { FinanceTreasuryPanel } from './FinanceTreasuryPanel'
import { MaintenanceFinancePanel } from './MaintenanceFinancePanel'

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

export function FinancePage({permissions}:{permissions:string[]}){
  const [area,setArea]=useState<Area>('overview')
  const [month,setMonth]=useState(currentMonth())
  const moreRef=useRef<HTMLDetailsElement>(null)
  const secondaryLabels:Partial<Record<Area,string>>={
    'billing-batches':'Emissão em lote',treasury:'Tesouraria',banking:'Bancos','bank-setup':'Contas e APIs',
    'bank-control':'Controle bancário',inter:'Banco Inter',reports:'Relatórios',
    classifications:'Classificações',portals:'Portais',rent:'Locações',maintenance:'Manutenções'
  }
  const choose=(next:Area)=>{
    setArea(next)
    if(moreRef.current)moreRef.current.open=false
  }
  const secondaryActive=Object.prototype.hasOwnProperty.call(secondaryLabels,area)
  return <><div className="workspace finance-area-switch finance-nav-workspace">
    <nav className="panel finance-nav-shell" aria-label="Navegação do Financeiro">
      <div className="finance-primary-tabs" role="group" aria-label="Áreas principais">
        <button type="button" className={area==='overview'?'active':''} onClick={()=>choose('overview')}><LayoutDashboard size={15}/> Visão geral</button>
        <button type="button" className={area==='ledger'?'active':''} onClick={()=>choose('ledger')}><ListTree size={15}/> Lançamentos</button>
        <button type="button" className={area==='cycle'?'active':''} onClick={()=>choose('cycle')}><TrendingUp size={15}/> Ciclo mensal</button>
        <button type="button" className={area==='billing'?'active':''} onClick={()=>choose('billing')}><Send size={15}/> Contas a receber</button>
        <button type="button" className={area==='repasses'?'active':''} onClick={()=>choose('repasses')}><Landmark size={15}/> Repasses</button>
        <button type="button" className={area==='delinquency'?'active':''} onClick={()=>choose('delinquency')}><AlertTriangle size={15}/> Inadimplência</button>
        <button type="button" className={area==='commissions'?'active':''} onClick={()=>choose('commissions')}><Percent size={15}/> Comissões</button>
      </div>
      <details className={'finance-more'+(secondaryActive?' active':'')} ref={moreRef}>
        <summary aria-label="Mais áreas do Financeiro">
          {secondaryActive?secondaryLabels[area]:'Mais'} <ChevronDown size={14}/>
        </summary>
        <div className="finance-more-menu" role="group" aria-label="Outras áreas do Financeiro">
          <span className="finance-more-heading">Operação complementar</span>
          <button type="button" className={area==='billing-batches'?'active':''} onClick={()=>choose('billing-batches')}><ReceiptText size={15}/> Emissão em lote</button>
          <button type="button" className={area==='treasury'?'active':''} onClick={()=>choose('treasury')}><TrendingUp size={15}/> Tesouraria</button>
          <button type="button" className={area==='rent'?'active':''} onClick={()=>choose('rent')}><Landmark size={15}/> Locações</button>
          <button type="button" className={area==='maintenance'?'active':''} onClick={()=>choose('maintenance')}><ReceiptText size={15}/> Manutenções</button>
          {permissions.includes('reports.view')&&<button type="button" className={area==='reports'?'active':''} onClick={()=>choose('reports')}><BarChart3 size={15}/> Relatórios</button>}
          <span className="finance-more-heading">Bancos e configurações</span>
          <button type="button" className={area==='banking'?'active':''} onClick={()=>choose('banking')}><WalletCards size={15}/> Bancos</button>
          <button type="button" className={area==='inter'?'active':''} onClick={()=>choose('inter')}><ShieldCheck size={15}/> Banco Inter</button>
          <button type="button" className={area==='bank-setup'?'active':''} onClick={()=>choose('bank-setup')}><PlugZap size={15}/> Contas e APIs</button>
          <button type="button" className={area==='bank-control'?'active':''} onClick={()=>choose('bank-control')}><LockKeyhole size={15}/> Controle bancário</button>
          <button type="button" className={area==='classifications'?'active':''} onClick={()=>choose('classifications')}><Tags size={15}/> Classificações</button>
          <button type="button" className={area==='portals'?'active':''} onClick={()=>choose('portals')}><ExternalLink size={15}/> Portais</button>
        </div>
      </details>
    </nav>
  </div>
  {area==='overview'?<FinanceDashboardPanel onNavigate={setArea} month={month} setMonth={setMonth}/>:area==='ledger'?<FinanceCorePanel permissions={permissions} onNavigateSource={source=>setArea(source==='maintenance'?'maintenance':'rent')}/>:area==='cycle'?<FinanceMonthlyCyclePanel permissions={permissions} onNavigateArea={target=>setArea(target)}/>:area==='billing'?<FinanceReceivablesPanel permissions={permissions} month={month} setMonth={setMonth}/>:area==='billing-batches'?<FinanceBillingPanel permissions={permissions}/>:area==='repasses'?<FinanceRepassesPanel permissions={permissions} month={month} setMonth={setMonth}/>:area==='delinquency'?<FinanceDelinquencyPanel permissions={permissions}/>:area==='treasury'?<FinanceTreasuryPanel permissions={permissions}/>:area==='banking'?<FinanceBankingPanel permissions={permissions}/>:area==='bank-setup'?<FinanceBankSetupPanel permissions={permissions}/>:area==='bank-control'?<FinanceBankControlPanel permissions={permissions}/>:area==='inter'?<FinanceInterPanel permissions={permissions}/>:area==='reports'?<FinanceReportsPanel permissions={permissions}/>:area==='commissions'?<FinanceCommissionsPanel permissions={permissions} month={month} setMonth={setMonth}/>:area==='classifications'?<FinanceClassificationsPanel permissions={permissions}/>:area==='portals'?<FinancePortalsPanel permissions={permissions}/>:area==='rent'?<FinanceRentPage permissions={permissions}/>:<MaintenanceFinancePanel permissions={permissions}/>}</>
}
