import { ArrowDown, ArrowUp, Check, ChevronLeft, ChevronRight, CircleAlert, Clock3, ExternalLink, History, Instagram, Save, Send, X } from 'lucide-react'
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
type InstagramPublicationHistoryItem = {
  media_id:string
  permalink:string|null
  published_at:string
  format:'carousel'|'single'|'story'|'reel'
  photo_count:number
}
type InstagramPublication = {
  property_id:string
  status:'draft'|'ready'|'publishing'|'published'|'inactive'|'failed'
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
  last_error:string|null
  history:InstagramPublicationHistoryItem[]
  story_status:'draft'|'ready'|'publishing'|'published'|'failed'
  story_photo_id:string|null
  story_media_id:string|null
  story_published_at:string|null
  story_last_error:string|null
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
  draft:'Rascunho',ready:'Pronto para publicar',publishing:'Publicando',published:'Publicado',inactive:'Inativo',failed:'Falha',
}
const storyStatusLabel:Record<InstagramPublication['story_status'],string>={
  draft:'Rascunho',ready:'Pronto',publishing:'Publicando',published:'Publicado',failed:'Falha',
}
const formatLabel=(value:InstagramPublicationHistoryItem['format'])=>({
  carousel:'Carrossel',single:'Foto única',story:'Story',reel:'Reel',
}[value])

