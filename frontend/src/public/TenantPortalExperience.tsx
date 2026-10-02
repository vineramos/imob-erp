import { CalendarDays, CheckCircle2, KeyRound, MessageCircle, Send, XCircle } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, publicApiRequest } from '../api/client'

type Lease = {
  id:string; code:string; status:string; property_address:Record<string,string>; start_date:string; end_date:string; operational_end_date:string|null
}
type Lifecycle = {
  id:string; code:string; lease_contract_id:string; process_type:string; status:string; initiated_by:string|null; requested_at:string;
  effective_date:string|null; reason:string|null; termination_fine_amount:number; fine_status:string; exit_inspection_id:string|null;
  keys_returned_at:string|null; financial_pending_count:number; financial_pending_amount:number; can_close:boolean; closed_at:string|null; updated_at:string
}
type Communication = { id:string; code:string; channel:string; category:string; subject:string; body:string; source_module:string|null; sent_at:string|null }
type Experience = { lifecycle:Lifecycle[]; communications:Communication[] }

type Props = { leases:Lease[]; onChanged:()=>Promise<void> }

const money=(value:number)=>Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
const localDate=(value:string)=>new Date(`${value.slice(0,10)}T12:00:00`)
const dateLabel=(value:string|null)=>value?localDate(value).toLocaleDateString('pt-BR'):'—'
const dateTimeLabel=(value:string|null)=>value?new Date(value).toLocaleString('pt-BR'):'—'
const addressLabel=(address:Record<string,string>)=>[address.street||address.logradouro,address.number||address.numero,address.complement||address.complemento,address.neighborhood||address.bairro,address.city||address.cidade,address.state||address.uf].filter(Boolean).join(', ')||'Endereço não informado'
const isoToday=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
const statusLabel=(value:string)=>({
  termination_requested:'Solicitação recebida',exit_inspection_pending:'Vistoria de saída',key_return_pending:'Devolução das chaves',
  financial_clearance_pending:'Acerto financeiro',closed:'Encerrado',cancelled:'Cancelado',renewal_proposed:'Renovação proposta',renewal_prepared:'Renovação preparada',renewed:'Renovado',
} as Record<string,string>)[value]||value
const channelLabel=(value:string)=>value==='whatsapp'?'WhatsApp':value==='email'?'E-mail':value

export function TenantPortalExperience({leases,onChanged}:Props){
  const [data,setData]=useState<Experience|null>(null)
  const [error,setError]=useState('')
  const [terminationOpen,setTerminationOpen]=useState(false)
  const activeLeases=useMemo(()=>leases.filter(item=>item.status==='signed'),[leases])

  const load=useCallback(async()=>{
    try{setData(await publicApiRequest<Experience>('/tenant-portal/experience'));setError('')}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o acompanhamento da locação.')}
  },[])
  useEffect(()=>{void load()},[load])

  const lifecycleByLease=useMemo(()=>new Map((data?.lifecycle||[]).map(item=>[item.lease_contract_id,item])),[data])
  const canRequest=activeLeases.some(lease=>{const item=lifecycleByLease.get(lease.id);return !item||item.status==='cancelled'})

  async function changed(){await load();await onChanged()}

  return <div className="tenant-stack" style={{marginTop:16}}>
    {error&&<div className="tenant-alert danger"><XCircle size={15}/><span>{error}</span></div>}
    <article className="tenant-card">
      <div className="tenant-card-section-head"><div><span className="tenant-section-kicker">Desocupação</span><h2>Encerramento da locação</h2><p>Acompanhe solicitação, vistoria final, chaves e acerto financeiro em uma única sequência.</p></div><KeyRound size={19}/></div>
      {activeLeases.length===0?<div className="tenant-empty-state"><CheckCircle2 size={23}/><strong>Nenhuma locação ativa</strong><span>Os processos encerrados continuam no histórico abaixo.</span></div>:null}
      <div className="tenant-stack">
        {leases.map(lease=>{const item=lifecycleByLease.get(lease.id);if(!item&&lease.status!=='signed')return null;return <div className="tenant-card" key={lease.id} style={{marginTop:10}}>
          <div className="tenant-card-head"><div><span>{lease.code}</span><h2>{addressLabel(lease.property_address)}</h2></div>{item?<span className={`tenant-inline-status ${item.status}`}>{statusLabel(item.status)}</span>:<span className="tenant-inline-status">Locação ativa</span>}</div>
          {item?<><div className="tenant-detail-grid"><div><span>Solicitado em</span><strong>{dateTimeLabel(item.requested_at)}</strong></div><div><span>Saída prevista</span><strong>{dateLabel(item.effective_date)}</strong></div><div><span>Multa estimada</span><strong>{money(item.termination_fine_amount)}</strong></div><div><span>Situação da multa</span><strong>{item.fine_status==='pending'?'Em análise / pendente':item.fine_status==='waived'?'Dispensada':item.fine_status==='registered'?'Registrada':'Não aplicável'}</strong></div><div><span>Chaves devolvidas</span><strong>{dateTimeLabel(item.keys_returned_at)}</strong></div><div><span>Pendências financeiras</span><strong>{item.financial_pending_count?`${item.financial_pending_count} · ${money(item.financial_pending_amount)}`:'Nenhuma pendência bloqueadora'}</strong></div></div>{item.reason&&<p style={{marginTop:12}}><b>Motivo informado:</b> {item.reason}</p>}</>:<p>A locação segue ativa e ainda não possui pedido de encerramento.</p>}
        </div>})}
      </div>
      {canRequest&&<button className="tenant-primary compact" style={{marginTop:14}} onClick={()=>setTerminationOpen(true)}><Send size={14}/> Solicitar desocupação</button>}
    </article>

    <article className="tenant-card">
      <div className="tenant-card-section-head"><div><span className="tenant-section-kicker">Comunicações</span><h2>Mensagens enviadas para você</h2><p>Somente comunicações efetivamente enviadas ao seu cadastro aparecem aqui.</p></div><MessageCircle size={19}/></div>
      {(data?.communications||[]).length?<div className="tenant-history-list">{data!.communications.map(item=><div className="tenant-history-row" key={item.id}><div className="tenant-history-main"><strong>{item.subject||item.category}</strong><span>{channelLabel(item.channel)} · {dateTimeLabel(item.sent_at)} · {item.code}</span><p style={{margin:'6px 0 0',whiteSpace:'pre-wrap'}}>{item.body}</p></div><small className="tenant-inline-status paid">Enviada</small></div>)}</div>:<div className="tenant-empty-state"><MessageCircle size={23}/><strong>Nenhuma comunicação no histórico</strong><span>E-mails e mensagens transacionais aparecerão aqui depois do envio pela imobiliária.</span></div>}
    </article>
    {terminationOpen&&<TerminationModal leases={activeLeases.filter(lease=>{const item=lifecycleByLease.get(lease.id);return !item||item.status==='cancelled'})} onClose={()=>setTerminationOpen(false)} onCreated={async()=>{setTerminationOpen(false);await changed()}}/>}
  </div>
}

