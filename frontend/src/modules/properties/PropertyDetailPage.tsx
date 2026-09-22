import {
  ArrowLeft, Bath, BedDouble, CalendarPlus, Car, CheckCircle2,
  CircleAlert, CircleDollarSign, ClipboardCheck, ExternalLink, FileText,
  Globe2, History, Home, MapPin, Maximize2, Pencil, RefreshCw,
  Share2, UserRound,
} from 'lucide-react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'
import type { AdministrationContract, Property, PublicationReadiness } from '../../api/types'
import { ActivityTimeline } from '../../components/ui/ActivityTimeline'
import { ContextTabs } from '../../components/ui/ContextTabs'
import { EmptyState } from '../../components/ui/EmptyState'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { EntityDocumentsPanel } from '../documents/EntityDocumentsPanel'
import { PropertyGallery } from './PropertyGallery'
import { PropertyLifecyclePanel } from './PropertyLifecyclePanel'
import { PropertyMaintenancePanel } from './PropertyMaintenancePanel'
import { formatBedroomSummary } from '../../utils/propertyRooms'
import './property-detail-v81.css'
import './property-detail-v81-fidelity.css'

export type PropertyDetailTab = 'overview' | 'finance' | 'contracts' | 'documents' | 'traceability' | 'inspections' | 'maintenance' | 'features' | 'location'
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
  error: string
  success: string
  onBack: () => void
  onEdit: () => void
  onRefresh: () => void
  onSaveCommercial: () => void
  onTogglePublication: (enabled: boolean) => void
  onOpenSite: (slug?: string | null) => void
  editorModal?: ReactNode
}

const tabs = [
  { key:'overview', label:'Visão Geral' }, { key:'finance', label:'Financeiro' },
  { key:'contracts', label:'Contratos' }, { key:'documents', label:'Documentos' },
  { key:'traceability', label:'Rastreabilidade' }, { key:'inspections', label:'Vistorias' },
  { key:'maintenance', label:'Manutenções' }, { key:'features', label:'Características' },
  { key:'location', label:'Localização' },
] as const

const statusLabels:Record<string,string>={draft:'Rascunho',available:'Disponível',reserved:'Reservado',leased:'Locado',inactive:'Inativo'}
const contractStatusLabels:Record<string,string>={draft:'Rascunho',review:'Em revisão',approved:'Aprovado',pending_signature:'Assinatura',signed:'Assinado',cancelled:'Cancelado'}
const inspectionStatusLabels:Record<string,string>={draft:'Rascunho',ready:'Laudo concluído',contested:'Contestada',finalized:'Finalizada',cancelled:'Cancelada'}
const propertyTypes:Record<string,string>={apartment:'Apartamento',house:'Casa',commercial:'Comercial',land:'Terreno',studio:'Studio',other:'Outro'}

