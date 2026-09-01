function visible(element: HTMLElement): boolean {
  const style = window.getComputedStyle(element)
  return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0'
}

export function installGlobalModalEscape(): () => void {
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== 'Escape' || event.defaultPrevented) return

    const candidates = Array.from(
      document.querySelectorAll<HTMLElement>(
        '[class*="modal-backdrop"], [class*="modal-overlay"], [class*="dialog-backdrop"], [data-modal-backdrop]',
      ),
    ).filter(visible)
    const backdrop = candidates.at(-1)
    if (!backdrop) return

    const dialog = backdrop.querySelector<HTMLElement>('[role="dialog"], [class*="modal"], [class*="dialog"]')
    const closeButton = dialog?.querySelector<HTMLButtonElement>(
      'button[aria-label="Fechar"], button[aria-label="fechar"], button[title="Fechar"], .portfolio-modal-close, .modal-close',
    ) ?? dialog?.querySelector<HTMLButtonElement>(':scope > [class*="header"] button:last-of-type')

    if (closeButton?.disabled) return
    event.preventDefault()
    event.stopPropagation()

    if (closeButton) {
      closeButton.click()
      return
    }

    backdrop.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    backdrop.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
  }

  window.addEventListener('keydown', onKeyDown, true)
  return () => window.removeEventListener('keydown', onKeyDown, true)
}
