import { Archive, Download, File as FileIcon, FileClock, FilePlus2, FileText, FolderArchive, History, Plus, RefreshCw, Search, Upload, X } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import './documents.css'

type CatalogItem = {
  key:string;source_kind:'managed'|'system';document_id:string|null;title:string;category:string;status:string;
  entity_type:string|null;entity_id:string|null;entity_label:string|null;filename:string;content_type:string;size_bytes:number|null;
  hash_sha256:string|null;version:number;version_count:number;created_at:string;updated_at:string;download_path:string;can_version:boolean
}
type Version = {version_number:number;original_filename:string;content_type:string;size_bytes:number;hash_sha256:string;notes:string|null;created_at:string;download_path:string}
type Detail = {id:string;code:string;title:string;category:string;status:string;entity_type:string|null;entity_id:string|null;entity_label:string|null;current_version:number;notes:string|null;created_at:string;updated_at:string;versions:Version[]}
type LinkRecord = {id:string;name?:string;code?:string;title?:string;public_title?:string;internal_number?:number;property_code?:string}
type EntityType = ''|'person'|'property'|'administration_contract'|'lease_contract'|'inspection'|'maintenance'
type UploadForm = {title:string;category:string;entity_type:EntityType;entity_id:string;notes:string;file:File|null}

const blankForm=():UploadForm=>({title:'',category:'general',entity_type:'',entity_id:'',notes:'',file:null})
const categories:Record<string,string>={general:'Geral',identity:'Identificação',property:'Imóvel',contract:'Contrato',inspection:'Vistoria',maintenance:'Manutenção',finance:'Financeiro',legal:'Jurídico',other:'Outros'}
const entityLabels:Record<string,string>={person:'Pessoa',property:'Imóvel',administration_contract:'Contrato de administração',lease_contract:'Contrato de locação',inspection:'Vistoria',maintenance:'Manutenção'}
const entityPaths:Record<string,string>={person:'/people',property:'/properties',administration_contract:'/administration-contracts',lease_contract:'/lease-contracts',inspection:'/inspections',maintenance:'/maintenance-v2'}
const bytes=(value:number|null)=>value==null?'—':value<1024?`${value} B`:value<1024*1024?`${(value/1024).toFixed(1)} KB`:`${(value/1024/1024).toFixed(1)} MB`
const when=(value:string)=>new Date(value).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'})

function recordLabel(type:EntityType,row:LinkRecord){
  if(type==='person')return row.name||'Pessoa'
  if(type==='property')return row.code||row.public_title||(row.internal_number?`Imóvel ${String(row.internal_number).padStart(6,'0')}`:'Imóvel')
  if(type==='maintenance')return `${row.code||'Manutenção'}${row.title?` · ${row.title}`:''}`
  return row.code||row.title||row.name||row.property_code||'Registro'
}
function openBlob(blob:Blob){const url=URL.createObjectURL(blob);window.open(url,'_blank','noopener,noreferrer');setTimeout(()=>URL.revokeObjectURL(url),60000)}

