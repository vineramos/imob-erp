import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CalendarCheck2,
  CalendarClock,
  FileSignature,
  Handshake,
  House,
  RefreshCw,
  TrendingDown,
  WalletCards,
  Wrench,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './dashboard-live.css'

type DashboardEvent = { id:string; title:string; start_at:string; event_type:string; module:string; priority:string }
type Overview = {
  administered_properties:number
  available_properties:number
  active_leases:number
  contracts_expiring_120:number
  open_maintenance:number
  overdue_amount:number
  pending_repasses_amount:number
  tasks_today:number
  overdue_tasks:number
  events_today:DashboardEvent[]
  open_captures:number
  approved_captures:number
  properties_without_administration:number
  properties_with_administration:number
  managed_properties:number
  contracts_awaiting_signature:number
  contracts_in_review:number
  recent_captures:Capture[]
}
type Capture = { id:string; status:string; contact_person_name:string|null; property_address:{city?:string;state?:string;street?:string}; estimated_rent:number|null; created_at:string }
type ModuleTarget = 'properties'|'contracts'|'maintenance'|'finance'|'agenda'|'captures'
type Props = { onNavigate:(module:ModuleTarget)=>void }

const money=(value:number)=>Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
const timeLabel=(value:string)=>new Date(value).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})
const dateLabel=(value:string)=>new Date(value).toLocaleDateString('pt-BR')
const eventLabel:Record<string,string>={task:'Tarefa',inspection:'Vistoria',inspection_deadline:'Prazo de vistoria',maintenance:'Manutenção',contract_expiry:'Contrato',adjustment:'Reajuste',billing:'Cobrança',repasse:'Repasse'}
const moduleTargets=new Set<ModuleTarget>(['properties','contracts','maintenance','finance','agenda','captures'])
const captureStageLabel:Record<string,string>={new:'Nova',negotiation:'Negociação',documents:'Documentos',inspection:'Vistoria / Cadastro',approved:'Aprovada',available:'Convertida',lost:'Perdida'}
const contractStageLabel:Record<string,string>={draft:'Rascunho',review:'Em revisão',approved:'Aprovado',pending_signature:'Assinatura',signed:'Assinado',cancelled:'Cancelado'}