export function PropertyInstagramPublicationPanel({propertyId,permissions}:Props){
  const canEdit=permissions.includes('properties.edit')
  const canPublish=permissions.includes('properties.publish')
  const [data,setData]=useState<InstagramPublication|null>(null)
  const [caption,setCaption]=useState('')
  const [photoIds,setPhotoIds]=useState<string[]>([])
  const [format,setFormat]=useState<InstagramPublication['format']>('carousel')
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState(false)
  const [publishing,setPublishing]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [openPhoto,setOpenPhoto]=useState<Photo|null>(null)
  const [previewIndex,setPreviewIndex]=useState(0)
  const [storyPhotoId,setStoryPhotoId]=useState<string|null>(null)
  const [savingStory,setSavingStory]=useState(false)
  const [publishingStory,setPublishingStory]=useState(false)

  useEffect(()=>{
    let active=true
    setLoading(true);setError('')
    void apiRequest<InstagramPublication>(`/properties/${propertyId}/instagram-publication`)
      .then(result=>{if(!active)return;setData(result);setCaption(result.caption);setPhotoIds(result.photo_ids);setFormat(result.format);setStoryPhotoId(result.story_photo_id)})
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
  const storyPhoto=(data?.photos??[]).find(photo=>photo.id===storyPhotoId)??null
  const dirty=Boolean(data)&&(caption!==data!.caption||format!==data!.format||photoIds.join('|')!==data!.photo_ids.join('|'))
  const storyDirty=Boolean(data)&&storyPhotoId!==data!.story_photo_id

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

  async function publish(){
    if(!canPublish||!data||dirty)return
    setPublishing(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<InstagramPublication>(`/properties/${propertyId}/instagram-publication/publish`,{method:'POST'})
      setData(result);setCaption(result.caption);setPhotoIds(result.photo_ids);setFormat(result.format)
      setSuccess(result.permalink?'Publicado no Instagram com sucesso. O link da publicação foi registrado no imóvel.':'Publicado no Instagram com sucesso.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível publicar o imóvel no Instagram.')}
    finally{setPublishing(false)}
  }

  async function saveStory(){
    if(!canEdit||!data||!storyPhotoId)return
    setSavingStory(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<InstagramPublication>(`/properties/${propertyId}/instagram-publication/story`,{
        method:'PUT',
        body:JSON.stringify({photo_id:storyPhotoId}),
      })
      setData(result);setStoryPhotoId(result.story_photo_id)
      setSuccess('Story salvo. A imagem fica independente do carrossel do post.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar o Story.')}
    finally{setSavingStory(false)}
  }

  async function publishStory(){
    if(!canPublish||!data||storyDirty||!storyPhotoId)return
    setPublishingStory(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<InstagramPublication>(`/properties/${propertyId}/instagram-publication/story/publish`,{method:'POST'})
      setData(result);setStoryPhotoId(result.story_photo_id)
      setSuccess('Story publicado no Instagram com sucesso.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível publicar o Story no Instagram.')}
    finally{setPublishingStory(false)}
  }

  if(loading)return <section className="property-surface property-instagram-panel"><div className="instagram-loading">Carregando publicação do Instagram...</div></section>
  if(!data)return <section className="property-surface property-instagram-panel"><div className="form-alert danger-alert">{error||'Publicação indisponível.'}</div></section>

  const inactive=!data.property_active||data.status==='inactive'
  const lastPublished=data.history[0]??(data.media_id&&data.published_at?{media_id:data.media_id,permalink:data.permalink,published_at:data.published_at,format:data.format,photo_count:photoIds.length}:null)

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
    {data.status==='failed'&&data.last_error&&<div className="instagram-inactive-alert instagram-failure-alert"><CircleAlert size={17}/><div><strong>Falha na última tentativa de publicação</strong><span>{data.last_error}</span></div></div>}

    {lastPublished&&<section className="property-surface instagram-publication-summary">
      <div className="instagram-publication-summary-main">
        <span className="instagram-publication-summary-icon"><Check size={17}/></span>
        <div><span>ÚLTIMA PUBLICAÇÃO</span><h3>{formatLabel(lastPublished.format)} · {lastPublished.photo_count} {lastPublished.photo_count===1?'imagem':'imagens'}</h3><p><Clock3 size={13}/>{new Date(lastPublished.published_at).toLocaleString('pt-BR')}</p></div>
      </div>
      <div className="instagram-publication-summary-actions">
        <small>ID {lastPublished.media_id}</small>
        {lastPublished.permalink&&<a className="button secondary compact-button" href={lastPublished.permalink} target="_blank" rel="noreferrer"><ExternalLink size={14}/>Abrir no Instagram</a>}
      </div>
    </section>}

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

        <section className="property-surface instagram-editor-section instagram-caption-card">
          <div className="instagram-caption-heading">
            <div><span>LEGENDA</span><h3>Legenda do post</h3><p>Edite o texto exatamente como ele será enviado ao Instagram.</p></div>
            <b>{caption.length.toLocaleString('pt-BR')} / 2.200</b>
          </div>
          <div className="instagram-caption-editor instagram-caption-editor-standalone">
            <textarea disabled={!canEdit||inactive} rows={12} maxLength={2200} value={caption} onChange={event=>setCaption(event.target.value)} placeholder="Escreva a legenda do imóvel..."/>
          </div>
          <div className="instagram-caption-help"><span>Use quebras de linha para deixar a legenda mais fácil de ler.</span></div>

          <div className="instagram-format-block">
            <div className="instagram-format-heading"><div><span>FORMATO</span><h3>Como este imóvel será publicado</h3></div><small>Carrossel é o padrão recomendado para anúncios imobiliários.</small></div>
            <div className="instagram-format-options" role="radiogroup" aria-label="Formato da publicação">
              {([
                ['carousel','Carrossel','Até 10 fotos'],
                ['single','Foto única','Uma imagem'],
                ['story','Story','Disponível após conexão Meta'],
                ['reel','Reel','Disponível após conexão Meta'],
              ] as const).map(([value,label,description])=>{
                const pending=value==='story'||value==='reel'
                return <button key={value} type="button" role="radio" aria-checked={format===value} className={format===value?'active':''} disabled={!canEdit||inactive||pending} onClick={()=>setFormat(value)}>
                  <span>{label}</span><small>{description}</small>{format===value&&<Check size={14}/>}
                </button>
              })}
            </div>
            <p className="instagram-format-note">Story e Reel aparecem desde já para deixar o fluxo preparado, mas o envio será liberado quando a conta profissional estiver conectada e validada na Meta.</p>
          </div>

          <div className="instagram-editor-savebar">
            <div><strong>Conteúdo exclusivo do Instagram</strong><span>Esta legenda e a ordem das fotos ficam salvas separadamente da descrição do site.</span></div>
            <button className="button primary" type="button" disabled={!canEdit||saving||inactive||!dirty} onClick={()=>void save()}><Save size={15}/>{saving?'Salvando...':dirty?'Salvar alterações':'Salvo'}</button>
          </div>
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
          <button className="button primary" type="button" disabled={!canPublish||inactive||!data.instagram_connected||data.status!=='ready'||dirty||publishing} title={!data.instagram_connected?'Conecte a conta do Instagram primeiro.':dirty?'Salve as alterações antes de publicar.':''} onClick={()=>void publish()}><Send size={14}/>{publishing?'Publicando...':'Publicar no Instagram'}</button>
        </section>

        {data.history.length>0&&<section className="property-surface instagram-history-card">
          <div className="instagram-history-heading"><div><span>HISTÓRICO</span><h3>Publicações recentes</h3></div><History size={17}/></div>
          <div className="instagram-history-list">{data.history.slice(0,5).map((entry,index)=><article key={entry.media_id}>
            <span className="instagram-history-index">{index+1}</span>
            <div><strong>{formatLabel(entry.format)} · {entry.photo_count} {entry.photo_count===1?'imagem':'imagens'}</strong><small>{new Date(entry.published_at).toLocaleString('pt-BR')}</small></div>
            {entry.permalink?<a href={entry.permalink} target="_blank" rel="noreferrer" title="Abrir no Instagram"><ExternalLink size={14}/></a>:<span/>}
          </article>)}</div>
        </section>}
      </aside>
    </div>

    <section className="property-surface instagram-story-workspace">
      <div className="instagram-story-heading">
        <div><span>STORY</span><h3>Publicação vertical</h3><p>Escolha uma foto específica para o Story. Ela é salva separadamente do post e do carrossel.</p></div>
        <i className={'status-badge '+(data.story_status==='published'?'success':data.story_status==='failed'?'danger':data.story_status==='ready'?'success':'neutral')}>{storyStatusLabel[data.story_status]}</i>
      </div>

      {data.story_status==='failed'&&data.story_last_error&&<div className="instagram-inactive-alert instagram-failure-alert"><CircleAlert size={17}/><div><strong>Falha no Story</strong><span>{data.story_last_error}</span></div></div>}

      <div className="instagram-story-layout">
        <div className="instagram-story-picker">
          <div className="instagram-story-picker-head"><strong>Foto do Story</strong><span>Prévia em 9:16</span></div>
          <div className="instagram-story-photo-grid">
            {data.photos.map(photo=><button key={photo.id} type="button" className={storyPhotoId===photo.id?'active':''} disabled={!canEdit||inactive} onClick={()=>setStoryPhotoId(photo.id)}>
              <div><PhotoPreview photo={photo}/></div>
              <span>{photo.caption||photo.filename}</span>
              {storyPhotoId===photo.id&&<Check size={14}/>}
            </button>)}
          </div>
          <div className="instagram-story-note"><CircleAlert size={14}/><span>O Story é publicado como mídia vertical. O Instagram não recebe uma legenda de post para Stories por este fluxo; qualquer texto precisa fazer parte da própria arte/imagem.</span></div>
          <div className="instagram-story-actions">
            <button className="button secondary" type="button" disabled={!canEdit||inactive||!storyDirty||!storyPhotoId||savingStory} onClick={()=>void saveStory()}><Save size={14}/>{savingStory?'Salvando...':storyDirty?'Salvar Story':'Story salvo'}</button>
            <button className="button primary" type="button" disabled={!canPublish||inactive||!data.instagram_connected||data.story_status!=='ready'||storyDirty||publishingStory} onClick={()=>void publishStory()}><Send size={14}/>{publishingStory?'Publicando...':'Publicar Story'}</button>
          </div>
        </div>

        <div className="instagram-story-preview-shell">
          <div className="instagram-story-preview">
            {storyPhoto?<PhotoPreview photo={storyPhoto} onOpen={setOpenPhoto}/>:<div className="instagram-story-preview-empty"><Instagram size={24}/><span>Selecione uma foto</span></div>}
            <div className="instagram-story-top"><span className="instagram-preview-avatar"><Instagram size={14}/></span><strong>imob.erp</strong><span>agora</span><b>•••</b></div>
          </div>
          {data.story_published_at&&<div className="instagram-story-last-published"><Check size={14}/><span>Último Story: {new Date(data.story_published_at).toLocaleString('pt-BR')}</span></div>}
        </div>
      </div>
    </section>
  </section>
}
