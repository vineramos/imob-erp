import { ExternalLink, Globe2, MapPin } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiRequest } from '../../api/client'
import type { Property, PublicationReadiness } from '../../api/types'
import './property-map-publication.css'

type Props = { permissions: string[] }
type MountState = {
  locationHost: HTMLElement
  publicationHost: HTMLElement
  property: Property
} | null

const channels = [
  { key: 'olx', mark: 'OLX', label: 'OLX' },
  { key: 'zap', mark: 'ZAP', label: 'ZAP Imóveis' },
  { key: 'vivareal', mark: 'VR', label: 'Viva Real' },
  { key: 'meta', mark: 'META', label: 'Facebook / Instagram' },
] as const

function propertyCodeFromDetail(): string | null {
  const label = document.querySelector<HTMLElement>('.property-detail-topline > span')?.textContent ?? ''
  return label.match(/#(\d{6})/)?.[1] ?? null
}

function addressQuery(property: Property) {
  const address = property.address
  return [address.street, address.number, address.neighborhood, address.city, address.state, address.postal_code, 'Brasil'].filter(Boolean).join(', ')
}

function displayAddress(property: Property) {
  const address = property.address
  return [address.street, address.number, address.neighborhood, address.city].filter(Boolean).join(', ') || 'Endereço não informado'
}

function locationLabel(property: Property) {
  const address = property.address
  const cityState = [address.city, address.state].filter(Boolean).join('/')
  return [address.neighborhood, cityState].filter(Boolean).join(' · ') || 'Localização não informada'
}

export function PropertyMapPublicationMount({ permissions }: Props) {
  const [mount, setMount] = useState<MountState>(null)
  const [readiness, setReadiness] = useState<PublicationReadiness | null>(null)
  const [saving, setSaving] = useState(false)
  const canPublish = permissions.includes('properties.publish')

  useEffect(() => {
    let active = true
    let hiddenLocation: HTMLElement | null = null
    let hiddenPublication: HTMLElement | null = null
    let locationHost: HTMLElement | null = null
    let publicationHost: HTMLElement | null = null
    let mountedCode: string | null = null
    let resolving = false

    function cleanup() {
      if (hiddenLocation) hiddenLocation.style.display = ''
      if (hiddenPublication) hiddenPublication.style.display = ''
      hiddenLocation = null
      hiddenPublication = null
      locationHost?.remove()
      publicationHost?.remove()
      locationHost = null
      publicationHost = null
      mountedCode = null
      if (active) { setMount(null); setReadiness(null) }
    }

    async function sync() {
      if (resolving) return
      const locationPanel = document.querySelector<HTMLElement>('.property-detail-workspace .property-location-panel')
      const publicationPanel = document.querySelector<HTMLElement>('.property-detail-workspace .property-publication-panel')
      const code = propertyCodeFromDetail()
      if (!locationPanel || !publicationPanel || !code) { if (locationHost || publicationHost) cleanup(); return }
      if (hiddenLocation === locationPanel && hiddenPublication === publicationPanel && locationHost?.isConnected && publicationHost?.isConnected && mountedCode === code) return

      resolving = true
      try {
        const properties = await apiRequest<Property[]>('/properties')
        const property = properties.find((item) => item.code === code)
        if (!active || !property) return
        const readinessResult = await Promise.allSettled([apiRequest<PublicationReadiness>(`/properties/${property.id}/publication-readiness`)])
        cleanup()
        hiddenLocation = locationPanel
        hiddenPublication = publicationPanel
        mountedCode = code
        locationPanel.style.display = 'none'
        publicationPanel.style.display = 'none'

        locationHost = document.createElement('div')
        locationHost.className = 'property-map-publication-location-host'
        locationHost.style.display = 'contents'
        publicationHost = document.createElement('div')
        publicationHost.className = 'property-map-publication-channel-host'
        publicationHost.style.display = 'contents'
        locationPanel.parentElement?.insertBefore(locationHost, locationPanel.nextSibling)
        publicationPanel.parentElement?.insertBefore(publicationHost, publicationPanel.nextSibling)

        if (active && locationHost && publicationHost) {
          setMount({ locationHost, publicationHost, property })
          setReadiness(readinessResult[0].status === 'fulfilled' ? readinessResult[0].value : null)
        }
      } finally { resolving = false }
    }

    const observer = new MutationObserver(() => { void sync() })
    observer.observe(document.body, { subtree: true, childList: true })
    void sync()
    return () => {
      active = false
      observer.disconnect()
      if (hiddenLocation) hiddenLocation.style.display = ''
      if (hiddenPublication) hiddenPublication.style.display = ''
      locationHost?.remove()
      publicationHost?.remove()
    }
  }, [])

  async function refreshState() {
    if (!mount) return
    try {
      const [properties, nextReadiness] = await Promise.all([
        apiRequest<Property[]>('/properties'),
        apiRequest<PublicationReadiness>(`/properties/${mount.property.id}/publication-readiness`),
      ])
      const property = properties.find((item) => item.id === mount.property.id)
      if (property) setMount((current) => current ? { ...current, property } : current)
      setReadiness(nextReadiness)
    } catch { /* o card principal já trata erros operacionais */ }
  }

  function openCommercialTab() {
    Array.from(document.querySelectorAll<HTMLButtonElement>('.property-detail-tabs button'))
      .find((button) => button.textContent?.trim() === 'Comercial')?.click()
  }

  async function triggerSitePublication() {
    if (!mount || !canPublish || saving) return
    if (!mount.property.publication_enabled && readiness && !readiness.ready) { openCommercialTab(); return }
    const headerButton = Array.from(document.querySelectorAll<HTMLButtonElement>('.property-detail-actions button'))
      .find((button) => /Publicar imóvel|Retirar do site/.test(button.textContent ?? ''))
    if (!headerButton) return
    setSaving(true)
    headerButton.click()
    window.setTimeout(() => { void refreshState().finally(() => setSaving(false)) }, 900)
  }

  const mapData = useMemo(() => {
    if (!mount) return null
    const query = addressQuery(mount.property)
    return {
      query,
      embed: query ? `https://www.google.com/maps?q=${encodeURIComponent(query)}&output=embed` : '',
      external: query ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}` : '',
    }
  }, [mount])

  if (!mount) return null
  const property = mount.property
  const published = property.publication_enabled
  const ready = readiness?.ready ?? false
  const completed = readiness?.checklist.filter((item) => item.ok).length ?? 0
  const total = readiness?.checklist.length ?? 0

  const locationPanel = <article className="panel property-location-panel property-location-live-panel">
    <div className="property-panel-heading"><h2>Localização</h2>{mapData?.external && <a className="property-map-link" href={mapData.external} target="_blank" rel="noreferrer">Ver no mapa <ExternalLink size={11}/></a>}</div>
    {mapData?.embed ? <div className="property-map-frame"><iframe title={`Mapa do imóvel ${property.code}`} src={mapData.embed} loading="lazy" allowFullScreen referrerPolicy="no-referrer-when-downgrade" /></div> : <div className="property-map-unavailable"><MapPin size={25}/><span>Endereço insuficiente para exibir o mapa.</span></div>}
    <strong>{locationLabel(property)}</strong>
    <span>{displayAddress(property)}</span>
  </article>

  const publicationPanel = <article className="panel property-publication-panel property-publication-live-panel">
    <div className="property-panel-heading"><h2>Publicação</h2></div>
    <div className="property-publication-list">
      <div className="property-publication-row">
        <span className="property-channel-mark site"><Globe2 size={13}/></span>
        <div><strong>Site próprio</strong><small>Anúncio público da imobiliária</small></div>
        <span className={`property-channel-status ${published ? 'published' : ready ? 'ready' : 'offline'}`}><i/>{published ? 'Publicado' : ready ? 'Pronto' : 'Não publicado'}</span>
        {canPublish ? <button className="property-channel-action" type="button" disabled={saving} onClick={() => void triggerSitePublication()}>{published ? 'Retirar' : ready ? 'Publicar' : 'Revisar'}</button> : <span className="property-channel-action muted">Consulta</span>}
      </div>
      {channels.map((channel) => <div className="property-publication-row" key={channel.key}>
        <span className={`property-channel-mark ${channel.key}`}>{channel.mark}</span>
        <div><strong>{channel.label}</strong><small>Canal externo</small></div>
        <span className="property-channel-status offline"><i/>Não integrado</span>
        <span className="property-channel-action muted">Em breve</span>
      </div>)}
    </div>
    {readiness && <div className="property-publication-readiness"><span>{completed}/{total} itens do checklist concluídos</span><button type="button" onClick={openCommercialTab}>Ver checklist</button></div>}
  </article>

  return <>{createPortal(locationPanel, mount.locationHost)}{createPortal(publicationPanel, mount.publicationHost)}</>
}