export function DashboardPage({onNavigate}:Props) {
  const [data,setData]=useState<Overview|null>(null)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')

  const load=useCallback(async()=>{
    setLoading(true);setError('')
    try{setData(await apiRequest<Overview>('/dashboard/overview'))}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o dashboard operacional.')}
    finally{setLoading(false)}
  },[])

  const reload=useCallback(()=>{void load()},[load])
  useEffect(()=>{reload()},[reload])

  const cards=useMemo(()=>[
    {label:'Imóveis administrados',value:data?.administered_properties??0,hint:'contratos de administração ativos',icon:Building2,module:'properties' as ModuleTarget,tone:'blue'},
    {label:'Imóveis disponíveis',value:data?.available_properties??0,hint:'estoque pronto para locação',icon:House,module:'properties' as ModuleTarget,tone:'green'},
    {label:'Contratos ativos',value:data?.active_leases??0,hint:'locações assinadas',icon:FileSignature,module:'contracts' as ModuleTarget,tone:'violet'},
    {label:'Vencendo em 120 dias',value:data?.contracts_expiring_120??0,hint:'administração + locação',icon:CalendarClock,module:'contracts' as ModuleTarget,tone:'orange'},
    {label:'Manutenções abertas',value:data?.open_maintenance??0,hint:'chamados ainda não concluídos',icon:Wrench,module:'maintenance' as ModuleTarget,tone:'orange'},
    {label:'Tarefas de hoje',value:data?.tasks_today??0,hint:data?.overdue_tasks?`${data.overdue_tasks} tarefa(s) atrasada(s)`:'agenda em dia',icon:CalendarCheck2,module:'agenda' as ModuleTarget,tone:data?.overdue_tasks?'orange':'green'},
  ],[data])

  const pipelineSummary=useMemo(()=>{
    return {
      openCaptures:data?.open_captures??0,
      approvedCaptures:data?.approved_captures??0,
      propertiesWithoutAdministration:data?.properties_without_administration??0,
      propertiesWithAdministration:data?.properties_with_administration??0,
      managedProperties:data?.managed_properties??0,
      contractsAwaitingSignature:data?.contracts_awaiting_signature??0,
      contractsInReview:data?.contracts_in_review??0,
    }
  },[data])

  const recentCaptures=data?.recent_captures??[]

  return <section className="workspace dashboard-workspace dashboard-live">
    <div className="page-heading dashboard-heading"><div><span className="eyebrow">Visão geral</span><h1>Dashboard</h1><p>Operação da imobiliária em tempo real, conectando entrada de carteira, imóveis, contratos, agenda, manutenção e financeiro.</p></div><button className="button secondary" type="button" onClick={reload} disabled={loading}><RefreshCw size={14}/> Atualizar</button></div>
    {error&&<div className="form-alert danger-alert">{error}</div>}

    <div className="dashboard-live-metrics">{cards.map(({icon:Icon,...card})=><button type="button" className={`panel dashboard-live-card tone-${card.tone}`} key={card.label} onClick={()=>onNavigate(card.module)}><div className="dashboard-live-icon"><Icon size={19}/></div><div><span>{card.label}</span><strong>{loading?'—':card.value}</strong><small>{card.hint}</small></div></button>)}</div>

    <article className="panel dashboard-pipeline">
      <div className="dashboard-section-heading"><div><span className="eyebrow">Entrada de carteira</span><h2>Pipeline operacional</h2><p>Acompanhe o caminho da oportunidade até o imóvel entrar efetivamente na operação.</p></div><button className="button secondary compact" type="button" onClick={()=>onNavigate('captures')}>Abrir captações <ArrowRight size={13}/></button></div>
      <div className="dashboard-pipeline-grid">
        <button type="button" className="dashboard-pipeline-card" onClick={()=>onNavigate('captures')}><span className="dashboard-pipeline-index">01</span><div><small>Captações em andamento</small><strong>{loading?'—':pipelineSummary.openCaptures}</strong><span>Novas oportunidades em negociação</span></div><ArrowRight size={15}/></button>
        <button type="button" className="dashboard-pipeline-card" onClick={()=>onNavigate('captures')}><span className="dashboard-pipeline-index">02</span><div><small>Aguardando conversão</small><strong>{loading?'—':pipelineSummary.approvedCaptures}</strong><span>Captações aprovadas para virar imóvel</span></div><ArrowRight size={15}/></button>
        <button type="button" className="dashboard-pipeline-card" onClick={()=>onNavigate('properties')}><span className="dashboard-pipeline-index">03</span><div><small>Imóveis sem administração</small><strong>{loading?'—':pipelineSummary.propertiesWithoutAdministration}</strong><span>Cadastros definitivos ainda sem contrato</span></div><ArrowRight size={15}/></button>
        <button type="button" className="dashboard-pipeline-card" onClick={()=>onNavigate('properties')}><span className="dashboard-pipeline-index">04</span><div><small>Imóveis com administração</small><strong>{loading?'—':pipelineSummary.propertiesWithAdministration}</strong><span>Cadastro com contrato ADM ativo</span></div><ArrowRight size={15}/></button>
        <button type="button" className="dashboard-pipeline-card" onClick={()=>onNavigate('properties')}><span className="dashboard-pipeline-index">05</span><div><small>Carteira administrada</small><strong>{loading?'—':pipelineSummary.managedProperties}</strong><span>Contrato ADM assinado e arquivado</span></div><ArrowRight size={15}/></button>
        <button type="button" className="dashboard-pipeline-card" onClick={()=>onNavigate('contracts')}><span className="dashboard-pipeline-index">06</span><div><small>Contratos em assinatura</small><strong>{loading?'—':pipelineSummary.contractsAwaitingSignature}</strong><span>{loading?'—':`${pipelineSummary.contractsInReview} em revisão`}</span></div><ArrowRight size={15}/></button>
      </div>
    </article>

    <div className="dashboard-live-grid">
      <article className="panel dashboard-today"><div className="dashboard-section-heading"><div><span className="eyebrow">Hoje</span><h2>Agenda operacional</h2><p>Compromissos automáticos e tarefas internas que pedem atenção hoje.</p></div><button className="button secondary compact" type="button" onClick={()=>onNavigate('agenda')}>Abrir agenda</button></div>{loading?<div className="settings-loading">Carregando compromissos...</div>:data?.events_today.length?<div className="dashboard-today-list">{data.events_today.map(item=><button type="button" key={item.id} onClick={()=>{if(moduleTargets.has(item.module as ModuleTarget))onNavigate(item.module as ModuleTarget);else onNavigate('agenda')}}><div className={`dashboard-event-dot priority-${item.priority}`}/><div><strong>{item.title}</strong><span>{eventLabel[item.event_type]||item.event_type} · {timeLabel(item.start_at)}</span></div></button>)}</div>:<div className="dashboard-empty"><CalendarCheck2 size={25}/><strong>Nenhum compromisso pendente hoje.</strong><span>A Agenda continuará monitorando vencimentos e eventos automáticos.</span></div>}</article>

      <article className="panel dashboard-financial"><div className="dashboard-section-heading"><div><span className="eyebrow">Financeiro</span><h2>Pontos de atenção</h2><p>Valores que exigem acompanhamento operacional.</p></div><button className="button secondary compact" type="button" onClick={()=>onNavigate('finance')}>Abrir financeiro</button></div><div className="dashboard-financial-list"><button type="button" onClick={()=>onNavigate('finance')}><span className="dashboard-financial-icon danger"><TrendingDown size={17}/></span><div><span>Inadimplência em aberto</span><strong>{loading?'—':money(data?.overdue_amount||0)}</strong><small>Cobranças vencidas e ainda não liquidadas</small></div></button><button type="button" onClick={()=>onNavigate('finance')}><span className="dashboard-financial-icon"><WalletCards size={17}/></span><div><span>Repasses pendentes</span><strong>{loading?'—':money(data?.pending_repasses_amount||0)}</strong><small>Valores de proprietários aguardando repasse</small></div></button><button type="button" onClick={()=>onNavigate('agenda')}><span className={`dashboard-financial-icon ${data?.overdue_tasks?'danger':''}`}><AlertTriangle size={17}/></span><div><span>Tarefas atrasadas</span><strong>{loading?'—':data?.overdue_tasks||0}</strong><small>Prazos internos vencidos e ainda pendentes</small></div></button></div></article>
    </div>

    <article className="panel dashboard-recent-captures"><div className="dashboard-section-heading"><div><span className="eyebrow">Movimentação</span><h2>Captações recentes</h2><p>As últimas oportunidades recebidas, com etapa atual e origem geográfica.</p></div><button className="button secondary compact" type="button" onClick={()=>onNavigate('captures')}>Ver todas</button></div>{loading?<div className="settings-loading">Carregando captações...</div>:recentCaptures.length?<div className="dashboard-recent-captures-list">{recentCaptures.map(item=><button type="button" key={item.id} onClick={()=>onNavigate('captures')}><span className={`capture-dot ${item.status}`}/><div><strong>{item.contact_person_name||'Contato não vinculado'}</strong><small>{item.property_address.city||'Cidade não informada'}{item.property_address.state?`/${item.property_address.state}`:''} · {captureStageLabel[item.status]||item.status}</small></div><span>{dateLabel(item.created_at)}</span></button>)}</div>:<div className="dashboard-empty"><Handshake size={25}/><strong>Nenhuma captação disponível para exibição.</strong><span>As novas oportunidades aparecerão aqui conforme forem cadastradas.</span></div>}</article>

    <article className="panel dashboard-operation-note"><CalendarClock size={21}/><div><span className="eyebrow">Integração operacional</span><h2>A Agenda acompanha o ERP automaticamente</h2><p>Vistorias agendadas, manutenções, reajustes, vencimentos de contratos em 120/90/60/30 dias, cobranças e repasses entram na linha do tempo sem cadastro duplicado.</p></div></article>
  </section>
}
