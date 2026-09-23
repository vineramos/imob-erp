import { Archive, Building2, CalendarClock, Camera, Check, CircleDollarSign, FileText, History, Home, Landmark, Mail, MapPin, Pencil, Phone, Plus, RotateCcw, Search, TrendingUp, Trash2, UserRound, Users, WalletCards, X } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import type { Address, Person, PersonCreate, Property } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EntityDocumentsPanel } from '../documents/EntityDocumentsPanel'
import './people-workspace.css'

const emptyAddress = (): Address => ({ street: '', number: '', complement: '', neighborhood: '', city: 'Curitiba', state: 'PR', postal_code: '' })
const emptyPersonForm = (): PersonCreate => ({ person_type: 'individual', name: '', document_number: '', email: '', phone: '', address: emptyAddress(), notes: '', role_keys: ['owner'] })
const roleOptions = [['owner','Proprietário'],['tenant','Locatário'],['guarantor','Fiador'],['broker','Corretor'],['supplier','Fornecedor'],['referrer','Angariador']] as const
type PersonRoleKey = PersonCreate['role_keys'][number]
type PeopleView = 'active' | 'archived'

type BankAccountType = 'checking' | 'savings' | 'payment'
type PixKeyType = 'none' | 'cpf_cnpj' | 'email' | 'phone' | 'random'
type BankForm = { bank_name:string; bank_code:string; branch:string; account_number:string; account_digit:string; account_type:BankAccountType; pix_key_type:PixKeyType; pix_key:string; account_holder_name:string; account_holder_document:string }
type BankDetails = BankForm & { id:string; person_id:string; created_at:string; updated_at:string }
const emptyBank = ():BankForm => ({ bank_name:'', bank_code:'', branch:'', account_number:'', account_digit:'', account_type:'checking', pix_key_type:'none', pix_key:'', account_holder_name:'', account_holder_document:'' })

type MaritalStatus = '' | 'single' | 'married' | 'stable_union' | 'divorced' | 'widowed' | 'separated' | 'other'
type ProfileForm = { secondary_phone:string; identity_number:string; identity_issuer:string; birth_date:string; nationality:string; marital_status:MaritalStatus; occupation:string; trade_name:string; state_registration:string; municipal_registration:string }
type ProfileDetails = Omit<ProfileForm,'marital_status'> & { marital_status:Exclude<MaritalStatus,''>|null; id:string; person_id:string; created_at:string; updated_at:string }
const emptyProfile = ():ProfileForm => ({ secondary_phone:'', identity_number:'', identity_issuer:'', birth_date:'', nationality:'Brasileira', marital_status:'', occupation:'', trade_name:'', state_registration:'', municipal_registration:'' })

type PersonTab = 'main' | 'address' | 'bank' | 'profile' | 'documents'
type ClientTab = 'overview' | 'properties' | 'contracts' | 'finance' | 'commercial' | 'documents' | 'history'
type ClientLease = {
  id:string; code:string; property_id:string; property_code:string; property_address:Record<string,string>;
  tenants:Array<{person_id:string;name:string}>; owners:Array<{name:string;ownership_percent:string|number}>;
  status:string; rent_amount:number; start_date:string; end_date:string
}

type ClientFinanceSummary = {
  tenant:{total_charges:number;open_count:number;overdue_count:number;open_amount:number;overdue_amount:number;paid_amount:number}
  owner:{property_count:number;total_repasses:number;pending_count:number;pending_amount:number;paid_amount:number}
  charges:Array<{id:string;lease_contract_id:string;property_id:string;competence:string;due_date:string;status:string;gross_amount:number;paid_amount:number|null;paid_at:string|null;property_code:string}>
  repasses:Array<{id:string;lease_contract_id:string;property_id:string;due_date:string;status:string;amount:number;paid_at:string|null}>
}
type ClientCommercialSummary = {
  metrics:{leads:number;active:number;visits:number;proposals:number;won:number}
  next_action:{title:string|null;at:string|null;notes:string|null;property_code:string}|null
  inquiries:Array<{id:string;property_id:string|null;property_code:string;property_title:string;status:string;source:string;responsible_name:string|null;next_action_title:string|null;next_action_at:string|null;created_at:string;updated_at:string}>
  visits:Array<{id:string;property_id:string|null;starts_at:string;status:string;notes:string|null}>
  proposals:Array<{id:string;property_id:string|null;status:string;rent_amount:number;start_date:string;lease_contract_id:string|null;created_at:string}>
  activities:Array<{id:string;title:string;notes:string|null;activity_type:string;created_at:string}>
}
type ClientHistoryEvent = {kind:string;title:string;detail:string|null;at:string}

function bankHasData(value:BankForm){return Boolean(value.bank_name.trim()||value.bank_code.trim()||value.branch.trim()||value.account_number.trim()||value.account_digit.trim()||value.pix_key_type!=='none'||value.pix_key.trim()||value.account_holder_name.trim()||value.account_holder_document.trim())}
function profileHasData(value:ProfileForm,personType:PersonCreate['person_type']){if(value.secondary_phone.trim())return true;if(personType==='company')return Boolean(value.trade_name.trim()||value.state_registration.trim()||value.municipal_registration.trim());return Boolean(value.identity_number.trim()||value.identity_issuer.trim()||value.birth_date||value.nationality.trim()||value.marital_status||value.occupation.trim())}
function PersonPhoto({person,className}:{person:Person;className:string}){
  const [src,setSrc]=useState('')
  useEffect(()=>{
    let active=true,objectUrl=''
    if(!person.photo_content_url){setSrc('');return()=>undefined}
    void apiBlobRequest(person.photo_content_url).then(blob=>{if(!active)return;objectUrl=URL.createObjectURL(blob);setSrc(objectUrl)}).catch(()=>{if(active)setSrc('')})
    return()=>{active=false;if(objectUrl)URL.revokeObjectURL(objectUrl)}
  },[person.id,person.photo_content_url,person.photo_updated_at])
  return src?<img className={className} src={src} alt={person.name}/>:<span className={className}>{person.name.trim().split(/\s+/).filter(Boolean).slice(0,2).map(part=>part[0]?.toUpperCase()).join('')||'CL'}</span>
}


