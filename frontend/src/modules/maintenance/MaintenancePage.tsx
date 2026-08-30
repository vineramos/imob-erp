import { Building2, ChevronDown, ChevronUp, FileCheck2, Plus, Wrench } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import { MaintenanceCallModal } from './MaintenanceCallModal'
import { MaintenanceDetail } from './MaintenanceDetail'
import { MaintenancePartners } from './MaintenancePartners'
import { Maintenance, MaintenanceForm, Partner, Person, Property, Lease, address, blankMaintenance, priorities, statusClass, statuses } from './types'
import './maintenance.css'

type FilterKey='all'|'open'|'awaiting_approval'|'execution'|'urgent'|'completed'|'cancelled'

export function MaintenancePage({permissions}:{permissions:string[]}){
  const canManage=permissions.includes('maintenance.manage')
  const [tab,setTab]=useState<'maintenance'|'partners'>('maintenance')
  const [items,setItems]=useState<Maintenance[]>([]),[properties,setProperties]=useState<Property[]>([]),[people,setPeople]=useState<Person[]>([]),[leases,setLeases]=useState<Lease[]>([]),[partners,setPartners]=useState<Partner[]>([])
  const [loading,setLoading]=useState(true),[saving,setSaving]=useState(false),[error,setError]=useState(''),[success,setSuccess]=useState('')
  const [query,setQuery]=useState(''),[filter,setFilter]=useState<FilterKey>('open'),[expanded,setExpanded]=useState<string|null>(null)
  const [showForm,setShowForm]=useState(false),[editing,setEditing]=useState<Maintenance|null>(null),[form,setForm]=useState<MaintenanceForm>(blankMaintenance())

  const load=useCallback(async()=>{
    setLoading(true);setError('')
    try{
      const [maintenance,props,persons,leaseItems,partnerItems]=await Promise.all([
        apiRequest<Maintenance[]>('/maintenance-v2'),
        apiRequest<Property[]>('/properties'),
        apiRequest<Person[]>('/people'),
        apiRequest<Lease[]>('/lease-contracts'),
        apiRequest<Partner[]>('/maintenance/partners?include_inactive=true'),
      ])
      setItems(maintenance);setProperties(props);setPeople(persons);setLeases(leaseItems);setPartners(partnerItems)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar as manutenções.')}
    finally{setLoading(false)}
  },[])
  useEffect(()=>{void load()},[load])

  const metrics=useMemo(()=>({
    open:items.filter(i=>!['completed','cancelled'].includes(i.status)).length,
    approval:items.filter(i=>i.status==='awaiting_approval').length,
    execution:items.filter(i=>['scheduled','in_progress'].includes(i.status)).length,
    urgent:items.filter(i=>i.priority==='urgent'&&!['completed','cancelled'].includes(i.status)).length,
    completed:items.filter(i=>i.status==='completed').length,
  }),[items])

  const visible=useMemo(()=>{
    const term=query.trim().toLowerCase()
    return items.filter(item=>{
      const matches=filter==='all'||
        (filter==='open'&&!['completed','cancelled'].includes(item.status))||
        (filter==='execution'&&['scheduled','in_progress'].includes(item.status))||
        (filter==='urgent'&&item.priority==='urgent'&&!['completed','cancelled'].includes(item.status))||
        (filter==='awaiting_approval'&&item.status==='awaiting_approval')||
        (filter==='completed'&&item.status==='completed')||
        (filter==='cancelled'&&item.status==='cancelled')
      const haystack=`${item.code} ${item.title} ${item.property_code} ${item.property_title} ${address(item.property_address)} ${item.requester_name??''} ${item.quotes.map(q=>q.supplier_name).join(' ')}`.toLowerCase()
      return matches&&(!term||haystack.includes(term))
    })
  },[items,query,filter])

  function selectMetric(next:Exclude<FilterKey,'all'|'cancelled'>){setFilter(current=>current===next?'all':next);setExpanded(null)}
  function openNew(){setEditing(null);setForm(blankMaintenance());setError('');setSuccess('');setShowForm(true)}
  function openEdit(item:Maintenance){setEditing(item);setForm({property_id:item.property_id,lease_contract_id:item.lease_contract_id??'',requester_person_id:item.requester_person_id??'',title:item.title,category:item.category,priority:item.priority,description:item.description,notes:item.notes??''});setError('');setShowForm(true)}
  function closeForm(){if(!saving){setShowForm(false);setEditing(null)}}
  async function save(event:FormEvent){
    event.preventDefault();setSaving(true);setError('');setSuccess('')
    try{
      const body={property_id:form.property_id,lease_contract_id:form.lease_contract_id||null,requester_person_id:form.requester_person_id||null,title:form.title,category:form.category,priority:form.priority,description:form.description,notes:form.notes||null,...(editing?{responsibility:editing.responsibility}:{})}
      const saved=await apiRequest<Maintenance>(editing?`/maintenance-v2/${editing.id}`:'/maintenance-v2',{method:editing?'PUT':'POST',body:JSON.stringify(body)})
      closeForm();await load();setExpanded(saved.id);setSuccess(editing?`${saved.code} atualizado.`:`${saved.code} aberto. Agora o setor de manutenção pode definir os serviços.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar o chamado.')}
    finally{setSaving(false)}
  }
  async function refreshItem(id:string){
    const maintenance=await apiRequest<Maintenance[]>('/maintenance-v2')
    setItems(maintenance);setExpanded(id)
  }

  return <section className="workspace maintenance-workspace">
    <div className="page-heading portfolio-heading"><div><span className="eyebrow">Operação do imóvel</span><h1>Manutenções</h1><p>Chamado, escopo de serviços, cotação por parceiro, aprovação, execução e financeiro em um único fluxo.</p></div>{canManage&&tab==='maintenance'&&<button className="button primary" type="button" onClick={openNew}><Plus size={15}/> Nova manutenção</button>}</div>
    <div className="panel maintenance-view-tabs"><button className={tab==='maintenance'?'active':''} type="button" onClick={()=>setTab('maintenance')}><Wrench size={15}/> Chamados <span>{items.length}</span></button><button className={tab==='partners'?'active':''} type="button" onClick={()=>setTab('partners')}><Building2 size={15}/> Parceiros terceirizados <span>{partners.filter(p=>p.is_active).length}</span></button></div>
    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}

    {tab==='maintenance'?<>
      <div className="dashboard-metrics maintenance-metrics">
        <button type="button" className={`panel metric-card maintenance-metric-button ${filter==='open'?'active':''}`} onClick={()=>selectMetric('open')}><span>Em aberto</span><strong>{metrics.open}</strong><small>chamados ativos</small></button>
        <button type="button" className={`panel metric-card maintenance-metric-button ${filter==='awaiting_approval'?'active':''}`} onClick={()=>selectMetric('awaiting_approval')}><span>Aguardando aprovação</span><strong>{metrics.approval}</strong><small>decisão pendente</small></button>
        <button type="button" className={`panel metric-card maintenance-metric-button ${filter==='execution'?'active':''}`} onClick={()=>selectMetric('execution')}><span>Agendadas / execução</span><strong>{metrics.execution}</strong><small>serviços em andamento</small></button>
        <button type="button" className={`panel metric-card maintenance-metric-button ${filter==='urgent'?'active':''}`} onClick={()=>selectMetric('urgent')}><span>Urgentes</span><strong>{metrics.urgent}</strong><small>prioridade máxima</small></button>
        <button type="button" className={`panel metric-card maintenance-metric-button ${filter==='completed'?'active':''}`} onClick={()=>selectMetric('completed')}><span>Concluídas</span><strong>{metrics.completed}</strong><small>histórico encerrado</small></button>
      </div>
      <div className="panel maintenance-toolbar"><label className="portfolio-search"><Wrench size={15}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Buscar chamado, imóvel, endereço ou parceiro..."/></label><select value={filter} onChange={e=>setFilter(e.target.value as FilterKey)}><option value="open">Em aberto</option><option value="all">Todos</option><option value="awaiting_approval">Aguardando aprovação</option><option value="execution">Agendados / execução</option><option value="urgent">Urgentes</option><option value="completed">Concluídos</option><option value="cancelled">Cancelados</option></select></div>
      {loading?<article className="panel settings-loading">Carregando manutenções...</article>:<div className="maintenance-list">{visible.map(item=>{const isOpen=expanded===item.id;return <article className={`panel maintenance-card priority-${item.priority}`} key={item.id}><button className="maintenance-card-head" type="button" onClick={()=>setExpanded(isOpen?null:item.id)}><div className="maintenance-code"><Wrench size={18}/><span>MANUTENÇÃO</span><strong>{item.code}</strong></div><div className="maintenance-main"><strong>{item.title}</strong><span>Imóvel {item.property_code} · {item.property_title}</span><small>{address(item.property_address)}{item.lease_code?` · ${item.lease_code}`:''}</small></div><div className="maintenance-meta"><i className={`status-badge ${statusClass(item.status)}`}>{statuses[item.status]??item.status}</i><span className={`maintenance-priority ${item.priority}`}>{priorities[item.priority]}</span></div><div className="maintenance-cost"><span>Escopo</span><strong>{item.services.length} serviço(s)</strong><small>{item.quotes.length} orçamento(s)</small></div>{isOpen?<ChevronUp size={17}/>:<ChevronDown size={17}/>}</button>{isOpen&&<div className="maintenance-detail"><MaintenanceDetail item={item} partners={partners} canManage={canManage} onRefresh={refreshItem} onError={setError} onSuccess={setSuccess} onEdit={()=>openEdit(item)}/></div>}</article>})}{!visible.length&&<article className="panel maintenance-empty"><FileCheck2 size={28}/><strong>Nenhum chamado encontrado.</strong><span>Abra uma manutenção ou ajuste os filtros.</span></article>}</div>}
    </>:<MaintenancePartners partners={partners} canManage={canManage} onReload={load} onSuccess={setSuccess}/>} 

    {showForm&&<MaintenanceCallModal editing={editing} form={form} setForm={setForm} properties={properties} people={people} leases={leases} saving={saving} onClose={closeForm} onSubmit={save}/>} 
  </section>
}
