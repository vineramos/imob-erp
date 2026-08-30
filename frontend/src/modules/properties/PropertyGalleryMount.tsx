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
    let resolving = false

    function cleanupMount() {
      if (hiddenPanel) hiddenPanel.style.display = ''
      hiddenPanel = null
      host?.remove()
      host = null
      mountedCode = null
      if (active) setMount(null)
    }

    async function sync() {
      if (resolving) return
      const panel = document.querySelector<HTMLElement>('.property-detail-workspace .property-media-panel')
      const code = propertyCodeFromDetail()
      if (!panel || !code) { if (host) cleanupMount(); return }
      if (hiddenPanel === panel && host?.isConnected && mountedCode === code) return

      resolving = true
      try {
        properties ??= await apiRequest<Property[]>('/properties')
        const property = properties.find((item) => item.code === code)
        if (!active || !property) return
        cleanupMount()
        hiddenPanel = panel
        mountedCode = code
        panel.style.display = 'none'
        host = document.createElement('div')
        host.className = 'property-gallery-mount'
        host.style.display = 'contents'
        panel.parentElement?.insertBefore(host, panel.nextSibling)
        if (active && host) setMount({ host, propertyId: property.id })
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
