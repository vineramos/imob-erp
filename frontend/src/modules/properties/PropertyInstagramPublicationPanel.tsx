import { ArrowDown, ArrowUp, Check, ChevronLeft, ChevronRight, CircleAlert, Instagram, Save, Send, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import './property-instagram-publication.css'

type Photo = {
  id:string
  filename:string
  caption:string|null
  position:number
  is_cover:boolean
  content_url:string
}
type InstagramPublication = {
  property_id:string
  status:'draft'|'ready'|'published'|'inactive'|'failed'
  format:'carousel'|'single'|'story'|'reel'
  caption:string
  photo_ids:string[]
  photos:Photo[]
  media_id:string|null
  permalink:string|null
  published_at:string|null
  inactivated_at:string|null
  inactivation_reason:string|null
  external_removal_pending:boolean
  property_active:boolean
  instagram_connected:boolean
}
type Props={propertyId:string;permissions:string[]}

function PhotoPreview({photo,onOpen,className=''}:{photo:Photo;onOpen?:(photo:Photo)=>void;className?:string}){
  const [src,setSrc]=useState('')
  useEffect(()=>{
    let active=true,objectUrl=''
    void apiBlobRequest(photo.content_url).then(blob=>{
      if(!active)return
      objectUrl=URL.createObjectURL(blob)
      setSrc(objectUrl)
    }).catch(()=>{if(active)setSrc('')})
    return()=>{active=false;if(objectUrl)URL.revokeObjectURL(objectUrl)}
  },[photo.content_url])
  if(!src)return <div className="instagram-photo-placeholder">Foto</div>
  if(!onOpen)return <img className={className} src={src} alt={photo.caption||photo.filename}/>
  return <button className={'instagram-photo-open '+className} type="button" onClick={()=>onOpen(photo)} title="Ampliar foto"><img src={src} alt={photo.caption||photo.filename}/></button>
}

const statusLabel:Record<InstagramPublication['status'],string>={
  draft:'Rascunho',ready:'Pronto para publicar',published:'Publicado',inactive:'Inativo',failed:'Falha',
}

export function PropertyInstagramPublicationPanel({propertyId,permissions}:Props){
  const canEdit=permissions.includes('properties.edit')
  const canPublish=permissions.includes('properties.publish')
  const [data,setData]=useState<InstagramPublication|null>(null)
  const [caption,setCaption]=useState('')
  const [photoIds,setPhotoIds]=useState<string[]>([])
  const [format,setFormat]=useState<InstagramPublication['format']>('carousel')
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [openPhoto,setOpenPhoto]=useState<Photo|null>(null)
  const [previewIndex,setPreviewIndex]=useState(0)

  useEffect(()=>{
    let active=true
    setLoading(true);setError('')
    void apiRequest<InstagramPublication>(`/properties/${propertyId}/instagram-publication`)
      .then(result=>{if(!active)return;setData(result);setCaption(result.caption);setPhotoIds(result.photo_ids);setFormat(result.format)})
      .catch(cause=>{if(active)setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar a publicação do Instagram.')})
      .finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[propertyId])

  useEffect(()=>{
    if(!openPhoto)return
    const previous=document.body.style.overflow
    document.body.style.overflow='hidden'
    const close=(event:KeyboardEvent)=>{if(event.key==='Escape')setOpenPhoto(null)}
    window.addEventListener('keydown',close)
    return()=>{document.body.style.overflow=previous;window.removeEventListener('keydown',close)}
  },[openPhoto])

  const byId=useMemo(()=>new Map((data?.photos??[]).map(photo=>[photo.id,photo])),[data?.photos])
  const selected=photoIds.map(id=>byId.get(id)).filter((item):item is Photo=>Boolean(item))
  const available=(data?.photos??[]).filter(photo=>!photoIds.includes(photo.id))
  const previewPhoto=selected[previewIndex]??selected[0]??null
  const dirty=Boolean(data)&&(caption!==data!.caption||format!==data!.format||photoIds.join('|')!==data!.photo_ids.join('|'))

  useEffect(()=>{
    setPreviewIndex(current=>selected.length===0?0:Math.min(current,selected.length-1))
  },[selected.length])

  function rotatePreview(direction:-1|1){
    if(selected.length<2)return
    setPreviewIndex(current=>(current+direction+selected.length)%selected.length)
  }

  function move(index:number,direction:-1|1){
    setPhotoIds(current=>{
      const target=index+direction
      if(target<0||target>=current.length)return current
      const next=[...current];[next[index],next[target]]=[next[target],next[index]]
      return next
    })
  }
  function add(photoId:string){
    if(photoIds.length>=10){setError('O carrossel aceita no máximo 10 imagens.');return}
    setError('');setPhotoIds(current=>[...current,photoId])
  }
  function remove(photoId:string){setPhotoIds(current=>current.filter(id=>id!==photoId))}

  async function save(){
    if(!canEdit||!data)return
    setSaving(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<InstagramPublication>(`/properties/${propertyId}/instagram-publication`,{
        method:'PUT',
        body:JSON.stringify({format,caption,photo_ids:photoIds}),
      })
      setData(result);setCaption(result.caption);setPhotoIds(result.photo_ids);setFormat(result.format)
      setSuccess('Rascunho do Instagram salvo.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar o rascunho do Instagram.')}
    finally{setSaving(false)}
  }

  if(loading)return <section className="property-surface property-instagram-panel"><div className="instagram-loading">Carregando publicação do Instagram...</div></section>
  if(!data)return <section className="property-surface property-instagram-panel"><div className="form-alert danger-alert">{error||'Publicação indisponível.'}</div></section>

  const inactive=!data.property_active||data.status==='inactive'

  return <section className="property-instagram-panel">
    {openPhoto&&<div className="instagram-photo-modal-backdrop" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget)setOpenPhoto(null)}}>
      <section className="instagram-photo-modal" role="dialog" aria-modal="true" aria-label="Visualização ampliada da foto">
        <header><div><span>FOTO DO IMÓVEL</span><strong>{openPhoto.caption||openPhoto.filename}</strong></div><button type="button" onClick={()=>setOpenPhoto(null)} aria-label="Fechar"><X size={18}/></button></header>
        <div className="instagram-photo-modal-image"><PhotoPreview photo={openPhoto}/></div>
        <footer><span>{openPhoto.is_cover?'Capa da galeria':`Foto ${openPhoto.position+1}`}</span><small>Pressione Esc ou clique fora para fechar</small></footer>
      </section>
    </div>}
    <header className="instagram-panel-header">
      <div className="instagram-panel-title"><span className="instagram-mark"><Instagram size={20}/></span><div><span>CONTEÚDO SOCIAL</span><h2>Instagram do imóvel</h2><p>Monte o carrossel e revise a legenda antes do envio para a Meta.</p></div></div>
      <div className="instagram-panel-status"><i className={'status-badge '+(inactive?'neutral':data.status==='ready'?'success':'warning')}>{statusLabel[data.status]}</i>{dirty&&<small>Alterações não salvas</small>}</div>
    </header>

    {error&&<div className="form-alert danger-alert">{error}</div>}
    {success&&<div className="form-alert success-alert">{success}</div>}
    {inactive&&<div className="instagram-inactive-alert"><CircleAlert size={17}/><div><strong>Publicação inativada junto com o imóvel</strong><span>{data.inactivation_reason||'Este imóvel não está mais disponível para anúncio.'}{data.external_removal_pending?' A retirada do conteúdo já publicado na Meta precisa ser concluída quando a conexão permitir essa ação.':''}</span></div></div>}

    <div className="instagram-editor-layout">
      <div className="instagram-editor-column">
        <section className="property-surface instagram-editor-section">
          <div className="instagram-section-heading"><div><span>CARROSSEL</span><h3>Sequência das fotos</h3></div><b>{photoIds.length}/10</b></div>
          <p className="instagram-help">A primeira imagem será a capa do post. A ordem abaixo é independente da galeria principal do imóvel.</p>
          {selected.length?<div className="instagram-selected-list">{selected.map((photo,index)=><article className="instagram-selected-photo" key={photo.id}>
            <div className="instagram-selected-thumb"><PhotoPreview photo={photo} onOpen={setOpenPhoto}/><span>{index+1}</span></div>
            <div className="instagram-selected-copy"><strong>{index===0?'Capa do carrossel':`Imagem ${index+1}`}</strong><small>{photo.caption||photo.filename}</small></div>
            <div className="instagram-photo-actions"><button type="button" disabled={!canEdit||index===0||inactive} onClick={()=>move(index,-1)} title="Mover para cima"><ArrowUp size={14}/></button><button type="button" disabled={!canEdit||index===selected.length-1||inactive} onClick={()=>move(index,1)} title="Mover para baixo"><ArrowDown size={14}/></button><button type="button" disabled={!canEdit||inactive} onClick={()=>remove(photo.id)} title="Remover do carrossel"><X size={14}/></button></div>
          </article>)}</div>:<div className="instagram-empty">Selecione fotos da galeria para montar o carrossel.</div>}

          {available.length>0&&<div className="instagram-available"><strong>Adicionar da galeria</strong><div>{available.map(photo=><button type="button" disabled={!canEdit||inactive||photoIds.length>=10} onClick={()=>add(photo.id)} key={photo.id}><span>{photo.is_cover?'Capa da galeria':'Foto '+(photo.position+1)}</span><small>{photo.caption||photo.filename}</small><Check size={13}/></button>)}</div></div>}
        </section>

        <section className="property-surface instagram-editor-section">
          <div className="instagram-section-heading"><div><span>TEXTO</span><h3>Legenda do post</h3></div><b>{caption.length}/2200</b></div>
          <textarea disabled={!canEdit||inactive} rows={12} maxLength={2200} value={caption} onChange={event=>setCaption(event.target.value)} placeholder="Escreva a legenda do imóvel..."/>
          <div className="instagram-format-row"><label><span>Formato</span><select disabled={!canEdit||inactive} value={format} onChange={event=>setFormat(event.target.value as InstagramPublication['format'])}><option value="carousel">Carrossel</option><option value="single">Foto única</option><option value="story">Story</option><option value="reel">Reel</option></select></label><small>Carrossel é o padrão recomendado para imóveis. Story e Reel serão habilitados no envio conforme a conexão Meta.</small></div>
        </section>
      </div>

      <aside className="instagram-preview-column">
        <section className="instagram-phone-preview">
          <div className="instagram-preview-top"><span className="instagram-preview-avatar"><Instagram size={15}/></span><strong>Prévia da publicação</strong><span>•••</span></div>
          <div className="instagram-preview-media">{previewPhoto?<PhotoPreview photo={previewPhoto} onOpen={setOpenPhoto} className="instagram-preview-open"/>:<div className="instagram-preview-empty">Selecione a foto de capa</div>}{selected.length>1&&<><button className="instagram-preview-arrow previous" type="button" onClick={()=>rotatePreview(-1)} aria-label="Foto anterior"><ChevronLeft size={22}/></button><button className="instagram-preview-arrow next" type="button" onClick={()=>rotatePreview(1)} aria-label="Próxima foto"><ChevronRight size={22}/></button><span className="instagram-preview-count">{previewIndex+1}/{selected.length}</span></>}</div>
          <div className="instagram-preview-actions">♡　◯　⌁</div>
          <div className="instagram-preview-caption"><strong>imobiliária</strong> <span>{caption||'A legenda aparecerá aqui.'}</span></div>
        </section>

        <section className="property-surface instagram-publish-card">
          <div><span>INTEGRAÇÃO META</span><h3>{data.instagram_connected?'Conta conectada':'Instagram ainda não conectado'}</h3><p>{data.instagram_connected?'O conteúdo pode ser enviado para publicação.':'O editor já está pronto. A publicação será liberada após conectarmos a conta profissional à Meta API.'}</p></div>
          <button className="button secondary" type="button" disabled={!canEdit||saving||inactive||!dirty} onClick={()=>void save()}><Save size={14}/>{saving?'Salvando...':'Salvar rascunho'}</button>
          <button className="button primary" type="button" disabled={!canPublish||inactive||!data.instagram_connected||data.status!=='ready'} title={!data.instagram_connected?'Conecte a conta do Instagram primeiro.':''}><Send size={14}/>Publicar no Instagram</button>
        </section>
      </aside>
    </div>
  </section>
}
