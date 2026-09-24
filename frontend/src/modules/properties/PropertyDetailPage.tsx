import {
  ArrowLeft, BedDouble, CalendarPlus, Car, CheckCircle2,
  CircleAlert, CircleDollarSign, ClipboardCheck, ExternalLink, FileText,
  Globe2, History, Home, MapPin, Maximize2, Pencil, RefreshCw,
  Share2, UserRound, UserRoundCheck, Search, X, Check,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'
import type { AdministrationContract, Person, Property, PublicationReadiness } from '../../api/types'
import { apiBlobRequest } from '../../api/client'
import { ActivityTimeline } from '../../components/ui/ActivityTimeline'
import { ContextTabs } from '../../components/ui/ContextTabs'
import { EmptyState } from '../../components/ui/EmptyState'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { EntityDocumentsPanel } from '../documents/EntityDocumentsPanel'
import { PropertyGallery } from './PropertyGallery'
import { PropertyLifecyclePanel } from './PropertyLifecyclePanel'
import { PropertyPortalPublicationPanel } from './PropertyPortalPublicationPanel'
import { PropertyMaintenancePanel } from './PropertyMaintenancePanel'
import { PropertyAdditionalChargesPanel } from './PropertyAdditionalChargesPanel'
import { formatBedroomSummary } from '../../utils/propertyRooms'
import './property-detail-v81.css'
import './property-detail-v81-fidelity.css'

export type PropertyDetailTab = 'overview' | 'publications' | 'finance' | 'contracts' | 'documents' | 'traceability' | 'inspections' | 'maintenance' | 'features' | 'location'
export type PropertyLease = { id:string; code:string; property_id:string; tenants:Array<{name:string}>; status:string; rent_amount:number; start_date:string; end_date:string; archive_status:string; final_document_hash:string|null; signed_at:string|null }
export type PropertyInspection = { id:string; code:string; property_id:string; lease_code:string; status:string; inspector_name:string|null; scheduled_at:string|null; performed_at:string|null; finalized_at:string|null; report_hash:string|null; key_handover:{handed_over_at:string;recipient_name:string}|null }
export type PropertyCommercialProfile = { property_id:string; status:'draft'|'available'|'inactive'; purpose:string; public_title:string; public_description:string; rent_amount:number|null; condo_amount:number|null; iptu_amount:number|null; publication_enabled:boolean }
export type PropertyCommercialDraft = { status:'draft'|'available'|'inactive'; public_title:string; public_description:string; rent_amount:string; condo_amount:string; iptu_amount:string }

type Props = {
  property: Property
  permissions: string[]
  activeTab: PropertyDetailTab
  onTabChange: (tab: PropertyDetailTab) => void
  organizationId: string
  readiness: PublicationReadiness | null
  administrationContracts: AdministrationContract[]
  leases: PropertyLease[]
  inspections: PropertyInspection[]
  commercialProfile: PropertyCommercialProfile | null
  commercialDraft: PropertyCommercialDraft | null
  setCommercialDraft: Dispatch<SetStateAction<PropertyCommercialDraft | null>>
  commercialEditing: boolean
  setCommercialEditing: Dispatch<SetStateAction<boolean>>
  detailLoading: boolean
  saving: boolean
  commercialSaving: boolean
  brokerSaving: boolean
  brokers: Person[]
  error: string
  success: string
  onBack: () => void
  onEdit: () => void
  onRefresh: () => void
  onAdditionalChargesUpdated: (updated:Property) => void
  onSaveCommercial: () => void
  onTogglePublication: (enabled: boolean) => void
  onAssignBroker: (brokerPersonId: string | null) => void
  onOpenSite: (slug?: string | null) => void
  editorModal?: ReactNode
}

const tabs = [
  { key:'overview', label:'Visão Geral' }, { key:'publications', label:'Publicações' }, { key:'finance', label:'Financeiro' },
  { key:'contracts', label:'Contratos' }, { key:'documents', label:'Documentos' },
  { key:'traceability', label:'Rastreabilidade' }, { key:'inspections', label:'Vistorias' },
  { key:'maintenance', label:'Manutenções' }, { key:'features', label:'Características' },
  { key:'location', label:'Localização' },
] as const

const statusLabels:Record<string,string>={draft:'Rascunho',available:'Disponível',reserved:'Reservado',leased:'Locado',inactive:'Inativo'}
const contractStatusLabels:Record<string,string>={draft:'Rascunho',review:'Em revisão',approved:'Aprovado',pending_signature:'Assinatura',signed:'Assinado',cancelled:'Cancelado'}
const inspectionStatusLabels:Record<string,string>={draft:'Rascunho',ready:'Laudo concluído',contested:'Contestada',finalized:'Finalizada',cancelled:'Cancelada'}
const propertyTypes:Record<string,string>={apartment:'Apartamento',house:'Casa',commercial:'Comercial',land:'Terreno',studio:'Studio',other:'Outro'}
const featureLabels:Record<string,string>={balcony:'Sacada',barbecue:'Churrasqueira',air_conditioning:'Ar-condicionado',planned_kitchen:'Cozinha planejada',closet:'Closet',lavabo:'Lavabo',office:'Escritório',laundry:'Lavanderia',heating:'Aquecimento',garden:'Jardim',private_pool:'Piscina privativa',service_area:'Área de serviço'}
const condominiumFeatureLabels:Record<string,string>={elevator:'Elevador',doorman_24h:'Portaria 24h',pool:'Piscina',gym:'Academia',party_room:'Salão de festas',playground:'Playground',gourmet_space:'Espaço gourmet',security:'Segurança',bike_rack:'Bicicletário',coworking:'Coworking'}
const solarLabels:Record<string,string>={north:'Norte',south:'Sul',east:'Leste',west:'Oeste',northeast:'Nordeste',northwest:'Noroeste',southeast:'Sudeste',southwest:'Sudoeste'}

function money(value:number|null|undefined){return value==null?'—':Number(value).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function dateLabel(value:string|null|undefined){return value?new Date(value).toLocaleDateString('pt-BR'):'—'}
function percentLabel(value:number){return `${Number(value).toLocaleString('pt-BR',{maximumFractionDigits:2})}%`}
function addressLine(property:Property){const a=property.address;return [a.street,a.number,a.complement].filter(Boolean).join(', ')||'Endereço não informado'}
function statusTone(value:string):'neutral'|'info'|'positive'|'attention'|'danger'{if(['available','signed','finalized','approved'].includes(value))return'positive';if(['inactive','cancelled','contested'].includes(value))return'danger';if(['reserved','review','pending_signature','ready'].includes(value))return'attention';return'neutral'}
function navigate(path:string){window.history.pushState({},'',path);window.dispatchEvent(new PopStateEvent('popstate'))}
function openPersonOverlay(personId:string){
  const url=new URL(window.location.href)
  url.searchParams.set('person',personId)
  window.history.pushState({},'',url.pathname+url.search)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function RelationPhoto({url,updatedAt,name,className}:{url?:string|null;updatedAt?:string|null;name:string;className:string}){
  const [src,setSrc]=useState('')
  useEffect(()=>{
    let active=true,objectUrl=''
    if(!url){setSrc('');return()=>undefined}
    void apiBlobRequest(url).then(blob=>{if(!active)return;objectUrl=URL.createObjectURL(blob);setSrc(objectUrl)}).catch(()=>{if(active)setSrc('')})
    return()=>{active=false;if(objectUrl)URL.revokeObjectURL(objectUrl)}
  },[url,updatedAt])
  if(src)return <img className={className} src={src} alt={name}/>
  return <span className={className}>{name.trim().split(/\s+/).filter(Boolean).slice(0,2).map(part=>part[0]?.toUpperCase()).join('')||'—'}</span>
}

export function PropertyDetailPage(props:Props){
  const { property, permissions, activeTab, readiness, administrationContracts, leases, inspections, commercialProfile, commercialDraft }=props
  const [brokerPickerOpen,setBrokerPickerOpen]=useState(false)
  const [brokerQuery,setBrokerQuery]=useState('')
  const filteredBrokers=useMemo(()=>{const term=brokerQuery.trim().toLowerCase();return term?props.brokers.filter(item=>(item.name+' '+(item.email??'')+' '+(item.phone??'')+' '+(item.notes??'')).toLowerCase().includes(term)):props.brokers},[brokerQuery,props.brokers])
  const granted=new Set(permissions)
  const canEdit=granted.has('properties.edit'), canPublish=granted.has('properties.publish')
  const latestLease=leases.find(item=>item.status!=='cancelled')??leases[0]
  const latestAdministration=administrationContracts.find(item=>item.status!=='cancelled')??administrationContracts[0]
  const requiredPending=readiness?.checklist.filter(item=>item.required&&!item.ok).length??0
  const ownerNames=property.owners.map(owner=>owner.name).join(' · ')

  async function share(){
    const url=property.publication_enabled&&property.public_slug?`${window.location.origin}/site/${props.organizationId}/imoveis/${property.public_slug}`:window.location.href
    if(navigator.share){await navigator.share({title:addressLine(property),text:addressLine(property),url}).catch(()=>undefined);return}
    await navigator.clipboard?.writeText(url)
  }

  const heroContent=<div className="property-hero-copy">
    <div className="property-hero-top"><StatusBadge tone={statusTone(property.status)}>{statusLabels[property.status]??property.status}</StatusBadge><span>IMÓVEL {property.code}</span></div>
    <div><p>{propertyTypes[property.property_type]??property.property_type} · {property.purpose==='sale'?'Venda':'Locação'}</p><h1>{addressLine(property)}</h1><address><MapPin size={16}/>{[property.address.neighborhood, property.address.city, property.address.state].filter(Boolean).join(' · ')}</address></div>
    <div className="property-hero-specs"><span><Maximize2 size={17}/><strong>{property.area_m2??'—'} m²</strong></span><span><BedDouble size={17}/><strong>{formatBedroomSummary(property.bedrooms,property.suites)}</strong></span><span><Car size={17}/><strong>{property.parking_spaces} vagas</strong></span></div>
    <div className="property-hero-price"><span>{property.purpose==='sale'?'Valor de venda':'Valor mensal'}</span><strong>{money(property.rent_amount)}</strong><small>Condomínio {money(property.condo_amount)} · IPTU {money(property.iptu_amount)}</small></div>
  </div>

  const heroActions=<div className="property-hero-actions">
    <button className="primary" type="button" onClick={()=>navigate(`/app/agenda?propertyId=${property.id}`)}><CalendarPlus size={15}/> Agendar visita</button>
    <button type="button" onClick={()=>void share()}><Share2 size={15}/> Compartilhar</button>
    {canEdit&&<button type="button" onClick={props.onEdit}><Pencil size={15}/> Editar</button>}
    {props.organizationId&&<button className="tertiary" type="button" onClick={()=>props.onOpenSite(property.publication_enabled?property.public_slug:null)}><ExternalLink size={15}/> {property.publication_enabled?'Ver anúncio':'Abrir site'}</button>}
  </div>

  return <section className="workspace property-detail-workspace property-detail-v81" data-property-id={property.id} data-property-code={property.code}>
    {brokerPickerOpen&&<div className="property-broker-picker-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget&&!props.brokerSaving)setBrokerPickerOpen(false)}}><section className="property-broker-picker" role="dialog" aria-modal="true" aria-label="Escolher corretor responsável"><header><div><span>Gestão do ativo</span><h3>Escolher corretor responsável</h3><p>Selecione um corretor cadastrado para assumir este imóvel.</p></div><button type="button" onClick={()=>setBrokerPickerOpen(false)} disabled={props.brokerSaving} aria-label="Fechar"><X size={16}/></button></header><label className="property-broker-picker-search"><Search size={14}/><input autoFocus value={brokerQuery} onChange={event=>setBrokerQuery(event.target.value)} placeholder="Buscar corretor por nome, contato ou CRECI"/></label><div className="property-broker-picker-list">{filteredBrokers.map(broker=>{const active=property.responsible_broker?.person_id===broker.id;const creci=(broker.notes||'').match(/(?:^|\n)CRECI:\s*(.+)/i)?.[1]?.trim();return <button type="button" key={broker.id} className={active?'active':''} disabled={props.brokerSaving} onClick={()=>{props.onAssignBroker(broker.id);setBrokerPickerOpen(false)}}><RelationPhoto url={broker.photo_content_url} updatedAt={broker.photo_updated_at} name={broker.name} className="property-broker-picker-avatar"/><span><strong>{broker.name}</strong><small>{[(creci?'CRECI '+creci:''),broker.email||broker.phone||''].filter(Boolean).join(' · ')||'Corretor cadastrado'}</small></span>{active&&<Check size={15}/>}</button>})}{filteredBrokers.length===0&&<div className="property-broker-picker-empty"><UserRoundCheck size={21}/><strong>Nenhum corretor encontrado</strong><span>Cadastre o corretor no módulo Corretores para vinculá-lo ao imóvel.</span></div>}</div>{property.responsible_broker&&<footer><button type="button" disabled={props.brokerSaving} onClick={()=>{props.onAssignBroker(null);setBrokerPickerOpen(false)}}>Remover corretor responsável</button></footer>}</section></div>}
    <div className="property-detail-topline"><button className="property-back" type="button" onClick={props.onBack}><ArrowLeft size={15}/> Todos os imóveis</button><span>Ficha operacional do ativo</span><button className="property-detail-refresh" type="button" onClick={props.onRefresh} disabled={props.detailLoading}><RefreshCw size={14}/>{props.detailLoading?'Atualizando':'Atualizar'}</button></div>
    <PropertyGallery propertyId={property.id} canManage={canEdit} variant="hero" heroContent={heroContent} heroActions={heroActions} overviewMountId={`property-overview-gallery-${property.id}`} onChanged={props.onRefresh}/>

    <div className="property-essential-strip" aria-label="Informações essenciais do imóvel">
      <div><span>Código</span><strong>{property.code}</strong></div><div><span>Finalidade</span><strong>{property.purpose==='sale'?'Venda':'Locação'}</strong></div><div><span>Tipo</span><strong>{propertyTypes[property.property_type]??property.property_type}</strong></div><div><span>Proprietário</span><strong>{ownerNames||'Não vinculado'}</strong></div><div><span>Corretor responsável</span><strong>{property.responsible_broker?.name||'Não atribuído'}</strong></div><div><span>Status comercial</span><strong>{statusLabels[property.status]??property.status}</strong></div><div><span>Entrada</span><strong>{dateLabel(property.created_at)}</strong></div>
    </div>

    <ContextTabs tabs={tabs} activeKey={activeTab} ariaLabel="Seções do imóvel" onChange={key=>props.onTabChange(key as PropertyDetailTab)}/>
    {props.error&&<div className="form-alert danger-alert" role="alert">{props.error}</div>}{props.success&&<div className="form-alert success-alert" role="status">{props.success}</div>}

    {activeTab==='overview'&&<div className="property-overview-layout">
      <div id={`property-overview-gallery-${property.id}`} className="property-overview-gallery-slot"/>
      <section className="property-surface property-main-information"><div className="property-section-heading"><div><span>Informações principais</span><h2>Ficha do imóvel</h2></div></div><dl className="property-overview-facts"><div><dt>Tipo</dt><dd>{propertyTypes[property.property_type]??property.property_type}</dd></div><div><dt>Status</dt><dd>{statusLabels[property.status]??property.status}</dd></div><div><dt>Área privativa</dt><dd>{property.area_m2??'—'} m²</dd></div><div><dt>Quartos</dt><dd>{formatBedroomSummary(property.bedrooms,property.suites)}</dd></div><div><dt>Banheiros</dt><dd>{property.bathrooms}</dd></div><div><dt>Vagas</dt><dd>{property.parking_spaces}</dd></div><div><dt>Condomínio</dt><dd>{money(property.condo_amount)}</dd></div><div><dt>IPTU</dt><dd>{money(property.iptu_amount)}</dd></div><div><dt>Código</dt><dd>{property.code}</dd></div><div><dt>Finalidade</dt><dd>{property.purpose==='sale'?'Venda':'Locação'}</dd></div><div><dt>Entrada</dt><dd>{dateLabel(property.created_at)}</dd></div></dl></section>
      <aside className="property-surface property-overview-summary">
        <section><div className="property-section-heading"><div><span>Responsáveis</span><h2>Gestão do ativo</h2></div></div><div className="property-people-summary property-owner-summary"><UserRound size={20}/><div><span>{property.owners.length===1?'Proprietário':'Proprietários'}</span>{property.owners.length?<div className="property-owner-list">{property.owners.map(owner=><button type="button" className="property-person-link" key={owner.person_id} onClick={()=>openPersonOverlay(owner.person_id)} title={`Abrir cadastro de ${owner.name}`}><RelationPhoto url={owner.photo_content_url} updatedAt={owner.photo_updated_at} name={owner.name} className="property-relation-avatar"/><strong>{owner.name}</strong><b>{percentLabel(owner.ownership_percent)}</b><ExternalLink size={11}/></button>)}</div>:<strong>Não vinculado</strong>}<small>{property.owners.length?`${property.owners.length} ${property.owners.length===1?'titular':'titulares'} · ${percentLabel(property.owners.reduce((total,owner)=>total+Number(owner.ownership_percent),0))} cadastrado`:'Vínculo pendente'}</small></div></div><div className="property-people-summary property-broker-summary"><UserRoundCheck size={20}/><div><span>Corretor responsável</span><button className={'property-broker-link '+(property.responsible_broker?'assigned':'')} type="button" onClick={()=>{if(canEdit){setBrokerQuery('');setBrokerPickerOpen(true)}else if(property.responsible_broker){openPersonOverlay(property.responsible_broker.person_id)}}}>{property.responsible_broker&&<RelationPhoto url={property.responsible_broker.photo_content_url} updatedAt={property.responsible_broker.photo_updated_at} name={property.responsible_broker.name} className="property-relation-avatar"/>}<span><strong>{property.responsible_broker?.name||'Não atribuído'}</strong><small>{property.responsible_broker?(property.responsible_broker.email||property.responsible_broker.phone||'Corretor vinculado'):(canEdit?'Clique para escolher um corretor':'Nenhum corretor vinculado')}</small></span></button></div></div></section>
        <section><div className="property-section-heading"><div><span>Financeiro</span><h2>Resumo mensal</h2></div><button type="button" onClick={()=>props.onTabChange('finance')}>Ver detalhes</button></div><div className="property-money-summary"><div className="primary"><span>Aluguel</span><strong>{money(property.rent_amount)}</strong></div><div className="property-money-detail-row"><span>Condomínio</span><small>Mensal</small><strong>{money(property.condo_amount)}</strong></div><div className="property-money-detail-row"><span>IPTU</span><small>Mensal</small><strong>{money(property.iptu_amount)}</strong></div>{(property.additional_charges||[]).filter(charge=>charge.active&&charge.include_in_invoice&&charge.payer==='tenant').map(charge=><div className="property-money-detail-row" key={charge.key}><span>{charge.label}</span><small>{charge.frequency==='monthly'?'Mensal':charge.frequency==='annual'?'Anual':'Única'}</small><strong>{money(Number(charge.amount||0))}</strong></div>)}</div></section>
      </aside>
      <section className="property-surface property-description"><div className="property-section-heading"><div><span>O imóvel</span><h2>Descrição do ativo</h2></div>{canEdit&&<button type="button" onClick={()=>props.setCommercialEditing(true)}><Pencil size={14}/> Editar apresentação</button>}</div><p>{commercialProfile?.public_description||'A descrição comercial deste imóvel ainda não foi preenchida.'}</p></section>
      <section className="property-surface property-progress-surface"><div className="property-section-heading"><div><span>Comercial</span><h2>Andamento do negócio</h2></div></div><div className="property-commercial-flow"><div className="done"><CheckCircle2 size={18}/><span><strong>Cadastro</strong><small>Ativo criado em {dateLabel(property.created_at)}</small></span></div><div className={ownerNames?'done':''}><CheckCircle2 size={18}/><span><strong>Titularidade</strong><small>{ownerNames||'Proprietário pendente'}</small></span></div><div className={readiness?.ready?'done':'attention'}><CircleAlert size={18}/><span><strong>Preparação</strong><small>{readiness?.ready?'Checklist concluído':`${requiredPending} pendência(s)`}</small></span></div><div className={property.publication_enabled?'done':'current'}><Globe2 size={18}/><span><strong>Publicação</strong><small>{property.publication_enabled?'Anúncio ativo':'Ainda não publicado'}</small></span></div></div></section>
      <aside className="property-surface property-overview-activity"><div className="property-section-heading"><div><span>Atividades</span><h2>Últimas movimentações</h2></div></div><ActivityTimeline items={[{id:'updated',title:'Cadastro atualizado',timestamp:dateLabel(property.updated_at),icon:RefreshCw},{id:'created',title:'Imóvel cadastrado',timestamp:dateLabel(property.created_at),icon:History},...(property.published_at?[{id:'published',title:'Anúncio publicado',timestamp:dateLabel(property.published_at),icon:Globe2}]:[])]}/><div className="property-publication-inline"><Globe2 size={18}/><span><strong>{property.publication_enabled?'Publicado no site':'Anúncio inativo'}</strong><small>{readiness?.ready?'Imóvel pronto para publicação':`${requiredPending} item(ns) pendente(s)`}</small></span>{canPublish&&<button type="button" disabled={props.saving||(!property.publication_enabled&&Boolean(readiness&&!readiness.ready))} onClick={()=>props.onTogglePublication(!property.publication_enabled)}>{property.publication_enabled?'Retirar':'Publicar'}</button>}</div></aside>
      <main className="property-overview-main">
        {props.commercialEditing&&commercialDraft&&<section className="property-surface property-commercial-inline"><div className="property-section-heading"><div><span>APRESENTAÇÃO</span><h2>Perfil comercial</h2></div></div><div className="property-commercial-form"><label><span>Situação comercial</span><select value={commercialDraft.status} onChange={event=>props.setCommercialDraft(current=>current?{...current,status:event.target.value as PropertyCommercialDraft['status']}:current)}><option value="draft">Rascunho</option><option value="available">Disponível para anunciar</option><option value="inactive">Inativo</option></select></label><label><span>Título público</span><input value={commercialDraft.public_title} onChange={event=>props.setCommercialDraft(current=>current?{...current,public_title:event.target.value}:current)}/></label><label className="full"><span>Descrição pública</span><textarea rows={5} value={commercialDraft.public_description} onChange={event=>props.setCommercialDraft(current=>current?{...current,public_description:event.target.value}:current)}/></label><label><span>Aluguel</span><input value={commercialDraft.rent_amount} onChange={event=>props.setCommercialDraft(current=>current?{...current,rent_amount:event.target.value}:current)}/></label><label><span>Condomínio</span><input value={commercialDraft.condo_amount} onChange={event=>props.setCommercialDraft(current=>current?{...current,condo_amount:event.target.value}:current)}/></label><label><span>IPTU</span><input value={commercialDraft.iptu_amount} onChange={event=>props.setCommercialDraft(current=>current?{...current,iptu_amount:event.target.value}:current)}/></label><div className="full property-commercial-actions"><button className="button secondary" type="button" onClick={()=>props.setCommercialEditing(false)}>Cancelar</button><button className="button primary" type="button" disabled={props.commercialSaving} onClick={props.onSaveCommercial}>{props.commercialSaving?'Salvando...':'Salvar perfil'}</button></div></div></section>}
      </main>
    </div>}

    {activeTab==='publications'&&<PropertyPortalPublicationPanel propertyId={property.id} permissions={permissions}/>}
    {activeTab==='finance'&&<section className="property-surface property-tab-surface"><div className="property-section-heading"><div><span>FINANCEIRO</span><h2>Valores e vínculo de locação</h2></div></div><div className="property-finance-wide"><div><span>Aluguel</span><strong>{money(property.rent_amount)}</strong></div><div><span>Condomínio</span><strong>{money(property.condo_amount)}</strong></div><div><span>IPTU</span><strong>{money(property.iptu_amount)}</strong></div><div><span>Locação vigente</span><strong>{latestLease?`${latestLease.code} · ${money(latestLease.rent_amount)}`:'Nenhuma'}</strong></div></div><PropertyAdditionalChargesPanel property={property} canEdit={props.permissions.includes('properties.edit')} onUpdated={props.onAdditionalChargesUpdated} hasSignedLease={props.leases.some(lease=>['signed','active'].includes(lease.status))}/></section>}
    {activeTab==='contracts'&&<section className="property-surface property-tab-surface"><div className="property-section-heading"><div><span>CONTRATOS</span><h2>Instrumentos vinculados ao imóvel</h2></div></div><div className="property-linked-groups"><div><h3>Administração</h3>{administrationContracts.length?administrationContracts.map(item=><article className="property-linked-row" key={item.id}><FileText size={18}/><div><strong>{item.code}</strong><span>Plano {item.plan} · taxa {item.admin_fee_type==='percent'?`${item.admin_fee_percent}%`:money(item.admin_fee_amount)}</span></div><StatusBadge tone={statusTone(item.status)}>{contractStatusLabels[item.status]??item.status}</StatusBadge></article>):<EmptyState compact title="Nenhum contrato de administração"/>}</div><div><h3>Locação</h3>{leases.length?leases.map(item=><article className="property-linked-row" key={item.id}><Home size={18}/><div><strong>{item.code}</strong><span>{item.tenants.map(tenant=>tenant.name).join(' · ')||'Sem locatário'} · {money(item.rent_amount)}</span></div><StatusBadge tone={statusTone(item.status)}>{contractStatusLabels[item.status]??item.status}</StatusBadge></article>):<EmptyState compact title="Nenhum contrato de locação"/>}</div></div></section>}
    {activeTab==='documents'&&<EntityDocumentsPanel entityType="property" entityId={property.id} entityLabel={`Imóvel ${property.code}`} permissions={permissions}/>} 
    {activeTab==='traceability'&&<PropertyLifecyclePanel propertyId={property.id} permissions={permissions}/>} 
    {activeTab==='inspections'&&<section className="property-surface property-tab-surface"><div className="property-section-heading"><div><span>VISTORIAS</span><h2>Histórico do imóvel</h2></div></div>{inspections.length?<div className="property-linked-list">{inspections.map(item=><article className="property-linked-row" key={item.id}><ClipboardCheck size={18}/><div><strong>{item.code} · {item.lease_code}</strong><span>{item.inspector_name||'Vistoriador não informado'} · {dateLabel(item.scheduled_at||item.performed_at)}</span></div><StatusBadge tone={statusTone(item.status)}>{inspectionStatusLabels[item.status]??item.status}</StatusBadge></article>)}</div>:<EmptyState title="Nenhuma vistoria vinculada" description="Quando uma vistoria for criada para este imóvel, ela aparecerá aqui."/>}</section>}
    {activeTab==='maintenance'&&<PropertyMaintenancePanel propertyId={property.id} permissions={permissions}/>} 
    {activeTab==='features'&&<section className="property-surface property-tab-surface"><div className="property-section-heading"><div><span>CARACTERÍSTICAS</span><h2>Ficha técnica e diferenciais</h2></div>{canEdit&&<button type="button" onClick={props.onEdit}><Pencil size={14}/> Editar</button>}</div><dl className="property-feature-list"><div><dt>Tipo</dt><dd>{propertyTypes[property.property_type]??property.property_type}</dd></div><div><dt>Finalidade</dt><dd>{property.purpose==='sale'?'Venda':'Locação'}</dd></div><div><dt>Área privativa</dt><dd>{property.area_m2??'—'} m²</dd></div><div><dt>Dormitórios</dt><dd>{property.bedrooms}</dd></div><div><dt>Suítes</dt><dd>{property.suites}</dd></div><div><dt>Banheiros</dt><dd>{property.bathrooms}</dd></div><div><dt>Vagas</dt><dd>{property.parking_spaces}</dd></div><div><dt>Andar</dt><dd>{property.features.floor??'—'}</dd></div><div><dt>Total de andares</dt><dd>{property.features.total_floors??'—'}</dd></div><div><dt>Elevadores</dt><dd>{property.features.elevators??'—'}</dd></div><div><dt>Posição solar</dt><dd>{solarLabels[property.features.solar_orientation]??'—'}</dd></div><div><dt>Ano de construção</dt><dd>{property.features.year_built??'—'}</dd></div><div><dt>Mobiliado</dt><dd>{property.furnished?'Sim':'Não'}</dd></div><div><dt>Aceita pets</dt><dd>{property.pets_allowed?'Sim':'Não'}</dd></div><div><dt>Condomínio</dt><dd>{money(property.condo_amount)}</dd></div><div><dt>IPTU</dt><dd>{money(property.iptu_amount)}</dd></div><div><dt>Publicação</dt><dd>{property.publication_enabled?'Ativa':'Inativa'}</dd></div></dl><div className="property-feature-groups"><article><span>IMÓVEL</span><h3>Diferenciais do imóvel</h3><div>{property.features.property.length?property.features.property.map(key=><span className="property-feature-chip" key={key}><CheckCircle2 size={13}/>{featureLabels[key]??key}</span>):<small>Nenhum diferencial informado.</small>}</div></article><article><span>CONDOMÍNIO</span><h3>Estrutura e lazer</h3><div>{property.features.condominium.length?property.features.condominium.map(key=><span className="property-feature-chip" key={key}><CheckCircle2 size={13}/>{condominiumFeatureLabels[key]??key}</span>):<small>Nenhuma característica informada.</small>}</div></article></div></section>}
    {activeTab==='location'&&<section className="property-surface property-tab-surface property-location-v81"><div className="property-section-heading"><div><span>LOCALIZAÇÃO</span><h2>{property.address.neighborhood||property.address.city}</h2><p>{addressLine(property)} · {property.address.city}/{property.address.state} · {property.address.postal_code||'CEP não informado'}</p></div><a href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([addressLine(property),property.address.city,property.address.state,'Brasil'].join(', '))}`} target="_blank" rel="noreferrer">Abrir no mapa <ExternalLink size={13}/></a></div><iframe title={`Mapa do imóvel ${property.code}`} loading="lazy" allowFullScreen referrerPolicy="no-referrer-when-downgrade" src={`https://www.google.com/maps?q=${encodeURIComponent([addressLine(property),property.address.city,property.address.state,'Brasil'].join(', '))}&output=embed`}/></section>}
    {props.editorModal}
  </section>
}