export function PeopleWorkspacePage({ permissions }: { permissions: string[] }) {
  const canCreate = permissions.includes('properties.create'), canEdit = permissions.includes('properties.edit')
  const [items,setItems]=useState<Person[]>([]),[properties,setProperties]=useState<Property[]>([]),[leases,setLeases]=useState<ClientLease[]>([]),[query,setQuery]=useState(''),[loading,setLoading]=useState(true),[saving,setSaving]=useState(false)
  const [view,setView]=useState<PeopleView>('active')
  const [roleFilter,setRoleFilter]=useState('all'),[personTypeFilter,setPersonTypeFilter]=useState('all'),[peopleSort,setPeopleSort]=useState<'name'|'recent'>('name')
  const [showForm,setShowForm]=useState(false),[editingId,setEditingId]=useState<string|null>(null),[form,setForm]=useState<PersonCreate>(emptyPersonForm)
  const [showArchiveConfirm,setShowArchiveConfirm]=useState(false)
  const [bank,setBank]=useState<BankForm>(emptyBank),[profile,setProfile]=useState<ProfileForm>(emptyProfile),[bankExists,setBankExists]=useState(false),[profileExists,setProfileExists]=useState(false)
  const [activeTab,setActiveTab]=useState<PersonTab>('main'),[detailsLoading,setDetailsLoading]=useState(false)
  const [selectedId,setSelectedId]=useState<string|null>(null),[clientTab,setClientTab]=useState<ClientTab>('overview'),[photoSaving,setPhotoSaving]=useState(false)
  const [financeSummary,setFinanceSummary]=useState<ClientFinanceSummary|null>(null),[commercialSummary,setCommercialSummary]=useState<ClientCommercialSummary|null>(null),[historyEvents,setHistoryEvents]=useState<ClientHistoryEvent[]>([]),[insightsLoading,setInsightsLoading]=useState(false),[insightsLoadedKey,setInsightsLoadedKey]=useState('')
  const [error,setError]=useState(''),[success,setSuccess]=useState('')
  const load=useCallback(async()=>{setLoading(true);setError('');try{const [active,archived,props,leaseItems]=await Promise.all([apiRequest<Person[]>('/people'),apiRequest<Person[]>('/people/archived'),apiRequest<Property[]>('/properties'),apiRequest<ClientLease[]>('/lease-contracts')]);setItems([...active,...archived].sort((a,b)=>a.name.localeCompare(b.name)));setProperties(props);setLeases(leaseItems)}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os clientes.')}finally{setLoading(false)}},[])
  useEffect(()=>{void load()},[load])
  useEffect(()=>{if(!showForm)return;const previous=document.body.style.overflow;document.body.style.overflow='hidden';const close=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!saving&&!showArchiveConfirm)setShowForm(false)};window.addEventListener('keydown',close);return()=>{document.body.style.overflow=previous;window.removeEventListener('keydown',close)}},[showForm,saving,showArchiveConfirm])
  const activeCount=useMemo(()=>items.filter(person=>person.is_active).length,[items])
  const archivedCount=items.length-activeCount
  const filtered=useMemo(()=>{const active=view==='active';const term=query.trim().toLowerCase();const base=items.filter(person=>{if(person.is_active!==active)return false;if(roleFilter!=='all'&&!person.role_keys.includes(roleFilter))return false;if(personTypeFilter!=='all'&&person.person_type!==personTypeFilter)return false;if(!term)return true;return (person.name+' '+(person.document_number??'')+' '+(person.email??'')+' '+(person.phone??'')).toLowerCase().includes(term)});return [...base].sort((a,b)=>peopleSort==='recent'?new Date(b.created_at).getTime()-new Date(a.created_at).getTime():a.name.localeCompare(b.name,'pt-BR'))},[items,query,view,roleFilter,personTypeFilter,peopleSort])
  useEffect(()=>{if(filtered.length===0){setSelectedId(null);return}if(!selectedId||!filtered.some(person=>person.id===selectedId))setSelectedId(filtered[0].id)},[filtered,selectedId])
  const selected=useMemo(()=>items.find(person=>person.id===selectedId)??null,[items,selectedId])
  useEffect(()=>{
    if(!selected)return
    const key=`${selected.id}:${clientTab}`
    if(insightsLoadedKey===key)return
    if(clientTab==='finance'){
      if(!permissions.includes('finance.view'))return
      setInsightsLoading(true)
      void apiRequest<ClientFinanceSummary>(`/people/${selected.id}/finance-summary`).then(data=>{setFinanceSummary(data);setInsightsLoadedKey(key)}).catch(cause=>setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o financeiro do cliente.')).finally(()=>setInsightsLoading(false))
    }else if(clientTab==='commercial'){
      if(!permissions.includes('crm.view'))return
      setInsightsLoading(true)
      void apiRequest<ClientCommercialSummary>(`/people/${selected.id}/commercial-summary`).then(data=>{setCommercialSummary(data);setInsightsLoadedKey(key)}).catch(cause=>setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o relacionamento comercial.')).finally(()=>setInsightsLoading(false))
    }else if(clientTab==='history'){
      setInsightsLoading(true)
      void apiRequest<ClientHistoryEvent[]>(`/people/${selected.id}/history`).then(data=>{setHistoryEvents(data);setInsightsLoadedKey(key)}).catch(cause=>setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o histórico do cliente.')).finally(()=>setInsightsLoading(false))
    }
  },[selected,clientTab,permissions,insightsLoadedKey])

  const selectedProperties=useMemo(()=>selected?properties.filter(property=>property.owners.some(owner=>owner.person_id===selected.id)):[],[properties,selected])
  const selectedLeases=useMemo(()=>selected?leases.filter(lease=>lease.tenants.some(tenant=>tenant.person_id===selected.id)||selectedProperties.some(property=>property.id===lease.property_id)):[],[leases,selected,selectedProperties])
  const activeLeases=selectedLeases.filter(lease=>!['cancelled','closed'].includes(lease.status))
  const personTypeLabel=(person:Person)=>person.person_type==='company'?'Pessoa jurídica':'Pessoa física'
  const initials=(name:string)=>name.trim().split(/\s+/).filter(Boolean).slice(0,2).map(part=>part[0]?.toUpperCase()).join('')||'CL'
  const addressSummary=(person:Person)=>[person.address?.city,person.address?.state].filter(Boolean).join('/')||'Localização não informada'
  const propertyAddress=(property:Property)=>[property.address?.street,property.address?.number,property.address?.neighborhood].filter(Boolean).join(', ')||'Endereço não informado'
  const money=(value:number|null|undefined)=>value==null?'—':Number(value).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
  const leaseStatus=(status:string)=>({draft:'Rascunho',review:'Em revisão',approved:'Aprovado',pending_signature:'Assinatura',signed:'Ativo',closed:'Encerrado',cancelled:'Cancelado'}[status]||status)
  const clientTabButton=(key:ClientTab,label:string,Icon:typeof Users)=><button type="button" className={clientTab===key?'active':''} onClick={()=>setClientTab(key)}><Icon size={13}/>{label}</button>
  function roleLabel(role:string){return roleOptions.find(([key])=>key===role)?.[1]??role}
  function resetExtended(){setBank(emptyBank());setProfile(emptyProfile());setBankExists(false);setProfileExists(false);setDetailsLoading(false);setActiveTab('main')}
  function openNew(){setEditingId(null);setForm(emptyPersonForm());resetExtended();setError('');setSuccess('');setShowArchiveConfirm(false);setShowForm(true)}
  async function openEdit(person:Person){
    if(!canEdit||!person.is_active)return
    setEditingId(person.id);setForm({person_type:person.person_type,name:person.name,document_number:person.document_number??'',email:person.email??'',phone:person.phone??'',address:{...emptyAddress(),...person.address},notes:person.notes??'',role_keys:person.role_keys as PersonRoleKey[]});resetExtended();setError('');setSuccess('');setShowArchiveConfirm(false);setShowForm(true);setDetailsLoading(true)
    try{
      const [loadedBank,loadedProfile]=await Promise.all([apiRequest<BankDetails|null>(`/people/${person.id}/bank-details`),apiRequest<ProfileDetails|null>(`/people/${person.id}/profile`)])
      if(loadedBank){setBankExists(true);setBank({bank_name:loadedBank.bank_name||'',bank_code:loadedBank.bank_code||'',branch:loadedBank.branch||'',account_number:loadedBank.account_number||'',account_digit:loadedBank.account_digit||'',account_type:loadedBank.account_type||'checking',pix_key_type:loadedBank.pix_key_type||'none',pix_key:loadedBank.pix_key||'',account_holder_name:loadedBank.account_holder_name||'',account_holder_document:loadedBank.account_holder_document||''})}
      if(loadedProfile){setProfileExists(true);setProfile({secondary_phone:loadedProfile.secondary_phone||'',identity_number:loadedProfile.identity_number||'',identity_issuer:loadedProfile.identity_issuer||'',birth_date:loadedProfile.birth_date||'',nationality:loadedProfile.nationality||'',marital_status:loadedProfile.marital_status||'',occupation:loadedProfile.occupation||'',trade_name:loadedProfile.trade_name||'',state_registration:loadedProfile.state_registration||'',municipal_registration:loadedProfile.municipal_registration||''})}
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os dados complementares da pessoa.')}finally{setDetailsLoading(false)}
  }
  function closeModal(){if(!saving&&!showArchiveConfirm){setShowForm(false);setEditingId(null);setError('');resetExtended()}}
  function updateAddress(key:keyof Address,value:string){setForm(current=>({...current,address:{...current.address,[key]:value}}))}
  function toggleRole(role:PersonRoleKey){setForm(current=>({...current,role_keys:current.role_keys.includes(role)?current.role_keys.filter(item=>item!==role):[...current.role_keys,role]}))}
  const setBankField=<K extends keyof BankForm>(key:K,value:BankForm[K])=>setBank(current=>({...current,[key]:value}))
  const setProfileField=<K extends keyof ProfileForm>(key:K,value:ProfileForm[K])=>setProfile(current=>({...current,[key]:value}))
  function updateSaved(saved:Person,editing:boolean){setItems(current=>(editing?current.map(item=>item.id===saved.id?saved:item):[...current,saved]).sort((a,b)=>a.name.localeCompare(b.name)))}
  async function archivePerson(){
    if(!editingId||!canEdit||saving)return
    setShowArchiveConfirm(false);setSaving(true);setError('');setSuccess('')
    try{const saved=await apiRequest<Person>(`/people/${editingId}/archive`,{method:'POST'});updateSaved(saved,true);setShowForm(false);setEditingId(null);resetExtended();setSuccess('Pessoa arquivada. O histórico foi preservado.')}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível arquivar a pessoa.')}
    finally{setSaving(false)}
  }
  async function restorePerson(person:Person){
    if(!canEdit||saving)return
    setSaving(true);setError('');setSuccess('')
    try{const saved=await apiRequest<Person>(`/people/${person.id}/restore`,{method:'POST'});updateSaved(saved,true);setSuccess(`${person.name} foi reativado(a).`)}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível reativar a pessoa.')}
    finally{setSaving(false)}
  }
  async function save(event:FormEvent){
    event.preventDefault();const editing=editingId!==null;if((editing&&!canEdit)||(!editing&&!canCreate))return
    if(!form.name.trim()){setActiveTab('main');setError('Informe o nome ou a razão social da pessoa.');return}
    if(bank.pix_key_type!=='none'&&!bank.pix_key.trim()){setActiveTab('bank');setError('Informe a chave Pix ou selecione “Sem chave Pix”.');return}
    setSaving(true);setError('');setSuccess('');let saved:Person|null=null
    try{
      saved=await apiRequest<Person>(editing?`/people/${editingId}`:'/people',{method:editing?'PUT':'POST',body:JSON.stringify(form)})
      setEditingId(saved.id)
      const extended:Promise<unknown>[]=[]
      if(bankExists||bankHasData(bank))extended.push(apiRequest<BankDetails>(`/people/${saved.id}/bank-details`,{method:'PUT',body:JSON.stringify({...bank,pix_key:bank.pix_key_type==='none'?null:bank.pix_key||null})}))
      if(profileExists||profileHasData(profile,form.person_type))extended.push(apiRequest<ProfileDetails>(`/people/${saved.id}/profile`,{method:'PUT',body:JSON.stringify({...profile,birth_date:profile.birth_date||null,marital_status:profile.marital_status||null})}))
      await Promise.all(extended)
      updateSaved(saved,editing);setShowForm(false);setEditingId(null);resetExtended();setSuccess(editing?'Cadastro atualizado.':'Pessoa cadastrada.')
    }catch(cause){
      if(saved){updateSaved(saved,editing);setError(`O cadastro principal foi salvo, mas os dados complementares não foram concluídos. ${cause instanceof ApiError?cause.detail:'Tente salvar novamente.'}`)}
      else setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar a pessoa.')
    }finally{setSaving(false)}
  }
  async function uploadPhoto(person:Person,file:File){
    if(!canEdit||photoSaving)return
    if(!['image/jpeg','image/png','image/webp'].includes(file.type)){setError('Use uma imagem JPG, PNG ou WEBP.');return}
    if(file.size>8*1024*1024){setError('A foto pode ter no máximo 8 MB.');return}
    setPhotoSaving(true);setError('');setSuccess('')
    try{
      const body=new FormData();body.append('file',file)
      await apiRequest<void>(`/people/${person.id}/photo`,{method:'POST',body})
      await load()
      setSuccess(person.person_type==='company'?'Logo atualizado.':'Foto atualizada.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível atualizar a foto.')}
    finally{setPhotoSaving(false)}
  }
  async function removePhoto(person:Person){
    if(!canEdit||photoSaving||!person.photo_content_url)return
    setPhotoSaving(true);setError('');setSuccess('')
    try{await apiRequest<void>(`/people/${person.id}/photo`,{method:'DELETE'});await load();setSuccess('Foto removida.')}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível remover a foto.')}
    finally{setPhotoSaving(false)}
  }
  const tabButton=(key:PersonTab,label:string,Icon:typeof UserRound)=><button type="button" role="tab" aria-selected={activeTab===key} className={activeTab===key?'active':''} onClick={()=>setActiveTab(key)}><Icon size={14}/><span>{label}</span></button>
  return <section className="workspace portfolio-workspace client-workspace-v9">
    <div className="page-heading portfolio-heading client-heading-v9">
      <div><span className="eyebrow">Relacionamento</span><h1>Clientes</h1><p>Cadastro, imóveis, contratos e histórico reunidos em uma única ficha.</p></div>
      {canCreate&&<button className="button primary" type="button" onClick={openNew}><Plus size={15}/> Novo cliente</button>}
    </div>
    {error&&!showForm&&<div className="form-alert danger-alert">{error}</div>}
    {success&&<div className="form-alert success-alert">{success}</div>}
    {loading?<article className="panel settings-loading">Carregando clientes...</article>:
    <div className="client-master-detail">
      <aside className="panel client-directory">
        <div className="client-directory-top">
          <label className="client-directory-search"><Search size={14}/><input placeholder="Buscar cliente..." value={query} onChange={event=>setQuery(event.target.value)}/></label>
          <div className="client-directory-status"><button className={view==='active'?'active':''} type="button" onClick={()=>setView('active')}>Ativos <span>{activeCount}</span></button><button className={view==='archived'?'active':''} type="button" onClick={()=>setView('archived')}>Arquivados <span>{archivedCount}</span></button></div>
          <div className="client-directory-filters">
            <select value={roleFilter} onChange={e=>setRoleFilter(e.target.value)}><option value="all">Todos os papéis</option>{roleOptions.map(([key,label])=><option value={key} key={key}>{label}</option>)}</select>
            <select value={personTypeFilter} onChange={e=>setPersonTypeFilter(e.target.value)}><option value="all">PF e PJ</option><option value="individual">Pessoa física</option><option value="company">Pessoa jurídica</option></select>
          </div>
          <div className="client-directory-count">{filtered.length} cliente(s) · <select value={peopleSort} onChange={e=>setPeopleSort(e.target.value as 'name'|'recent')}><option value="name">Nome A–Z</option><option value="recent">Mais recentes</option></select></div>
        </div>
        <div className="client-directory-list">
          {filtered.map(person=>{
            const personProps=properties.filter(property=>property.owners.some(owner=>owner.person_id===person.id))
            const personLeases=leases.filter(lease=>lease.tenants.some(tenant=>tenant.person_id===person.id)||personProps.some(property=>property.id===lease.property_id))
            return <button type="button" key={person.id} className={'client-directory-row '+(selectedId===person.id?'active':'')} onClick={()=>{setSelectedId(person.id);setClientTab('overview');setInsightsLoadedKey('');setFinanceSummary(null);setCommercialSummary(null);setHistoryEvents([])}}>
              <PersonPhoto person={person} className="client-directory-avatar"/>
              <span className="client-directory-copy"><strong>{person.name}</strong><small>{person.document_number||'Documento não informado'} · {person.phone||'Sem telefone'}</small><span className="client-directory-roles">{person.role_keys.slice(0,3).map(role=><i key={role}>{roleLabel(role)}</i>)}</span><em>{personProps.length} imóvel(is) · {personLeases.filter(lease=>!['cancelled','closed'].includes(lease.status)).length} contrato(s) ativo(s)</em></span>
            </button>
          })}
          {filtered.length===0&&<div className="client-directory-empty"><Users size={24}/><strong>Nenhum cliente encontrado.</strong><span>Ajuste os filtros ou cadastre um novo cliente.</span></div>}
        </div>
      </aside>

      <main className="panel client-profile">
        {!selected?<div className="client-profile-empty"><Users size={28}/><strong>Selecione um cliente</strong><span>A ficha completa aparecerá aqui.</span></div>:<>
          <header className="client-profile-header">
            <div className="client-profile-photo-wrap">
              <PersonPhoto person={selected} className="client-profile-avatar"/>
              {canEdit&&<label className="client-photo-upload" title={selected.photo_content_url?'Trocar foto':'Adicionar foto'}><Camera size={12}/><input type="file" accept="image/jpeg,image/png,image/webp" disabled={photoSaving} onChange={event=>{const file=event.target.files?.[0];if(file)void uploadPhoto(selected,file);event.currentTarget.value=''}}/></label>}
              {canEdit&&selected.photo_content_url&&<button className="client-photo-remove" type="button" title="Remover foto" disabled={photoSaving} onClick={()=>void removePhoto(selected)}><Trash2 size={10}/></button>}
            </div>
            <div className="client-profile-title">
              <div className="client-profile-name-row"><h2>{selected.name}</h2><i className={'status-badge '+(selected.is_active?'success':'neutral')}>{selected.is_active?'Ativo':'Arquivado'}</i></div>
              <div className="client-profile-badges"><span>{personTypeLabel(selected)}</span>{selected.role_keys.map(role=><i key={role}>{roleLabel(role)}</i>)}</div>
              <div className="client-profile-contact">
                <span><FileText size={11}/>{selected.document_number||'Documento não informado'}</span>
                <span><Phone size={11}/>{selected.phone||'Telefone não informado'}</span>
                <span><Mail size={11}/>{selected.email||'E-mail não informado'}</span>
                <span><MapPin size={11}/>{addressSummary(selected)}</span>
              </div>
            </div>
            {canEdit&&(selected.is_active?<button className="button secondary" type="button" onClick={()=>void openEdit(selected)}><Pencil size={13}/> Editar</button>:<button className="button secondary" type="button" onClick={()=>void restorePerson(selected)} disabled={saving}><RotateCcw size={13}/> Reativar</button>)}
          </header>

          <nav className="client-profile-tabs">
            {clientTabButton('overview','Visão Geral',UserRound)}
            {clientTabButton('properties','Imóveis',Home)}
            {clientTabButton('contracts','Contratos',FileText)}
            {clientTabButton('finance','Financeiro',CircleDollarSign)}
            {clientTabButton('commercial','Comercial',Users)}
            {clientTabButton('documents','Documentos',FileText)}
            {clientTabButton('history','Histórico',History)}
          </nav>

          <div className="client-profile-body">
            {clientTab==='overview'&&<div className="client-overview">
              <div className="client-kpi-grid">
                <article><span>Imóveis vinculados</span><strong>{selectedProperties.length}</strong><small>{selectedProperties.filter(property=>property.status==='available').length} disponível(is)</small></article>
                <article><span>Contratos</span><strong>{activeLeases.length}</strong><small>{selectedLeases.length} no histórico</small></article>
                <article><span>Relacionamentos</span><strong>{selected.role_keys.length}</strong><small>{selected.role_keys.map(roleLabel).join(' · ')||'Sem papel operacional'}</small></article>
                <article><span>Status cadastral</span><strong>{selected.is_active?'Ativo':'Arquivado'}</strong><small>Cadastro desde {new Date(selected.created_at).toLocaleDateString('pt-BR')}</small></article>
              </div>
              <div className="client-overview-grid">
                <article><span>Dados principais</span><strong>{selected.document_number||'Documento não informado'}</strong><small>{personTypeLabel(selected)}</small></article>
                <article><span>Contato</span><strong>{selected.phone||'Telefone não informado'}</strong><small>{selected.email||'E-mail não informado'}</small></article>
                <article><span>Endereço</span><strong>{[selected.address?.street,selected.address?.number].filter(Boolean).join(', ')||'Endereço não informado'}</strong><small>{[selected.address?.neighborhood,selected.address?.city,selected.address?.state].filter(Boolean).join(' · ')}</small></article>
                <article><span>Relacionamentos</span><strong>{selected.role_keys.length?selected.role_keys.map(roleLabel).join(' · '):'Sem vínculos operacionais'}</strong><small>{selected.role_keys.includes('owner')?'Proprietário de '+selectedProperties.length+' imóvel(is)':''}{selected.role_keys.includes('owner')&&selected.role_keys.includes('tenant')?' · ':''}{selected.role_keys.includes('tenant')?'Locatário em '+selectedLeases.filter(lease=>lease.tenants.some(tenant=>tenant.person_id===selected.id)&&!['cancelled','closed'].includes(lease.status)).length+' contrato(s)':''}</small></article>
              </div>
              <article className="client-notes-card"><span>Observações internas</span><p>{selected.notes||'Nenhuma observação cadastrada para este cliente.'}</p></article>
              <section className="client-recent-activity">
                <div className="client-tab-heading"><div><span className="eyebrow">Atividade recente</span><h3>Resumo operacional</h3></div></div>
                <div className="client-activity-grid">
                  <article><History size={14}/><div><span>Cadastro criado</span><strong>{new Date(selected.created_at).toLocaleString('pt-BR')}</strong></div></article>
                  <article><Home size={14}/><div><span>Imóveis vinculados</span><strong>{selectedProperties.length?selectedProperties.length+' vínculo(s) ativo(s)':'Nenhum imóvel vinculado'}</strong></div></article>
                  <article><FileText size={14}/><div><span>Contratos ativos</span><strong>{activeLeases.length?activeLeases.length+' contrato(s) em andamento':'Nenhum contrato ativo'}</strong></div></article>
                  <article><Users size={14}/><div><span>Papéis atuais</span><strong>{selected.role_keys.map(roleLabel).join(' · ')||'Nenhum papel operacional'}</strong></div></article>
                </div>
              </section>
            </div>}

            {clientTab==='properties'&&<div className="client-tab-section"><div className="client-tab-heading"><div><span className="eyebrow">Patrimônio e vínculos</span><h3>Imóveis</h3></div><strong>{selectedProperties.length}</strong></div>{selectedProperties.length?<div className="client-entity-list">{selectedProperties.map(property=><article key={property.id}><div><span>{property.code}</span><strong>{property.public_title||propertyAddress(property)}</strong><small>{propertyAddress(property)}</small></div><div><strong>{money(property.rent_amount)}</strong><small>{property.status} · {property.publication_enabled?'Publicado':'Não publicado'}</small></div></article>)}</div>:<div className="client-tab-empty"><Home size={22}/>Nenhum imóvel vinculado a este cliente.</div>}</div>}

            {clientTab==='contracts'&&<div className="client-tab-section"><div className="client-tab-heading"><div><span className="eyebrow">Relação contratual</span><h3>Contratos</h3></div><strong>{selectedLeases.length}</strong></div>{selectedLeases.length?<div className="client-entity-list">{selectedLeases.map(lease=><article key={lease.id}><div><span>{lease.code} · {lease.property_code}</span><strong>{[lease.property_address?.street,lease.property_address?.number].filter(Boolean).join(', ')||'Imóvel vinculado'}</strong><small>{lease.tenants.some(tenant=>tenant.person_id===selected.id)?'Locatário':'Proprietário'} · {lease.start_date?new Date(lease.start_date+'T12:00:00').toLocaleDateString('pt-BR'):'—'} até {lease.end_date?new Date(lease.end_date+'T12:00:00').toLocaleDateString('pt-BR'):'—'}</small></div><div><strong>{money(lease.rent_amount)}</strong><i className={'status-badge '+(['signed','approved'].includes(lease.status)?'success':['cancelled'].includes(lease.status)?'danger':'neutral')}>{leaseStatus(lease.status)}</i></div></article>)}</div>:<div className="client-tab-empty"><FileText size={22}/>Nenhum contrato vinculado a este cliente.</div>}</div>}

            {clientTab==='finance'&&(permissions.includes('finance.view')?
              <div className="client-tab-section client-insights-tab">
                <div className="client-tab-heading"><div><span className="eyebrow">Movimentação financeira</span><h3>Financeiro do cliente</h3></div><CircleDollarSign size={20}/></div>
                {insightsLoading&&!financeSummary?<div className="client-tab-empty">Carregando financeiro...</div>:financeSummary&&<>
                  <div className="client-insight-metrics">
                    <article><span>Em aberto</span><strong>{money(financeSummary.tenant.open_amount)}</strong><small>{financeSummary.tenant.open_count} cobrança(s)</small></article>
                    <article className={financeSummary.tenant.overdue_count?'attention':''}><span>Em atraso</span><strong>{money(financeSummary.tenant.overdue_amount)}</strong><small>{financeSummary.tenant.overdue_count} vencida(s)</small></article>
                    <article><span>Recebido</span><strong>{money(financeSummary.tenant.paid_amount)}</strong><small>aluguéis liquidados</small></article>
                    <article><span>Repasses pendentes</span><strong>{money(financeSummary.owner.pending_amount)}</strong><small>{financeSummary.owner.pending_count} repasse(s)</small></article>
                  </div>
                  <div className="client-insight-columns">
                    <section><div className="client-insight-title"><WalletCards size={15}/><div><strong>Cobranças como locatário</strong><span>{financeSummary.tenant.total_charges} lançamento(s)</span></div></div>{financeSummary.charges.length?<div className="client-compact-list">{financeSummary.charges.slice(0,10).map(row=><article key={row.id}><div><strong>{row.property_code?`Imóvel #${row.property_code}`:'Locação'}</strong><small>Venc. {new Date(row.due_date+'T12:00:00').toLocaleDateString('pt-BR')} · competência {new Date(row.competence+'T12:00:00').toLocaleDateString('pt-BR',{month:'2-digit',year:'numeric'})}</small></div><div><strong>{money(row.gross_amount)}</strong><i className={'status-badge '+(row.status==='paid'?'success':new Date(row.due_date+'T23:59:59')<new Date()?'danger':'neutral')}>{row.status==='paid'?'Pago':row.status==='cancelled'?'Cancelado':'Aberto'}</i></div></article>)}</div>:<div className="client-mini-empty">Nenhuma cobrança vinculada.</div>}</section>
                    <section><div className="client-insight-title"><Landmark size={15}/><div><strong>Repasses como proprietário</strong><span>{financeSummary.owner.total_repasses} lançamento(s)</span></div></div>{financeSummary.repasses.length?<div className="client-compact-list">{financeSummary.repasses.slice(0,10).map(row=><article key={row.id}><div><strong>Repasse</strong><small>Previsto para {new Date(row.due_date+'T12:00:00').toLocaleDateString('pt-BR')}</small></div><div><strong>{money(row.amount)}</strong><i className={'status-badge '+(row.status==='paid'?'success':'neutral')}>{row.status==='paid'?'Pago':'Pendente'}</i></div></article>)}</div>:<div className="client-mini-empty">Nenhum repasse vinculado.</div>}</section>
                  </div>
                </>}
              </div>:<div className="client-tab-empty">Sem permissão para visualizar dados financeiros.</div>)}
            {clientTab==='commercial'&&(permissions.includes('crm.view')?
              <div className="client-tab-section client-insights-tab">
                <div className="client-tab-heading"><div><span className="eyebrow">Relacionamento</span><h3>Comercial</h3></div><TrendingUp size={20}/></div>
                {insightsLoading&&!commercialSummary?<div className="client-tab-empty">Carregando relacionamento comercial...</div>:commercialSummary&&<>
                  <div className="client-insight-metrics">
                    <article><span>Leads</span><strong>{commercialSummary.metrics.leads}</strong><small>{commercialSummary.metrics.active} ativo(s)</small></article>
                    <article><span>Visitas</span><strong>{commercialSummary.metrics.visits}</strong><small>agendadas/realizadas</small></article>
                    <article><span>Propostas</span><strong>{commercialSummary.metrics.proposals}</strong><small>histórico comercial</small></article>
                    <article><span>Fechamentos</span><strong>{commercialSummary.metrics.won}</strong><small>negócio(s) ganho(s)</small></article>
                  </div>
                  {commercialSummary.next_action&&<div className="client-next-action"><CalendarClock size={17}/><div><span>Próxima atividade</span><strong>{commercialSummary.next_action.title||'Atividade comercial'}</strong><small>{commercialSummary.next_action.at?new Date(commercialSummary.next_action.at).toLocaleString('pt-BR'):'Sem data'} · imóvel #{commercialSummary.next_action.property_code}</small></div></div>}
                  <div className="client-insight-columns">
                    <section><div className="client-insight-title"><Users size={15}/><div><strong>Atendimentos</strong><span>{commercialSummary.inquiries.length} lead(s)</span></div></div>{commercialSummary.inquiries.length?<div className="client-compact-list">{commercialSummary.inquiries.slice(0,12).map(row=><article key={row.id}><div><strong>#{row.property_code} · {row.property_title}</strong><small>{row.responsible_name||'Sem responsável'}{row.next_action_title?` · próxima: ${row.next_action_title}`:''}</small></div><div><i className={'status-badge '+(row.status==='won'?'success':row.status==='lost'?'danger':'neutral')}>{({new:'Novo',contacted:'Contato',visit_scheduled:'Visita',qualified:'Qualificado',proposal:'Proposta',converted:'Contrato',won:'Fechado',lost:'Perdido'} as Record<string,string>)[row.status]||row.status}</i></div></article>)}</div>:<div className="client-mini-empty">Nenhum atendimento comercial vinculado.</div>}</section>
                    <section><div className="client-insight-title"><FileText size={15}/><div><strong>Propostas recentes</strong><span>{commercialSummary.proposals.length} proposta(s)</span></div></div>{commercialSummary.proposals.length?<div className="client-compact-list">{commercialSummary.proposals.slice(0,10).map(row=><article key={row.id}><div><strong>{money(row.rent_amount)}</strong><small>Início {new Date(row.start_date+'T12:00:00').toLocaleDateString('pt-BR')}</small></div><div><i className={'status-badge '+(['accepted','converted','won'].includes(row.status)?'success':['rejected','withdrawn'].includes(row.status)?'danger':'neutral')}>{row.status}</i></div></article>)}</div>:<div className="client-mini-empty">Nenhuma proposta vinculada.</div>}</section>
                  </div>
                </>}
              </div>:<div className="client-tab-empty">Sem permissão para visualizar o CRM.</div>)}
            {clientTab==='documents'&&(permissions.includes('documents.view')?<EntityDocumentsPanel entityType="person" entityId={selected.id} entityLabel={selected.name} permissions={permissions} compact/>:<div className="client-tab-empty">Sem permissão para visualizar documentos.</div>)}
            {clientTab==='history'&&<div className="client-tab-section client-insights-tab"><div className="client-tab-heading"><div><span className="eyebrow">Rastreabilidade</span><h3>Histórico do cliente</h3></div><History size={20}/></div>{insightsLoading&&!historyEvents.length?<div className="client-tab-empty">Carregando histórico...</div>:historyEvents.length?<div className="client-timeline-real">{historyEvents.map((event,index)=><article key={event.kind+'-'+event.at+'-'+index}><span className="client-timeline-dot"/><div><strong>{event.title}</strong>{event.detail&&<small>{event.detail}</small>}</div><time>{new Date(event.at).toLocaleString('pt-BR')}</time></article>)}</div>:<div className="client-tab-empty">Nenhuma movimentação registrada.</div>}</div>}
          </div>
        </>}
      </main>
    </div>}
    {showForm&&<div className="portfolio-modal-backdrop" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget)closeModal()}}><form className="panel portfolio-modal person-modal" onSubmit={save} role="dialog" aria-modal="true" aria-labelledby="person-modal-title"><div className="portfolio-modal-header"><div><span className="eyebrow">Cadastro canônico</span><h2 id="person-modal-title">{editingId?'Editar pessoa':'Nova pessoa'}</h2><p>Identificação, endereço, recebimentos e dados contratuais no mesmo cadastro.</p></div><button className="portfolio-modal-close" type="button" onClick={closeModal} disabled={saving} aria-label="Fechar"><X size={18}/></button></div>
    <div className="person-form-tabs" role="tablist" aria-label="Seções do cadastro">{tabButton('main','Dados principais',UserRound)}{tabButton('address','Endereço',MapPin)}{tabButton('bank','Dados bancários',Landmark)}{tabButton('profile','Contratuais',FileText)}{editingId&&permissions.includes('documents.view')&&tabButton('documents','Documentos',FileText)}</div>
    <div className="portfolio-modal-body person-modal-body">{error&&<div className="form-alert danger-alert">{error}</div>}{detailsLoading&&<div className="person-detail-loading">Carregando dados complementares...</div>}
      {activeTab==='main'&&<div className="person-tab-panel"><div className="person-tab-heading"><strong>Identificação e contato</strong><span>Dados básicos e papéis que esta pessoa exerce na operação.</span></div><div className="form-grid three-columns"><label className="field"><span>Tipo</span><select value={form.person_type} onChange={e=>setForm(c=>({...c,person_type:e.target.value as PersonCreate['person_type']}))}><option value="individual">Pessoa física</option><option value="company">Pessoa jurídica</option></select></label><label className="field"><span>{form.person_type==='company'?'CNPJ':'CPF'}</span><input data-format="cpf-cnpj" value={form.document_number??''} onChange={e=>setForm(c=>({...c,document_number:e.target.value}))}/></label><label className="field field-span-2"><span>{form.person_type==='company'?'Razão social':'Nome completo'}</span><input autoFocus value={form.name} onChange={e=>setForm(c=>({...c,name:e.target.value}))}/></label><label className="field field-span-2"><span>E-mail</span><input type="email" value={form.email??''} onChange={e=>setForm(c=>({...c,email:e.target.value}))}/></label><label className="field field-span-2"><span>Telefone / WhatsApp</span><input data-format="phone" value={form.phone??''} onChange={e=>setForm(c=>({...c,phone:e.target.value}))}/></label><div className="field field-span-3"><span>Papéis na operação</span><div className="portfolio-role-grid">{roleOptions.map(([key,label])=>{const selected=form.role_keys.includes(key);return <label className={`portfolio-role-option ${selected?'is-selected':''}`} key={key}><input type="checkbox" checked={selected} onChange={()=>toggleRole(key)}/><span className="portfolio-role-check" aria-hidden="true">{selected&&<Check size={11}/>}</span><span className="portfolio-role-label">{label}</span></label>})}</div></div></div></div>}
      {activeTab==='address'&&<div className="person-tab-panel"><div className="person-tab-heading"><strong>Endereço principal</strong><span>Usado em contratos, correspondências e documentos da operação.</span></div><div className="form-grid three-columns"><label className="field"><span>CEP</span><input data-format="cep" value={form.address.postal_code} onChange={e=>updateAddress('postal_code',e.target.value)}/></label><label className="field field-span-2"><span>Rua / Logradouro</span><input value={form.address.street} onChange={e=>updateAddress('street',e.target.value)}/></label><label className="field"><span>Número</span><input value={form.address.number} onChange={e=>updateAddress('number',e.target.value)}/></label><label className="field field-span-2"><span>Complemento</span><input value={form.address.complement} onChange={e=>updateAddress('complement',e.target.value)}/></label><label className="field field-span-2"><span>Bairro</span><input value={form.address.neighborhood} onChange={e=>updateAddress('neighborhood',e.target.value)}/></label><label className="field field-span-2"><span>Cidade</span><input value={form.address.city} onChange={e=>updateAddress('city',e.target.value)}/></label><label className="field"><span>UF</span><input maxLength={2} value={form.address.state} onChange={e=>updateAddress('state',e.target.value.toUpperCase())}/></label></div></div>}
      {activeTab==='bank'&&<div className="person-tab-panel"><div className="person-tab-heading"><strong>Dados bancários</strong><span>Conta preferencial reutilizada em repasses, comissões e outros pagamentos do ERP.</span></div><div className="form-grid three-columns person-bank-grid"><label className="field field-span-2"><span>Banco</span><input value={bank.bank_name} onChange={e=>setBankField('bank_name',e.target.value)} placeholder="Ex.: Banco Inter"/></label><label className="field"><span>Código</span><input inputMode="numeric" value={bank.bank_code} onChange={e=>setBankField('bank_code',e.target.value)} placeholder="077"/></label><label className="field"><span>Agência</span><input value={bank.branch} onChange={e=>setBankField('branch',e.target.value)} placeholder="0001"/></label><label className="field field-span-2"><span>Conta</span><div className="person-account-combo"><input value={bank.account_number} onChange={e=>setBankField('account_number',e.target.value)} placeholder="00000000"/><input value={bank.account_digit} onChange={e=>setBankField('account_digit',e.target.value)} placeholder="DV" aria-label="Dígito da conta"/></div></label><label className="field"><span>Tipo de conta</span><select value={bank.account_type} onChange={e=>setBankField('account_type',e.target.value as BankAccountType)}><option value="checking">Conta corrente</option><option value="savings">Conta poupança</option><option value="payment">Conta de pagamento</option></select></label><label className="field"><span>Tipo da chave Pix</span><select value={bank.pix_key_type} onChange={e=>setBankField('pix_key_type',e.target.value as PixKeyType)}><option value="none">Sem chave Pix</option><option value="cpf_cnpj">CPF / CNPJ</option><option value="email">E-mail</option><option value="phone">Telefone</option><option value="random">Chave aleatória</option></select></label><label className="field field-span-2"><span>Chave Pix</span><input disabled={bank.pix_key_type==='none'} data-format={bank.pix_key_type==='cpf_cnpj'?'cpf-cnpj':bank.pix_key_type==='phone'?'phone':undefined} value={bank.pix_key} onChange={e=>setBankField('pix_key',e.target.value)} placeholder={bank.pix_key_type==='none'?'Selecione um tipo de chave Pix':'Informe a chave Pix'}/></label><label className="field field-span-2"><span>Titular da conta</span><input value={bank.account_holder_name} onChange={e=>setBankField('account_holder_name',e.target.value)} placeholder={form.name||'Nome do titular'}/></label><label className="field field-span-2"><span>CPF / CNPJ do titular</span><input data-format="cpf-cnpj" value={bank.account_holder_document} onChange={e=>setBankField('account_holder_document',e.target.value)} placeholder={form.document_number||'CPF ou CNPJ'}/></label></div><div className="person-tab-helper"><Landmark size={14}/><span>O cadastro bancário é único por Pessoa. Se ela também for corretor ou proprietário, o Financeiro usa estes mesmos dados.</span></div></div>}
      {activeTab==='profile'&&<div className="person-tab-panel"><div className="person-tab-heading"><strong>Dados complementares e contratuais</strong><span>Informações que normalmente seriam pedidas novamente na elaboração de contratos.</span></div><div className="form-grid three-columns">{form.person_type==='individual'?<><label className="field"><span>RG / Identidade</span><input value={profile.identity_number} onChange={e=>setProfileField('identity_number',e.target.value)}/></label><label className="field"><span>Órgão emissor</span><input value={profile.identity_issuer} onChange={e=>setProfileField('identity_issuer',e.target.value)} placeholder="Ex.: SESP/PR"/></label><label className="field"><span>Data de nascimento</span><input type="date" value={profile.birth_date} onChange={e=>setProfileField('birth_date',e.target.value)}/></label><label className="field"><span>Nacionalidade</span><input value={profile.nationality} onChange={e=>setProfileField('nationality',e.target.value)}/></label><label className="field"><span>Estado civil</span><select value={profile.marital_status} onChange={e=>setProfileField('marital_status',e.target.value as MaritalStatus)}><option value="">Não informado</option><option value="single">Solteiro(a)</option><option value="married">Casado(a)</option><option value="stable_union">União estável</option><option value="divorced">Divorciado(a)</option><option value="widowed">Viúvo(a)</option><option value="separated">Separado(a)</option><option value="other">Outro</option></select></label><label className="field field-span-2"><span>Profissão</span><input value={profile.occupation} onChange={e=>setProfileField('occupation',e.target.value)}/></label></>:<><label className="field field-span-2"><span>Nome fantasia</span><input value={profile.trade_name} onChange={e=>setProfileField('trade_name',e.target.value)}/></label><label className="field"><span>Inscrição estadual</span><input value={profile.state_registration} onChange={e=>setProfileField('state_registration',e.target.value)}/></label><label className="field"><span>Inscrição municipal</span><input value={profile.municipal_registration} onChange={e=>setProfileField('municipal_registration',e.target.value)}/></label></>}<label className="field field-span-2"><span>Telefone alternativo</span><input data-format="phone" value={profile.secondary_phone} onChange={e=>setProfileField('secondary_phone',e.target.value)}/></label><label className="field field-span-3"><span>Observações internas</span><textarea rows={4} maxLength={2000} value={form.notes??''} onChange={e=>setForm(c=>({...c,notes:e.target.value}))} placeholder="Informações complementares relevantes para a operação..."/></label></div><div className="person-tab-helper"><FileText size={14}/><span>Cônjuge, representantes e outras pessoas relacionadas devem continuar sendo cadastrados como Pessoas próprias; o vínculo será tratado na operação/contrato, evitando dados duplicados.</span></div></div>}
      {activeTab==='documents'&&editingId&&<EntityDocumentsPanel entityType="person" entityId={editingId} entityLabel={form.name||'Pessoa'} permissions={permissions} compact/>}
    </div><div className={`form-actions portfolio-modal-actions ${editingId?'person-edit-actions':''}`}>{editingId&&canEdit&&<button className="button person-archive-button" type="button" onClick={()=>setShowArchiveConfirm(true)} disabled={saving||detailsLoading}><Archive size={14}/> Arquivar pessoa</button>}<div className="person-modal-primary-actions"><button className="button secondary" type="button" onClick={closeModal} disabled={saving}>Cancelar</button><button className="button primary" disabled={saving||detailsLoading} type="submit">{saving?'Salvando...':editingId?'Salvar alterações':'Cadastrar pessoa'}</button></div></div></form></div>}
    <ConfirmDialog open={showArchiveConfirm} title="Arquivar pessoa" description={`Deseja arquivar ${form.name || 'esta pessoa'}? O histórico será preservado e a pessoa poderá ser reativada depois.`} confirmLabel="Arquivar pessoa" tone="attention" busy={saving} onCancel={()=>setShowArchiveConfirm(false)} onConfirm={()=>void archivePerson()}/>
  </section>
}
