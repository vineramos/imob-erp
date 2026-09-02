import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiRequest } from '../../api/client'
import type { Property } from '../../api/types'
import { PropertyGallery } from './PropertyGallery'

type Props = { permissions: string[] }
type MountState = { host: HTMLElement; propertyId: string } | null

function propertyCodeFromDetail(): string | null {
  const label = document.querySelector<HTMLElement>('.property-detail-topline > span')?.textContent ?? ''
  const match = label.match(/#(\d{6})/)
  return match?.[1] ?? null
}

export function PropertyGalleryMount({ permissions }: Props) {
  const [mount, setMount] = useState<MountState>(null)
  const canManage = permissions.includes('properties.edit')

  useEffect(() => {
    let active = true
    let properties: Property[] | null = null
    let hiddenPanel: HTMLElement | null = null
    let host: HTMLElement | null = null
    let mountedCode: string | null = null
    let mountedMode: 'summary' | 'commercial' | null = null
    let resolving = false

    function cleanupMount() {
      if (hiddenPanel) hiddenPanel.style.display = ''
      hiddenPanel = null
      host?.remove()
      host = null
      mountedCode = null
      mountedMode = null
      if (active) setMount(null)
    }

    async function sync() {
      if (resolving) return
      const summaryGrid = document.querySelector<HTMLElement>('.property-detail-workspace .property-summary-grid')
      const commercialPanel = document.querySelector<HTMLElement>('.property-detail-workspace .property-media-panel')
      const code = propertyCodeFromDetail()
      const mode: 'summary' | 'commercial' | null = summaryGrid ? 'summary' : commercialPanel ? 'commercial' : null
      if (!mode || !code) { if (host) cleanupMount(); return }
      if (host?.isConnected && mountedCode === code && mountedMode === mode) return

      resolving = true
      try {
        properties ??= await apiRequest<Property[]>('/properties')
        const property = properties.find((item) => item.code === code)
        if (!active || !property) return
        cleanupMount()
        mountedCode = code
        mountedMode = mode
        host = document.createElement('div')
        host.className = `property-gallery-mount property-gallery-${mode}-mount`
        host.style.display = 'contents'

        if (mode === 'summary' && summaryGrid) {
          summaryGrid.parentElement?.insertBefore(host, summaryGrid)
        } else if (commercialPanel) {
          hiddenPanel = commercialPanel
          commercialPanel.style.display = 'none'
          commercialPanel.parentElement?.insertBefore(host, commercialPanel.nextSibling)
        }

        if (active && host?.isConnected) setMount({ host, propertyId: property.id })
      } finally { resolving = false }
    }

    const observer = new MutationObserver(() => { void sync() })
    observer.observe(document.body, { subtree: true, childList: true })
    void sync()
    return () => { active = false; observer.disconnect(); if (hiddenPanel) hiddenPanel.style.display = ''; host?.remove() }
  }, [])

  function refreshLinkedDetail() {
    const refreshButton = Array.from(document.querySelectorAll<HTMLButtonElement>('.property-detail-actions button'))
      .find((button) => button.textContent?.trim().startsWith('Atualizar'))
    refreshButton?.click()
  }

  return mount ? createPortal(<PropertyGallery propertyId={mount.propertyId} canManage={canManage} onChanged={refreshLinkedDetail}/>, mount.host) : null
}
