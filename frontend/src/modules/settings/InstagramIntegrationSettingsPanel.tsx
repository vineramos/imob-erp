import { CheckCircle2, CircleAlert, Instagram, RefreshCw, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'

type InstagramConfig={
  provider:string
  graph_version:string
  account_id:string
  username:string
  token_configured:boolean
  configured:boolean
  reachable:boolean|null
  account_type:string|null
  message:string
  checked_at:string|null
}

const emptyConfig:InstagramConfig={
  provider:'instagram_meta',graph_version:'v26.0',account_id:'',username:'',token_configured:false,
  configured:false,reachable:null,account_type:null,message:'',checked_at:null,
}

export function InstagramIntegrationSettingsPanel({canEdit}:{canEdit:boolean}){
  const [config,setConfig]=useState<InstagramConfig>(emptyConfig)
  const [accessToken,setAccessToken]=useState('')
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState(false)
  const [testing,setTesting]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')

  useEffect(()=>{
    let active=true
    void apiRequest<InstagramConfig>('/meta-instagram/config')
      .then(data=>{if(active)setConfig(data)})
      .catch(cause=>{if(active)setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o Instagram.')})
      .finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[])

  async function save(){
    if(!canEdit)return
    setSaving(true);setError('');setSuccess('')
    try{
      const updated=await apiRequest<InstagramConfig>('/meta-instagram/config',{
        method:'PUT',
        body:JSON.stringify({
          graph_version:config.graph_version,
          account_id:config.account_id,
          username:config.username,
          access_token:accessToken||null,
        }),
      })
      setConfig(updated);setAccessToken('')
      setSuccess('Token do Instagram salvo de forma criptografada. Agora teste a conta para validar o acesso.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar a integração do Instagram.')}
    finally{setSaving(false)}
  }

  async function test(){
    if(!canEdit)return
    setTesting(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<{reachable:boolean;account_id:string;username:string;account_type:string|null;message:string}>('/meta-instagram/test',{method:'POST'})
      setConfig(current=>({
        ...current,configured:true,reachable:result.reachable,account_id:result.account_id,username:result.username,
        account_type:result.account_type,message:result.message,checked_at:new Date().toISOString(),
      }))
      setSuccess(result.message+' O botão de publicação dos imóveis já pode usar esta conta.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível validar a conta do Instagram na Meta.')}
    finally{setTesting(false)}
  }

  if(loading)return <article className="panel integration-card integration-card-expanded"><div className="integration-content"><strong>Instagram</strong><span>Carregando configuração...</span></div></article>

  return <article className="panel integration-card integration-card-expanded">
    <div className="integration-icon"><Instagram size={19}/></div>
    <div className="integration-content"><strong>Instagram Business API</strong><span>Meta · publicação de imóveis e futura captação de leads</span></div>
    <i className={'status-badge '+(config.reachable?'success':config.configured?'warning':'neutral')}>{config.reachable?'Conectado':config.configured?'Pronto para testar':'Não configurado'}</i>

    {error&&<div className="form-alert danger-alert">{error}</div>}
    {success&&<div className="form-alert success-alert">{success}</div>}

    <div className="smtp-config-panel">
      <div className="form-grid smtp-config-grid">
        <label className="field"><span>Graph API</span><input disabled={!canEdit} value={config.graph_version} onChange={e=>setConfig(current=>({...current,graph_version:e.target.value}))}/></label>
        <label className="field"><span>Conta conectada</span><input disabled value={config.username?('@'+config.username):'Será identificada automaticamente no teste'}/></label>
        <label className="field"><span>Instagram User ID</span><input disabled value={config.account_id||'Identificado automaticamente'}/></label>
        <label className="field"><span>Tipo de conta</span><input disabled value={config.account_type||'—'}/></label>
        <label className="field field-span-2"><span>Access Token {config.token_configured?'· cadastrado':''}</span><input disabled={!canEdit} type="password" autoComplete="new-password" placeholder={config.token_configured?'Deixe vazio para manter o token atual':'Cole aqui o token gerado no Meta for Developers'} value={accessToken} onChange={e=>setAccessToken(e.target.value)}/></label>
      </div>

      <div className="integration-health">
        <div className="integration-health-copy">
          {config.reachable?<CheckCircle2 size={16}/>:<CircleAlert size={16}/>}
          <div><strong>{config.username?'@'+config.username:'Conta profissional de teste'}</strong><span>{config.message||'Salve o token e execute o teste. O Imob consulta a identidade da conta sem publicar conteúdo.'}</span></div>
        </div>
      </div>

      <div className="smtp-test-row">
        <button className="button secondary compact-button" type="button" disabled={!canEdit||testing||!config.token_configured} onClick={()=>void test()}><RefreshCw size={14}/>{testing?'Testando...':'Testar Meta'}</button>
        <button className="button primary compact-button" type="button" disabled={!canEdit||saving||(!accessToken&&!config.token_configured)} onClick={()=>void save()}><Save size={14}/>{saving?'Salvando...':'Salvar Instagram'}</button>
      </div>
      <small className="smtp-security-note">O token é criptografado e nunca é exibido novamente. O teste consulta apenas a identidade da conta; não publica nada.</small>
    </div>
  </article>
}
