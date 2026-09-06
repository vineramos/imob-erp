import {
  AlertTriangle, CalendarClock, CheckCircle2, Clipboard, MessageCircle, RefreshCw,
  ShieldCheck, TimerReset, UserRound, X,
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
    if(filter==='resolved')return item.status==='resolved'
    if(item.status==='resolved')return false
    if(filter==='critical')return item.critical
    if(filter==='promise')return item.workflow.promise_status==='pending'||item.workflow.promise_status==='broken'
    if(filter==='guarantee')return item.workflow.guarantee_status!=='not_applicable'
    return true
  }),[cases,filter])

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

    <div className="finance-filter delinquency-filter">
      <button className={filter==='active'?'active':''} onClick={()=>setFilter('active')}>Ativos</button>
      <button className={filter==='critical'?'active':''} onClick={()=>setFilter('critical')}>Críticos</button>
      <button className={filter==='promise'?'active':''} onClick={()=>setFilter('promise')}>Promessas</button>
      <button className={filter==='guarantee'?'active':''} onClick={()=>setFilter('guarantee')}>Garantias</button>
      <button className={filter==='resolved'?'active':''} onClick={()=>setFilter('resolved')}>Resolvidos</button>
    </div>

    {loading?<article className="panel settings-loading">Carregando casos de inadimplência...</article>:<div className="delinquency-list">{filtered.map(item=>{
      const flow=item.workflow, contact=item.tenant_contacts[0]
      return <article className={`panel delinquency-case ${item.critical?'critical':''}`} key={item.id}>
        <div className="delinquency-case-head"><div className="delinquency-case-title"><div className="delinquency-icon"><AlertTriangle size={18}/></div><div><span>{item.code} · {item.charge_code}</span><strong>{item.tenant_name}</strong><small>{item.lease_code} · Imóvel #{item.property_code}</small></div></div><div className="delinquency-days"><span>Atraso</span><strong>D+{item.days_overdue}</strong><small>Venceu {dateLabel(item.due_date)}</small></div><div className="delinquency-amount"><span>Em aberto</span><strong>{money(item.amount)}</strong><i className={`status-badge ${caseStatusClass(item.status)}`}>{statusLabels[item.status]||item.status}</i></div></div>

        <div className="delinquency-ladder"><span className={item.days_overdue>=item.first_contact_after_days?'done':''}>D+{item.first_contact_after_days}<b>1º contato</b></span><span className={item.days_overdue>=item.followup_after_days?'done':''}>D+{item.followup_after_days}<b>Acompanhamento</b></span><span className={item.days_overdue>=item.critical_after_days?'critical done':''}>D+{item.critical_after_days}<b>Garantia</b></span></div>

        <div className="delinquency-grid">
          <div><span>Contato</span><strong>{contact?.phone||contact?.email||'Sem contato cadastrado'}</strong><small>Último registro: {dateTimeLabel(item.last_contact_at)}</small></div>
          <div><span>Próximo passo</span><strong>{item.suggested_action||'Caso encerrado'}</strong><small>{item.next_action_at?`Agenda: ${dateTimeLabel(item.next_action_at)}`:`${item.pending_agenda_tasks} tarefa(s) pendente(s) na Agenda`}</small></div>
          <div><span>Garantia</span><strong>{flow.guarantee_label}</strong><small>{flow.guarantee_provider_name||'Prestador não informado'}{flow.guarantee_policy_number?` · ${flow.guarantee_policy_number}`:''}</small></div>
          <div><span>Andamento da garantia</span><strong><i className={`status-badge ${guaranteeStatusClass(flow.guarantee_status)}`}>{guaranteeLabels[flow.guarantee_status]||flow.guarantee_status}</i></strong><small>{flow.guarantee_protocol?`Protocolo ${flow.guarantee_protocol}`:'Sem protocolo'}</small></div>
        </div>

        {flow.promise_status&&<div className={`delinquency-promise ${flow.promise_status}`}><CalendarClock size={15}/><div><strong>{promiseLabels[flow.promise_status]||flow.promise_status}</strong><span>{flow.promise_due_date?`${money(flow.promise_amount)} para ${dateLabel(flow.promise_due_date)}`:money(flow.promise_amount)}</span></div></div>}
        {flow.guarantee_status==='received'&&<div className="delinquency-indemnity"><CheckCircle2 size={15}/><div><strong>Indenização registrada: {money(flow.received_amount)}</strong><span>Isso não baixa automaticamente o débito do locatário. A cobrança original permanece rastreável até sua regularização.</span></div></div>}

        <div className="delinquency-actions">{item.status!=='resolved'&&<><button className="button secondary compact" type="button" onClick={()=>void copyMessage(item)}><Clipboard size={13}/> Copiar mensagem</button>{canManage&&<button className="button secondary compact" type="button" onClick={()=>open(item,'contact')}><MessageCircle size={13}/> Registrar contato</button>}{canManage&&<button className="button secondary compact" type="button" onClick={()=>open(item,'promise')}><CalendarClock size={13}/> Promessa</button>}{canManage&&flow.guarantee_type!=='none'&&<button className="button primary compact" type="button" onClick={()=>open(item,'guarantee')}><ShieldCheck size={13}/> Garantia</button>}</>}</div>

        <details className="delinquency-history"><summary>Histórico do caso · {item.action_log.length} evento(s)</summary><div>{[...item.action_log].reverse().map((row,index)=><div key={`${row.at||index}-${index}`}><span>{dateTimeLabel(row.at)}</span><strong>{actionLabels[row.action||'']||row.action||'Evento'}</strong><small>{row.detail||row.notes||''}{row.channel?` · ${row.channel}`:''}</small></div>)}</div></details>
      </article>
    })}{filtered.length===0&&<article className="panel finance-empty"><ShieldCheck size={26}/><strong>Nenhum caso neste filtro.</strong><span>A régua abre casos automaticamente quando uma cobrança vence sem baixa.</span></article>}</div>}

    {modal&&selected&&<div className="portfolio-modal-backdrop delinquency-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target)close()}}>
      {modal==='contact'&&<form className="panel portfolio-modal delinquency-modal" onSubmit={submitContact}><div className="portfolio-modal-header"><div><span className="eyebrow">{selected.code}</span><h2>Registrar contato</h2><p>O registro conclui o marco correspondente da régua e mantém o histórico auditável.</p></div><button className="portfolio-modal-close" type="button" onClick={close}><X size={17}/></button></div><div className="delinquency-modal-body"><label><span>Canal</span><select value={channel} onChange={e=>setChannel(e.target.value)}><option value="whatsapp">WhatsApp</option><option value="phone">Telefone</option><option value="email">E-mail</option><option value="other">Outro</option></select></label><label><span>Próxima ação (opcional)</span><input type="datetime-local" value={nextAction} onChange={e=>setNextAction(e.target.value)}/></label><label className="full"><span>Retorno / observações</span><textarea rows={5} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Ex.: locatário informou que pagará amanhã."/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={close}>Cancelar</button><button className="button primary" disabled={saving}>{saving?'Salvando...':'Registrar contato'}</button></div></form>}

      {modal==='promise'&&<form className="panel portfolio-modal delinquency-modal" onSubmit={submitPromise}><div className="portfolio-modal-header"><div><span className="eyebrow">{selected.code}</span><h2>Promessa de pagamento</h2><p>Como o Imob não aceita pagamento parcial, a promessa também é registrada pelo valor integral da cobrança.</p></div><button className="portfolio-modal-close" type="button" onClick={close}><X size={17}/></button></div><div className="delinquency-modal-body"><label><span>Valor integral</span><input value={money(selected.amount)} disabled/></label><label><span>Data prometida</span><input type="date" min={today()} required value={promiseDate} onChange={e=>setPromiseDate(e.target.value)}/></label><label className="full"><span>Observações</span><textarea rows={4} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Como o acordo foi feito, contato utilizado, observações relevantes..."/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={close}>Cancelar</button><button className="button primary" disabled={saving}>{saving?'Salvando...':'Registrar promessa'}</button></div></form>}

      {modal==='guarantee'&&<form className="panel portfolio-modal delinquency-modal delinquency-guarantee-modal" onSubmit={submitGuarantee}><div className="portfolio-modal-header"><div><span className="eyebrow">{selected.workflow.guarantee_label} · {selected.code}</span><h2>Acompanhar garantia</h2><p>Registro interno. Salvar “Acionada” não envia dados para a seguradora ou terceiro.</p></div><button className="portfolio-modal-close" type="button" onClick={close}><X size={17}/></button></div><div className="delinquency-external-warning"><AlertTriangle size={15}/><span><strong>Nenhum envio externo será executado.</strong> Registre aqui somente o que foi feito/confirmado fora do Imob.</span></div><div className="delinquency-modal-body"><label><span>Status</span><select value={guaranteeStatus} onChange={e=>setGuaranteeStatus(e.target.value)}><option value="available">Disponível</option><option value="prepared">Preparada</option><option value="submitted">Acionada</option><option value="under_review">Em análise</option><option value="approved">Aprovada</option><option value="rejected">Recusada</option><option value="received">Indenizada / recebida</option><option value="cancelled">Cancelada</option></select></label><label><span>Seguradora / terceiro</span><input value={provider} onChange={e=>setProvider(e.target.value)} placeholder="Nome do prestador"/></label><label><span>Apólice / referência</span><input value={policy} onChange={e=>setPolicy(e.target.value)} placeholder="Opcional"/></label><label><span>Protocolo</span><input value={protocol} onChange={e=>setProtocol(e.target.value)} placeholder={selected.workflow.guarantee_type==='insurance'?'Obrigatório ao acionar seguro':'Protocolo / referência'}/></label><label><span>Valor acionado</span><input type="number" min="0.01" step="0.01" value={claimed} onChange={e=>setClaimed(e.target.value)}/></label><label><span>Valor aprovado</span><input type="number" min="0" step="0.01" value={approved} onChange={e=>setApproved(e.target.value)}/></label><label><span>Valor recebido</span><input type="number" min="0" step="0.01" value={received} onChange={e=>setReceived(e.target.value)}/></label><label><span>Referência do recebimento</span><input value={paymentReference} onChange={e=>setPaymentReference(e.target.value)} placeholder="PIX, comprovante, protocolo..."/></label><label className="full"><span>Próximo acompanhamento</span><input type="datetime-local" value={nextAction} onChange={e=>setNextAction(e.target.value)}/></label><label className="full"><span>Observações</span><textarea rows={4} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Documentos encaminhados, retorno da seguradora, pendências..."/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={close}>Cancelar</button><button className="button primary" disabled={saving}>{saving?'Salvando...':'Salvar acompanhamento'}</button></div></form>}
    </div>}
  </section>
}