function TerminationModal({leases,onClose,onCreated}:{leases:Lease[];onClose:()=>void;onCreated:()=>Promise<void>}){
  const [leaseId,setLeaseId]=useState(leases[0]?.id||'')
  const [effectiveDate,setEffectiveDate]=useState(isoToday())
  const [reason,setReason]=useState('')
  const [error,setError]=useState('')
  const [saving,setSaving]=useState(false)
  const selected=leases.find(item=>item.id===leaseId)
  async function submit(event:FormEvent){
    event.preventDefault();setError('');setSaving(true)
    try{await publicApiRequest('/tenant-portal/termination',{method:'POST',body:JSON.stringify({lease_contract_id:leaseId,effective_date:effectiveDate,reason})});await onCreated()}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível registrar a solicitação de desocupação.')}
    finally{setSaving(false)}
  }
  return <div className="tenant-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target&&!saving)onClose()}}><form className="tenant-modal" onSubmit={submit} role="dialog" aria-modal="true"><div className="tenant-modal-head"><div><span className="tenant-eyebrow">Encerramento</span><h2>Solicitar desocupação</h2><p>O pedido inicia o fluxo formal da imobiliária. A multa exibida depois é uma estimativa contratual e permanece sujeita à análise do processo.</p></div><button type="button" onClick={onClose} disabled={saving}>×</button></div>{error&&<div className="tenant-alert danger"><XCircle size={15}/><span>{error}</span></div>}<label><span>Locação</span><select value={leaseId} onChange={event=>setLeaseId(event.target.value)} required>{leases.map(item=><option key={item.id} value={item.id}>{item.code} · {addressLabel(item.property_address)}</option>)}</select></label>{selected&&<small className="tenant-selected-address">Contrato até {dateLabel(selected.end_date)}</small>}<label><span>Data prevista para desocupação</span><input type="date" min={isoToday()} value={effectiveDate} onChange={event=>setEffectiveDate(event.target.value)} required/></label><label><span>Motivo</span><textarea rows={5} minLength={3} maxLength={3000} value={reason} onChange={event=>setReason(event.target.value)} required placeholder="Informe brevemente o motivo e qualquer contexto útil para a equipe."/></label><div className="tenant-password-note"><CalendarDays size={15}/><span>Após o pedido, a equipe seguirá com vistoria de saída, devolução de chaves e acerto financeiro antes do encerramento definitivo.</span></div><div className="tenant-modal-actions"><button type="button" className="tenant-secondary" onClick={onClose} disabled={saving}>Cancelar</button><button className="tenant-primary" disabled={saving||!leaseId||reason.trim().length<3}>{saving?'Enviando...':'Confirmar solicitação'}</button></div></form></div>
}
