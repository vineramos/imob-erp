import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { PropertyGallery } from './PropertyGallery'

type Props = { permissions: string[] }
type MountState = { host: HTMLElement; propertyId: string } | null

function propertyFromDetail() {
  const detail = document.querySelector<HTMLElement>('.property-detail-workspace')
  return { id: detail?.dataset.propertyId ?? null, code: detail?.dataset.propertyCode ?? null }
}

export function PropertyGalleryMount({ permissions }: Props) {
  const [mount, setMount] = useState<MountState>(null)
  const canManage = permissions.includes('properties.edit')

  useEffect(() => {
    let active = true
    let hiddenPanel: HTMLElement | null = null
    let summaryLayout: HTMLElement | null = null
    let host: HTMLElement | null = null
    let mountedCode: string | null = null
    let mountedMode: 'summary' | 'commercial' | null = null
    let resolving = false

    function cleanupMount() {
      if (hiddenPanel) hiddenPanel.style.display = ''
      hiddenPanel = null
      summaryLayout?.classList.remove('property-summary-grid-with-gallery')
      summaryLayout = null
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
      const property = propertyFromDetail()
      const code = property.code
      const mode: 'summary' | 'commercial' | null = summaryGrid ? 'summary' : commercialPanel ? 'commercial' : null
      if (!mode || !code) { if (host) cleanupMount(); return }
      if (host?.isConnected && mountedCode === code && mountedMode === mode) return

      resolving = true
      try {
        if (!active || !property.id) return
        cleanupMount()
        mountedCode = code
        mountedMode = mode
        host = document.createElement('div')
        host.className = `property-gallery-mount property-gallery-${mode}-mount`
        host.style.display = 'contents'

        if (mode === 'summary' && summaryGrid) {
          summaryLayout = summaryGrid
          summaryGrid.classList.add('property-summary-grid-with-gallery')
          summaryGrid.insertBefore(host, summaryGrid.firstChild)
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
    return () => {
      active = false
      observer.disconnect()
      if (hiddenPanel) hiddenPanel.style.display = ''
      summaryLayout?.classList.remove('property-summary-grid-with-gallery')
      host?.remove()
    }
  }, [])

  function refreshLinkedDetail() {
    const refreshButton = Array.from(document.querySelectorAll<HTMLButtonElement>('.property-detail-actions button'))
      .find((button) => button.textContent?.trim().startsWith('Atualizar'))
    refreshButton?.click()
  }

  return mount ? createPortal(<PropertyGallery propertyId={mount.propertyId} canManage={canManage} onChanged={refreshLinkedDetail}/>, mount.host) : null
}
