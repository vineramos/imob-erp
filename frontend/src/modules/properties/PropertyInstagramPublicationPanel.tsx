import { ArrowDown, ArrowUp, Bath, BedDouble, Car, Check, ChevronLeft, ChevronRight, CircleAlert, Clock3, Copy, DollarSign, ExternalLink, History, Instagram, Move, Minus, Plus, RotateCcw, Ruler, Save, Send, X } from 'lucide-react'
import { type CSSProperties, type PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import { useTheme } from '../../theme/ThemeProvider'
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
  story_zoom:number
  story_offset_x:number
  story_offset_y:number
  story_description_media_id:string|null
  story_site_url:string|null
  story_text_scale:number
  story_qr_scale:number
  story_text_offset_x:number
  story_text_offset_y:number
  story_qr_offset_x:number
  story_qr_offset_y:number
  story_attributes_enabled:boolean
  story_attributes_layout:'horizontal'|'vertical'|'chips'|'bottom_bar'
  story_attributes_scale:number
  story_attributes_offset_x:number
  story_attributes_offset_y:number
  story_attributes:{key:string;value:string;label:string}[]
  story_published_at:string|null
  story_last_error:string|null
  property_active:boolean
  instagram_connected:boolean
}
type Props={propertyId:string;permissions:string[]}

function PhotoPreview({photo,onOpen,className='',imageStyle}:{photo:Photo;onOpen?:(photo:Photo)=>void;className?:string;imageStyle?:CSSProperties}){
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
  if(!onOpen)return <img className={className} style={imageStyle} src={src} alt={photo.caption||photo.filename}/>
  return <button className={'instagram-photo-open '+className} type="button" onClick={()=>onOpen(photo)} title="Ampliar foto"><img style={imageStyle} src={src} alt={photo.caption||photo.filename}/></button>
}