function money(value:number|null|undefined){return value==null?'—':Number(value).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function dateLabel(value:string|null|undefined){return value?new Date(value).toLocaleDateString('pt-BR'):'—'}
function addressLine(property:Property){const a=property.address;return [a.street,a.number,a.complement].filter(Boolean).join(', ')||'Endereço não informado'}
function statusTone(value:string):'neutral'|'info'|'positive'|'attention'|'danger'{if(['available','signed','finalized','approved'].includes(value))return'positive';if(['inactive','cancelled','contested'].includes(value))return'danger';if(['reserved','review','pending_signature','ready'].includes(value))return'attention';return'neutral'}
function navigate(path:string){window.history.pushState({},'',path);window.dispatchEvent(new PopStateEvent('popstate'))}

export function PropertyDetailPage(props:Props){
  const { property, permissions, activeTab, readiness, administrationContracts, leases, inspections, commercialProfile, commercialDraft }=props
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
    <div className="property-detail-topline"><button className="property-back" type="button" onClick={props.onBack}><ArrowLeft size={15}/> Todos os imóveis</button><span>Ficha operacional do ativo</span><button className="property-detail-refresh" type="button" onClick={props.onRefresh} disabled={props.detailLoading}><RefreshCw size={14}/>{props.detailLoading?'Atualizando':'Atualizar'}</button></div>
    <PropertyGallery propertyId={property.id} canManage={canEdit} variant="hero" heroContent={heroContent} heroActions={heroActions} overviewMountId={`property-overview-gallery-${property.id}`} onChanged={props.onRefresh}/>

    <div className="property-essential-strip" aria-label="Informações essenciais do imóvel">
      <div><span>Código</span><strong>{property.code}</strong></div><div><span>Finalidade</span><strong>{property.purpose==='sale'?'Venda':'Locação'}</strong></div><div><span>Tipo</span><strong>{propertyTypes[property.property_type]??property.property_type}</strong></div><div><span>Proprietário</span><strong>{ownerNames||'Não vinculado'}</strong></div><div><span>Corretor responsável</span><strong>Não atribuído</strong></div><div><span>Status comercial</span><strong>{statusLabels[property.status]??property.status}</strong></div><div><span>Entrada</span><strong>{dateLabel(property.created_at)}</strong></div>
    </div>

    <ContextTabs tabs={tabs} activeKey={activeTab} ariaLabel="Seções do imóvel" onChange={key=>props.onTabChange(key as PropertyDetailTab)}/>
    {props.error&&<div className="form-alert danger-alert" role="alert">{props.error}</div>}{props.success&&<div className="form-alert success-alert" role="status">{props.success}</div>}

    {activeTab==='overview'&&<div className="property-overview-layout">
      <div id={`property-overview-gallery-${property.id}`} className="property-overview-gallery-slot"/>
      <section className="property-surface property-main-information"><div className="property-section-heading"><div><span>Informações principais</span><h2>Ficha do imóvel</h2></div></div><dl className="property-overview-facts"><div><dt>Tipo</dt><dd>{propertyTypes[property.property_type]??property.property_type}</dd></div><div><dt>Status</dt><dd>{statusLabels[property.status]??property.status}</dd></div><div><dt>Área privativa</dt><dd>{property.area_m2??'—'} m²</dd></div><div><dt>Quartos</dt><dd>{formatBedroomSummary(property.bedrooms,property.suites)}</dd></div><div><dt>Banheiros</dt><dd>{property.bathrooms}</dd></div><div><dt>Vagas</dt><dd>{property.parking_spaces}</dd></div><div><dt>Condomínio</dt><dd>{money(property.condo_amount)}</dd></div><div><dt>IPTU</dt><dd>{money(property.iptu_amount)}</dd></div><div><dt>Código</dt><dd>{property.code}</dd></div><div><dt>Finalidade</dt><dd>{property.purpose==='sale'?'Venda':'Locação'}</dd></div><div><dt>Entrada</dt><dd>{dateLabel(property.created_at)}</dd></div></dl></section>
      <aside className="property-surface property-overview-summary">
        <section><div className="property-section-heading"><div><span>Responsáveis</span><h2>Gestão do ativo</h2></div></div><div className="property-people-summary"><UserRound size={20}/><div><span>Proprietário</span><strong>{ownerNames||'Não vinculado'}</strong><small>{property.owners.length?`${property.owners.length} titular(es)`:'Vínculo pendente'}</small></div></div><div className="property-people-summary"><UserRound size={20}/><div><span>Corretor responsável</span><strong>Não atribuído</strong><small>Vínculo ainda não fornecido pelo cadastro</small></div></div></section>
        <section><div className="property-section-heading"><div><span>Financeiro</span><h2>Resumo mensal</h2></div><button type="button" onClick={()=>props.onTabChange('finance')}>Ver detalhes</button></div><div className="property-money-summary"><div className="primary"><span>Aluguel</span><strong>{money(property.rent_amount)}</strong></div><div><span>Condomínio</span><strong>{money(property.condo_amount)}</strong></div><div><span>IPTU</span><strong>{money(property.iptu_amount)}</strong></div></div></section>
      </aside>
      <section className="property-surface property-description"><div className="property-section-heading"><div><span>O imóvel</span><h2>Descrição do ativo</h2></div>{canEdit&&<button type="button" onClick={()=>props.setCommercialEditing(true)}><Pencil size={14}/> Editar apresentação</button>}</div><p>{commercialProfile?.public_description||'A descrição comercial deste imóvel ainda não foi preenchida.'}</p></section>
      <section className="property-surface property-progress-surface"><div className="property-section-heading"><div><span>Comercial</span><h2>Andamento do negócio</h2></div></div><div className="property-commercial-flow"><div className="done"><CheckCircle2 size={18}/><span><strong>Cadastro</strong><small>Ativo criado em {dateLabel(property.created_at)}</small></span></div><div className={ownerNames?'done':''}><CheckCircle2 size={18}/><span><strong>Titularidade</strong><small>{ownerNames||'Proprietário pendente'}</small></span></div><div className={readiness?.ready?'done':'attention'}><CircleAlert size={18}/><span><strong>Preparação</strong><small>{readiness?.ready?'Checklist concluído':`${requiredPending} pendência(s)`}</small></span></div><div className={property.publication_enabled?'done':'current'}><Globe2 size={18}/><span><strong>Publicação</strong><small>{property.publication_enabled?'Anúncio ativo':'Ainda não publicado'}</small></span></div></div></section>
      <aside className="property-surface property-overview-activity"><div className="property-section-heading"><div><span>Atividades</span><h2>Últimas movimentações</h2></div></div><ActivityTimeline items={[{id:'updated',title:'Cadastro atualizado',timestamp:dateLabel(property.updated_at),icon:RefreshCw},{id:'created',title:'Imóvel cadastrado',timestamp:dateLabel(property.created_at),icon:History},...(property.published_at?[{id:'published',title:'Anúncio publicado',timestamp:dateLabel(property.published_at),icon:Globe2}]:[])]}/><div className="property-publication-inline"><Globe2 size={18}/><span><strong>{property.publication_enabled?'Publicado no site':'Anúncio inativo'}</strong><small>{readiness?.ready?'Imóvel pronto para publicação':`${requiredPending} item(ns) pendente(s)`}</small></span>{canPublish&&<button type="button" disabled={props.saving||(!property.publication_enabled&&Boolean(readiness&&!readiness.ready))} onClick={()=>props.onTogglePublication(!property.publication_enabled)}>{property.publication_enabled?'Retirar':'Publicar'}</button>}</div></aside>
      <main className="property-overview-main">
        {props.commercialEditing&&commercialDraft&&<section className="property-surface property-commercial-inline"><div className="property-section-heading"><div><span>APRESENTAÇÃO</span><h2>Perfil comercial</h2></div></div><div className="property-commercial-form"><label><span>Situação comercial</span><select value={commercialDraft.status} onChange={event=>props.setCommercialDraft(current=>current?{...current,status:event.target.value as PropertyCommercialDraft['status']}:current)}><option value="draft">Rascunho</option><option value="available">Disponível para anunciar</option><option value="inactive">Inativo</option></select></label><label><span>Título público</span><input value={commercialDraft.public_title} onChange={event=>props.setCommercialDraft(current=>current?{...current,public_title:event.target.value}:current)}/></label><label className="full"><span>Descrição pública</span><textarea rows={5} value={commercialDraft.public_description} onChange={event=>props.setCommercialDraft(current=>current?{...current,public_description:event.target.value}:current)}/></label><label><span>Aluguel</span><input value={commercialDraft.rent_amount} onChange={event=>props.setCommercialDraft(current=>current?{...current,rent_amount:event.target.value}:current)}/></label><label><span>Condomínio</span><input value={commercialDraft.condo_amount} onChange={event=>props.setCommercialDraft(current=>current?{...current,condo_amount:event.target.value}:current)}/></label><label><span>IPTU</span><input value={commercialDraft.iptu_amount} onChange={event=>props.setCommercialDraft(current=>current?{...current,iptu_amount:event.target.value}:current)}/></label><div className="full property-commercial-actions"><button className="button secondary" type="button" onClick={()=>props.setCommercialEditing(false)}>Cancelar</button><button className="button primary" type="button" disabled={props.commercialSaving} onClick={props.onSaveCommercial}>{props.commercialSaving?'Salvando...':'Salvar perfil'}</button></div></div></section>}
      </main>
    </div>}

    {activeTab==='finance'&&<section className="property-surface property-tab-surface"><div className="property-section-heading"><div><span>FINANCEIRO</span><h2>Valores e vínculo de locação</h2></div></div><div className="property-finance-wide"><div><span>Aluguel</span><strong>{money(property.rent_amount)}</strong></div><div><span>Condomínio</span><strong>{money(property.condo_amount)}</strong></div><div><span>IPTU</span><strong>{money(property.iptu_amount)}</strong></div><div><span>Locação vigente</span><strong>{latestLease?`${latestLease.code} · ${money(latestLease.rent_amount)}`:'Nenhuma'}</strong></div></div><EmptyState compact icon={CircleDollarSign} title="Lançamentos detalhados ainda não disponíveis nesta API" description="Os valores cadastrais e a locação vinculada continuam visíveis acima."/></section>}
    {activeTab==='contracts'&&<section className="property-surface property-tab-surface"><div className="property-section-heading"><div><span>CONTRATOS</span><h2>Instrumentos vinculados ao imóvel</h2></div></div><div className="property-linked-groups"><div><h3>Administração</h3>{administrationContracts.length?administrationContracts.map(item=><article className="property-linked-row" key={item.id}><FileText size={18}/><div><strong>{item.code}</strong><span>Plano {item.plan} · taxa {item.admin_fee_type==='percent'?`${item.admin_fee_percent}%`:money(item.admin_fee_amount)}</span></div><StatusBadge tone={statusTone(item.status)}>{contractStatusLabels[item.status]??item.status}</StatusBadge></article>):<EmptyState compact title="Nenhum contrato de administração"/>}</div><div><h3>Locação</h3>{leases.length?leases.map(item=><article className="property-linked-row" key={item.id}><Home size={18}/><div><strong>{item.code}</strong><span>{item.tenants.map(tenant=>tenant.name).join(' · ')||'Sem locatário'} · {money(item.rent_amount)}</span></div><StatusBadge tone={statusTone(item.status)}>{contractStatusLabels[item.status]??item.status}</StatusBadge></article>):<EmptyState compact title="Nenhum contrato de locação"/>}</div></div></section>}
    {activeTab==='documents'&&<EntityDocumentsPanel entityType="property" entityId={property.id} entityLabel={`Imóvel ${property.code}`} permissions={permissions}/>} 
    {activeTab==='traceability'&&<PropertyLifecyclePanel propertyId={property.id} permissions={permissions}/>} 
    {activeTab==='inspections'&&<section className="property-surface property-tab-surface"><div className="property-section-heading"><div><span>VISTORIAS</span><h2>Histórico do imóvel</h2></div></div>{inspections.length?<div className="property-linked-list">{inspections.map(item=><article className="property-linked-row" key={item.id}><ClipboardCheck size={18}/><div><strong>{item.code} · {item.lease_code}</strong><span>{item.inspector_name||'Vistoriador não informado'} · {dateLabel(item.scheduled_at||item.performed_at)}</span></div><StatusBadge tone={statusTone(item.status)}>{inspectionStatusLabels[item.status]??item.status}</StatusBadge></article>)}</div>:<EmptyState title="Nenhuma vistoria vinculada" description="Quando uma vistoria for criada para este imóvel, ela aparecerá aqui."/>}</section>}
    {activeTab==='maintenance'&&<PropertyMaintenancePanel propertyId={property.id} permissions={permissions}/>} 
    {activeTab==='features'&&<section className="property-surface property-tab-surface"><div className="property-section-heading"><div><span>CARACTERÍSTICAS</span><h2>Ficha técnica e comercial</h2></div>{canEdit&&<button type="button" onClick={props.onEdit}><Pencil size={14}/> Editar</button>}</div><dl className="property-feature-list"><div><dt>Tipo</dt><dd>{propertyTypes[property.property_type]??property.property_type}</dd></div><div><dt>Finalidade</dt><dd>{property.purpose==='sale'?'Venda':'Locação'}</dd></div><div><dt>Área privativa</dt><dd>{property.area_m2??'—'} m²</dd></div><div><dt>Dormitórios</dt><dd>{property.bedrooms}</dd></div><div><dt>Suítes</dt><dd>{property.suites}</dd></div><div><dt>Banheiros</dt><dd>{property.bathrooms}</dd></div><div><dt>Vagas</dt><dd>{property.parking_spaces}</dd></div><div><dt>Mobiliado</dt><dd>{property.furnished?'Sim':'Não'}</dd></div><div><dt>Aceita pets</dt><dd>{property.pets_allowed?'Sim':'Não'}</dd></div><div><dt>Condomínio</dt><dd>{money(property.condo_amount)}</dd></div><div><dt>IPTU</dt><dd>{money(property.iptu_amount)}</dd></div><div><dt>Publicação</dt><dd>{property.publication_enabled?'Ativa':'Inativa'}</dd></div></dl></section>}
    {activeTab==='location'&&<section className="property-surface property-tab-surface property-location-v81"><div className="property-section-heading"><div><span>LOCALIZAÇÃO</span><h2>{property.address.neighborhood||property.address.city}</h2><p>{addressLine(property)} · {property.address.city}/{property.address.state} · {property.address.postal_code||'CEP não informado'}</p></div><a href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([addressLine(property),property.address.city,property.address.state,'Brasil'].join(', '))}`} target="_blank" rel="noreferrer">Abrir no mapa <ExternalLink size={13}/></a></div><iframe title={`Mapa do imóvel ${property.code}`} loading="lazy" allowFullScreen referrerPolicy="no-referrer-when-downgrade" src={`https://www.google.com/maps?q=${encodeURIComponent([addressLine(property),property.address.city,property.address.state,'Brasil'].join(', '))}&output=embed`}/></section>}
    {props.editorModal}
  </section>
}
