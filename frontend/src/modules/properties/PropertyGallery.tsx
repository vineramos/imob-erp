import { Camera, ChevronLeft, ChevronRight, ImagePlus, Settings2, Star, Trash2, X } from 'lucide-react'
import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import './property-gallery.css'

type PropertyPhoto = {
  id: string
  property_id: string
  filename: string
  content_type: string
  size_bytes: number
  caption: string | null
  position: number
  is_cover: boolean
  content_url: string
  created_at: string
}

type PhotoView = PropertyPhoto & { objectUrl: string }
type Props = { propertyId: string; canManage: boolean; onChanged?: () => void; variant?: 'panel' | 'hero'; heroContent?: ReactNode; heroActions?: ReactNode; overviewMountId?: string }

export function PropertyGallery({ propertyId, canManage, onChanged, variant = 'panel', heroContent, heroActions, overviewMountId }: Props) {
  const [photos, setPhotos] = useState<PhotoView[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [caption, setCaption] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<PropertyPhoto | null>(null)
  const [viewerOpen, setViewerOpen] = useState(false)
  const [managerOpen, setManagerOpen] = useState(false)
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [dragOverId, setDragOverId] = useState<string | null>(null)
  const [overviewMount, setOverviewMount] = useState<HTMLElement | null>(null)
  const urlsRef = useRef<string[]>([])

  const releaseUrls = useCallback(() => {
    urlsRef.current.forEach((url) => URL.revokeObjectURL(url))
    urlsRef.current = []
  }, [])

  const load = useCallback(async () => {
    setError('')
    try {
      const metadata = await apiRequest<PropertyPhoto[]>(`/properties/${propertyId}/photos`)
      const loaded = await Promise.all(metadata.map(async (photo) => {
        const blob = await apiBlobRequest(photo.content_url)
        return { ...photo, objectUrl: URL.createObjectURL(blob) }
      }))
      releaseUrls()
      urlsRef.current = loaded.map((photo) => photo.objectUrl)
      setPhotos(loaded)
      setSelectedId((current) => current && loaded.some((photo) => photo.id === current)
        ? current
        : (loaded.find((photo) => photo.is_cover)?.id ?? loaded[0]?.id ?? null))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar as fotos do imóvel.')
    }
  }, [propertyId, releaseUrls])

  useEffect(() => { void load(); return releaseUrls }, [load, releaseUrls])
  useEffect(() => {
    const nextMount = overviewMountId ? document.getElementById(overviewMountId) : null
    setOverviewMount((current) => current === nextMount ? current : nextMount)
  })

  const selected = useMemo(() => photos.find((photo) => photo.id === selectedId) ?? photos.find((photo) => photo.is_cover) ?? photos[0] ?? null, [photos, selectedId])
  useEffect(() => { setCaption(selected?.caption ?? '') }, [selected?.id, selected?.caption])
  useEffect(() => {
    if (!viewerOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setViewerOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [viewerOpen])

  async function refreshAfterMutation(message?: string) {
    await load()
    onChanged?.()
    if (message) setError('')
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (!files.length || !canManage) return
    setBusy(true); setError('')
    try {
      for (const file of files) {
        const body = new FormData()
        body.append('file', file)
        await apiRequest(`/properties/${propertyId}/photos`, { method: 'POST', body })
      }
      await refreshAfterMutation()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível enviar as fotos.')
    } finally { setBusy(false) }
  }

  async function setCover(photo: PropertyPhoto) {
    if (!canManage || photo.is_cover) return
    setBusy(true); setError('')
    try {
      await apiRequest(`/properties/${propertyId}/photos/${photo.id}`, { method: 'PATCH', body: JSON.stringify({ is_cover: true }) })
      setSelectedId(photo.id)
      await refreshAfterMutation()
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível definir a capa.') }
    finally { setBusy(false) }
  }

  async function saveCaption() {
    if (!selected || !canManage || caption.trim() === (selected.caption ?? '')) return
    setBusy(true); setError('')
    try {
      await apiRequest(`/properties/${propertyId}/photos/${selected.id}`, { method: 'PATCH', body: JSON.stringify({ caption: caption.trim() || null }) })
      await refreshAfterMutation()
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar a legenda.') }
    finally { setBusy(false) }
  }

  async function persistOrder(ids: string[]) {
    if (!canManage || busy) return
    setBusy(true); setError('')
    try {
      await apiRequest(`/properties/${propertyId}/photos/reorder`, { method: 'POST', body: JSON.stringify({ photo_ids: ids }) })
      await refreshAfterMutation()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível reordenar as fotos.')
      await load()
    } finally {
      setBusy(false)
      setDraggedId(null)
      setDragOverId(null)
    }
  }

  async function move(direction: -1 | 1) {
    if (!selected || !canManage) return
    const index = photos.findIndex((photo) => photo.id === selected.id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= photos.length) return
    const ids = photos.map((photo) => photo.id)
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    await persistOrder(ids)
  }

  function reorderByDrag(sourceId: string, targetId: string) {
    if (!canManage || busy || sourceId === targetId) return
    const sourceIndex = photos.findIndex((photo) => photo.id === sourceId)
    const targetIndex = photos.findIndex((photo) => photo.id === targetId)
    if (sourceIndex < 0 || targetIndex < 0) return
    const reordered = [...photos]
    const [moved] = reordered.splice(sourceIndex, 1)
    reordered.splice(targetIndex, 0, moved)
    setPhotos(reordered.map((photo, index) => ({ ...photo, position: index })))
    setSelectedId(sourceId)
    void persistOrder(reordered.map((photo) => photo.id))
  }

  async function remove(photo: PropertyPhoto) {
    if (!canManage) return
    setBusy(true); setError('')
    try {
      await apiRequest(`/properties/${propertyId}/photos/${photo.id}`, { method: 'DELETE' })
      setDeleteTarget(null)
      await refreshAfterMutation()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível excluir a foto.')
    } finally { setBusy(false) }
  }

  const overviewGallery = overviewMount && createPortal(<section className="property-overview-gallery" aria-label="Galeria de fotos do imóvel">
    <div className="property-overview-gallery-heading"><div><span>Galeria</span><h2>Fotos do imóvel</h2></div><div><strong>{photos.length}</strong><span>{photos.length === 1 ? 'foto' : 'fotos'}</span></div></div>
    {selected ? <>
      <button className="property-overview-gallery-stage" type="button" onClick={() => setViewerOpen(true)} aria-label="Abrir galeria ampliada">
        <img src={selected.objectUrl} alt={selected.caption || selected.filename}/>
        <span>{photos.findIndex((photo) => photo.id === selected.id) + 1} / {photos.length}</span>
        {selected.is_cover && <small><Star size={11} fill="currentColor"/> Capa</small>}
      </button>
      <div className="property-overview-gallery-footer"><div className="property-overview-gallery-thumbs">{photos.slice(0, 5).map(photo => <button type="button" className={photo.id === selected.id ? 'active' : ''} key={photo.id} onClick={() => setSelectedId(photo.id)}><img src={photo.objectUrl} alt={photo.caption || photo.filename}/></button>)}</div><button type="button" onClick={() => setViewerOpen(true)}><Camera size={14}/> Visualizar todas</button></div>
    </> : <div className="property-overview-gallery-empty"><Camera size={27}/><strong>Nenhuma foto cadastrada</strong><span>A apresentação visual aparecerá aqui quando houver imagens.</span></div>}
  </section>, overviewMount)

  return <>
    <article className={`panel property-media-panel property-gallery ${variant === 'hero' ? 'property-gallery--hero' : ''}`}>
      {variant !== 'hero' && <div className="property-panel-heading property-gallery-heading">
        <div><h2>Fotos</h2><span>{photos.length ? `${photos.length} foto(s) · ${photos.findIndex((photo) => photo.id === selected?.id) + 1} de ${photos.length}` : 'Galeria comercial do imóvel'}</span></div>
        {canManage && <label className={`button secondary compact-button property-gallery-upload ${busy ? 'disabled' : ''}`}><ImagePlus size={14}/> Adicionar fotos<input type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={upload}/></label>}
      </div>}
      {error && <div className="property-gallery-error">{error}</div>}
      {!selected ? <><div className="property-gallery-empty"><Camera size={31}/><strong>Nenhuma foto cadastrada</strong><span>Adicione fotos comerciais do imóvel. Elas ficam separadas das imagens das vistorias.</span>{heroContent}{canManage && <label className="button primary property-gallery-empty-action"><ImagePlus size={14}/> Selecionar fotos<input type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={upload}/></label>}</div>{variant === 'hero' && heroActions}</> : <>
        <div className="property-gallery-main"><img src={selected.objectUrl} alt={selected.caption || selected.filename}/><button className="property-gallery-expand" type="button" onClick={() => setViewerOpen(true)} aria-label="Ampliar foto selecionada"><Camera size={15}/> Ver todas</button>{selected.is_cover && <span className="property-gallery-cover"><Star size={12} fill="currentColor"/> Foto de capa</span>}{heroContent}</div>
        {variant === 'hero' && <div className="property-gallery-hero-toolbar"><span><Camera size={14}/>{photos.findIndex((photo) => photo.id === selected.id) + 1} de {photos.length} fotos</span><div><button type="button" onClick={() => setViewerOpen(true)}><Camera size={14}/> Visualizar todas</button>{canManage && <button type="button" aria-expanded={managerOpen} onClick={() => setManagerOpen(value => !value)}><Settings2 size={14}/>{managerOpen ? 'Concluir edição' : 'Gerenciar fotos'}</button>}{canManage && managerOpen && <label className={`property-gallery-add ${busy ? 'disabled' : ''}`}><ImagePlus size={14}/> Adicionar<input type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={upload}/></label>}</div></div>}
        <div className={`property-gallery-thumbs ${canManage && managerOpen ? 'is-reorderable' : ''}`} aria-label="Fotos do imóvel">{photos.map((photo, index) => <button type="button" className={[
          photo.id === selected.id ? 'active' : '',
          photo.id === draggedId ? 'is-dragging' : '',
          photo.id === dragOverId ? 'is-drag-over' : '',
        ].filter(Boolean).join(' ')} key={photo.id} onClick={() => setSelectedId(photo.id)} draggable={canManage && managerOpen && !busy} onDragStart={(event) => { if (!canManage || !managerOpen || busy) return; setDraggedId(photo.id); event.dataTransfer.effectAllowed='move'; event.dataTransfer.setData('text/plain',photo.id) }} onDragEnter={(event) => { if (!draggedId || photo.id===draggedId) return; event.preventDefault(); setDragOverId(photo.id) }} onDragOver={(event) => { if (!draggedId) return; event.preventDefault(); event.dataTransfer.dropEffect='move' }} onDrop={(event) => { event.preventDefault(); const sourceId=event.dataTransfer.getData('text/plain')||draggedId; if (sourceId) reorderByDrag(sourceId,photo.id) }} onDragEnd={() => { setDraggedId(null); setDragOverId(null) }} title={canManage && managerOpen ? `Foto ${index+1}: arraste para mudar a ordem` : undefined}><img src={photo.objectUrl} alt={photo.caption || photo.filename}/>{canManage && managerOpen && <span className="property-gallery-order-index">{index+1}</span>}{photo.is_cover && <Star size={11} fill="currentColor"/>}</button>)}</div>
        {canManage && (variant !== 'hero' || managerOpen) && <div className="property-gallery-editor">{variant === 'hero' && managerOpen && <div className="property-gallery-reorder-hint"><strong>Ordenar fotos</strong><span>Arraste as miniaturas para definir a sequência exibida no sistema e no site. Os botões Anterior/Próxima continuam disponíveis como alternativa.</span></div>}<div className="property-gallery-actions"><button className="button secondary compact-button" type="button" disabled={busy || photos[0]?.id === selected.id} onClick={() => void move(-1)}><ChevronLeft size={14}/> Anterior</button><button className="button secondary compact-button" type="button" disabled={busy || photos[photos.length - 1]?.id === selected.id} onClick={() => void move(1)}>Próxima <ChevronRight size={14}/></button><button className="button secondary compact-button" type="button" disabled={busy || selected.is_cover} onClick={() => void setCover(selected)}><Star size={14}/> Definir capa</button><button className="button secondary compact-button property-gallery-delete" type="button" disabled={busy} onClick={() => setDeleteTarget(selected)}><Trash2 size={14}/> Excluir</button></div><label className="property-gallery-caption"><span>Legenda</span><div><input maxLength={300} value={caption} onChange={(event) => setCaption(event.target.value)} placeholder="Ex.: Sala integrada com ampla iluminação natural"/><button className="button secondary compact-button" type="button" disabled={busy || caption.trim() === (selected.caption ?? '')} onClick={() => void saveCaption()}>Salvar</button></div></label></div>}
        {variant === 'hero' && heroActions}
      </>}
    </article>
    {viewerOpen && selected && <div className="property-gallery-viewer-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setViewerOpen(false) }}>
      <section className="property-gallery-viewer" role="dialog" aria-modal="true" aria-label="Visualização ampliada da foto">
        <header className="property-gallery-viewer-heading"><div><strong>{selected.caption || 'Foto do imóvel'}</strong><span>{selected.filename}</span></div><button type="button" onClick={() => setViewerOpen(false)} aria-label="Fechar visualização"><X size={18}/></button></header>
        <div className="property-gallery-viewer-stage"><img src={selected.objectUrl} alt={selected.caption || selected.filename}/></div>
      </section>
    </div>}
    <ConfirmDialog
      open={Boolean(deleteTarget)}
      title="Excluir foto"
      description={deleteTarget ? `Deseja excluir a foto “${deleteTarget.filename}”? Essa ação remove a imagem da galeria comercial do imóvel.` : ''}
      confirmLabel="Excluir foto"
      tone="danger"
      busy={busy}
      onCancel={() => { if (!busy) setDeleteTarget(null) }}
      onConfirm={() => { if (deleteTarget) void remove(deleteTarget) }}
    />
    {overviewGallery}
  </>
}
