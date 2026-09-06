import { Camera, ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { publicApiRequest } from '../api/client'
import type { PublicProperty } from '../api/types'
import { runtimeConfig } from '../config/runtime'
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

type PublicPropertyWithCover = PublicProperty & { cover_photo_url?: string | null }

function propertyType(value: string) {
  const labels: Record<string, string> = { apartment: 'Apartamento', house: 'Casa', commercial: 'Comercial', land: 'Terreno', studio: 'Studio', other: 'Imóvel' }
  return labels[value] ?? value
}

function mediaUrl(path: string) {
  if (/^https?:\/\//i.test(path)) return path
  return `${runtimeConfig.apiUrl}${path.startsWith('/') ? path : `/${path}`}`
}

export function PublicPropertyCardMedia({ organizationId: _organizationId, item }: { organizationId: string; item: PublicProperty }) {
  const cover = (item as PublicPropertyWithCover).cover_photo_url || null
  return <div className={`public-property-visual ${cover ? 'public-property-photo' : ''}`}>
    {cover ? <img loading="lazy" src={mediaUrl(cover)} alt={item.title}/> : <span>{propertyType(item.property_type)}</span>}
    <small>#{item.code}</small>
  </div>
}

export function PublicPropertyGallery({ organizationId, item }: { organizationId: string; item: PublicProperty }) {
  const [photos, setPhotos] = useState<PublicPhoto[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const metadata = await publicApiRequest<PublicPhoto[]>(`/public/sites/${organizationId}/properties/${item.slug}/photos`)
        if (!active) return
        setPhotos(metadata)
        setSelectedId(metadata.find((photo) => photo.is_cover)?.id ?? metadata[0]?.id ?? null)
      } catch { /* mantém fallback visual */ }
    }
    void load()
    return () => { active = false }
  }, [organizationId, item.slug])

  const selected = useMemo(() => photos.find((photo) => photo.id === selectedId) ?? photos.find((photo) => photo.is_cover) ?? photos[0] ?? null, [photos, selectedId])
  const index = selected ? photos.findIndex((photo) => photo.id === selected.id) : -1
  function shift(delta: number) { if (!photos.length) return; const next = (index + delta + photos.length) % photos.length; setSelectedId(photos[next].id) }

  if (!selected) return <div className="public-detail-visual public-detail-photo-fallback"><Camera size={28}/><span>{propertyType(item.property_type)}</span><strong>{item.title}</strong></div>

  return <div className="public-detail-gallery">
    <div className="public-detail-gallery-main"><img src={mediaUrl(selected.content_url)} alt={selected.caption || item.title}/>{photos.length > 1 && <><button type="button" className="previous" aria-label="Foto anterior" onClick={() => shift(-1)}><ChevronLeft size={19}/></button><button type="button" className="next" aria-label="Próxima foto" onClick={() => shift(1)}><ChevronRight size={19}/></button></>}<span>{index + 1} / {photos.length}</span></div>
    {photos.length > 1 && <div className="public-detail-gallery-thumbs">{photos.map((photo) => <button type="button" className={photo.id === selected.id ? 'active' : ''} key={photo.id} onClick={() => setSelectedId(photo.id)}><img loading="lazy" src={mediaUrl(photo.content_url)} alt={photo.caption || item.title}/></button>)}</div>}
    {selected.caption && <small className="public-detail-gallery-caption">{selected.caption}</small>}
  </div>
}
