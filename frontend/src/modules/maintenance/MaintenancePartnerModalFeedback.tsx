import { useEffect } from 'react'

export function MaintenancePartnerModalFeedback() {
  useEffect(() => {
    let capturedText = ''
    let localAlert: HTMLDivElement | null = null

    const sync = () => {
      const modalBody = document.querySelector<HTMLElement>('.maintenance-partner-modal .portfolio-modal-body')
      const globalAlert = document.querySelector<HTMLElement>('.maintenance-workspace > .danger-alert')

      if (modalBody && globalAlert) {
        const text = (globalAlert.textContent ?? '').trim()
        if (!text) return
        capturedText = text
        globalAlert.dataset.partnerModalCaptured = 'true'
        globalAlert.style.display = 'none'

        if (!localAlert || !localAlert.isConnected) {
          localAlert = document.createElement('div')
          localAlert.className = 'form-alert danger-alert maintenance-partner-modal-alert'
          localAlert.setAttribute('role', 'alert')
          localAlert.style.marginBottom = '12px'
          modalBody.prepend(localAlert)
        }
        localAlert.textContent = text
        return
      }

      if (!modalBody && localAlert) {
        localAlert.remove()
        localAlert = null
      }

      if (!modalBody && globalAlert?.dataset.partnerModalCaptured === 'true') {
        const text = (globalAlert.textContent ?? '').trim()
        if (text && text !== capturedText) {
          delete globalAlert.dataset.partnerModalCaptured
          globalAlert.style.display = ''
          capturedText = ''
        } else {
          globalAlert.style.display = 'none'
        }
      }
    }

    const observer = new MutationObserver(sync)
    observer.observe(document.body, { subtree: true, childList: true, characterData: true })
    sync()

    return () => {
      observer.disconnect()
      localAlert?.remove()
      const globalAlert = document.querySelector<HTMLElement>('.maintenance-workspace > .danger-alert[data-partner-modal-captured="true"]')
      if (globalAlert) {
        delete globalAlert.dataset.partnerModalCaptured
        globalAlert.style.display = ''
      }
    }
  }, [])

  return null
}
