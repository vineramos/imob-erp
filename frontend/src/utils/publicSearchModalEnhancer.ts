import { publicApiRequest } from '../api/client'
import { runtimeConfig } from '../config/runtime'

type PublicPhoto = {
  id: string
  caption: string | null
  position: number
  is_cover: boolean
  content_url: string
}

type MapPosition = {
  latitude: number
  longitude: number
  precision: 'exact' | 'street' | 'postal_code'
}

type Coordinate = [number, number]

type ModalController = {
  modal: HTMLElement
  body: HTMLElement
  list: HTMLElement
  mapPane: HTMLElement
  mapCanvas: HTMLElement
  mapCount: HTMLElement
  listButton: HTMLButtonElement
  mapButton: HTMLButtonElement
  mode: 'list' | 'map'
  map: any | null
  markerLayer: any | null
  coordinates: Map<string, Coordinate>
  refreshTimer: number | null
}

declare global {
  interface Window {
    L?: any
  }
}

const LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
const LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
const controllers = new WeakMap<HTMLElement, ModalController>()
const photoCache = new Map<string, Promise<PublicPhoto[]>>()
const positionCache = new Map<string, Promise<MapPosition | null>>()
let leafletPromise: Promise<any> | null = null
let installed = false

function organizationIdFromPath() {
  const match = window.location.pathname.match(/^\/site\/([^/]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

function slugFromCard(card: HTMLElement) {
  const href = card.getAttribute('href') || card.querySelector<HTMLAnchorElement>('a[href*="/imoveis/"]')?.getAttribute('href') || ''
  const match = href.match(/\/imoveis\/([^/?#]+)/)
  return match ? decodeURIComponent(match[1]) : null
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
      if (window.L) { resolve(window.L); return }
      existing.addEventListener('load', () => window.L ? resolve(window.L) : reject(new Error('Leaflet indisponível.')), { once: true })
      existing.addEventListener('error', () => reject(new Error('Falha ao carregar o mapa.')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.src = LEAFLET_JS
    script.crossOrigin = ''
    script.dataset.imobSearchLeaflet = 'true'
    script.onload = () => window.L ? resolve(window.L) : reject(new Error('Leaflet indisponível.'))
    script.onerror = () => reject(new Error('Falha ao carregar o mapa.'))
    document.head.appendChild(script)
  })

  return leafletPromise
}

function loadPhotos(organizationId: string, slug: string) {
  const key = `${organizationId}:${slug}`
  const cached = photoCache.get(key)
  if (cached) return cached
  const request = publicApiRequest<PublicPhoto[]>(`/public/sites/${organizationId}/properties/${encodeURIComponent(slug)}/photos`)
    .then((items) => [...items].sort((a, b) => Number(b.is_cover) - Number(a.is_cover) || a.position - b.position))
    .catch(() => [])
  photoCache.set(key, request)
  return request
}

function loadPosition(organizationId: string, slug: string) {
  const key = `${organizationId}:${slug}`
  const cached = positionCache.get(key)
  if (cached) return cached
  const request = publicApiRequest<MapPosition>(`/public/sites/${organizationId}/properties/${encodeURIComponent(slug)}/map-position`)
    .then((position) => Number.isFinite(Number(position.latitude)) && Number.isFinite(Number(position.longitude)) ? position : null)
    .catch(() => null)
  positionCache.set(key, request)
  return request
}

function stopCardNavigation(event: Event) {
  event.preventDefault()
  event.stopPropagation()
}

async function enhanceCarousel(card: HTMLElement, organizationId: string) {
  if (card.dataset.searchCarousel === 'ready' || card.dataset.searchCarousel === 'loading') return
  const slug = slugFromCard(card)
  const media = card.querySelector<HTMLElement>('.public-search-result-media')
  if (!slug || !media) return

  card.dataset.searchCarousel = 'loading'
  const photos = await loadPhotos(organizationId, slug)
  if (!card.isConnected) return
  if (!photos.length) { card.dataset.searchCarousel = 'ready'; return }

  let index = Math.max(0, photos.findIndex((photo) => photo.is_cover))
  let image = media.querySelector<HTMLImageElement>('img')
  if (!image) {
    image = document.createElement('img')
    image.className = 'public-search-carousel-image'
    media.querySelector<HTMLElement>('.public-property-visual')?.setAttribute('hidden', 'true')
    media.appendChild(image)
  }

  image.src = mediaUrl(photos[index].content_url)
  image.alt = photos[index].caption || card.querySelector('h3')?.textContent || 'Foto do imóvel'

  if (photos.length > 1) {
    const previous = document.createElement('button')
    previous.type = 'button'
    previous.className = 'public-search-photo-arrow previous'
    previous.setAttribute('aria-label', 'Foto anterior')
    previous.innerHTML = '&#8249;'

    const next = document.createElement('button')
    next.type = 'button'
    next.className = 'public-search-photo-arrow next'
    next.setAttribute('aria-label', 'Próxima foto')
    next.innerHTML = '&#8250;'

    const counter = document.createElement('span')
    counter.className = 'public-search-photo-counter'

    const render = () => {
      const photo = photos[index]
      image!.src = mediaUrl(photo.content_url)
      image!.alt = photo.caption || card.querySelector('h3')?.textContent || 'Foto do imóvel'
      counter.textContent = `${index + 1} / ${photos.length}`
    }

    previous.addEventListener('click', (event) => {
      stopCardNavigation(event)
      index = (index - 1 + photos.length) % photos.length
      render()
    })
    next.addEventListener('click', (event) => {
      stopCardNavigation(event)
      index = (index + 1) % photos.length
      render()
    })

    media.append(previous, next, counter)
    render()
  }

  card.dataset.searchCarousel = 'ready'
}

function resultCards(controller: ModalController) {
  return Array.from(controller.list.querySelectorAll<HTMLElement>('.public-search-result-card'))
}

function clearMapFiltering(controller: ModalController) {
  resultCards(controller).forEach((card) => card.classList.remove('is-outside-map', 'is-map-selected'))
}

function updateVisibleCards(controller: ModalController) {
  if (!controller.map || controller.mode !== 'map') return
  const bounds = controller.map.getBounds()
  let visible = 0
  resultCards(controller).forEach((card) => {
    const slug = slugFromCard(card)
    const coordinate = slug ? controller.coordinates.get(slug) : null
    const isVisible = coordinate ? bounds.contains(coordinate) : true
    card.classList.toggle('is-outside-map', !isVisible)
    if (isVisible) visible += 1
  })
  controller.mapCount.textContent = `${visible} ${visible === 1 ? 'imóvel nesta área' : 'imóveis nesta área'}`
}

function priceLabel(card: HTMLElement) {
  return card.querySelector<HTMLElement>('.public-search-result-price > strong')?.textContent?.trim() || 'Imóvel'
}

function priceIcon(L: any, label: string, active = false) {
  const safe = label.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char)
  return L.divIcon({
    className: `public-search-map-price${active ? ' is-active' : ''}`,
    html: `<span>${safe}</span>`,
    iconSize: [86, 32],
    iconAnchor: [43, 16],
  })
}

async function renderMap(controller: ModalController) {
  if (controller.mode !== 'map') return
  const organizationId = organizationIdFromPath()
  if (!organizationId) return
  const cards = resultCards(controller)
  controller.mapCount.textContent = 'Carregando imóveis no mapa...'

  try {
    const L = await ensureLeaflet()
    if (!controller.modal.isConnected || controller.mode !== 'map') return

    if (!controller.map) {
      controller.map = L.map(controller.mapCanvas, { zoomControl: true, scrollWheelZoom: true }).setView([-25.4284, -49.2733], 12)
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors',
      }).addTo(controller.map)
      controller.markerLayer = L.layerGroup().addTo(controller.map)
      controller.map.on('moveend zoomend', () => updateVisibleCards(controller))
    }

    controller.markerLayer.clearLayers()
    controller.coordinates.clear()
    const bounds: Coordinate[] = []

    await Promise.all(cards.map(async (card) => {
      const slug = slugFromCard(card)
      if (!slug) return
      const position = await loadPosition(organizationId, slug)
      if (!position || !controller.modal.isConnected) return
      const coordinate: Coordinate = [Number(position.latitude), Number(position.longitude)]
      controller.coordinates.set(slug, coordinate)
      bounds.push(coordinate)

      const marker = L.marker(coordinate, { icon: priceIcon(L, priceLabel(card)) })
      marker.on('click', () => {
        cards.forEach((item) => item.classList.remove('is-map-selected'))
        card.classList.add('is-map-selected')
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      })
      marker.addTo(controller.markerLayer)
    }))

    if (bounds.length) {
      controller.map.fitBounds(bounds, { padding: [42, 42], maxZoom: 16 })
      window.setTimeout(() => updateVisibleCards(controller), 100)
    } else {
      controller.mapCount.textContent = 'Nenhum imóvel desta busca possui posição disponível.'
    }
    window.setTimeout(() => controller.map?.invalidateSize(), 50)
  } catch {
    controller.mapCount.textContent = 'Não foi possível carregar o mapa agora.'
  }
}

function setMode(controller: ModalController, mode: 'list' | 'map') {
  controller.mode = mode
  controller.body.classList.toggle('is-map-view', mode === 'map')
  controller.listButton.classList.toggle('active', mode === 'list')
  controller.mapButton.classList.toggle('active', mode === 'map')
  controller.listButton.setAttribute('aria-pressed', String(mode === 'list'))
  controller.mapButton.setAttribute('aria-pressed', String(mode === 'map'))
  controller.mapPane.hidden = mode !== 'map'
  if (mode === 'map') void renderMap(controller)
  else clearMapFiltering(controller)
}

function scheduleRefresh(controller: ModalController) {
  if (controller.refreshTimer != null) window.clearTimeout(controller.refreshTimer)
  controller.refreshTimer = window.setTimeout(() => {
    controller.refreshTimer = null
    const organizationId = organizationIdFromPath()
    if (organizationId) resultCards(controller).forEach((card) => void enhanceCarousel(card, organizationId))
    if (controller.mode === 'map') void renderMap(controller)
  }, 80)
}

function enhanceModal(modal: HTMLElement) {
  const existing = controllers.get(modal)
  if (existing) { scheduleRefresh(existing); return }

  const body = modal.querySelector<HTMLElement>('.public-search-modal-body')
  const summary = modal.querySelector<HTMLElement>('.public-search-modal-summary')
  const list = modal.querySelector<HTMLElement>('.public-search-results-list')
  if (!body || !summary || !list) return

  const viewToggle = document.createElement('div')
  viewToggle.className = 'public-search-view-toggle'
  const listButton = document.createElement('button')
  listButton.type = 'button'
  listButton.textContent = 'Lista'
  listButton.className = 'active'
  listButton.setAttribute('aria-pressed', 'true')
  const mapButton = document.createElement('button')
  mapButton.type = 'button'
  mapButton.textContent = 'Mapa'
  mapButton.setAttribute('aria-pressed', 'false')
  viewToggle.append(listButton, mapButton)
  summary.appendChild(viewToggle)

  const mapPane = document.createElement('div')
  mapPane.className = 'public-search-map-pane'
  mapPane.hidden = true
  const mapCanvas = document.createElement('div')
  mapCanvas.className = 'public-search-map-canvas'
  const mapCount = document.createElement('span')
  mapCount.className = 'public-search-map-count'
  mapCount.textContent = 'Carregando mapa...'
  const privacy = document.createElement('span')
  privacy.className = 'public-search-map-privacy'
  privacy.textContent = 'Número do endereço oculto'
  mapPane.append(mapCanvas, mapCount, privacy)
  body.insertBefore(mapPane, list)

  const controller: ModalController = {
    modal, body, list, mapPane, mapCanvas, mapCount, listButton, mapButton,
    mode: 'list', map: null, markerLayer: null, coordinates: new Map(), refreshTimer: null,
  }
  controllers.set(modal, controller)

  listButton.addEventListener('click', () => setMode(controller, 'list'))
  mapButton.addEventListener('click', () => setMode(controller, 'map'))

  const organizationId = organizationIdFromPath()
  if (organizationId) resultCards(controller).forEach((card) => void enhanceCarousel(card, organizationId))
}

function scan(root: ParentNode = document) {
  root.querySelectorAll<HTMLElement>('.public-search-modal').forEach(enhanceModal)
}

export function installPublicSearchModalEnhancer() {
  if (installed) return
  installed = true
  scan()
  const observer = new MutationObserver((mutations) => {
    const modals = new Set<HTMLElement>()
    mutations.forEach((mutation) => {
      if (!(mutation.target instanceof Element)) return
      const modal = mutation.target.closest<HTMLElement>('.public-search-modal')
      if (modal) modals.add(modal)
      mutation.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return
        if (node.matches('.public-search-modal')) modals.add(node as HTMLElement)
        node.querySelectorAll<HTMLElement>('.public-search-modal').forEach((item) => modals.add(item))
      })
    })
    modals.forEach(enhanceModal)
  })
  observer.observe(document.body, { childList: true, subtree: true })
}
