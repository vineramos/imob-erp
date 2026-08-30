import { Camera, ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { publicApiRequest, publicBlobRequest } from '../api/client'
import type { PublicProperty } from '../api/types'
import './public-property-media.css'

type PublicPhoto = {
  id: string
  filename: string
  content_type: string
  caption: string | null
  position: number
  is_cover: boolean
  content_url: string
}

type LoadedPhoto = PublicPhoto & { objectUrl: string }

function propertyType(value: string) {
  const labels: Record<string, string> = { apartment: 'Apartamento', house: 'Casa', commercial: 'Comercial', land: 'Terreno', studio: 'Studio', other: 'Imóvel' }
  return labels[value] ?? value
}

export function PublicPropertyCardMedia({ organizationId, item }: { organizationId: string; item: PublicProperty }) {
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    async function load() {
      try {
        const photos = await publicApiRequest<PublicPhoto[]>(`/public/sites/${organizationId}/properties/${item.slug}/photos`)
        const cover = photos.find((photo) => photo.is_cover) ?? photos[0]
        if (!cover) return
        const blob = await publicBlobRequest(cover.content_url)
        objectUrl = URL.createObjectURL(blob)
        if (active) setPhotoUrl(objectUrl)
      } catch { /* mantém fallback visual */ }
    }
    void load()
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [organizationId, item.slug])

  return <div className={`public-property-visual ${photoUrl ? 'public-property-photo' : ''}`}>
    {photoUrl ? <img src={photoUrl} alt={item.title}/> : <span>{propertyType(item.property_type)}</span>}
    <small>#{item.code}</small>
  </div>
}

export function PublicPropertyGallery({ organizationId, item }: { organizationId: string; item: PublicProperty }) {
  const [photos, setPhotos] = useState<LoadedPhoto[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const urls = useRef<string[]>([])

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const metadata = await publicApiRequest<PublicPhoto[]>(`/public/sites/${organizationId}/properties/${item.slug}/photos`)
        const loaded = await Promise.all(metadata.map(async (photo) => ({ ...photo, objectUrl: URL.createObjectURL(await publicBlobRequest(photo.content_url)) })))
        if (!active) { loaded.forEach((photo) => URL.revokeObjectURL(photo.objectUrl)); return }
        urls.current.forEach((url) => URL.revokeObjectURL(url))
        urls.current = loaded.map((photo) => photo.objectUrl)
        setPhotos(loaded)
        setSelectedId(loaded.find((photo) => photo.is_cover)?.id ?? loaded[0]?.id ?? null)
      } catch { /* mantém fallback visual */ }
    }
    void load()
    return () => { active = false; urls.current.forEach((url) => URL.revokeObjectURL(url)); urls.current = [] }
  }, [organizationId, item.slug])

  const selected = useMemo(() => photos.find((photo) => photo.id === selectedId) ?? photos.find((photo) => photo.is_cover) ?? photos[0] ?? null, [photos, selectedId])
  const index = selected ? photos.findIndex((photo) => photo.id === selected.id) : -1
  function shift(delta: number) { if (!photos.length) return; const next = (index + delta + photos.length) % photos.length; setSelectedId(photos[next].id) }

  if (!selected) return <div className="public-detail-visual public-detail-photo-fallback"><Camera size={28}/><span>{propertyType(item.property_type)}</span><strong>{item.title}</strong></div>

  return <div className="public-detail-gallery">
    <div className="public-detail-gallery-main"><img src={selected.objectUrl} alt={selected.caption || item.title}/>{photos.length > 1 && <><button type="button" className="previous" aria-label="Foto anterior" onClick={() => shift(-1)}><ChevronLeft size={19}/></button><button type="button" className="next" aria-label="Próxima foto" onClick={() => shift(1)}><ChevronRight size={19}/></button></>}<span>{index + 1} / {photos.length}</span></div>
    {photos.length > 1 && <div className="public-detail-gallery-thumbs">{photos.map((photo) => <button type="button" className={photo.id === selected.id ? 'active' : ''} key={photo.id} onClick={() => setSelectedId(photo.id)}><img src={photo.objectUrl} alt={photo.caption || item.title}/></button>)}</div>}
    {selected.caption && <small className="public-detail-gallery-caption">{selected.caption}</small>}
  </div>
}
