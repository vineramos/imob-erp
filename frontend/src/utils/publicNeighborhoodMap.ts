import { publicApiRequest } from '../api/client'
import type { PublicProperty } from '../api/types'
import { runtimeConfig } from '../config/runtime'

type PublicMapProperty = PublicProperty & { cover_photo_url?: string | null }
type Coordinate = [number, number]
type PreparedMapProperty = {
  item: PublicMapProperty
  position: Coordinate
  groupKey: string
  neighborhood: string
}

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

function mediaUrl(path: string) {
  if (/^https?:\/\//i.test(path)) return path
  return `${runtimeConfig.apiUrl}${path.startsWith('/') ? path : `/${path}`}`
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

function priceIcon(L: any, item: PublicMapProperty, active = false) {
  const label = item.rent_amount == null ? 'Imóvel' : money(item.rent_amount).replace(',00', '')
  return L.divIcon({
    className: `public-map-price-icon${active ? ' is-active' : ''}`,
    html: `<span>${label}</span>`,
    iconSize: [78, 32], iconAnchor: [39, 16],
  })
}

function clusterIcon(L: any, count: number) {
  return L.divIcon({
    className: 'public-map-cluster-icon',
    html: `<span>${count} ${count === 1 ? 'imóvel' : 'imóveis'}</span>`,
    iconSize: [88, 34], iconAnchor: [44, 17],
  })
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

function makeSelect(labelText: string, options: Array<[string, string]>) {
  const label = document.createElement('label')
  label.className = 'public-map-explorer-filter'
  const caption = document.createElement('span')
  caption.textContent = labelText
  const select = document.createElement('select')
  options.forEach(([value, text]) => {
    const option = document.createElement('option')
    option.value = value
    option.textContent = text
    select.appendChild(option)
  })
  label.append(caption, select)
  return { label, select }
}

function copyThemeVariables(source: HTMLElement, target: HTMLElement) {
  const computed = getComputedStyle(source)
  const names = ['--site-primary', '--site-primary-strong', '--site-primary-soft', '--site-bg', '--site-surface', '--site-ink', '--site-muted', '--site-line', '--site-heading-font', '--site-body-font']
  names.forEach((name) => {
    const value = computed.getPropertyValue(name)
    if (value) target.style.setProperty(name, value)
  })
}

function openExplorerModal(L: any, organizationId: string, prepared: PreparedMapProperty[], themeHost: HTMLElement) {
  const existing = document.querySelector<HTMLElement>('.public-map-explorer-backdrop')
  if (existing) {
    existing.querySelector<HTMLElement>('.public-map-explorer-close')?.focus()
    return
  }

  const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const previousOverflow = document.body.style.overflow
  let activeSlug: string | null = null
  let map: any = null
  let markerLayer: any = null
  const markerBySlug = new Map<string, any>()

  const backdrop = document.createElement('div')
  backdrop.className = 'public-map-explorer-backdrop'
  copyThemeVariables(themeHost, backdrop)

  const panel = document.createElement('section')
  panel.className = 'public-map-explorer-modal'
  panel.setAttribute('role', 'dialog')
  panel.setAttribute('aria-modal', 'true')
  panel.setAttribute('aria-labelledby', 'public-map-explorer-title')
  panel.tabIndex = -1

  const header = document.createElement('header')
  header.className = 'public-map-explorer-header'
  const heading = document.createElement('div')
  heading.className = 'public-map-explorer-heading'
  const kicker = document.createElement('span')
  kicker.textContent = 'EXPLORE A REGIÃO'
  const title = document.createElement('h2')
  title.id = 'public-map-explorer-title'
  title.textContent = 'Imóveis no mapa'
  const subtitle = document.createElement('p')
  subtitle.textContent = 'Aproxime, mova o mapa e veja apenas os imóveis disponíveis nesta área.'
  heading.append(kicker, title, subtitle)

  const privacy = document.createElement('span')
  privacy.className = 'public-map-explorer-privacy'
  privacy.textContent = 'Localização aproximada por bairro'

  const close = document.createElement('button')
  close.type = 'button'
  close.className = 'public-map-explorer-close'
  close.setAttribute('aria-label', 'Fechar mapa')
  close.textContent = '×'

  const headerActions = document.createElement('div')
  headerActions.className = 'public-map-explorer-header-actions'
  headerActions.append(privacy, close)
  header.append(heading, headerActions)

  const toolbar = document.createElement('div')
  toolbar.className = 'public-map-explorer-toolbar'
  const typeFilter = makeSelect('Tipo de imóvel', [
    ['all', 'Todos'], ['apartment', 'Apartamento'], ['house', 'Casa'], ['commercial', 'Comercial'], ['land', 'Terreno'], ['studio', 'Studio'], ['other', 'Outros'],
  ])
  const rentFilter = makeSelect('Valor máximo', [
    ['0', 'Qualquer valor'], ['2000', 'Até R$ 2.000'], ['3000', 'Até R$ 3.000'], ['5000', 'Até R$ 5.000'], ['8000', 'Até R$ 8.000'], ['12000', 'Até R$ 12.000'],
  ])
  const bedroomFilter = makeSelect('Quartos', [
    ['0', 'Todos'], ['1', '1+ quarto'], ['2', '2+ quartos'], ['3', '3+ quartos'], ['4', '4+ quartos'],
  ])
  const reset = document.createElement('button')
  reset.type = 'button'
  reset.className = 'public-map-explorer-reset'
  reset.textContent = 'Limpar filtros'
  toolbar.append(typeFilter.label, rentFilter.label, bedroomFilter.label, reset)

  const body = document.createElement('div')
  body.className = 'public-map-explorer-body'
  const mapHost = document.createElement('div')
  mapHost.className = 'public-map-explorer-map'
  const sidebar = document.createElement('aside')
  sidebar.className = 'public-map-explorer-sidebar'
  const sidebarHeader = document.createElement('div')
  sidebarHeader.className = 'public-map-explorer-sidebar-header'
  const resultTitle = document.createElement('strong')
  resultTitle.textContent = 'Imóveis nesta área'
  const resultCount = document.createElement('span')
  sidebarHeader.append(resultTitle, resultCount)
  const list = document.createElement('div')
  list.className = 'public-map-explorer-list'
  sidebar.append(sidebarHeader, list)
  body.append(mapHost, sidebar)

  panel.append(header, toolbar, body)
  backdrop.appendChild(panel)
  document.body.appendChild(backdrop)
  document.body.style.overflow = 'hidden'

  function matchesFilters(entry: PreparedMapProperty) {
    const type = typeFilter.select.value
    const maxRent = Number(rentFilter.select.value || 0)
    const bedrooms = Number(bedroomFilter.select.value || 0)
    if (type !== 'all' && entry.item.property_type !== type) return false
    if (maxRent > 0 && (entry.item.rent_amount == null || Number(entry.item.rent_amount) > maxRent)) return false
    if (bedrooms > 0 && Number(entry.item.bedrooms || 0) < bedrooms) return false
    return true
  }

  function matchingEntries() {
    return prepared.filter(matchesFilters)
  }

  function visibleEntries() {
    const matched = matchingEntries()
    if (!map) return matched
    const bounds = map.getBounds()
    return matched.filter((entry) => bounds.contains(entry.position))
  }

  function createSidebarCard(entry: PreparedMapProperty) {
    const { item } = entry
    const card = document.createElement('article')
    card.className = `public-map-explorer-card${activeSlug === item.slug ? ' is-active' : ''}`
    card.dataset.mapSlug = item.slug
    card.tabIndex = 0

    const media = document.createElement('div')
    media.className = 'public-map-explorer-card-media'
    if (item.cover_photo_url) {
      const image = document.createElement('img')
      image.src = mediaUrl(item.cover_photo_url)
      image.alt = ''
      image.loading = 'lazy'
      media.appendChild(image)
    } else {
      const placeholder = document.createElement('span')
      placeholder.textContent = 'IMÓVEL'
      media.appendChild(placeholder)
    }

    const copy = document.createElement('div')
    copy.className = 'public-map-explorer-card-copy'
    const location = document.createElement('span')
    location.textContent = locationLabel(item)
    const name = document.createElement('strong')
    name.textContent = item.title
    const price = document.createElement('b')
    price.textContent = `${money(item.rent_amount)} / mês`
    const facts = document.createElement('small')
    facts.textContent = `${item.bedrooms} quartos · ${item.parking_spaces} vagas${item.area_m2 != null ? ` · ${item.area_m2} m²` : ''}`
    const link = document.createElement('a')
    link.href = `/site/${organizationId}/imoveis/${item.slug}`
    link.textContent = 'Ver imóvel →'
    link.addEventListener('click', (event) => event.stopPropagation())
    copy.append(location, name, price, facts, link)
    card.append(media, copy)

    const activate = () => {
      activeSlug = item.slug
      if (map) {
        const zoom = Math.max(map.getZoom(), 15)
        map.flyTo(entry.position, zoom, { duration: 0.45 })
      }
      renderMarkers()
      renderSidebar()
      window.setTimeout(() => {
        list.querySelector<HTMLElement>(`[data-map-slug="${CSS.escape(item.slug)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }, 80)
    }
    card.addEventListener('click', activate)
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        activate()
      }
    })
    return card
  }

  function renderSidebar() {
    const visible = visibleEntries()
    const matched = matchingEntries()
    resultCount.textContent = `${visible.length} de ${matched.length} ${matched.length === 1 ? 'imóvel' : 'imóveis'}`
    list.replaceChildren()
    if (!visible.length) {
      const empty = document.createElement('div')
      empty.className = 'public-map-explorer-empty'
      const strong = document.createElement('strong')
      strong.textContent = 'Nenhum imóvel nesta área'
      const text = document.createElement('span')
      text.textContent = 'Afaste o mapa, mova para outra região ou ajuste os filtros.'
      empty.append(strong, text)
      list.appendChild(empty)
      return
    }
    visible.forEach((entry) => list.appendChild(createSidebarCard(entry)))
  }

  function renderMarkers() {
    if (!map || !markerLayer) return
    markerLayer.clearLayers()
    markerBySlug.clear()
    const matched = matchingEntries()
    const zoom = map.getZoom()

    if (zoom < 14) {
      const groups = new Map<string, PreparedMapProperty[]>()
      matched.forEach((entry) => {
        const group = groups.get(entry.groupKey) ?? []
        group.push(entry)
        groups.set(entry.groupKey, group)
      })
      groups.forEach((entries) => {
        if (entries.length === 1) {
          const entry = entries[0]
          const marker = L.marker(entry.position, { icon: priceIcon(L, entry.item, activeSlug === entry.item.slug) }).addTo(markerLayer)
          marker.on('click', () => {
            activeSlug = entry.item.slug
            renderMarkers(); renderSidebar()
            list.querySelector<HTMLElement>(`[data-map-slug="${CSS.escape(entry.item.slug)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
          })
          markerBySlug.set(entry.item.slug, marker)
          return
        }
        const lat = entries.reduce((sum, entry) => sum + entry.position[0], 0) / entries.length
        const lng = entries.reduce((sum, entry) => sum + entry.position[1], 0) / entries.length
        const marker = L.marker([lat, lng], { icon: clusterIcon(L, entries.length) }).addTo(markerLayer)
        marker.on('click', () => {
          const bounds = L.latLngBounds(entries.map((entry) => entry.position))
          map.fitBounds(bounds, { padding: [70, 70], maxZoom: 15 })
        })
      })
      return
    }

    matched.forEach((entry) => {
      const marker = L.marker(entry.position, { icon: priceIcon(L, entry.item, activeSlug === entry.item.slug) }).addTo(markerLayer)
      marker.on('click', () => {
        activeSlug = entry.item.slug
        renderMarkers(); renderSidebar()
        window.setTimeout(() => list.querySelector<HTMLElement>(`[data-map-slug="${CSS.escape(entry.item.slug)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 30)
      })
      markerBySlug.set(entry.item.slug, marker)
    })
  }

  function refresh() {
    renderMarkers()
    renderSidebar()
  }

  function closeModal() {
    document.removeEventListener('keydown', keyHandler, true)
    try { map?.remove() } catch { /* Leaflet já removido */ }
    backdrop.remove()
    document.body.style.overflow = previousOverflow
    previousFocus?.focus()
  }

  function keyHandler(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeModal()
      return
    }
    if (event.key !== 'Tab') return
    const focusables = Array.from(panel.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),select:not([disabled]),input:not([disabled]),[tabindex]:not([tabindex="-1"])')).filter((element) => !element.hasAttribute('hidden'))
    if (!focusables.length) {
      event.preventDefault(); panel.focus(); return
    }
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus()
    }
  }

  close.addEventListener('click', closeModal)
  backdrop.addEventListener('click', (event) => { if (event.target === backdrop) closeModal() })
  document.addEventListener('keydown', keyHandler, true)

  map = L.map(mapHost, { zoomControl: true, scrollWheelZoom: true, attributionControl: true }).setView([-25.4284, -49.2733], 12)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map)
  markerLayer = L.layerGroup().addTo(map)

  const allCoordinates = prepared.map((entry) => entry.position)
  if (allCoordinates.length === 1) map.setView(allCoordinates[0], 14)
  else if (allCoordinates.length > 1) map.fitBounds(L.latLngBounds(allCoordinates), { padding: [70, 70], maxZoom: 13 })

  map.on('moveend', refresh)
  map.on('zoomend', refresh)
  typeFilter.select.addEventListener('change', () => { activeSlug = null; refresh() })
  rentFilter.select.addEventListener('change', () => { activeSlug = null; refresh() })
  bedroomFilter.select.addEventListener('change', () => { activeSlug = null; refresh() })
  reset.addEventListener('click', () => {
    typeFilter.select.value = 'all'
    rentFilter.select.value = '0'
    bedroomFilter.select.value = '0'
    activeSlug = null
    if (allCoordinates.length === 1) map.setView(allCoordinates[0], 14)
    else if (allCoordinates.length > 1) map.fitBounds(L.latLngBounds(allCoordinates), { padding: [70, 70], maxZoom: 13 })
    refresh()
  })

  window.setTimeout(() => {
    map.invalidateSize()
    refresh()
    close.focus()
  }, 80)
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
    mapHost.setAttribute('aria-label', 'Mapa de imóveis. Clique no mapa para ampliar.')
    const cardHost = document.createElement('div')
    cardHost.className = 'public-live-map-card-host'
    const badge = document.createElement('span')
    badge.className = 'public-live-map-privacy'
    badge.textContent = 'Localização aproximada por bairro'
    const expand = document.createElement('button')
    expand.type = 'button'
    expand.className = 'public-live-map-expand'
    expand.textContent = 'Explorar mapa'
    const loading = document.createElement('div')
    loading.className = 'public-live-map-loading'
    loading.textContent = 'Localizando imóveis…'
    shell.append(mapHost, cardHost, badge, expand, loading)
    target.replaceChildren(shell)

    const map = L.map(mapHost, { zoomControl: true, scrollWheelZoom: false, attributionControl: true }).setView([-25.4284, -49.2733], 12)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map)

    const coordinates: Coordinate[] = []
    const prepared: PreparedMapProperty[] = []
    let firstProperty: PublicMapProperty | null = null

    for (const [groupKey, properties] of groups.entries()) {
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
        prepared.push({ item, position, groupKey, neighborhood: String(item.address.neighborhood || '') })
        const marker = L.marker(position, { icon: priceIcon(L, item) }).addTo(map)
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

    const themeHost = target.closest<HTMLElement>('.public-site-premium') ?? target
    const openExplorer = () => openExplorerModal(L, organizationId, prepared, themeHost)
    expand.addEventListener('click', (event) => { event.stopPropagation(); openExplorer() })
    mapHost.addEventListener('click', (event) => {
      const element = event.target instanceof Element ? event.target : null
      if (element?.closest('.leaflet-control, .leaflet-marker-icon, .leaflet-popup-pane')) return
      openExplorer()
    })

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
