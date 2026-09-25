import {
  AlertTriangle, CheckCircle2, FileText, History, Mail, MessageCircle, Plus, RefreshCw, Send, Settings2, X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './communications.css'

type MessageEvent={id:string;event_type:string;event_data:Record<string,unknown>;created_at:string}
type Message={
  id:string;internal_number:number;person_id:string|null;recipient_name:string;recipient_email:string|null;recipient_phone:string|null;
  recipient_role:string;channel:string;category:string;origin:string;subject:string;body:string;status:string;source_module:string|null;
  source_type:string|null;source_id:string|null;attachment_manifest:Array<Record<string,unknown>>;provider_name:string|null;provider_message_id:string|null;
  error_message:string|null;attempt_count:number;suggested_at:string|null;queued_at:string|null;sent_at:string|null;failed_at:string|null;
  cancelled_at:string|null;created_at:string;updated_at:string;send_allowed:boolean;blocked_reason:string|null;events:MessageEvent[]
}
type Overview={total:number;counts:Record<string,number>;email_configured:boolean;whatsapp_configured:boolean;human_confirmation_required:boolean}
type Capabilities={email:{configured:boolean;provider:string;supports_attachments:boolean};whatsapp:{configured:boolean;provider:string|null;webhook_configured?:boolean;api_version?:string;reason?:string|null}}
type Template={id:string;key:string;channel:string;name:string;subject_template:string;body_template:string;is_active:boolean;is_system_default:boolean;updated_at:string}
type Preference={person_id:string;person_name:string;email:string|null;phone:string|null;email_enabled:boolean;whatsapp_enabled:boolean;transactional_enabled:boolean;preferred_channel:string;notes:string|null}
type Tab='queue'|'history'|'templates'
type Props={permissions:string[]}

const statusLabel:Record<string,string>={draft:'Rascunho',pending:'Aguardando envio',sending:'Enviando',sent:'Enviado',failed:'Falhou',cancelled:'Cancelado'}
const categoryLabel:Record<string,string>={rent_overdue:'Cobrança em atraso',lease_adjustment:'Reajuste',lease_expiry:'Término de contrato',lease_signed:'Contrato assinado',owner_repasse_paid:'Repasse realizado',owner_repasse_overdue:'Repasse pendente',inspection_schedule:'Vistoria',maintenance_update:'Manutenção',manual:'Manual'}
const roleLabel:Record<string,string>={tenant:'Inquilino',owner:'Proprietário',other:'Outro'}
const dateTime=(value:string|null|undefined)=>value?new Date(value).toLocaleString('pt-BR'):'—'
const code=(item:Message)=>`COM-${String(item.internal_number).padStart(6,'0')}`
function errorText(cause:unknown,fallback:string){return cause instanceof ApiError?cause.detail:fallback}

export default function CommunicationsPage({permissions}:Props){
  const canManage=permissions.includes('communications.manage')
  const canSend=permissions.includes('communications.send')
  const [messages,setMessages]=useState<Message[]>([])
  const [overview,setOverview]=useState<Overview|null>(null)
  const [capabilities,setCapabilities]=useState<Capabilities|null>(null)
  const [templates,setTemplates]=useState<Template[]>([])
  const [tab,setTab]=useState<Tab>('queue')
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [selected,setSelected]=useState<Message|null>(null)
  const [subject,setSubject]=useState('')
  const [body,setBody]=useState('')
  const [recipientName,setRecipientName]=useState('')
  const [recipientEmail,setRecipientEmail]=useState('')
  const [recipientPhone,setRecipientPhone]=useState('')
  const [channel,setChannel]=useState<'email'|'whatsapp'>('email')
  const [compose,setCompose]=useState(false)
  const [templateEdit,setTemplateEdit]=useState<Template|null>(null)
  const [preference,setPreference]=useState<Preference|null>(null)

  const load=useCallback(async()=>{
    setLoading(true);setError('')
    try{
      const [items,summary,caps,modelos]=await Promise.all([
        apiRequest<Message[]>('/communications/messages'),
        apiRequest<Overview>('/communications/overview'),
        apiRequest<Capabilities>('/communications/capabilities'),
        apiRequest<Template[]>('/communications/templates'),
      ])
      setMessages(items);setOverview(summary);setCapabilities(caps);setTemplates(modelos)
    }catch(cause){setError(errorText(cause,'Não foi possível carregar a Central de Comunicações.'))}
    finally{setLoading(false)}
  },[])
  useEffect(()=>{void load()},[load])

  const queue=useMemo(()=>messages.filter(item=>['draft','pending','sending','failed'].includes(item.status)),[messages])
  const history=useMemo(()=>messages.filter(item=>['sent','cancelled'].includes(item.status)),[messages])

  async function refreshSuggestions(){
    setSaving(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<{created:number}>('/communications/suggestions/refresh',{method:'POST',body:JSON.stringify({include_overdue_charges:true,include_contracts:true,include_owner_repasses:true})})
      await load();setSuccess(result.created?`${result.created} nova(s) comunicação(ões) sugerida(s). Nenhuma foi enviada automaticamente.`:'Nenhuma nova sugestão. A proteção contra duplicidade está ativa.')
    }catch(cause){setError(errorText(cause,'Não foi possível atualizar as sugestões.'))}
    finally{setSaving(false)}
  }

  async function openMessage(item:Message){
    setError('');setSuccess('')
    try{
      const detail=await apiRequest<Message>(`/communications/messages/${item.id}`)
      setSelected(detail);setSubject(detail.subject);setBody(detail.body);setRecipientName(detail.recipient_name);setRecipientEmail(detail.recipient_email||'');setRecipientPhone(detail.recipient_phone||'');setChannel(detail.channel as 'email'|'whatsapp')
    }catch(cause){setError(errorText(cause,'Não foi possível abrir a comunicação.'))}
  }
  function closeMessage(){if(!saving){setSelected(null);setPreference(null)}}

  async function saveMessage(){
    if(!selected)return
    setSaving(true);setError('')
    try{
      const updated=await apiRequest<Message>(`/communications/messages/${selected.id}`,{method:'PATCH',body:JSON.stringify({recipient_name:recipientName,recipient_email:recipientEmail||null,recipient_phone:recipientPhone||null,channel,subject,body})})
      setSelected(updated);await load();setSuccess(`${code(updated)} atualizado.`)
    }catch(cause){setError(errorText(cause,'Não foi possível salvar a comunicação.'))}
    finally{setSaving(false)}
  }

  async function sendMessage(retry=false){
    if(!selected)return
    setSaving(true);setError('')
    try{
      const updated=await apiRequest<Message>(`/communications/messages/${selected.id}/${retry?'retry':'send'}`,{method:'POST'})
      setSelected(updated);await load();setSuccess(`${code(updated)} enviado e registrado no histórico.`)
    }catch(cause){setError(errorText(cause,'Não foi possível enviar a comunicação.'));try{setSelected(await apiRequest<Message>(`/communications/messages/${selected.id}`));await load()}catch{/* mantém modal */}}
    finally{setSaving(false)}
  }

  async function cancelMessage(){
    if(!selected)return
    setSaving(true);setError('')
    try{const updated=await apiRequest<Message>(`/communications/messages/${selected.id}/cancel`,{method:'POST'});setSelected(updated);await load();setSuccess(`${code(updated)} cancelado sem envio externo.`)}
    catch(cause){setError(errorText(cause,'Não foi possível cancelar a comunicação.'))}
    finally{setSaving(false)}
  }

  async function createManual(event:FormEvent){
    event.preventDefault();setSaving(true);setError('')
    try{
      const item=await apiRequest<Message>('/communications/messages',{method:'POST',body:JSON.stringify({recipient_name:recipientName,recipient_email:recipientEmail||null,recipient_phone:recipientPhone||null,recipient_role:'other',channel,category:'manual',subject,body})})
      setCompose(false);await load();await openMessage(item);setSuccess(`${code(item)} criado como rascunho.`)
    }catch(cause){setError(errorText(cause,'Não foi possível criar a comunicação.'))}
    finally{setSaving(false)}
  }

  function startCompose(){setCompose(true);setSelected(null);setRecipientName('');setRecipientEmail('');setRecipientPhone('');setChannel('email');setSubject('');setBody('');setError('');setSuccess('')}

  async function saveTemplate(event:FormEvent){
    event.preventDefault();if(!templateEdit)return
    setSaving(true);setError('')
    try{await apiRequest(`/communications/templates/${templateEdit.id}`,{method:'PUT',body:JSON.stringify({name:templateEdit.name,subject_template:templateEdit.subject_template,body_template:templateEdit.body_template,is_active:templateEdit.is_active})});setTemplateEdit(null);await load();setSuccess('Modelo atualizado. Novas sugestões usarão esta versão.')}
    catch(cause){setError(errorText(cause,'Não foi possível atualizar o modelo.'))}
    finally{setSaving(false)}
  }

  async function openPreference(){
    if(!selected?.person_id)return
    try{setPreference(await apiRequest<Preference>(`/communications/preferences/${selected.person_id}`))}
    catch(cause){setError(errorText(cause,'Não foi possível carregar as preferências do cliente.'))}
  }
  async function savePreference(){
    if(!preference)return
    setSaving(true);setError('')
    try{
      const next=await apiRequest<Preference>(`/communications/preferences/${preference.person_id}`,{method:'PUT',body:JSON.stringify({email_enabled:preference.email_enabled,whatsapp_enabled:preference.whatsapp_enabled,transactional_enabled:preference.transactional_enabled,preferred_channel:preference.preferred_channel,notes:preference.notes})})
      setPreference(next);if(selected)setSelected(await apiRequest<Message>(`/communications/messages/${selected.id}`));await load();setSuccess('Preferências de comunicação atualizadas.')
    }catch(cause){setError(errorText(cause,'Não foi possível salvar as preferências.'))}
    finally{setSaving(false)}
  }

  const rows=tab==='queue'?queue:history
  const whatsappStatus=capabilities?.whatsapp.configured
    ? (capabilities.whatsapp.webhook_configured?'Envio + webhook prontos':'Envio pronto · webhook pendente')
    : 'Credenciais pendentes'
  return <section className="workspace communications-workspace">
    <div className="page-heading communications-heading"><div><span className="eyebrow">Relacionamento · operação</span><h1>Comunicações</h1><p>Fila, revisão humana, envio e histórico auditável de mensagens transacionais.</p></div><div className="heading-actions"><button className="button secondary" type="button" disabled={loading||saving} onClick={()=>void load()}><RefreshCw size={14}/> Atualizar</button>{canManage&&<button className="button secondary" type="button" onClick={startCompose}><Plus size={14}/> Nova comunicação</button>}{canManage&&<button className="button primary" type="button" disabled={saving} onClick={()=>void refreshSuggestions()}><Settings2 size={14}/> Atualizar sugestões</button>}</div></div>

    <div className="communication-safety"><CheckCircle2 size={17}/><div><strong>Controle humano obrigatório.</strong><span>O Imob pode preparar mensagens a partir dos eventos do ERP, mas nenhuma sugestão é enviada sozinha. O envio exige uma ação explícita de usuário autorizado.</span></div></div>
    <div className="communication-capabilities"><span className={capabilities?.email.configured?'ready':'pending'}><Mail size={15}/><b>E-mail / SMTP</b>{capabilities?.email.configured?'Configurado':'Não configurado'}</span><span className={capabilities?.whatsapp.configured?'ready':'pending'}><MessageCircle size={15}/><b>WhatsApp · Meta {capabilities?.whatsapp.api_version||''}</b>{whatsappStatus}</span></div>

    {overview&&<div className="communication-metrics"><article className="panel"><span>Aguardando</span><strong>{(overview.counts.draft||0)+(overview.counts.pending||0)}</strong><small>Revisão e confirmação humana</small></article><article className={`panel ${overview.counts.failed?'critical':''}`}><span>Falhas</span><strong>{overview.counts.failed||0}</strong><small>Disponíveis para correção/reenvio</small></article><article className="panel"><span>Enviadas</span><strong>{overview.counts.sent||0}</strong><small>Histórico preservado</small></article><article className="panel"><span>Total</span><strong>{overview.total}</strong><small>Todos os estados</small></article></div>}
    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}

    <div className="communications-tabs panel"><button className={tab==='queue'?'active':''} onClick={()=>setTab('queue')}><Mail size={15}/> Fila <small>{queue.length}</small></button><button className={tab==='history'?'active':''} onClick={()=>setTab('history')}><History size={15}/> Histórico <small>{history.length}</small></button><button className={tab==='templates'?'active':''} onClick={()=>setTab('templates')}><FileText size={15}/> Modelos <small>{templates.length}</small></button></div>

    {loading?<article className="panel settings-loading">Carregando comunicações...</article>:tab==='templates'?<div className="communication-template-grid">{templates.map(item=><article className="panel communication-template" key={item.id}><div><span>{item.channel.toUpperCase()} · {item.key}</span><strong>{item.name}</strong><small>{item.is_active?'Ativo':'Inativo'} · {item.is_system_default?'Modelo padrão':'Personalizado'}</small></div><p>{item.subject_template||'Sem assunto'}</p>{canManage&&<button className="button secondary" onClick={()=>setTemplateEdit({...item})}>Editar modelo</button>}</article>)}</div>:rows.length===0?<article className="panel communication-empty"><Mail size={24}/><strong>{tab==='queue'?'Fila vazia':'Nenhuma comunicação concluída'}</strong><span>{tab==='queue'?'Atualize as sugestões ou crie uma comunicação manual.':'Os envios e cancelamentos aparecerão aqui.'}</span></article>:<div className="communication-list">{rows.map(item=><button className={`panel communication-row status-${item.status}`} type="button" key={item.id} onClick={()=>void openMessage(item)}><div className="communication-row-code"><span>{code(item)}</span><i>{statusLabel[item.status]||item.status}</i></div><div className="communication-row-main"><strong>{item.recipient_name}</strong><span>{categoryLabel[item.category]||item.category} · {roleLabel[item.recipient_role]||item.recipient_role}</span><small>{item.subject||'Sem assunto'}</small></div><div className="communication-row-meta"><span>{item.channel==='email'?<Mail size={14}/>:<MessageCircle size={14}/>} {item.channel}</span><small>{dateTime(item.sent_at||item.suggested_at||item.created_at)}</small>{item.blocked_reason&&item.status!=='sent'&&<em>{item.blocked_reason}</em>}</div></button>)}</div>}

    {selected&&<div className="modal-backdrop"><div className="modal-card communications-modal"><div className="modal-header"><div><span className="eyebrow">{code(selected)} · {statusLabel[selected.status]||selected.status}</span><h2>Prévia da comunicação</h2></div><button className="modal-close" onClick={closeMessage}><X size={18}/></button></div><div className="communications-modal-body">
      <div className="communication-recipient-grid"><label>Destinatário<input value={recipientName} disabled={!canManage||['sent','cancelled'].includes(selected.status)} onChange={e=>setRecipientName(e.target.value)}/></label><label>E-mail<input value={recipientEmail} disabled={!canManage||['sent','cancelled'].includes(selected.status)} onChange={e=>setRecipientEmail(e.target.value)}/></label><label>Telefone<input value={recipientPhone} disabled={!canManage||['sent','cancelled'].includes(selected.status)} onChange={e=>setRecipientPhone(e.target.value)}/></label><label>Canal<select value={channel} disabled={!canManage||['sent','cancelled'].includes(selected.status)} onChange={e=>setChannel(e.target.value as 'email'|'whatsapp')}><option value="email">E-mail</option><option value="whatsapp">WhatsApp</option></select></label></div>
      <label>Assunto<input value={subject} disabled={!canManage||['sent','cancelled'].includes(selected.status)} onChange={e=>setSubject(e.target.value)}/></label><label>Mensagem<textarea rows={12} value={body} disabled={!canManage||['sent','cancelled'].includes(selected.status)} onChange={e=>setBody(e.target.value)}/></label>
      {selected.attachment_manifest.length>0&&<div className="communication-attachments"><strong>Anexos e referências contextuais</strong>{selected.attachment_manifest.map((entry,index)=><span key={index}><FileText size={14}/>{String(entry.label||entry.kind||'Documento')}</span>)}</div>}
      {selected.provider_message_id&&<div className="communication-attachments"><strong>Rastreio do provider</strong><span>{selected.provider_name||'provider'} · {selected.provider_message_id}</span></div>}
      {selected.error_message&&<div className="form-alert danger-alert"><AlertTriangle size={15}/>{selected.error_message}</div>}
      {selected.blocked_reason&&selected.status!=='sent'&&<div className="communication-blocked"><AlertTriangle size={15}/><span>{selected.blocked_reason}</span></div>}
      {selected.person_id&&canManage&&<button className="button link-button" type="button" onClick={()=>void openPreference()}>Preferências deste cliente</button>}
      {preference&&<div className="communication-preference panel"><div><strong>{preference.person_name}</strong><small>{preference.email||'Sem e-mail'} · {preference.phone||'Sem telefone'}</small></div><label><input type="checkbox" checked={preference.transactional_enabled} onChange={e=>setPreference({...preference,transactional_enabled:e.target.checked})}/> Comunicações transacionais</label><label><input type="checkbox" checked={preference.email_enabled} onChange={e=>setPreference({...preference,email_enabled:e.target.checked})}/> E-mail</label><label><input type="checkbox" checked={preference.whatsapp_enabled} onChange={e=>setPreference({...preference,whatsapp_enabled:e.target.checked})}/> WhatsApp</label><button className="button secondary" disabled={saving} onClick={()=>void savePreference()}>Salvar preferências</button></div>}
      {selected.events.length>0&&<div className="communication-timeline"><strong>Histórico</strong>{selected.events.map(event=><div key={event.id}><span>{event.event_type.replaceAll('_',' ')}</span><small>{dateTime(event.created_at)}</small></div>)}</div>}
    </div><div className="modal-actions">{canManage&&!['sent','cancelled'].includes(selected.status)&&<button className="button secondary" disabled={saving} onClick={()=>void saveMessage()}>Salvar alterações</button>}{canManage&&!['sent','cancelled'].includes(selected.status)&&<button className="button danger" disabled={saving} onClick={()=>void cancelMessage()}>Cancelar</button>}{canSend&&selected.status==='failed'&&<button className="button primary" disabled={saving||!selected.send_allowed} onClick={()=>void sendMessage(true)}><RefreshCw size={14}/> Reenviar</button>}{canSend&&['draft','pending'].includes(selected.status)&&<button className="button primary" disabled={saving||!selected.send_allowed} onClick={()=>void sendMessage(false)}><Send size={14}/> Enviar agora</button>}</div></div></div>}

    {compose&&<div className="modal-backdrop"><form className="modal-card communications-modal" onSubmit={createManual}><div className="modal-header"><div><span className="eyebrow">Comunicação manual</span><h2>Nova comunicação</h2></div><button type="button" className="modal-close" onClick={()=>setCompose(false)}><X size={18}/></button></div><div className="communications-modal-body"><div className="communication-recipient-grid"><label>Destinatário<input required value={recipientName} onChange={e=>setRecipientName(e.target.value)}/></label><label>E-mail<input type="email" value={recipientEmail} onChange={e=>setRecipientEmail(e.target.value)}/></label><label>Telefone<input value={recipientPhone} onChange={e=>setRecipientPhone(e.target.value)}/></label><label>Canal<select value={channel} onChange={e=>setChannel(e.target.value as 'email'|'whatsapp')}><option value="email">E-mail</option><option value="whatsapp">WhatsApp</option></select></label></div><label>Assunto<input value={subject} onChange={e=>setSubject(e.target.value)}/></label><label>Mensagem<textarea required rows={12} value={body} onChange={e=>setBody(e.target.value)}/></label><div className="communication-blocked"><CheckCircle2 size={15}/><span>A criação salva um rascunho. O envio será confirmado separadamente.</span></div></div><div className="modal-actions"><button type="button" className="button secondary" onClick={()=>setCompose(false)}>Voltar</button><button className="button primary" disabled={saving}>Criar rascunho</button></div></form></div>}

    {templateEdit&&<div className="modal-backdrop"><form className="modal-card communications-modal" onSubmit={saveTemplate}><div className="modal-header"><div><span className="eyebrow">{templateEdit.key}</span><h2>Editar modelo</h2></div><button type="button" className="modal-close" onClick={()=>setTemplateEdit(null)}><X size={18}/></button></div><div className="communications-modal-body"><label>Nome<input required value={templateEdit.name} onChange={e=>setTemplateEdit({...templateEdit,name:e.target.value})}/></label><label>Assunto<input value={templateEdit.subject_template} onChange={e=>setTemplateEdit({...templateEdit,subject_template:e.target.value})}/></label><label>Mensagem<textarea rows={12} required value={templateEdit.body_template} onChange={e=>setTemplateEdit({...templateEdit,body_template:e.target.value})}/></label><label className="communication-check"><input type="checkbox" checked={templateEdit.is_active} onChange={e=>setTemplateEdit({...templateEdit,is_active:e.target.checked})}/> Modelo ativo</label><small>Variáveis aceitas usam o formato {'{{variavel}}'}. O motor não executa código nem expressões.</small></div><div className="modal-actions"><button type="button" className="button secondary" onClick={()=>setTemplateEdit(null)}>Cancelar</button><button className="button primary" disabled={saving}>Salvar modelo</button></div></form></div>}
  </section>
}