export function DocumentsPage({permissions}:{permissions:string[]}){
  const canManage=permissions.includes('documents.manage')
  const [items,setItems]=useState<CatalogItem[]>([]),[loading,setLoading]=useState(true),[saving,setSaving]=useState(false)
  const [query,setQuery]=useState(''),[category,setCategory]=useState(''),[source,setSource]=useState(''),[statusFilter,setStatusFilter]=useState('')
  const [error,setError]=useState(''),[success,setSuccess]=useState('')
  const [showCreate,setShowCreate]=useState(false),[form,setForm]=useState<UploadForm>(blankForm())
  const [linkOptions,setLinkOptions]=useState<LinkRecord[]>([]),[loadingLinks,setLoadingLinks]=useState(false)
  const [detail,setDetail]=useState<Detail|null>(null),[detailLoading,setDetailLoading]=useState(false)
  const [versionFile,setVersionFile]=useState<File|null>(null),[versionNotes,setVersionNotes]=useState('')

  const load=useCallback(async()=>{
    setLoading(true);setError('')
    try{
      const params=new URLSearchParams();if(query.trim())params.set('q',query.trim());if(category)params.set('category',category);if(source)params.set('source_kind',source);if(statusFilter)params.set('status',statusFilter)
      const suffix=params.toString()
      setItems(await apiRequest<CatalogItem[]>(`/documents${suffix?`?${suffix}`:''}`))
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os documentos.')}
    finally{setLoading(false)}
  },[query,category,source,statusFilter])
  useEffect(()=>{const timer=window.setTimeout(()=>void load(),query?250:0);return()=>window.clearTimeout(timer)},[load,query])

  const metrics=useMemo(()=>({total:items.length,system:items.filter(i=>i.source_kind==='system').length,managed:items.filter(i=>i.source_kind==='managed').length,archived:items.filter(i=>i.status==='archived').length}),[items])

  async function chooseEntity(type:EntityType){
    setForm(current=>({...current,entity_type:type,entity_id:''}));setLinkOptions([])
    if(!type)return
    setLoadingLinks(true)
    try{setLinkOptions(await apiRequest<LinkRecord[]>(entityPaths[type]))}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os registros para vínculo.')}
    finally{setLoadingLinks(false)}
  }
  function openCreate(){setForm(blankForm());setLinkOptions([]);setError('');setSuccess('');setShowCreate(true)}
  function closeCreate(){if(!saving)setShowCreate(false)}
  async function submitCreate(event:FormEvent){
    event.preventDefault();if(!form.file)return
    setSaving(true);setError('')
    const body=new FormData();body.append('title',form.title);body.append('category',form.category);if(form.entity_type&&form.entity_id){body.append('entity_type',form.entity_type);body.append('entity_id',form.entity_id)}if(form.notes.trim())body.append('notes',form.notes.trim());body.append('file',form.file)
    try{const created=await apiRequest<Detail>('/documents',{method:'POST',body});setShowCreate(false);setForm(blankForm());setSuccess(`${created.code} incluído com a versão v1.`);await load();setDetail(created)}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível incluir o documento.')}
    finally{setSaving(false)}
  }
  async function openItem(item:CatalogItem){
    setError('')
    if(item.source_kind==='system'){try{openBlob(await apiBlobRequest(item.download_path))}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível abrir o documento.')}return}
    if(!item.document_id)return
    setDetail(null);setDetailLoading(true)
    try{setDetail(await apiRequest<Detail>(`/documents/managed/${item.document_id}`));setVersionFile(null);setVersionNotes('')}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível abrir o documento.')}
    finally{setDetailLoading(false)}
  }
  async function download(path:string){if(!path)return;try{openBlob(await apiBlobRequest(path))}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível abrir o arquivo.')}}
  async function addVersion(event:FormEvent){
    event.preventDefault();if(!detail||!versionFile)return
    setSaving(true);setError('');const body=new FormData();body.append('file',versionFile);if(versionNotes.trim())body.append('notes',versionNotes.trim())
    try{const updated=await apiRequest<Detail>(`/documents/managed/${detail.id}/versions`,{method:'POST',body});setDetail(updated);setVersionFile(null);setVersionNotes('');setSuccess(`${updated.code} atualizado para v${updated.current_version}. A versão anterior foi preservada.`);await load()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível criar a nova versão.')}
    finally{setSaving(false)}
  }
  async function archive(){
    if(!detail)return;setSaving(true);setError('');const body=new FormData();body.append('reason','Arquivado pelo módulo Documentos.')
    try{const updated=await apiRequest<Detail>(`/documents/managed/${detail.id}/archive`,{method:'POST',body});setDetail(updated);setSuccess(`${updated.code} arquivado sem excluir o histórico.`);await load()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível arquivar o documento.')}
    finally{setSaving(false)}
  }

  return <section className="workspace documents-workspace">
    <div className="page-heading documents-heading"><div><span className="eyebrow">Central documental</span><h1>Documentos</h1><p>Contratos, laudos e anexos da operação em um catálogo único, com vínculo ao registro de origem e histórico de versões.</p></div>{canManage&&<button className="button primary" type="button" onClick={openCreate}><Plus size={15}/> Novo documento</button>}</div>
    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}
    <div className="dashboard-metrics documents-metrics"><article className="panel metric-card"><span>No catálogo</span><strong>{metrics.total}</strong><small>itens no filtro atual</small></article><article className="panel metric-card"><span>Automáticos</span><strong>{metrics.system}</strong><small>contratos e laudos</small></article><article className="panel metric-card"><span>Anexos versionados</span><strong>{metrics.managed}</strong><small>documentos incluídos</small></article><article className="panel metric-card"><span>Arquivados</span><strong>{metrics.archived}</strong><small>histórico preservado</small></article></div>
    <div className="panel documents-toolbar"><label className="documents-search"><Search size={15}/><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Buscar documento, arquivo ou registro vinculado..."/></label><select value={category} onChange={event=>setCategory(event.target.value)}><option value="">Todas as categorias</option>{Object.entries(categories).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select><select value={source} onChange={event=>setSource(event.target.value)}><option value="">Todas as origens</option><option value="system">Automáticos</option><option value="managed">Anexos</option></select><select value={statusFilter} onChange={event=>setStatusFilter(event.target.value)}><option value="">Todos os status</option><option value="active">Ativos</option><option value="archived">Arquivados</option></select><button className="icon-button" type="button" title="Atualizar" onClick={()=>void load()}><RefreshCw size={15}/></button></div>
    <article className="panel documents-table-panel">{loading?<div className="settings-loading">Carregando documentos...</div>:items.length===0?<div className="documents-empty"><FolderArchive size={30}/><strong>Nenhum documento encontrado.</strong><span>Inclua um anexo ou ajuste os filtros.</span></div>:<div className="documents-table-wrap"><table className="documents-table"><thead><tr><th>Documento</th><th>Categoria</th><th>Vinculado a</th><th>Origem</th><th>Versão</th><th>Atualizado</th><th></th></tr></thead><tbody>{items.map(item=><tr key={item.key}><td><div className="documents-name"><span className="documents-file-icon">{item.content_type==='application/pdf'?<FileText size={16}/>:<FileIcon size={16}/>}</span><div><strong>{item.title}</strong><small>{item.filename} · {bytes(item.size_bytes)}</small></div></div></td><td><span className="documents-category">{categories[item.category]||item.category}</span></td><td>{item.entity_label||<span className="documents-muted">Sem vínculo</span>}</td><td><span className={`documents-source ${item.source_kind}`}>{item.source_kind==='system'?'Automático':'Anexo'}</span></td><td><strong>v{item.version}</strong>{item.version_count>1&&<small className="documents-version-count">{item.version_count} versões</small>}</td><td>{when(item.updated_at)}</td><td><button className="icon-button" type="button" title={item.source_kind==='system'?'Abrir arquivo':'Ver detalhes'} onClick={()=>void openItem(item)}>{item.source_kind==='system'?<Download size={15}/>:<FileClock size={15}/>}</button></td></tr>)}</tbody></table></div>}</article>

    {showCreate&&<div className="documents-modal-backdrop" role="presentation" onMouseDown={event=>{if(event.currentTarget===event.target)closeCreate()}}><form className="documents-modal" onSubmit={submitCreate}><div className="documents-modal-head"><div><span className="eyebrow">Novo documento</span><h2>Incluir arquivo</h2><p>O primeiro envio será registrado como v1 e nunca será sobrescrito por versões futuras.</p></div><button className="icon-button" type="button" onClick={closeCreate}><X size={17}/></button></div><div className="documents-form-grid"><label className="span-2"><span>Título</span><input required maxLength={220} value={form.title} onChange={event=>setForm(current=>({...current,title:event.target.value}))} placeholder="Ex.: Matrícula atualizada do imóvel"/></label><label><span>Categoria</span><select value={form.category} onChange={event=>setForm(current=>({...current,category:event.target.value}))}>{Object.entries(categories).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label><span>Vincular a</span><select value={form.entity_type} onChange={event=>void chooseEntity(event.target.value as EntityType)}><option value="">Sem vínculo</option>{Object.entries(entityLabels).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></label>{form.entity_type&&<label className="span-2"><span>Registro</span><select required value={form.entity_id} onChange={event=>setForm(current=>({...current,entity_id:event.target.value}))}><option value="">{loadingLinks?'Carregando...':'Selecione...'}</option>{linkOptions.map(row=><option key={row.id} value={row.id}>{recordLabel(form.entity_type,row)}</option>)}</select></label>}<label className="span-2"><span>Observações</span><textarea rows={3} value={form.notes} onChange={event=>setForm(current=>({...current,notes:event.target.value}))} placeholder="Contexto ou observação opcional..."/></label><label className="span-2 documents-file-field"><span>Arquivo · até 20 MB</span><input required type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,.txt,.doc,.docx,.xls,.xlsx" onChange={event=>setForm(current=>({...current,file:event.target.files?.[0]||null}))}/>{form.file&&<small>{form.file.name} · {bytes(form.file.size)}</small>}</label></div><div className="documents-modal-actions"><button className="button secondary" type="button" onClick={closeCreate}>Cancelar</button><button className="button primary" disabled={saving||!form.file||!form.title.trim()||(!!form.entity_type&&!form.entity_id)}><Upload size={14}/>{saving?' Salvando...':' Incluir documento'}</button></div></form></div>}

    {(detail||detailLoading)&&<div className="documents-modal-backdrop" role="presentation" onMouseDown={event=>{if(event.currentTarget===event.target&&!saving)setDetail(null)}}>{detailLoading&&!detail?<div className="documents-modal documents-detail"><div className="settings-loading">Carregando documento...</div></div>:detail&&<div className="documents-modal documents-detail"><div className="documents-modal-head"><div><span className="eyebrow">{detail.code}</span><h2>{detail.title}</h2><p>{detail.entity_label||'Documento sem vínculo operacional'} · {categories[detail.category]||detail.category}</p></div><button className="icon-button" type="button" onClick={()=>setDetail(null)}><X size={17}/></button></div><div className="documents-detail-summary"><div><span>Status</span><strong>{detail.status==='archived'?'Arquivado':'Ativo'}</strong></div><div><span>Versão atual</span><strong>v{detail.current_version}</strong></div><div><span>Versões</span><strong>{detail.versions.length}</strong></div><div><span>Atualizado</span><strong>{when(detail.updated_at)}</strong></div></div>{detail.notes&&<div className="documents-notes">{detail.notes}</div>}<div className="documents-history-title"><History size={15}/><strong>Histórico de versões</strong></div><div className="documents-version-list">{[...detail.versions].reverse().map(version=><div className="documents-version" key={version.version_number}><div className="documents-version-badge">v{version.version_number}</div><div><strong>{version.original_filename}</strong><span>{when(version.created_at)} · {bytes(version.size_bytes)}</span>{version.notes&&<small>{version.notes}</small>}</div><button className="icon-button" type="button" title="Abrir versão" onClick={()=>void download(version.download_path)}><Download size={15}/></button></div>)}</div>{canManage&&detail.status==='active'&&<form className="documents-new-version" onSubmit={addVersion}><div><FilePlus2 size={17}/><strong>Nova versão</strong><span>A versão atual continuará disponível no histórico.</span></div><input required type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,.txt,.doc,.docx,.xls,.xlsx" onChange={event=>setVersionFile(event.target.files?.[0]||null)}/><input value={versionNotes} onChange={event=>setVersionNotes(event.target.value)} placeholder="Motivo/observação da versão (opcional)"/><button className="button primary compact" disabled={saving||!versionFile}><Upload size={13}/> Criar v{detail.current_version+1}</button></form>}<div className="documents-modal-actions"><button className="button secondary" type="button" onClick={()=>void download(detail.versions.find(version=>version.version_number===detail.current_version)?.download_path||'')}><Download size={14}/> Abrir versão atual</button>{canManage&&detail.status==='active'&&<button className="button secondary documents-archive-button" type="button" disabled={saving} onClick={()=>void archive()}><Archive size={14}/> Arquivar</button>}</div></div>}</div>}
  </section>
}
