import { Archive, Download, File as FileIcon, FileClock, FilePlus2, FileText, History, Plus, RefreshCw, Search, Upload, X } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import './entity-documents.css'

export type DocumentEntityType = 'person'|'property'|'administration_contract'|'lease_contract'|'inspection'|'maintenance'
export type DocumentEntityRef = { type: DocumentEntityType; id: string }

type CatalogItem = {
  key:string;source_kind:'managed'|'system';document_id:string|null;title:string;category:string;status:string;
  entity_type:DocumentEntityType|null;entity_id:string|null;entity_label:string|null;filename:string;content_type:string;size_bytes:number|null;
  hash_sha256:string|null;version:number;version_count:number;created_at:string;updated_at:string;download_path:string;can_version:boolean
}
type Version = {version_number:number;original_filename:string;content_type:string;size_bytes:number;hash_sha256:string;notes:string|null;created_at:string;download_path:string}
type Detail = {id:string;code:string;title:string;category:string;status:string;entity_type:DocumentEntityType|null;entity_id:string|null;entity_label:string|null;current_version:number;notes:string|null;created_at:string;updated_at:string;versions:Version[]}
type UploadForm = {title:string;category:string;notes:string;file:File|null}

type Props = {
  entityType: DocumentEntityType
  entityId: string
  entityLabel: string
  permissions: string[]
  relatedEntities?: DocumentEntityRef[]
  compact?: boolean
}

const categories:Record<string,string>={general:'Geral',identity:'Identificação',property:'Imóvel',contract:'Contrato',inspection:'Vistoria',maintenance:'Manutenção',finance:'Financeiro',legal:'Jurídico',other:'Outros'}
const blankForm=():UploadForm=>({title:'',category:'general',notes:'',file:null})
const bytes=(value:number|null)=>value==null?'—':value<1024?`${value} B`:value<1024*1024?`${(value/1024).toFixed(1)} KB`:`${(value/1024/1024).toFixed(1)} MB`
const when=(value:string)=>new Date(value).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'})
function openBlob(blob:Blob){const url=URL.createObjectURL(blob);window.open(url,'_blank','noopener,noreferrer');window.setTimeout(()=>URL.revokeObjectURL(url),60000)}