function StoryAttributeIcon({kind}:{kind:string}){
  if(kind==='bedrooms')return <BedDouble size={16}/>
  if(kind==='bathrooms')return <Bath size={16}/>
  if(kind==='area')return <Ruler size={16}/>
  if(kind==='parking')return <Car size={16}/>
  return <DollarSign size={16}/>
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
  const {theme}=useTheme()
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
  const [storyZoom,setStoryZoom]=useState(1)
  const [storyOffsetX,setStoryOffsetX]=useState(0)
  const [storyOffsetY,setStoryOffsetY]=useState(0)
  const [cropOpen,setCropOpen]=useState(false)
  const [detailsOpen,setDetailsOpen]=useState(false)
  const cropFrameRef=useRef<HTMLDivElement|null>(null)
  const attributesOverlayRef=useRef<HTMLDivElement|null>(null)
  const detailsFrameRef=useRef<HTMLDivElement|null>(null)
  const cropDragRef=useRef<{pointerId:number;clientX:number;clientY:number;offsetX:number;offsetY:number}|null>(null)
  const attributesDragRef=useRef<{pointerId:number;grabOffsetX:number;grabOffsetY:number}|null>(null)
  const detailsDragRef=useRef<{pointerId:number;target:'text'|'qr';clientX:number;clientY:number;offsetX:number;offsetY:number}|null>(null)
  const [storyTextScale,setStoryTextScale]=useState(1)
  const [storyQrScale,setStoryQrScale]=useState(1)
  const [storyTextOffsetX,setStoryTextOffsetX]=useState(0)
  const [storyTextOffsetY,setStoryTextOffsetY]=useState(0)
  const [storyQrOffsetX,setStoryQrOffsetX]=useState(0)
  const [storyQrOffsetY,setStoryQrOffsetY]=useState(0)
  const [storyAttributesEnabled,setStoryAttributesEnabled]=useState(true)
  const [storyAttributesLayout,setStoryAttributesLayout]=useState<InstagramPublication['story_attributes_layout']>('bottom_bar')
  const [storyAttributesScale,setStoryAttributesScale]=useState(1)
  const [storyAttributesOffsetX,setStoryAttributesOffsetX]=useState(0)
  const [storyAttributesOffsetY,setStoryAttributesOffsetY]=useState(0)
  const [savingStory,setSavingStory]=useState(false)
  const [publishingStory,setPublishingStory]=useState(false)

  useEffect(()=>{
    let active=true
    setLoading(true);setError('')
    void apiRequest<InstagramPublication>(`/properties/${propertyId}/instagram-publication`)
      .then(result=>{if(!active)return;setData(result);setCaption(result.caption);setPhotoIds(result.photo_ids);setFormat(result.format);setStoryPhotoId(result.story_photo_id);setStoryZoom(result.story_zoom||1);setStoryOffsetX(result.story_offset_x||0);setStoryOffsetY(result.story_offset_y||0);setStoryTextScale(result.story_text_scale||1);setStoryQrScale(result.story_qr_scale||1);setStoryTextOffsetX(result.story_text_offset_x||0);setStoryTextOffsetY(result.story_text_offset_y||0);setStoryQrOffsetX(result.story_qr_offset_x||0);setStoryQrOffsetY(result.story_qr_offset_y||0);setStoryAttributesEnabled(result.story_attributes_enabled??true);setStoryAttributesLayout(result.story_attributes_layout||'bottom_bar');setStoryAttributesScale(result.story_attributes_scale||1);setStoryAttributesOffsetX(result.story_attributes_offset_x||0);setStoryAttributesOffsetY(result.story_attributes_offset_y||0)})
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
  const storyDirty=Boolean(data)&&(storyPhotoId!==data!.story_photo_id||Math.abs(storyZoom-(data!.story_zoom||1))>0.001||Math.abs(storyOffsetX-(data!.story_offset_x||0))>0.001||Math.abs(storyOffsetY-(data!.story_offset_y||0))>0.001||Math.abs(storyTextScale-(data!.story_text_scale||1))>0.001||Math.abs(storyQrScale-(data!.story_qr_scale||1))>0.001||Math.abs(storyTextOffsetX-(data!.story_text_offset_x||0))>0.001||Math.abs(storyTextOffsetY-(data!.story_text_offset_y||0))>0.001||Math.abs(storyQrOffsetX-(data!.story_qr_offset_x||0))>0.001||Math.abs(storyQrOffsetY-(data!.story_qr_offset_y||0))>0.001||storyAttributesEnabled!==(data!.story_attributes_enabled??true)||storyAttributesLayout!==(data!.story_attributes_layout||'bottom_bar')||Math.abs(storyAttributesScale-(data!.story_attributes_scale||1))>0.001||Math.abs(storyAttributesOffsetX-(data!.story_attributes_offset_x||0))>0.001||Math.abs(storyAttributesOffsetY-(data!.story_attributes_offset_y||0))>0.001)

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

  function resetStoryCrop(){
    setStoryZoom(1);setStoryOffsetX(0);setStoryOffsetY(0)
  }

  function resetStoryAttributes(){
    setStoryAttributesEnabled(true);setStoryAttributesLayout('bottom_bar');setStoryAttributesScale(1);setStoryAttributesOffsetX(0);setStoryAttributesOffsetY(0)
  }

  function beginAttributesDrag(event:ReactPointerEvent<HTMLDivElement>){
    const overlay=attributesOverlayRef.current
    if(!cropFrameRef.current||!overlay)return
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    const rect=overlay.getBoundingClientRect()
    attributesDragRef.current={
      pointerId:event.pointerId,
      grabOffsetX:event.clientX-(rect.left+rect.width/2),
      grabOffsetY:event.clientY-(rect.top+rect.height/2),
    }
  }

  function moveAttributesDrag(event:ReactPointerEvent<HTMLDivElement>){
    const drag=attributesDragRef.current
    const frame=cropFrameRef.current
    const overlay=attributesOverlayRef.current
    if(!drag||drag.pointerId!==event.pointerId||!frame||!overlay)return
    event.stopPropagation()

    const frameRect=frame.getBoundingClientRect()
    const overlayRect=overlay.getBoundingClientRect()
    const margin=8
    const halfW=overlayRect.width/2
    const halfH=overlayRect.height/2

    const minCenterX=frameRect.left+margin+halfW
    const maxCenterX=frameRect.right-margin-halfW
    const minCenterY=frameRect.top+margin+halfH
    const maxCenterY=frameRect.bottom-margin-halfH

    const desiredCenterX=event.clientX-drag.grabOffsetX
    const desiredCenterY=event.clientY-drag.grabOffsetY
    const centerX=minCenterX>maxCenterX?frameRect.left+frameRect.width/2:Math.max(minCenterX,Math.min(maxCenterX,desiredCenterX))
    const centerY=minCenterY>maxCenterY?frameRect.top+frameRect.height/2:Math.max(minCenterY,Math.min(maxCenterY,desiredCenterY))

    const centerXPct=((centerX-frameRect.left)/frameRect.width)*100
    const centerYPct=((centerY-frameRect.top)/frameRect.height)*100
    const baseY=storyAttributesLayout==='vertical'?62:storyAttributesLayout==='chips'?74:storyAttributesLayout==='horizontal'?78:82

    const nextX=Math.max(-1,Math.min(1,(centerXPct-50)/50))
    const nextY=Math.max(-1,Math.min(1,(centerYPct-baseY)/50))
    setStoryAttributesOffsetX(Math.round(nextX*1000)/1000)
    setStoryAttributesOffsetY(Math.round(nextY*1000)/1000)
  }

  function endAttributesDrag(event:ReactPointerEvent<HTMLDivElement>){
    event.stopPropagation()
    if(attributesDragRef.current?.pointerId===event.pointerId)attributesDragRef.current=null
  }

  function resetDetailsLayout(){
    setStoryTextScale(1);setStoryQrScale(1);setStoryTextOffsetX(0);setStoryTextOffsetY(0);setStoryQrOffsetX(0);setStoryQrOffsetY(0)
  }

  function beginDetailsDrag(target:'text'|'qr',event:ReactPointerEvent<HTMLDivElement>){
    if(!detailsFrameRef.current)return
    event.currentTarget.setPointerCapture(event.pointerId)
    detailsDragRef.current={
      pointerId:event.pointerId,target,clientX:event.clientX,clientY:event.clientY,
      offsetX:target==='text'?storyTextOffsetX:storyQrOffsetX,
      offsetY:target==='text'?storyTextOffsetY:storyQrOffsetY,
    }
  }

  function moveDetailsDrag(event:ReactPointerEvent<HTMLDivElement>){
    const drag=detailsDragRef.current
    const frame=detailsFrameRef.current
    if(!drag||drag.pointerId!==event.pointerId||!frame)return
    const rect=frame.getBoundingClientRect()
    const nextX=Math.max(-1,Math.min(1,drag.offsetX+(event.clientX-drag.clientX)/(rect.width/2)))
    const nextY=Math.max(-1,Math.min(1,drag.offsetY+(event.clientY-drag.clientY)/(rect.height/2)))
    if(drag.target==='text'){setStoryTextOffsetX(Math.round(nextX*1000)/1000);setStoryTextOffsetY(Math.round(nextY*1000)/1000)}
    else{setStoryQrOffsetX(Math.round(nextX*1000)/1000);setStoryQrOffsetY(Math.round(nextY*1000)/1000)}
  }

  function endDetailsDrag(event:ReactPointerEvent<HTMLDivElement>){
    if(detailsDragRef.current?.pointerId===event.pointerId)detailsDragRef.current=null
  }

  function beginStoryDrag(event:ReactPointerEvent<HTMLDivElement>){
    if(!cropFrameRef.current)return
    event.currentTarget.setPointerCapture(event.pointerId)
    cropDragRef.current={pointerId:event.pointerId,clientX:event.clientX,clientY:event.clientY,offsetX:storyOffsetX,offsetY:storyOffsetY}
  }

  function moveStoryDrag(event:ReactPointerEvent<HTMLDivElement>){
    const drag=cropDragRef.current
    const frame=cropFrameRef.current
    if(!drag||drag.pointerId!==event.pointerId||!frame)return
    const rect=frame.getBoundingClientRect()
    const nextX=Math.max(-1,Math.min(1,drag.offsetX+(event.clientX-drag.clientX)/(rect.width/2)))
    const nextY=Math.max(-1,Math.min(1,drag.offsetY+(event.clientY-drag.clientY)/(rect.height/2)))
    setStoryOffsetX(Math.round(nextX*1000)/1000)
    setStoryOffsetY(Math.round(nextY*1000)/1000)
  }

  function endStoryDrag(event:ReactPointerEvent<HTMLDivElement>){
    if(cropDragRef.current?.pointerId===event.pointerId)cropDragRef.current=null
  }

  async function copyStorySite(){
    if(!data?.story_site_url)return
    try{await navigator.clipboard.writeText(data.story_site_url);setSuccess('Link público do imóvel copiado.')}catch{}
  }

  async function saveStory(){
    if(!canEdit||!data||!storyPhotoId)return
    setSavingStory(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<InstagramPublication>(`/properties/${propertyId}/instagram-publication/story`,{
        method:'PUT',
        body:JSON.stringify({photo_id:storyPhotoId,zoom:storyZoom,offset_x:storyOffsetX,offset_y:storyOffsetY,text_scale:storyTextScale,qr_scale:storyQrScale,text_offset_x:storyTextOffsetX,text_offset_y:storyTextOffsetY,qr_offset_x:storyQrOffsetX,qr_offset_y:storyQrOffsetY,attributes_enabled:storyAttributesEnabled,attributes_layout:storyAttributesLayout,attributes_scale:storyAttributesScale,attributes_offset_x:storyAttributesOffsetX,attributes_offset_y:storyAttributesOffsetY}),
      })
      setData(result);setStoryPhotoId(result.story_photo_id);setStoryZoom(result.story_zoom||1);setStoryOffsetX(result.story_offset_x||0);setStoryOffsetY(result.story_offset_y||0);setStoryTextScale(result.story_text_scale||1);setStoryQrScale(result.story_qr_scale||1);setStoryTextOffsetX(result.story_text_offset_x||0);setStoryTextOffsetY(result.story_text_offset_y||0);setStoryQrOffsetX(result.story_qr_offset_x||0);setStoryQrOffsetY(result.story_qr_offset_y||0);setStoryAttributesEnabled(result.story_attributes_enabled??true);setStoryAttributesLayout(result.story_attributes_layout||'bottom_bar');setStoryAttributesScale(result.story_attributes_scale||1);setStoryAttributesOffsetX(result.story_attributes_offset_x||0);setStoryAttributesOffsetY(result.story_attributes_offset_y||0)
      setSuccess('Story salvo. A imagem fica independente do carrossel do post.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar o Story.')}
    finally{setSavingStory(false)}
  }

  async function publishStory(){
    if(!canPublish||!data||storyDirty||!storyPhotoId)return
    setPublishingStory(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<InstagramPublication>(`/properties/${propertyId}/instagram-publication/story/publish`,{method:'POST'})
      setData(result);setStoryPhotoId(result.story_photo_id);setStoryZoom(result.story_zoom||1);setStoryOffsetX(result.story_offset_x||0);setStoryOffsetY(result.story_offset_y||0);setStoryTextScale(result.story_text_scale||1);setStoryQrScale(result.story_qr_scale||1);setStoryTextOffsetX(result.story_text_offset_x||0);setStoryTextOffsetY(result.story_text_offset_y||0);setStoryQrOffsetX(result.story_qr_offset_x||0);setStoryQrOffsetY(result.story_qr_offset_y||0);setStoryAttributesEnabled(result.story_attributes_enabled??true);setStoryAttributesLayout(result.story_attributes_layout||'bottom_bar');setStoryAttributesScale(result.story_attributes_scale||1);setStoryAttributesOffsetX(result.story_attributes_offset_x||0);setStoryAttributesOffsetY(result.story_attributes_offset_y||0)
      setSuccess('2 Stories publicados: foto enquadrada + card com detalhes e QR Code do imóvel.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível publicar o Story no Instagram.')}
    finally{setPublishingStory(false)}
  }

  if(loading)return <section className="property-surface property-instagram-panel"><div className="instagram-loading">Carregando publicação do Instagram...</div></section>
  if(!data)return <section className="property-surface property-instagram-panel"><div className="form-alert danger-alert">{error||'Publicação indisponível.'}</div></section>

  const inactive=!data.property_active||data.status==='inactive'
  const lastPublished=data.history[0]??(data.media_id&&data.published_at?{media_id:data.media_id,permalink:data.permalink,published_at:data.published_at,format:data.format,photo_count:photoIds.length}:null)

  return <section className="property-instagram-panel">
    {cropOpen&&storyPhoto&&<div className="instagram-story-crop-backdrop" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget)setCropOpen(false)}}>
      <section className="instagram-story-crop-modal" role="dialog" aria-modal="true" aria-label="Editar enquadramento do Story">
        <header><div><span>ENQUADRAMENTO DO STORY</span><strong>Arraste e aproxime como quiser</strong></div><button type="button" onClick={()=>setCropOpen(false)} aria-label="Fechar"><X size={18}/></button></header>
        <div className="instagram-story-crop-body">
          <div className="instagram-story-crop-stage" onPointerDown={beginStoryDrag} onPointerMove={moveStoryDrag} onPointerUp={endStoryDrag} onPointerCancel={endStoryDrag}>
            <div className="instagram-story-crop-image-layer">
              <PhotoPreview photo={storyPhoto} imageStyle={{transform:`translate(${storyOffsetX*50}%, ${storyOffsetY*50}%) scale(${storyZoom})`}}/>
            </div>
            <div ref={cropFrameRef} className="instagram-story-crop-frame">
              <span>ÁREA QUE SERÁ PUBLICADA</span>
              {storyAttributesEnabled&&data.story_attributes.length>0&&<div
                ref={attributesOverlayRef}
                className={'instagram-story-attributes-overlay layout-'+storyAttributesLayout}
                style={{
                  left:`${50+storyAttributesOffsetX*50}%`,
                  top:`${(storyAttributesLayout==='vertical'?62:storyAttributesLayout==='chips'?74:storyAttributesLayout==='horizontal'?78:82)+storyAttributesOffsetY*50}%`,
                  transform:`translate(-50%,-50%) scale(${storyAttributesScale})`,
                }}
                onPointerDown={beginAttributesDrag}
                onPointerMove={moveAttributesDrag}
                onPointerUp={endAttributesDrag}
                onPointerCancel={endAttributesDrag}
              >
                {data.story_attributes.map(item=><div className={'instagram-story-attribute-item '+(item.key==='rent'?'rent':'')} key={item.key}>
                  <span className="instagram-story-attribute-icon"><StoryAttributeIcon kind={item.key}/></span>
                  <span className="instagram-story-attribute-copy"><strong>{item.value}</strong><small>{item.label}</small></span>
                </div>)}
              </div>}
            </div>
          </div>
          <aside className="instagram-story-crop-controls">
            <div><span>Zoom da foto</span><b>{Math.round(storyZoom*100)}%</b></div>
            <div className="instagram-story-zoom-row">
              <button type="button" disabled={storyZoom<=.2} onClick={()=>setStoryZoom(current=>Math.max(.2,Math.round((current-.05)*100)/100))}><Minus size={14}/></button>
              <input type="range" min=".2" max="2" step=".05" value={storyZoom} onChange={event=>setStoryZoom(Number(event.target.value))}/>
              <button type="button" disabled={storyZoom>=2} onClick={()=>setStoryZoom(current=>Math.min(2,Math.round((current+.05)*100)/100))}><Plus size={14}/></button>
            </div>
            <div className="instagram-story-crop-position"><Move size={15}/><span>Arraste a foto diretamente para mudar o ponto central.</span></div>

            <div className="instagram-story-attributes-divider"/>
            <label className="instagram-story-attributes-toggle">
              <input type="checkbox" checked={storyAttributesEnabled} onChange={event=>setStoryAttributesEnabled(event.target.checked)}/>
              <span><strong>Resumo do imóvel</strong><small>Exibir atributos sobre a foto</small></span>
            </label>
            <label className="instagram-story-attributes-field">
              <span>Layout</span>
              <select disabled={!storyAttributesEnabled} value={storyAttributesLayout} onChange={event=>{setStoryAttributesLayout(event.target.value as InstagramPublication['story_attributes_layout']);setStoryAttributesOffsetX(0);setStoryAttributesOffsetY(0)}}>
                <option value="horizontal">Horizontal</option>
                <option value="vertical">Vertical</option>
                <option value="chips">Chips separados</option>
                <option value="bottom_bar">Barra inferior</option>
              </select>
            </label>
            <div><span>Tamanho da caixa</span><b>{Math.round(storyAttributesScale*100)}%</b></div>
            <div className="instagram-story-zoom-row">
              <button type="button" disabled={!storyAttributesEnabled||storyAttributesScale<=.6} onClick={()=>setStoryAttributesScale(current=>Math.max(.6,Math.round((current-.05)*100)/100))}><Minus size={14}/></button>
              <input disabled={!storyAttributesEnabled} type="range" min=".6" max="1.6" step=".05" value={storyAttributesScale} onChange={event=>setStoryAttributesScale(Number(event.target.value))}/>
              <button type="button" disabled={!storyAttributesEnabled||storyAttributesScale>=1.6} onClick={()=>setStoryAttributesScale(current=>Math.min(1.6,Math.round((current+.05)*100)/100))}><Plus size={14}/></button>
            </div>
            <div className="instagram-story-crop-position"><Move size={15}/><span>Arraste o resumo diretamente sobre a foto para escolher a melhor posição.</span></div>
            <div className="instagram-story-crop-secondary-actions">
              <button className="button secondary" type="button" onClick={resetStoryCrop}><RotateCcw size={14}/>Resetar foto</button>
              <button className="button secondary" type="button" onClick={resetStoryAttributes}><RotateCcw size={14}/>Resetar resumo</button>
            </div>
            <button className="button primary" type="button" onClick={()=>setCropOpen(false)}><Check size={14}/>Usar este enquadramento</button>
          </aside>
        </div>
      </section>
    </div>}
    {detailsOpen&&<div className="instagram-story-crop-backdrop" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget)setDetailsOpen(false)}}>
      <section className="instagram-story-crop-modal instagram-story-details-modal" role="dialog" aria-modal="true" aria-label="Editar segundo Story">
        <header><div><span>2º STORY · DETALHES</span><strong>Ajuste texto e QR Code</strong></div><button type="button" onClick={()=>setDetailsOpen(false)} aria-label="Fechar"><X size={18}/></button></header>
        <div className="instagram-story-crop-body">
          <div className="instagram-story-details-stage">
            <div ref={detailsFrameRef} className="instagram-story-details-canvas">
              <div className="instagram-story-details-brand">
                {theme.logoUrl?<img src={theme.logoUrl} alt="Logo da imobiliária"/>:<span>{(theme.companyShortName||theme.companyName||'IM').slice(0,2).toUpperCase()}</span>}
              </div>
              <div
                className="instagram-story-details-text"
                style={{transform:`translate(${storyTextOffsetX*42}%, ${storyTextOffsetY*42}%) scale(${storyTextScale})`}}
                onPointerDown={event=>beginDetailsDrag('text',event)}
                onPointerMove={moveDetailsDrag}
                onPointerUp={endDetailsDrag}
                onPointerCancel={endDetailsDrag}
              >
                <span>IMÓVEL EM DESTAQUE</span>
                <strong>{caption.split('\n').filter(Boolean)[0]?.replace(/^🏡\s*/,'')||'Detalhes do imóvel'}</strong>
                <small>{caption.split('\n').filter(Boolean).slice(1,4).join(' · ')||'Localização · características · valor'}</small>
                <p>{caption.split('\n').filter(Boolean).slice(4,8).join(' ')||'Confira as principais informações deste imóvel.'}</p>
              </div>
              <div className="instagram-story-details-footer">
                <div><strong>Veja todos os detalhes no site</strong><span>Aponte a câmera para o QR Code</span></div>
                <div
                  className="instagram-story-details-qr"
                  style={{transform:`translate(${storyQrOffsetX*34}%, ${storyQrOffsetY*34}%) scale(${storyQrScale})`}}
                  onPointerDown={event=>beginDetailsDrag('qr',event)}
                  onPointerMove={moveDetailsDrag}
                  onPointerUp={endDetailsDrag}
                  onPointerCancel={endDetailsDrag}
                >
                  <i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/>
                </div>
              </div>
            </div>
          </div>
          <aside className="instagram-story-crop-controls instagram-story-details-controls">
            <div><span>Caixa de texto</span><b>{Math.round(storyTextScale*100)}%</b></div>
            <div className="instagram-story-zoom-row">
              <button type="button" disabled={storyTextScale<=.6} onClick={()=>setStoryTextScale(current=>Math.max(.6,Math.round((current-.05)*100)/100))}><Minus size={14}/></button>
              <input type="range" min=".6" max="1.8" step=".05" value={storyTextScale} onChange={event=>setStoryTextScale(Number(event.target.value))}/>
              <button type="button" disabled={storyTextScale>=1.8} onClick={()=>setStoryTextScale(current=>Math.min(1.8,Math.round((current+.05)*100)/100))}><Plus size={14}/></button>
            </div>
            <div><span>QR Code</span><b>{Math.round(storyQrScale*100)}%</b></div>
            <div className="instagram-story-zoom-row">
              <button type="button" disabled={storyQrScale<=.6} onClick={()=>setStoryQrScale(current=>Math.max(.6,Math.round((current-.05)*100)/100))}><Minus size={14}/></button>
              <input type="range" min=".6" max="1.8" step=".05" value={storyQrScale} onChange={event=>setStoryQrScale(Number(event.target.value))}/>
              <button type="button" disabled={storyQrScale>=1.8} onClick={()=>setStoryQrScale(current=>Math.min(1.8,Math.round((current+.05)*100)/100))}><Plus size={14}/></button>
            </div>
            <div className="instagram-story-crop-position"><Move size={15}/><span>Arraste a caixa de texto ou o QR Code diretamente na prévia para reposicionar.</span></div>
            <button className="button secondary" type="button" onClick={resetDetailsLayout}><RotateCcw size={14}/>Resetar layout</button>
            <button className="button primary" type="button" onClick={()=>setDetailsOpen(false)}><Check size={14}/>Usar este layout</button>
          </aside>
        </div>
      </section>
    </div>}
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
          <div className="instagram-story-sequence">
            <article className="instagram-story-sequence-editable"><b>1</b><div><strong>Story da foto</strong><span>Enquadramento, zoom e posição da imagem.</span></div><button type="button" disabled={!canEdit||inactive||!storyPhoto} onClick={()=>setCropOpen(true)}><Move size={13}/>Editar</button></article>
            <article className="instagram-story-sequence-editable"><b>2</b><div><strong>Story com os detalhes</strong><span>Logo, texto e QR Code com tamanho e posição ajustáveis.</span></div><button type="button" disabled={!canEdit||inactive} onClick={()=>setDetailsOpen(true)}><Move size={13}/>Editar</button></article>
          </div>
          <div className="instagram-story-note"><CircleAlert size={14}/><span>O Story é publicado como mídia vertical. O Instagram não recebe uma legenda de post para Stories por este fluxo; qualquer texto precisa fazer parte da própria arte/imagem.</span></div>
          <div className="instagram-story-actions">
            <button className="button secondary" type="button" disabled={!canEdit||inactive||!storyDirty||!storyPhotoId||savingStory} onClick={()=>void saveStory()}><Save size={14}/>{savingStory?'Salvando...':storyDirty?'Salvar Story':'Story salvo'}</button>
            <button className="button primary" type="button" disabled={!canPublish||inactive||!data.instagram_connected||!['ready','failed'].includes(data.story_status)||storyDirty||publishingStory} onClick={()=>void publishStory()}><Send size={14}/>{publishingStory?'Publicando...':data.story_status==='failed'&&data.story_media_id&&!data.story_description_media_id?'Tentar 2º Story novamente':data.story_status==='failed'?'Tentar novamente':'Publicar 2 Stories'}</button>
          </div>
        </div>

        <div className="instagram-story-preview-shell">
          <div className="instagram-story-preview">
            {storyPhoto?<PhotoPreview photo={storyPhoto} onOpen={setOpenPhoto} imageStyle={{transform:`translate(${storyOffsetX*50}%, ${storyOffsetY*50}%) scale(${storyZoom})`}}/>:<div className="instagram-story-preview-empty"><Instagram size={24}/><span>Selecione uma foto</span></div>}
            <div className="instagram-story-top"><span className="instagram-preview-avatar"><Instagram size={14}/></span><strong>imob.erp</strong><span>agora</span><b>•••</b></div>
          </div>
          {data.story_published_at&&<div className="instagram-story-last-published"><Check size={14}/><span>Último envio: 2 Stories · {new Date(data.story_published_at).toLocaleString('pt-BR')}</span></div>}
          {data.story_site_url&&<button className="instagram-story-site-link" type="button" onClick={()=>void copyStorySite()}><Copy size={13}/><span>Copiar link do imóvel</span></button>}
        </div>
      </div>
    </section>
  </section>
}
