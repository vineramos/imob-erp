import { CheckCircle2, CircleAlert, Copy, MessageCircle, RefreshCw, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'

type WhatsAppConfig = {
  provider:string
  graph_version:string
  business_account_id:string
  phone_number_id:string
  display_phone_number:string
  token_configured:boolean
  verify_token_configured:boolean
  app_secret_configured:boolean
  configured:boolean
  webhook_url:string
  checked_at:string|null
  reachable:boolean|null
  message:string
  last_webhook_at:string|null
  last_webhook_status:string
  last_webhook_message_count:number
  last_webhook_error:string
}

const emptyConfig:WhatsAppConfig={
  provider:'whatsapp_meta',graph_version:'v26.0',business_account_id:'',phone_number_id:'',display_phone_number:'',
  token_configured:false,verify_token_configured:false,app_secret_configured:false,configured:false,webhook_url:'',
  checked_at:null,reachable:null,message:'',last_webhook_at:null,last_webhook_status:'never',last_webhook_message_count:0,last_webhook_error:''
}

export function WhatsAppIntegrationSettingsPanel({canEdit}:{canEdit:boolean}){
  const [config,setConfig]=useState<WhatsAppConfig>(emptyConfig)
  const [accessToken,setAccessToken]=useState('')
  const [verifyToken,setVerifyToken]=useState('')
  const [appSecret,setAppSecret]=useState('')
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState(false)
  const [testing,setTesting]=useState(false)
  const [subscribing,setSubscribing]=useState(false)
  const [subscription,setSubscription]=useState<{subscribed:boolean;message:string}|null>(null)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [copied,setCopied]=useState(false)

  useEffect(()=>{let active=true;void apiRequest<WhatsAppConfig>('/meta-whatsapp/config').then(data=>{if(active)setConfig(data)}).catch(cause=>{if(active)setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o WhatsApp.')}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[])
  useEffect(()=>{let active=true;void apiRequest<{subscribed:boolean;message:string}>('/meta-whatsapp/subscription').then(data=>{if(active)setSubscription(data)}).catch(()=>{if(active)setSubscription(null)});return()=>{active=false}},[])

  async function save(){
    if(!canEdit)return
    setSaving(true);setError('');setSuccess('')
    try{
      const updated=await apiRequest<WhatsAppConfig>('/meta-whatsapp/config',{method:'PUT',body:JSON.stringify({
        graph_version:config.graph_version,
        business_account_id:config.business_account_id,
        phone_number_id:config.phone_number_id,
        display_phone_number:config.display_phone_number,
        access_token:accessToken||null,
        verify_token:verifyToken||null,
        app_secret:appSecret||null,
      })})
      setConfig(updated);setAccessToken('');setVerifyToken('');setAppSecret('')
      setSuccess('WhatsApp Business salvo. As credenciais ficaram protegidas e não serão exibidas novamente.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar o WhatsApp Business.')}
    finally{setSaving(false)}
  }

  async function test(){
    if(!canEdit)return
    setTesting(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<{reachable:boolean;verified_name:string|null;display_phone_number:string|null;message:string}>('/meta-whatsapp/test',{method:'POST'})
      setConfig(current=>({...current,reachable:result.reachable,display_phone_number:result.display_phone_number||current.display_phone_number}))
      setSuccess(result.message+(result.verified_name?' Conta: '+result.verified_name+'.':''))
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível validar a conexão com a Meta.')}
    finally{setTesting(false)}
  }

  async function subscribe(){
    if(!canEdit)return
    setSubscribing(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<{subscribed:boolean;message:string}>('/meta-whatsapp/subscription',{method:'POST'})
      setSubscription(result);setSuccess(result.message)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível inscrever o app na WABA.')}
    finally{setSubscribing(false)}
  }

  async function copyWebhook(){
    try{await navigator.clipboard.writeText(config.webhook_url);setCopied(true);window.setTimeout(()=>setCopied(false),1600)}catch{}
  }

  if(loading)return <article className="panel integration-card integration-card-expanded"><div className="integration-content"><strong>WhatsApp Business</strong><span>Carregando configuração...</span></div></article>

  return <article className="panel integration-card integration-card-expanded">
    <div className="integration-icon"><MessageCircle size={19}/></div>
    <div className="integration-content"><strong>WhatsApp Business API</strong><span>Meta Cloud API · mensagens, leads e automações</span></div>
    <i className={'status-badge '+(config.reachable?'success':config.configured?'warning':'neutral')}>{config.reachable?'Conectado':config.configured?'Pronto para testar':'Não configurado'}</i>

    {error&&<div className="form-alert danger-alert">{error}</div>}
    {success&&<div className="form-alert success-alert">{success}</div>}

    <div className="smtp-config-panel">
      <div className="form-grid smtp-config-grid">
        <label className="field"><span>Graph API</span><input disabled={!canEdit} value={config.graph_version} onChange={e=>setConfig(current=>({...current,graph_version:e.target.value}))}/></label>
        <label className="field"><span>WhatsApp Business Account ID</span><input disabled={!canEdit} inputMode="numeric" autoComplete="off" data-format="raw" placeholder="WABA ID" value={config.business_account_id} onChange={e=>setConfig(current=>({...current,business_account_id:e.target.value.replace(/\D/g,'')}))}/></label>
        <label className="field"><span>Phone Number ID</span><input disabled={!canEdit} inputMode="numeric" autoComplete="off" data-format="raw" placeholder="ID do número na Meta" value={config.phone_number_id} onChange={e=>setConfig(current=>({...current,phone_number_id:e.target.value.replace(/\D/g,'')}))}/></label>
        <label className="field"><span>Número exibido</span><input disabled={!canEdit} placeholder="+55 41 ..." value={config.display_phone_number} onChange={e=>setConfig(current=>({...current,display_phone_number:e.target.value}))}/></label>
        <label className="field"><span>Access Token {config.token_configured?'· cadastrado':''}</span><input disabled={!canEdit} type="password" autoComplete="new-password" placeholder={config.token_configured?'Deixe vazio para manter':'Token permanente da Meta'} value={accessToken} onChange={e=>setAccessToken(e.target.value)}/></label>
        <label className="field"><span>Verify Token {config.verify_token_configured?'· cadastrado':''}</span><input disabled={!canEdit} type="password" autoComplete="new-password" placeholder={config.verify_token_configured?'Deixe vazio para manter':'Token criado por você para o webhook'} value={verifyToken} onChange={e=>setVerifyToken(e.target.value)}/></label>
        <label className="field"><span>App Secret {config.app_secret_configured?'· cadastrado':''}</span><input disabled={!canEdit} type="password" autoComplete="new-password" placeholder={config.app_secret_configured?'Deixe vazio para manter':'Recomendado para validar assinatura do webhook'} value={appSecret} onChange={e=>setAppSecret(e.target.value)}/></label>
      </div>

      <div className="integration-health">
        <div className="integration-health-copy">
          {config.configured?<CheckCircle2 size={16}/>:<CircleAlert size={16}/>}
          <div><strong>Callback URL do webhook</strong><span>{config.webhook_url||'Salve a configuração para gerar a URL pública.'}</span></div>
        </div>
        <button className="button secondary compact-button" type="button" disabled={!config.webhook_url} onClick={()=>void copyWebhook()}><Copy size={13}/>{copied?'Copiado':'Copiar URL'}</button>
      </div>

      <div className="integration-health">
        <div className="integration-health-copy">
          {config.last_webhook_status==='processed'?<CheckCircle2 size={16}/>:<CircleAlert size={16}/>}
          <div>
            <strong>Diagnóstico do webhook</strong>
            <span>{config.last_webhook_at?('Último evento em '+new Date(config.last_webhook_at).toLocaleString('pt-BR')+' · '+config.last_webhook_message_count+' mensagem(ns) · '+config.last_webhook_status):'Nenhum POST da Meta chegou ao Imob ainda.'}</span>
            {config.last_webhook_error&&<small>{config.last_webhook_error}</small>}
          </div>
        </div>
      </div>

      <div className="integration-health">
        <div className="integration-health-copy">
          {subscription?.subscribed?<CheckCircle2 size={16}/>:<CircleAlert size={16}/>}
          <div><strong>Assinatura da conta WhatsApp</strong><span>{subscription?.message||'Ainda não foi possível confirmar se o app está inscrito na WABA.'}</span></div>
        </div>
        <button className="button secondary compact-button" type="button" disabled={!canEdit||subscribing||!config.configured} onClick={()=>void subscribe()}>{subscribing?'Ativando...':subscription?.subscribed?'Revalidar assinatura':'Ativar recebimento'}</button>
      </div>

      <div className="smtp-test-row">
        <button className="button secondary compact-button" type="button" disabled={!canEdit||testing||!config.configured} onClick={()=>void test()}><RefreshCw size={14}/>{testing?'Testando...':'Testar Meta'}</button>
        <button className="button primary compact-button" type="button" disabled={!canEdit||saving||!config.phone_number_id} onClick={()=>void save()}><Save size={14}/>{saving?'Salvando...':'Salvar WhatsApp'}</button>
      </div>
      <small className="smtp-security-note">Access Token, Verify Token e App Secret são criptografados. O App Secret habilita validação HMAC dos eventos recebidos da Meta.</small>
    </div>
  </article>
}
