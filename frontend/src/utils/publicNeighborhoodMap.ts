import { publicApiRequest } from '../api/client'
import type { PublicProperty } from '../api/types'

type PublicMapProperty = PublicProperty & { cover_photo_url?: string | null }
type Coordinate = [number, number]

declare global {
  interface Window {
    L?: any
  }
}

const LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
const LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
const GEO_CACHE_PREFIX = 'imob:public-map:geo:'

let leafletPromise: Promise<any> | null = null
let geocodeQueue = Promise.resolve()

function organizationIdFromPath() {
  const match = window.location.pathname.match(/^\/site\/([^/]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

function money(value: number | null) {
  if (value == null) return 'Consulte'
  return Number(value).toLocaleString('pt-BR', {
    style: 'currency', currency: 'BRL', minimumFractionDigits: 0, maximumFractionDigits: 0,
  })
}

function locationLabel(item: PublicMapProperty) {
  return [item.address.neighborhood, item.address.city, item.address.state].filter(Boolean).join(' · ') || 'Localização sob consulta'
}

function ensureLeaflet(): Promise<any> {
  if (window.L) return Promise.resolve(window.L)
  if (leafletPromise) return leafletPromise

  leafletPromise = new Promise((resolve, reject) => {
    if (!document.querySelector(`link[href="${LEAFLET_CSS}"]`)) {
      const link = document.createElement('link')
      link.rel = 'stylesheet'
      link.href = LEAFLET_CSS
      link.crossOrigin = ''
      document.head.appendChild(link)
    }

    const existing = document.querySelector<HTMLScriptElement>(`script[src="${LEAFLET_JS}"]`)
    if (existing) {
      existing.addEventListener('load', () => window.L ? resolve(window.L) : reject(new Error('Leaflet indisponível.')), { once: true })
      existing.addEventListener('error', () => reject(new Error('Falha ao carregar o mapa.')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.src = LEAFLET_JS
    script.crossOrigin = ''
    script.dataset.imobLeaflet = 'true'
    script.onload = () => window.L ? resolve(window.L) : reject(new Error('Leaflet indisponível.'))
    script.onerror = () => reject(new Error('Falha ao carregar o mapa.'))
    document.head.appendChild(script)
  })

  return leafletPromise
}

function normalizedGeoKey(neighborhood: string, city: string, state: string) {
  return `${neighborhood}|${city}|${state}`.trim().toLowerCase()
}

function cachedCoordinate(key: string): Coordinate | null {
  try {
    const raw = localStorage.getItem(`${GEO_CACHE_PREFIX}${key}`)
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed) || parsed.length !== 2) return null
    const lat = Number(parsed[0]); const lng = Number(parsed[1])
    return Number.isFinite(lat) && Number.isFinite(lng) ? [lat, lng] : null
  } catch { return null }
}

function saveCoordinate(key: string, coordinate: Coordinate) {
  try { localStorage.setItem(`${GEO_CACHE_PREFIX}${key}`, JSON.stringify(coordinate)) } catch { /* cache opcional */ }
}

async function geocodeNeighborhood(neighborhood: string, city: string, state: string): Promise<Coordinate | null> {
  const key = normalizedGeoKey(neighborhood, city, state)
  const cached = cachedCoordinate(key)
  if (cached) return cached

  const task = geocodeQueue.then(async () => {
    const cachedAfterWait = cachedCoordinate(key)
    if (cachedAfterWait) return cachedAfterWait
    const query = [neighborhood, city, state, 'Brasil'].filter(Boolean).join(', ')
    const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=br&q=${encodeURIComponent(query)}`
    const response = await fetch(url, { headers: { 'Accept-Language': 'pt-BR,pt;q=0.9' } })
    if (!response.ok) return null
    const rows = await response.json() as Array<{ lat?: string; lon?: string }>
    const lat = Number(rows[0]?.lat); const lng = Number(rows[0]?.lon)
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null
    const coordinate: Coordinate = [lat, lng]
    saveCoordinate(key, coordinate)
    return coordinate
  }).catch(() => null)

  geocodeQueue = task.then(() => new Promise<void>((resolve) => window.setTimeout(resolve, 1050)))
  return task
}

function propertyOffset(code: string, index: number): Coordinate {
  let hash = 0
  for (const char of `${code}-${index}`) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0
  const angle = (Math.abs(hash) % 360) * Math.PI / 180
  const ring = 0.0017 + (Math.abs(hash >> 5) % 4) * 0.00055
  return [Math.sin(angle) * ring, Math.cos(angle) * ring]
}

function buildCard(host: HTMLElement, organizationId: string, item: PublicMapProperty) {
  host.replaceChildren()
  const card = document.createElement('article')
  card.className = 'public-map-property-card'

  const copy = document.createElement('div')
  copy.className = 'public-map-property-copy'
  const kicker = document.createElement('span')
  kicker.textContent = 'IMÓVEL NESTA REGIÃO'
  const title = document.createElement('strong')
  title.textContent = item.title
  const location = document.createElement('small')
  location.textContent = locationLabel(item)
  const price = document.createElement('b')
  price.textContent = `${money(item.rent_amount)} / mês`
  const facts = document.createElement('p')
  facts.textContent = `${item.bedrooms} quartos · ${item.parking_spaces} vagas${item.area_m2 != null ? ` · ${item.area_m2} m²` : ''}`
  copy.append(kicker, title, location, price, facts)

  const link = document.createElement('a')
  link.href = `/site/${organizationId}/imoveis/${item.slug}`
  link.textContent = 'Ver imóvel →'
  link.className = 'public-map-property-link'

  card.append(copy, link)
  host.appendChild(card)
}

async function enhanceMap(target: HTMLElement) {
  if (target.dataset.liveMap === 'loading' || target.dataset.liveMap === 'ready') return
  const organizationId = organizationIdFromPath()
  if (!organizationId) return
  target.dataset.liveMap = 'loading'

  try {
    const [L, items] = await Promise.all([
      ensureLeaflet(),
      publicApiRequest<PublicMapProperty[]>(`/public/sites/${organizationId}/properties`),
    ])
    if (!target.isConnected) return

    const rentals = items.filter((item) => item.purpose === 'rent' && item.address.neighborhood && item.address.city)
    if (!rentals.length) { target.dataset.liveMap = 'empty'; return }

    const groups = new Map<string, PublicMapProperty[]>()
    rentals.forEach((item) => {
      const key = normalizedGeoKey(String(item.address.neighborhood || ''), String(item.address.city || ''), String(item.address.state || ''))
      const existing = groups.get(key) ?? []
      existing.push(item); groups.set(key, existing)
    })

    const shell = document.createElement('div')
    shell.className = 'public-live-map-shell'
    const mapHost = document.createElement('div')
    mapHost.className = 'public-live-map-canvas'
    const cardHost = document.createElement('div')
    cardHost.className = 'public-live-map-card-host'
    const badge = document.createElement('span')
    badge.className = 'public-live-map-privacy'
    badge.textContent = 'Localização aproximada por bairro'
    const loading = document.createElement('div')
    loading.className = 'public-live-map-loading'
    loading.textContent = 'Localizando imóveis…'
    shell.append(mapHost, cardHost, badge, loading)
    target.replaceChildren(shell)

    const map = L.map(mapHost, { zoomControl: true, scrollWheelZoom: false, attributionControl: true }).setView([-25.4284, -49.2733], 12)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map)

    const coordinates: Coordinate[] = []
    let firstProperty: PublicMapProperty | null = null

    for (const properties of groups.values()) {
      const sample = properties[0]
      const center = await geocodeNeighborhood(
        String(sample.address.neighborhood || ''),
        String(sample.address.city || ''),
        String(sample.address.state || ''),
      )
      if (!center || !target.isConnected) continue

      properties.forEach((item, index) => {
        const offset = propertyOffset(item.code, index)
        const position: Coordinate = [center[0] + offset[0], center[1] + offset[1]]
        coordinates.push(position)
        const label = item.rent_amount == null ? 'Imóvel' : money(item.rent_amount).replace(',00', '')
        const icon = L.divIcon({
          className: 'public-map-price-icon',
          html: `<span>${label}</span>`,
          iconSize: [78, 32], iconAnchor: [39, 16],
        })
        const marker = L.marker(position, { icon }).addTo(map)
        marker.on('click', () => buildCard(cardHost, organizationId, item))
        if (!firstProperty) firstProperty = item
      })
    }

    loading.remove()
    if (!coordinates.length) {
      target.replaceChildren()
      target.dataset.liveMap = 'unavailable'
      return
    }

    if (coordinates.length === 1) map.setView(coordinates[0], 14)
    else map.fitBounds(L.latLngBounds(coordinates), { padding: [36, 36], maxZoom: 14 })
    if (firstProperty) buildCard(cardHost, organizationId, firstProperty)
    window.setTimeout(() => map.invalidateSize(), 50)
    target.dataset.liveMap = 'ready'
  } catch {
    target.dataset.liveMap = 'failed'
  }
}

export function installPublicNeighborhoodMap() {
  function scan() {
    document.querySelectorAll<HTMLElement>('.public-site-premium .public-map-art').forEach((target) => { void enhanceMap(target) })
  }
  const observer = new MutationObserver(scan)
  observer.observe(document.documentElement, { subtree: true, childList: true })
  scan()
}
