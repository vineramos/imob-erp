import { Camera, ChevronLeft, ChevronRight, ImagePlus, Star, Trash2 } from 'lucide-react'
import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
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
type Props = { propertyId: string; canManage: boolean; onChanged?: () => void }

export function PropertyGallery({ propertyId, canManage, onChanged }: Props) {
  const [photos, setPhotos] = useState<PhotoView[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [caption, setCaption] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
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

  const selected = useMemo(() => photos.find((photo) => photo.id === selectedId) ?? photos.find((photo) => photo.is_cover) ?? photos[0] ?? null, [photos, selectedId])
  useEffect(() => { setCaption(selected?.caption ?? '') }, [selected?.id, selected?.caption])

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

  async function move(direction: -1 | 1) {
    if (!selected || !canManage) return
    const index = photos.findIndex((photo) => photo.id === selected.id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= photos.length) return
    const ids = photos.map((photo) => photo.id)
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    setBusy(true); setError('')
    try {
      await apiRequest(`/properties/${propertyId}/photos/reorder`, { method: 'POST', body: JSON.stringify({ photo_ids: ids }) })
      await refreshAfterMutation()
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível reordenar as fotos.') }
    finally { setBusy(false) }
  }

  async function remove(photo: PropertyPhoto) {
    if (!canManage || !window.confirm(`Excluir a foto “${photo.filename}”?`)) return
    setBusy(true); setError('')
    try {
      await apiRequest(`/properties/${propertyId}/photos/${photo.id}`, { method: 'DELETE' })
      await refreshAfterMutation()
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível excluir a foto.') }
    finally { setBusy(false) }
  }

  return <article className="panel property-media-panel property-gallery">
    <div className="property-panel-heading property-gallery-heading">
      <div><h2>Fotos</h2><span>{photos.length ? `${photos.length} foto(s) · ${photos.findIndex((photo) => photo.id === selected?.id) + 1} de ${photos.length}` : 'Galeria comercial do imóvel'}</span></div>
      {canManage && <label className={`button secondary compact-button property-gallery-upload ${busy ? 'disabled' : ''}`}><ImagePlus size={14}/> Adicionar fotos<input type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={upload}/></label>}
    </div>
    {error && <div className="property-gallery-error">{error}</div>}
    {!selected ? <div className="property-gallery-empty"><Camera size={31}/><strong>Nenhuma foto cadastrada</strong><span>Adicione fotos comerciais do imóvel. Elas ficam separadas das imagens das vistorias.</span>{canManage && <label className="button primary property-gallery-empty-action"><ImagePlus size={14}/> Selecionar fotos<input type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={upload}/></label>}</div> : <>
      <div className="property-gallery-main"><img src={selected.objectUrl} alt={selected.caption || selected.filename}/>{selected.is_cover && <span className="property-gallery-cover"><Star size={12} fill="currentColor"/> Capa do anúncio</span>}</div>
      <div className="property-gallery-thumbs" aria-label="Fotos do imóvel">{photos.map((photo) => <button type="button" className={photo.id === selected.id ? 'active' : ''} key={photo.id} onClick={() => setSelectedId(photo.id)}><img src={photo.objectUrl} alt={photo.caption || photo.filename}/>{photo.is_cover && <Star size={11} fill="currentColor"/>}</button>)}</div>
      {canManage && <div className="property-gallery-editor"><div className="property-gallery-actions"><button className="button secondary compact-button" type="button" disabled={busy || photos[0]?.id === selected.id} onClick={() => void move(-1)}><ChevronLeft size={14}/> Anterior</button><button className="button secondary compact-button" type="button" disabled={busy || photos[photos.length - 1]?.id === selected.id} onClick={() => void move(1)}>Próxima <ChevronRight size={14}/></button><button className="button secondary compact-button" type="button" disabled={busy || selected.is_cover} onClick={() => void setCover(selected)}><Star size={14}/> Definir capa</button><button className="button secondary compact-button property-gallery-delete" type="button" disabled={busy} onClick={() => void remove(selected)}><Trash2 size={14}/> Excluir</button></div><label className="property-gallery-caption"><span>Legenda</span><div><input maxLength={300} value={caption} onChange={(event) => setCaption(event.target.value)} placeholder="Ex.: Sala integrada com ampla iluminação natural"/><button className="button secondary compact-button" type="button" disabled={busy || caption.trim() === (selected.caption ?? '')} onClick={() => void saveCaption()}>Salvar</button></div></label></div>}
    </>}
  </article>
}
