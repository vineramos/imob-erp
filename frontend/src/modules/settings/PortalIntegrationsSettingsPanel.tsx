import { CheckCircle2, CircleAlert, Copy, ExternalLink, RadioTower, RefreshCw, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './portal-integrations-settings.css'

type Validation = {
  valid:boolean
  xml_valid:boolean
  xml_error:string|null
  document_issues?:string[]
  selected_count:number
  invalid_count:number
  invalid_properties:Array<{code:string;issues:string[]}>
  checked_at:string
}
type Channel = {
  key:'olx'|'vrsync'
  label:string
  status:'not_configured'|'pending_homologation'|'active'|'rejected'
  notes:string
  last_validated_at:string|null
  last_validation:Validation|null
  feed_url:string
}
type PortalConfig = {channels:Channel[]}

const statusLabel:Record<Channel['status'],string>={
  not_configured:'Não configurado',
  pending_homologation:'Aguardando homologação',
  active:'Ativo no portal',
  rejected:'Rejeitado / ajustes',
}

function badge(channel:Channel){
  if(channel.status==='active')return <i className="status-badge success">Ativo</i>
  if(channel.status==='pending_homologation')return <i className="status-badge warning">Em homologação</i>
  if(channel.status==='rejected')return <i className="status-badge danger">Rejeitado</i>
  return <i className="status-badge neutral">Não configurado</i>
}

export function PortalIntegrationsSettingsPanel({canEdit}:{canEdit:boolean}){
  const [channels,setChannels]=useState<Channel[]>([])
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState('')
  const [validating,setValidating]=useState('')
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [copied,setCopied]=useState('')

  useEffect(()=>{let active=true;void apiRequest<PortalConfig>('/integrations/portals').then(data=>{if(active)setChannels(data.channels)}).catch(cause=>{if(active)setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os portais.')}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[])

  function patch(key:Channel['key'],value:Partial<Channel>){setChannels(current=>current.map(item=>item.key===key?{...item,...value}:item))}

  async function save(channel:Channel){
    if(!canEdit)return
    setSaving(channel.key);setError('');setSuccess('')
    try{
      const updated=await apiRequest<Channel>(`/integrations/portals/${channel.key}`,{method:'PUT',body:JSON.stringify({status:channel.status,notes:channel.notes})})
      patch(channel.key,updated)
      setSuccess(`${channel.label}: status de homologação salvo.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar o portal.')}
    finally{setSaving('')}
  }

  async function validate(channel:Channel){
    if(!canEdit)return
    setValidating(channel.key);setError('');setSuccess('')
    try{
      const result=await apiRequest<Channel&{validation:Validation}>(`/integrations/portals/${channel.key}/validate`,{method:'POST'})
      patch(channel.key,{...result,last_validation:result.validation,last_validated_at:result.validation.checked_at})
      if(result.validation.valid)setSuccess(`${channel.label}: XML válido e ${result.validation.selected_count} imóvel(is) pronto(s) no feed.`)
      else setError(`${channel.label}: validação encontrou pendências antes da homologação.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível validar o feed.')}
    finally{setValidating('')}
  }

  async function copy(channel:Channel){
    try{await navigator.clipboard.writeText(channel.feed_url);setCopied(channel.key);window.setTimeout(()=>setCopied(''),1600)}catch{}
  }

  return <article className="panel portal-settings-card">
    <div className="panel-heading panel-heading-row portal-settings-heading">
      <div><span className="eyebrow">Portais imobiliários</span><h2>Distribuição de anúncios</h2><p>Valide o XML, acompanhe a homologação e mantenha a URL entregue a cada portal.</p></div>
      <RadioTower size={19}/>
    </div>
    {error&&<div className="form-alert danger-alert">{error}</div>}
    {success&&<div className="form-alert success-alert">{success}</div>}
    {loading?<div className="portal-settings-loading">Carregando canais...</div>:<div className="portal-settings-list">
      {channels.map(channel=>{
        const validation=channel.last_validation
        return <section className="portal-settings-channel" key={channel.key}>
          <div className={'portal-settings-mark '+channel.key}>{channel.key==='olx'?'OLX':'ZAP + VR'}</div>
          <div className="portal-settings-main">
            <div className="portal-settings-title"><div><strong>{channel.label}</strong><small>{channel.key==='olx'?'Feed XML OLX · homologação própria':'VRSync compartilhado entre ZAP Imóveis e Viva Real'}</small></div>{badge(channel)}</div>
            <div className="portal-settings-feed"><code>{channel.feed_url}</code><button type="button" onClick={()=>void copy(channel)}><Copy size={12}/>{copied===channel.key?'Copiado':'Copiar'}</button><a href={channel.feed_url} target="_blank" rel="noreferrer"><ExternalLink size={12}/></a></div>
            <div className="portal-settings-validation">
              {validation?.valid?<CheckCircle2 size={14}/>:<CircleAlert size={14}/>}
              <div><strong>{validation?validation.valid?'Feed validado':'Feed com pendências':'Ainda não validado'}</strong><span>{validation?`${validation.selected_count} selecionado(s) · ${validation.invalid_count} inválido(s) · XML ${validation.xml_valid?'bem-formado':'inválido'}`:'Execute a validação antes de enviar a URL ao portal.'}</span></div>
              <button className="button secondary compact-button" disabled={!canEdit||Boolean(validating)} type="button" onClick={()=>void validate(channel)}><RefreshCw size={13}/>{validating===channel.key?'Validando...':'Validar XML'}</button>
            </div>
            {validation&&validation.invalid_properties.length>0&&<div className="portal-settings-invalids">{validation.invalid_properties.slice(0,4).map(item=><div key={item.code}><strong>{item.code}</strong><span>{item.issues.join(' ')}</span></div>)}</div>}
            {validation?.document_issues&&validation.document_issues.length>0&&<div className="portal-settings-invalids">{validation.document_issues.slice(0,6).map((issue,index)=><div key={issue+index}><strong>XML OLX</strong><span>{issue}</span></div>)}</div>}
            <div className="portal-settings-form">
              <label className="field"><span>Status da homologação</span><select disabled={!canEdit} value={channel.status} onChange={e=>patch(channel.key,{status:e.target.value as Channel['status']})}>{Object.entries(statusLabel).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
              <label className="field"><span>Observações / protocolo</span><input disabled={!canEdit} maxLength={1000} placeholder="Ex.: chamado aberto, protocolo, retorno do portal..." value={channel.notes} onChange={e=>patch(channel.key,{notes:e.target.value})}/></label>
              <button className="button primary compact-button" disabled={!canEdit||Boolean(saving)} type="button" onClick={()=>void save(channel)}><Save size={13}/>{saving===channel.key?'Salvando...':'Salvar'}</button>
            </div>
          </div>
        </section>
      })}
    </div>}
    <div className="portal-settings-foot"><strong>Importante</strong><span>“Feed validado” confirma a consistência técnica gerada pelo ERP. “Ativo no portal” deve ser marcado após a homologação externa da OLX ou do Canal Pro.</span></div>
  </article>
}
