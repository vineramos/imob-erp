import {
  AlertTriangle, CalendarClock, CheckCircle2, Clipboard, MessageCircle, RefreshCw,
  ShieldCheck, TimerReset, Search, History, X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './finance-delinquency.css'

type TenantContact={name:string;email:string|null;phone:string|null}
type Workflow={
  guarantee_type:string;guarantee_label:string;guarantee_provider_name:string|null;guarantee_policy_number:string|null;
  guarantee_status:string;guarantee_protocol:string|null;claimed_amount:number|null;approved_amount:number|null;received_amount:number|null;
  guarantee_submitted_at:string|null;guarantee_approved_at:string|null;guarantee_received_at:string|null;guarantee_rejected_at:string|null;
  guarantee_payment_reference:string|null;promise_amount:number|null;promise_due_date:string|null;promise_status:string|null;
  promise_recorded_at:string|null;promise_broken_at:string|null;notes:string|null;external_submission_performed:boolean
}
type ActionLog={at?:string;action?:string;detail?:string;notes?:string|null;channel?:string|null;source?:string;protocol?:string|null}
type Case={
  id:string;code:string;charge_id:string;charge_code:string;lease_contract_id:string;lease_code:string;property_id:string;property_code:string;
  tenant_name:string;tenant_contacts:TenantContact[];due_date:string;amount:number;days_overdue:number;first_contact_after_days:number;
  followup_after_days:number;critical_after_days:number;critical:boolean;status:string;suggested_action:string|null;insurer_protocol:string|null;
  assigned_user_id:string|null;pending_agenda_tasks:number;opened_at:string;critical_at:string|null;last_contact_at:string|null;next_action_at:string|null;
  insurer_triggered_at:string|null;resolved_at:string|null;notes:string|null;action_log:ActionLog[];workflow:Workflow
}
type Overview={open_cases:number;critical_cases:number;overdue_amount:number;critical_amount:number;promises_pending:number;promises_broken:number;guarantees_available:number;guarantees_submitted:number;guarantees_received:number;guarantees_received_amount:number}
type Modal='contact'|'promise'|'guarantee'|null

type Props={permissions:string[]}

const statusLabels:Record<string,string>={open:'Em aberto',contacted:'Contatado',negotiating:'Negociação',insurer_triggered:'Garantia acionada',resolved:'Resolvido'}
const guaranteeLabels:Record<string,string>={not_applicable:'Não aplicável',available:'Disponível',prepared:'Preparada',submitted:'Acionada',under_review:'Em análise',approved:'Aprovada',rejected:'Recusada',received:'Indenizada',cancelled:'Cancelada'}
const promiseLabels:Record<string,string>={pending:'Promessa vigente',kept:'Cumprida',broken:'Não cumprida',cancelled:'Cancelada'}
const actionLabels:Record<string,string>={opened:'Caso aberto',reopened:'Caso reaberto',ladder_first_contact:'D+1 · primeiro contato',ladder_followup:'D+3 · acompanhamento',critical:'Marco crítico',contacted:'Contato registrado',negotiating:'Negociação',promise_recorded:'Promessa registrada',promise_broken:'Promessa não cumprida',insurer_triggered:'Garantia acionada',guarantee_prepared:'Garantia preparada',guarantee_submitted:'Garantia acionada',guarantee_under_review:'Garantia em análise',guarantee_approved:'Garantia aprovada',guarantee_rejected:'Garantia recusada',guarantee_received:'Indenização registrada',guarantee_cancelled:'Garantia cancelada',resolved:'Caso resolvido'}
const money=(value:number|null|undefined)=>Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
const dateLabel=(value:string|null|undefined)=>value?new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString('pt-BR'):'—'
const dateTimeLabel=(value:string|null|undefined)=>value?new Date(value).toLocaleString('pt-BR'):'—'
function today(){const now=new Date();const offset=now.getTimezoneOffset();return new Date(now.getTime()-offset*60000).toISOString().slice(0,10)}
function localDateTime(value?:string|null){const date=value?new Date(value):new Date();const offset=date.getTimezoneOffset();return new Date(date.getTime()-offset*60000).toISOString().slice(0,16)}
function guaranteeStatusClass(value:string){return value==='received'||value==='approved'?'success':value==='rejected'||value==='cancelled'?'danger':value==='submitted'||value==='under_review'?'warning':'neutral'}
function caseStatusClass(value:string){return value==='resolved'?'success':value==='insurer_triggered'?'warning':value==='open'?'danger':'neutral'}

export function FinanceDelinquencyPanel({permissions}:Props){
  const canManage=permissions.includes('finance.payment.approve')
  const [cases,setCases]=useState<Case[]>([])
  const [overview,setOverview]=useState<Overview|null>(null)
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [filter,setFilter]=useState<'active'|'critical'|'promise'|'guarantee'|'resolved'>('active')
  const [query,setQuery]=useState('')
  const [activeId,setActiveId]=useState<string|null>(null)
  const [detailTab,setDetailTab]=useState<'overview'|'guarantee'|'history'>('overview')
  const [selected,setSelected]=useState<Case|null>(null)
  const [modal,setModal]=useState<Modal>(null)
  const [channel,setChannel]=useState('whatsapp')
  const [notes,setNotes]=useState('')
  const [nextAction,setNextAction]=useState('')
  const [promiseDate,setPromiseDate]=useState(today())
  const [guaranteeStatus,setGuaranteeStatus]=useState('prepared')
  const [provider,setProvider]=useState('')
  const [policy,setPolicy]=useState('')
  const [protocol,setProtocol]=useState('')
  const [claimed,setClaimed]=useState('')
  const [approved,setApproved]=useState('')
  const [received,setReceived]=useState('')
  const [paymentReference,setPaymentReference]=useState('')

  const load=useCallback(async()=>{
    setLoading(true);setError('')
    try{
      const [summary,items]=await Promise.all([
        apiRequest<Overview>('/finance/advanced/delinquency/overview'),
        apiRequest<Case[]>('/finance/advanced/delinquency'),
      ])
      setOverview(summary);setCases(items)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar a inadimplência.')}
    finally{setLoading(false)}
  },[])
  useEffect(()=>{void load()},[load])

  const filtered=useMemo(()=>cases.filter(item=>{
    const term=query.trim().toLocaleLowerCase('pt-BR')
    if(term&&![item.code,item.charge_code,item.lease_code,item.property_code,item.tenant_name].join(' ').toLocaleLowerCase('pt-BR').includes(term))return false
    if(filter==='resolved')return item.status==='resolved'
    if(item.status==='resolved')return false
    if(filter==='critical')return item.critical
    if(filter==='promise')return item.workflow.promise_status==='pending'||item.workflow.promise_status==='broken'
    if(filter==='guarantee')return item.workflow.guarantee_status!=='not_applicable'
    return true
  }),[cases,filter,query])
  const active=filtered.find(item=>item.id===activeId)||filtered[0]||null

  function open(item:Case,next:Exclude<Modal,null>){
    setSelected(item);setModal(next);setError('');setSuccess('');setNotes('');setNextAction(item.next_action_at?localDateTime(item.next_action_at):'')
    if(next==='contact')setChannel('whatsapp')
    if(next==='promise'){setPromiseDate(today())}
    if(next==='guarantee'){
      const flow=item.workflow
      setGuaranteeStatus(flow.guarantee_status==='available'?'prepared':flow.guarantee_status)
      setProvider(flow.guarantee_provider_name||'');setPolicy(flow.guarantee_policy_number||'');setProtocol(flow.guarantee_protocol||'')
      setClaimed(String(flow.claimed_amount??item.amount));setApproved(flow.approved_amount==null?'':String(flow.approved_amount));setReceived(flow.received_amount==null?'':String(flow.received_amount));setPaymentReference(flow.guarantee_payment_reference||'')
    }
  }
  function close(){if(!saving){setModal(null);setSelected(null)}}

  async function refresh(){
    setSaving(true);setError('');setSuccess('')
    try{await apiRequest('/finance/advanced/delinquency/refresh',{method:'POST'});await load();setSuccess('Régua de cobrança atualizada. Tarefas e marcos foram sincronizados com a Agenda.')}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível atualizar a régua de cobrança.')}
    finally{setSaving(false)}
  }

  async function submitContact(event:FormEvent){
    event.preventDefault();if(!selected)return
    setSaving(true);setError('')
    try{
      await apiRequest(`/finance/advanced/delinquency/${selected.id}/action`,{method:'POST',body:JSON.stringify({status:'contacted',channel,notes:notes||null,next_action_at:nextAction?new Date(nextAction).toISOString():null,insurer_protocol:null})})
      close();await load();setSuccess(`Contato de ${selected.code} registrado e Agenda sincronizada.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível registrar o contato.')}
    finally{setSaving(false)}
  }

  async function submitPromise(event:FormEvent){
    event.preventDefault();if(!selected)return
    setSaving(true);setError('')
    try{
      await apiRequest(`/finance/advanced/delinquency/${selected.id}/promise`,{method:'POST',body:JSON.stringify({due_date:promiseDate,amount:selected.amount,notes:notes||null})})
      close();await load();setSuccess(`Promessa integral de ${selected.code} registrada para ${dateLabel(promiseDate)}.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível registrar a promessa.')}
    finally{setSaving(false)}
  }

  async function submitGuarantee(event:FormEvent){
    event.preventDefault();if(!selected)return
    setSaving(true);setError('')
    try{
      await apiRequest(`/finance/advanced/delinquency/${selected.id}/guarantee`,{method:'POST',body:JSON.stringify({
        status:guaranteeStatus,provider_name:provider||null,policy_number:policy||null,protocol:protocol||null,
        claimed_amount:claimed?Number(claimed):null,approved_amount:approved?Number(approved):null,received_amount:received?Number(received):null,
        payment_reference:paymentReference||null,notes:notes||null,next_action_at:nextAction?new Date(nextAction).toISOString():null,
      })})
      close();await load();setSuccess(`Acompanhamento da garantia de ${selected.code} atualizado. Nenhum envio externo foi executado pelo Imob.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível atualizar a garantia.')}
    finally{setSaving(false)}
  }

  async function copyMessage(item:Case){
    const contact=item.tenant_contacts[0]
    const text=`Olá, ${contact?.name||item.tenant_name}. Identificamos que a cobrança ${item.charge_code}, no valor de ${money(item.amount)}, com vencimento em ${dateLabel(item.due_date)}, permanece em aberto. Por gentileza, verifique a regularização ou entre em contato conosco para alinharmos o pagamento.`
    try{await navigator.clipboard.writeText(text);setSuccess('Mensagem-base de cobrança copiada. Revise antes de enviar ao locatário.')}
    catch{setError('Não foi possível copiar a mensagem.')}
  }

  return <section className="workspace delinquency-workspace">
    <div className="page-heading delinquency-heading"><div><span className="eyebrow">Financeiro · cobrança</span><h1>Inadimplência</h1><p>Régua D+1 / D+3 / D+5, promessas de pagamento e acompanhamento da garantia em um fluxo auditável.</p></div><div className="heading-actions"><button className="button secondary" type="button" disabled={saving||loading} onClick={()=>void load()}><RefreshCw size={14}/> Atualizar</button>{canManage&&<button className="button primary" type="button" disabled={saving} onClick={()=>void refresh()}><TimerReset size={14}/> Processar régua</button>}</div></div>

    <div className="delinquency-safety"><ShieldCheck size={17}/><div><strong>Acionamento da garantia permanece sob controle humano.</strong><span>O Imob registra preparo, protocolo, análise e indenização, mas não envia solicitação para seguradora/fiador automaticamente enquanto não existir integração externa validada.</span></div></div>

    {overview&&<div className="delinquency-metrics">
      <article className="panel"><span>Em cobrança</span><strong>{overview.open_cases}</strong><small>{money(overview.overdue_amount)} em aberto</small></article>
      <article className={`panel ${overview.critical_cases?'critical':''}`}><span>Críticos</span><strong>{overview.critical_cases}</strong><small>{money(overview.critical_amount)} após o marco crítico</small></article>
      <article className={`panel ${overview.promises_broken?'critical':''}`}><span>Promessas</span><strong>{overview.promises_pending}</strong><small>{overview.promises_broken} não cumprida(s)</small></article>
      <article className="panel"><span>Garantias acionadas</span><strong>{overview.guarantees_submitted}</strong><small>{overview.guarantees_received} indenizada(s) · {money(overview.guarantees_received_amount)}</small></article>
    </div>}

    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}

    {loading?<article className="panel settings-loading">Carregando casos de inadimplência...</article>:
    <div className="delinquency-master-detail">
      <aside className="panel delinquency-directory" aria-label="Lista de inadimplência">
        <label className="delinquency-search"><Search size={15}/><input aria-label="Buscar caso" placeholder="Buscar locatário, imóvel ou cobrança..." value={query} onChange={e=>setQuery(e.target.value)}/></label>
        <select aria-label="Filtro de casos" value={filter} onChange={e=>{setFilter(e.target.value as typeof filter);setDetailTab('overview')}}>
          <option value="active">Em acompanhamento</option><option value="critical">Críticos</option><option value="promise">Promessas</option><option value="guarantee">Garantias</option><option value="resolved">Resolvidos</option>
        </select>
        <small>{filtered.length} de {cases.length} caso(s)</small>
        <div className="delinquency-directory-list">
          {filtered.map(item=><button key={item.id} type="button" aria-pressed={active?.id===item.id} className={'delinquency-directory-row '+(active?.id===item.id?'active':'')+(item.critical?' critical':'')} onClick={()=>{setActiveId(item.id);setDetailTab('overview')}}>
            <span className="delinquency-directory-head"><strong>{item.tenant_name}</strong><i className={'status-badge '+caseStatusClass(item.status)}>{statusLabels[item.status]||item.status}</i></span>
            <small>{item.code} · Imóvel #{item.property_code}</small>
            <span className="delinquency-directory-head"><b>{money(item.amount)}</b><em>D+{item.days_overdue}</em></span>
            <small>Próxima ação: {item.next_action_at?dateTimeLabel(item.next_action_at):item.suggested_action||'Não definida'}</small>
          </button>)}
          {!filtered.length&&<div className="delinquency-directory-empty">Nenhum caso encontrado neste filtro.</div>}
        </div>
      </aside>
      <section className="panel delinquency-detail" aria-label="Ficha de inadimplência">
        {!active?<div className="delinquency-directory-empty">Selecione um caso para visualizar a ficha operacional.</div>:<>
          <header className="delinquency-detail-header">
            <div><span className="eyebrow">INADIMPLÊNCIA · {active.code}</span><h2>{active.tenant_name} <i className={'status-badge '+caseStatusClass(active.status)}>{statusLabels[active.status]||active.status}</i></h2><p>{active.charge_code} · {active.lease_code} · Imóvel #{active.property_code}</p></div>
            <div className="delinquency-detail-actions">
              {active.status!=='resolved'&&<><button type="button" className="button secondary" onClick={()=>void copyMessage(active)}><Clipboard size={14}/> Copiar mensagem</button>
              {canManage&&<button type="button" className="button primary" onClick={()=>open(active,'contact')}><MessageCircle size={14}/> Registrar contato</button>}</>}
            </div>
          </header>
          <div className="delinquency-detail-strip">
            <div><span>Valor em aberto</span><strong>{money(active.amount)}</strong></div>
            <div><span>Atraso</span><strong>D+{active.days_overdue}</strong></div>
            <div><span>Vencimento</span><strong>{dateLabel(active.due_date)}</strong></div>
            <div><span>Próxima ação</span><strong>{dateTimeLabel(active.next_action_at)}</strong></div>
          </div>
          <nav className="delinquency-detail-tabs" aria-label="Abas da inadimplência">
            <button type="button" className={detailTab==='overview'?'active':''} onClick={()=>setDetailTab('overview')}><CalendarClock size={14}/> Visão geral</button>
            <button type="button" className={detailTab==='guarantee'?'active':''} onClick={()=>setDetailTab('guarantee')}><ShieldCheck size={14}/> Garantia e promessa</button>
            <button type="button" className={detailTab==='history'?'active':''} onClick={()=>setDetailTab('history')}><History size={14}/> Histórico de contatos</button>
          </nav>
          <div className="delinquency-detail-body">
            {detailTab==='overview'&&<div className="delinquency-detail-panels">
              <article className="delinquency-detail-card"><h3>Plano de acompanhamento</h3>
                <div className="delinquency-ladder"><span className={active.days_overdue>=active.first_contact_after_days?'done':''}>D+{active.first_contact_after_days}<b>Primeiro contato</b></span><span className={active.days_overdue>=active.followup_after_days?'done':''}>D+{active.followup_after_days}<b>Acompanhamento</b></span><span className={active.days_overdue>=active.critical_after_days?'critical done':''}>D+{active.critical_after_days}<b>Marco crítico</b></span></div>
                <div className="delinquency-detail-facts">
                  <div><span>Último contato</span><strong>{dateTimeLabel(active.last_contact_at)}</strong></div>
                  <div><span>Próximo passo sugerido</span><strong>{active.suggested_action||'Não definido'}</strong></div>
                  <div><span>Responsável</span><strong>{active.assigned_user_id?'Usuário vinculado':'Não atribuído'}</strong><small>Identificação interna: {active.assigned_user_id||'—'}</small></div>
                  <div><span>Agenda</span><strong>{active.pending_agenda_tasks} tarefa(s) pendente(s)</strong></div>
                  <div><span>Contato do locatário</span><strong>{active.tenant_contacts[0]?.phone||active.tenant_contacts[0]?.email||'Não informado'}</strong></div>
                  <div><span>Situação</span><strong>{statusLabels[active.status]||active.status}</strong></div>
                </div>
              </article>
              <article className="delinquency-detail-card"><h3>Ações do caso</h3>
                <div className="delinquency-detail-action-list">
                  <div><span>Próxima ação agendada</span><strong>{dateTimeLabel(active.next_action_at)}</strong></div>
                  <div><span>Último contato</span><strong>{dateTimeLabel(active.last_contact_at)}</strong></div>
                  <div><span>Garantia</span><strong>{active.workflow.guarantee_label}</strong></div>
                  <div><span>Promessa</span><strong>{active.workflow.promise_status?promiseLabels[active.workflow.promise_status]||active.workflow.promise_status:'Não registrada'}</strong></div>
                </div>
                {active.status!=='resolved'&&canManage&&<div className="delinquency-detail-buttons">
                  <button type="button" className="button secondary" onClick={()=>open(active,'promise')}><CalendarClock size={14}/> Registrar promessa</button>
                  {active.workflow.guarantee_type!=='none'&&<button type="button" className="button secondary" onClick={()=>open(active,'guarantee')}><ShieldCheck size={14}/> Acompanhar garantia</button>}
                </div>}
              </article>
            </div>}
            {detailTab==='guarantee'&&<div className="delinquency-detail-panels">
              <article className="delinquency-detail-card"><h3>Garantia</h3><div className="delinquency-detail-facts">
                <div><span>Tipo</span><strong>{active.workflow.guarantee_label}</strong></div>
                <div><span>Status</span><strong>{guaranteeLabels[active.workflow.guarantee_status]||active.workflow.guarantee_status}</strong></div>
                <div><span>Prestador</span><strong>{active.workflow.guarantee_provider_name||'Não informado'}</strong></div>
                <div><span>Protocolo</span><strong>{active.workflow.guarantee_protocol||'Não informado'}</strong></div>
                <div><span>Valor solicitado</span><strong>{money(active.workflow.claimed_amount)}</strong></div>
                <div><span>Valor recebido</span><strong>{money(active.workflow.received_amount)}</strong></div>
              </div>
              {active.status!=='resolved'&&canManage&&active.workflow.guarantee_type!=='none'&&<button type="button" className="button secondary" onClick={()=>open(active,'guarantee')}>Atualizar acompanhamento</button>}
              </article>
              <article className="delinquency-detail-card"><h3>Promessa de pagamento</h3><div className="delinquency-detail-action-list">
                <div><span>Situação</span><strong>{active.workflow.promise_status?promiseLabels[active.workflow.promise_status]||active.workflow.promise_status:'Não registrada'}</strong></div>
                <div><span>Valor</span><strong>{money(active.workflow.promise_amount)}</strong></div>
                <div><span>Data prometida</span><strong>{dateLabel(active.workflow.promise_due_date)}</strong></div>
              </div>
              {active.status!=='resolved'&&canManage&&<button type="button" className="button secondary" onClick={()=>open(active,'promise')}>Registrar promessa</button>}
              </article>
            </div>}
            {detailTab==='history'&&<article className="delinquency-detail-card"><h3>Histórico do caso · {active.action_log.length} evento(s)</h3>
              <div className="delinquency-detail-history">{[...active.action_log].reverse().map((row,index)=><div key={(row.at||index)+'-'+index}>
                <span>{dateTimeLabel(row.at)}</span><div><strong>{actionLabels[row.action||'']||row.action||'Evento'}</strong><small>{row.detail||row.notes||''}{row.channel?' · '+row.channel:''}</small></div>
              </div>)}
              {!active.action_log.length&&<p>Nenhum evento registrado neste caso.</p>}</div>
            </article>}
          </div>
        </>}
      </section>
    </div>}

    {modal&&selected&&<div className="portfolio-modal-backdrop delinquency-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target)close()}}>
      {modal==='contact'&&<form className="panel portfolio-modal delinquency-modal" onSubmit={submitContact}><div className="portfolio-modal-header"><div><span className="eyebrow">{selected.code}</span><h2>Registrar contato</h2><p>O registro conclui o marco correspondente da régua e mantém o histórico auditável.</p></div><button className="portfolio-modal-close" type="button" onClick={close}><X size={17}/></button></div><div className="delinquency-modal-body"><label><span>Canal</span><select value={channel} onChange={e=>setChannel(e.target.value)}><option value="whatsapp">WhatsApp</option><option value="phone">Telefone</option><option value="email">E-mail</option><option value="other">Outro</option></select></label><label><span>Próxima ação (opcional)</span><input type="datetime-local" value={nextAction} onChange={e=>setNextAction(e.target.value)}/></label><label className="full"><span>Retorno / observações</span><textarea rows={5} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Ex.: locatário informou que pagará amanhã."/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={close}>Cancelar</button><button className="button primary" disabled={saving}>{saving?'Salvando...':'Registrar contato'}</button></div></form>}

      {modal==='promise'&&<form className="panel portfolio-modal delinquency-modal" onSubmit={submitPromise}><div className="portfolio-modal-header"><div><span className="eyebrow">{selected.code}</span><h2>Promessa de pagamento</h2><p>Como o Imob não aceita pagamento parcial, a promessa também é registrada pelo valor integral da cobrança.</p></div><button className="portfolio-modal-close" type="button" onClick={close}><X size={17}/></button></div><div className="delinquency-modal-body"><label><span>Valor integral</span><input value={money(selected.amount)} disabled/></label><label><span>Data prometida</span><input type="date" min={today()} required value={promiseDate} onChange={e=>setPromiseDate(e.target.value)}/></label><label className="full"><span>Observações</span><textarea rows={4} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Como o acordo foi feito, contato utilizado, observações relevantes..."/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={close}>Cancelar</button><button className="button primary" disabled={saving}>{saving?'Salvando...':'Registrar promessa'}</button></div></form>}

      {modal==='guarantee'&&<form className="panel portfolio-modal delinquency-modal delinquency-guarantee-modal" onSubmit={submitGuarantee}><div className="portfolio-modal-header"><div><span className="eyebrow">{selected.workflow.guarantee_label} · {selected.code}</span><h2>Acompanhar garantia</h2><p>Registro interno. Salvar “Acionada” não envia dados para a seguradora ou terceiro.</p></div><button className="portfolio-modal-close" type="button" onClick={close}><X size={17}/></button></div><div className="delinquency-external-warning"><AlertTriangle size={15}/><span><strong>Nenhum envio externo será executado.</strong> Registre aqui somente o que foi feito/confirmado fora do Imob.</span></div><div className="delinquency-modal-body"><label><span>Status</span><select value={guaranteeStatus} onChange={e=>setGuaranteeStatus(e.target.value)}><option value="available">Disponível</option><option value="prepared">Preparada</option><option value="submitted">Acionada</option><option value="under_review">Em análise</option><option value="approved">Aprovada</option><option value="rejected">Recusada</option><option value="received">Indenizada / recebida</option><option value="cancelled">Cancelada</option></select></label><label><span>Seguradora / terceiro</span><input value={provider} onChange={e=>setProvider(e.target.value)} placeholder="Nome do prestador"/></label><label><span>Apólice / referência</span><input value={policy} onChange={e=>setPolicy(e.target.value)} placeholder="Opcional"/></label><label><span>Protocolo</span><input value={protocol} onChange={e=>setProtocol(e.target.value)} placeholder={selected.workflow.guarantee_type==='insurance'?'Obrigatório ao acionar seguro':'Protocolo / referência'}/></label><label><span>Valor acionado</span><input type="number" min="0.01" step="0.01" value={claimed} onChange={e=>setClaimed(e.target.value)}/></label><label><span>Valor aprovado</span><input type="number" min="0" step="0.01" value={approved} onChange={e=>setApproved(e.target.value)}/></label><label><span>Valor recebido</span><input type="number" min="0" step="0.01" value={received} onChange={e=>setReceived(e.target.value)}/></label><label><span>Referência do recebimento</span><input value={paymentReference} onChange={e=>setPaymentReference(e.target.value)} placeholder="PIX, comprovante, protocolo..."/></label><label className="full"><span>Próximo acompanhamento</span><input type="datetime-local" value={nextAction} onChange={e=>setNextAction(e.target.value)}/></label><label className="full"><span>Observações</span><textarea rows={4} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Documentos encaminhados, retorno da seguradora, pendências..."/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={close}>Cancelar</button><button className="button primary" disabled={saving}>{saving?'Salvando...':'Salvar acompanhamento'}</button></div></form>}
    </div>}
  </section>
}
