import { CheckCircle2, CircleAlert, Copy, ExternalLink, RadioTower, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './property-portal-publication.css'

type Channel = {
  key: 'olx' | 'vrsync'
  label: string
  enabled: boolean
  ready: boolean
  issues: string[]
  feed_url: string
}
type PortalState = { property_id: string; channels: Channel[] }

export function PropertyPortalPublicationPanel({ propertyId, permissions }: { propertyId:string; permissions:string[] }) {
  const canPublish = permissions.includes('properties.publish')
  const [data,setData]=useState<PortalState|null>(null)
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState('')
  const [error,setError]=useState('')
  const [copied,setCopied]=useState('')

  async function load(){
    setLoading(true);setError('')
    try{setData(await apiRequest<PortalState>(`/properties/${propertyId}/portal-publications`))}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os portais.')}
    finally{setLoading(false)}
  }
  useEffect(()=>{void load()},[propertyId])

  async function toggle(channel:Channel){
    if(!canPublish||saving)return
    const next=!(channel.enabled)
    if(next&&!channel.ready){setError(`${channel.label}: revise as pendências antes de ativar.`);return}
    const current=Object.fromEntries((data?.channels||[]).map(item=>[item.key,item.enabled])) as Record<'olx'|'vrsync',boolean>
    current[channel.key]=next
    setSaving(channel.key);setError('')
    try{
      setData(await apiRequest<PortalState>(`/properties/${propertyId}/portal-publications`,{method:'PUT',body:JSON.stringify(current)}))
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível atualizar a publicação.')}
    finally{setSaving('')}
  }
  async function copyFeed(channel:Channel){
    try{await navigator.clipboard.writeText(channel.feed_url);setCopied(channel.key);window.setTimeout(()=>setCopied(''),1600)}catch{setCopied('')}
  }
  const active=useMemo(()=>data?.channels.filter(item=>item.enabled).length||0,[data])

  return <section className="property-surface property-tab-surface portal-publication-panel">
    <div className="property-section-heading portal-publication-heading">
      <div><span>PUBLICAÇÃO MULTICANAL</span><h2>Portais imobiliários</h2><p>Selecione os canais que devem receber este imóvel. O ERP mantém um feed XML público para cada integração.</p></div>
      <button type="button" onClick={()=>void load()} disabled={loading}><RefreshCw size={13}/> Atualizar</button>
    </div>
    {error&&<div className="form-alert danger-alert">{error}</div>}
    <div className="portal-publication-summary">
      <article><span>Canais ativos</span><strong>{active}</strong><small>de {data?.channels.length||2} disponíveis</small></article>
      <article><span>Integração</span><strong>XML</strong><small>sem cadastro manual anúncio a anúncio</small></article>
      <article><span>Atualização</span><strong>Automática</strong><small>o portal relê o feed periodicamente</small></article>
    </div>
    {loading?<div className="portal-publication-loading">Carregando configuração dos portais...</div>:<div className="portal-publication-channels">
      {data?.channels.map(channel=><article key={channel.key} className={'portal-channel-card '+(channel.enabled?'enabled ':'')+(channel.ready?'ready':'blocked')}>
        <div className={'portal-channel-mark '+channel.key}>{channel.key==='olx'?'OLX':'ZAP + VR'}</div>
        <div className="portal-channel-main">
          <div className="portal-channel-title"><div><strong>{channel.label}</strong><small>{channel.key==='olx'?'Feed XML específico da OLX':'Um único feed VRSync para ZAP Imóveis e Viva Real'}</small></div><i className={'status-badge '+(channel.enabled?'success':channel.ready?'neutral':'warning')}>{channel.enabled?'Ativo':channel.ready?'Pronto para ativar':'Com pendências'}</i></div>
          {channel.issues.length?<div className="portal-channel-issues"><CircleAlert size={14}/><div>{channel.issues.map(issue=><span key={issue}>{issue}</span>)}</div></div>:<div className="portal-channel-ok"><CheckCircle2 size={14}/><span>Imóvel atende aos requisitos básicos deste feed.</span></div>}
          <div className="portal-channel-feed"><RadioTower size={13}/><code>{channel.feed_url}</code><button type="button" onClick={()=>void copyFeed(channel)}><Copy size={12}/>{copied===channel.key?'Copiado':'Copiar XML'}</button><a href={channel.feed_url} target="_blank" rel="noreferrer" title="Abrir feed XML"><ExternalLink size={12}/></a></div>
        </div>
        <div className="portal-channel-actions">
          <button className={channel.enabled?'button secondary':'button primary'} type="button" disabled={!canPublish||Boolean(saving)||( !channel.enabled&&!channel.ready)} onClick={()=>void toggle(channel)}>{saving===channel.key?'Salvando...':channel.enabled?'Desativar':'Ativar canal'}</button>
        </div>
      </article>)}
    </div>}
    <div className="portal-publication-note"><strong>Ativação externa</strong><span>Depois de ativar o canal no ERP, a URL do XML precisa ser cadastrada/homologada na conta profissional do portal. O ERP passa a ser a origem dos dados desse anúncio.</span></div>
  </section>
}