export function EntityDocumentsPanel({entityType,entityId,entityLabel,permissions,relatedEntities=[],compact=false}:Props){
  const canView=permissions.includes('documents.view'),canManage=permissions.includes('documents.manage')
  const [items,setItems]=useState<CatalogItem[]>([]),[loading,setLoading]=useState(false),[saving,setSaving]=useState(false)
  const [query,setQuery]=useState(''),[error,setError]=useState(''),[success,setSuccess]=useState('')
  const [showCreate,setShowCreate]=useState(false),[form,setForm]=useState<UploadForm>(blankForm())
  const [detail,setDetail]=useState<Detail|null>(null),[detailLoading,setDetailLoading]=useState(false)
  const [versionFile,setVersionFile]=useState<File|null>(null),[versionNotes,setVersionNotes]=useState('')

  const relatedSignature=useMemo(()=>relatedEntities.map(ref=>`${ref.type}:${ref.id}`).sort().join('|'),[relatedEntities])
  const refs=useMemo(()=>{
    const map=new Map<string,DocumentEntityRef>()
    ;[{type:entityType,id:entityId},...relatedEntities].forEach(ref=>map.set(`${ref.type}:${ref.id}`,ref))
    return [...map.values()]
  },[entityType,entityId,relatedSignature])
  const refKeys=useMemo(()=>new Set(refs.map(ref=>`${ref.type}:${ref.id}`)),[refs])
  const entityTypes=useMemo(()=>[...new Set(refs.map(ref=>ref.type))],[refs])

  const load=useCallback(async()=>{
    if(!canView)return
    setLoading(true);setError('')
    try{
      const groups=await Promise.all(entityTypes.map(type=>apiRequest<CatalogItem[]>(`/documents?entity_type=${encodeURIComponent(type)}`)))
      const deduped=new Map<string,CatalogItem>()
      groups.flat().forEach(item=>{if(item.entity_type&&item.entity_id&&refKeys.has(`${item.entity_type}:${item.entity_id}`))deduped.set(item.key,item)})
      setItems([...deduped.values()].sort((a,b)=>new Date(b.updated_at||b.created_at).getTime()-new Date(a.updated_at||a.created_at).getTime()))
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os documentos vinculados.')}
    finally{setLoading(false)}
  },[canView,entityTypes,refKeys])
  useEffect(()=>{void load()},[load])

  const filtered=useMemo(()=>{const term=query.trim().toLowerCase();if(!term)return items;return items.filter(item=>`${item.title} ${item.filename} ${item.entity_label||''} ${categories[item.category]||item.category}`.toLowerCase().includes(term))},[items,query])

  function openCreate(){setForm(blankForm());setError('');setSuccess('');setShowCreate(true)}
  function closeCreate(){if(!saving)setShowCreate(false)}
  async function submitCreate(event:FormEvent){
    event.preventDefault();if(!form.file)return
    setSaving(true);setError('')
    const body=new FormData();body.append('title',form.title);body.append('category',form.category);body.append('entity_type',entityType);body.append('entity_id',entityId);if(form.notes.trim())body.append('notes',form.notes.trim());body.append('file',form.file)
    try{const created=await apiRequest<Detail>('/documents',{method:'POST',body});setShowCreate(false);setForm(blankForm());setSuccess(`${created.code} incluído em ${entityLabel}.`);await load();setDetail(created)}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível incluir o documento.')}
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
  async function download(path:string){try{openBlob(await apiBlobRequest(path))}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível abrir o arquivo.')}}
  async function addVersion(event:FormEvent){
    event.preventDefault();if(!detail||!versionFile)return
    setSaving(true);setError('');const body=new FormData();body.append('file',versionFile);if(versionNotes.trim())body.append('notes',versionNotes.trim())
    try{const updated=await apiRequest<Detail>(`/documents/managed/${detail.id}/versions`,{method:'POST',body});setDetail(updated);setVersionFile(null);setVersionNotes('');setSuccess(`${updated.code} atualizado para v${updated.current_version}.`);await load()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível criar a nova versão.')}
    finally{setSaving(false)}
  }
  async function archive(){
    if(!detail)return
    setSaving(true);setError('');const body=new FormData();body.append('reason',`Arquivado a partir de ${entityLabel}.`)
    try{const updated=await apiRequest<Detail>(`/documents/managed/${detail.id}/archive`,{method:'POST',body});setDetail(updated);setSuccess(`${updated.code} arquivado com histórico preservado.`);await load()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível arquivar o documento.')}
    finally{setSaving(false)}
  }

  if(!canView)return <article className={`panel entity-documents-panel ${compact?'compact':''}`}><div className="entity-documents-empty"><FileText size={24}/><strong>Documentos</strong><span>Seu perfil não possui permissão para visualizar documentos.</span></div></article>

  return <article className={`panel entity-documents-panel ${compact?'compact':''}`}>
    <div className="entity-documents-head"><div><span className="eyebrow">Documentos</span><h2>Arquivos vinculados</h2><p>Documentos de {entityLabel} e registros operacionais relacionados, sem duplicar arquivos na Central de Documentos.</p></div>{canManage&&<button className="button primary compact" type="button" onClick={openCreate}><Plus size={14}/> Adicionar documento</button>}</div>
    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}
    <div className="entity-documents-toolbar"><label><Search size={14}/><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Buscar nesta pasta..."/></label><button className="icon-button" type="button" title="Atualizar" onClick={()=>void load()}><RefreshCw size={14}/></button></div>
    {loading?<div className="settings-loading">Carregando documentos...</div>:filtered.length===0?<div className="entity-documents-empty"><FileText size={24}/><strong>Nenhum documento vinculado.</strong><span>{canManage?'Use “Adicionar documento” para incluir o primeiro arquivo.':'Ainda não há arquivos para este cadastro.'}</span></div>:<div className="entity-documents-list">{filtered.map(item=><button className="entity-document-row" type="button" key={item.key} onClick={()=>void openItem(item)}><span className="entity-document-icon">{item.content_type==='application/pdf'?<FileText size={17}/>:<FileIcon size={17}/>}</span><span className="entity-document-main"><strong>{item.title}</strong><small>{item.filename} · {bytes(item.size_bytes)}</small></span><span className="entity-document-link"><strong>{item.entity_label||entityLabel}</strong><small>{item.source_kind==='system'?'Automático':'Anexo'} · {categories[item.category]||item.category}</small></span><span className="entity-document-version"><strong>v{item.version}</strong><small>{item.version_count>1?`${item.version_count} versões`:when(item.updated_at)}</small></span><Download size={15}/></button>)}</div>}

    {showCreate&&<div className="entity-documents-backdrop" role="presentation" onMouseDown={event=>{if(event.currentTarget===event.target)closeCreate()}}><form className="entity-documents-modal" onSubmit={submitCreate}><div className="entity-documents-modal-head"><div><span className="eyebrow">{entityLabel}</span><h2>Adicionar documento</h2><p>O vínculo com este cadastro será feito automaticamente.</p></div><button className="icon-button" type="button" onClick={closeCreate}><X size={17}/></button></div><div className="entity-documents-form"><label className="wide"><span>Título</span><input required maxLength={220} value={form.title} onChange={event=>setForm(current=>({...current,title:event.target.value}))} placeholder="Ex.: Matrícula atualizada"/></label><label><span>Categoria</span><select value={form.category} onChange={event=>setForm(current=>({...current,category:event.target.value}))}>{Object.entries(categories).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label className="wide"><span>Observações</span><textarea rows={3} value={form.notes} onChange={event=>setForm(current=>({...current,notes:event.target.value}))}/></label><label className="wide entity-documents-file"><span>Arquivo · até 20 MB</span><input required type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,.txt,.doc,.docx,.xls,.xlsx" onChange={event=>setForm(current=>({...current,file:event.target.files?.[0]||null}))}/>{form.file&&<small>{form.file.name} · {bytes(form.file.size)}</small>}</label></div><div className="entity-documents-actions"><button className="button secondary" type="button" onClick={closeCreate}>Cancelar</button><button className="button primary" disabled={saving||!form.file||!form.title.trim()}><Upload size={14}/>{saving?' Salvando...':' Incluir documento'}</button></div></form></div>}

    {(detail||detailLoading)&&<div className="entity-documents-backdrop" role="presentation" onMouseDown={event=>{if(event.currentTarget===event.target&&!saving)setDetail(null)}}>{detailLoading&&!detail?<div className="entity-documents-modal"><div className="settings-loading">Carregando documento...</div></div>:detail&&<div className="entity-documents-modal entity-documents-detail"><div className="entity-documents-modal-head"><div><span className="eyebrow">{detail.code}</span><h2>{detail.title}</h2><p>{detail.entity_label||entityLabel} · {categories[detail.category]||detail.category}</p></div><button className="icon-button" type="button" onClick={()=>setDetail(null)}><X size={17}/></button></div><div className="entity-documents-summary"><div><span>Status</span><strong>{detail.status==='archived'?'Arquivado':'Ativo'}</strong></div><div><span>Versão atual</span><strong>v{detail.current_version}</strong></div><div><span>Versões</span><strong>{detail.versions.length}</strong></div></div><div className="entity-documents-history"><div className="entity-documents-section-title"><History size={15}/><strong>Histórico de versões</strong></div>{[...detail.versions].reverse().map(version=><div className="entity-document-version-row" key={version.version_number}><div><strong>v{version.version_number} · {version.original_filename}</strong><span>{when(version.created_at)} · {bytes(version.size_bytes)}{version.notes?` · ${version.notes}`:''}</span></div><button className="button secondary compact" type="button" onClick={()=>void download(version.download_path)}><Download size={13}/> Abrir</button></div>)}</div>{canManage&&detail.status==='active'&&<form className="entity-documents-new-version" onSubmit={addVersion}><div className="entity-documents-section-title"><FilePlus2 size={15}/><strong>Nova versão</strong></div><input required type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,.txt,.doc,.docx,.xls,.xlsx" onChange={event=>setVersionFile(event.target.files?.[0]||null)}/><input value={versionNotes} onChange={event=>setVersionNotes(event.target.value)} placeholder="Motivo ou observação da nova versão"/><button className="button primary compact" disabled={saving||!versionFile}><Upload size={13}/> Criar versão</button></form>}<div className="entity-documents-actions"><button className="button secondary" type="button" onClick={()=>void download(detail.versions.find(version=>version.version_number===detail.current_version)?.download_path||detail.versions.at(-1)?.download_path||'')}><Download size={14}/> Abrir atual</button>{canManage&&detail.status==='active'&&<button className="button ghost-danger" type="button" disabled={saving} onClick={()=>void archive()}><Archive size={14}/> Arquivar</button>}</div></div>}</div>}
  </article>
}
