function visible(element: HTMLElement): boolean {
  const style = window.getComputedStyle(element)
  return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0'
}

function clickClose(dialog: HTMLElement): boolean {
  const explicit = dialog.querySelector<HTMLButtonElement>(
    'button[aria-label="Fechar"], button[aria-label="fechar"], button[title="Fechar"], .portfolio-modal-close, .modal-close',
  ) ?? dialog.querySelector<HTMLButtonElement>(':scope > [class*="header"] button:last-of-type')
  if (explicit?.disabled) return false
  if (explicit) {
    explicit.click()
    return true
  }
  const cancel = Array.from(dialog.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
    !button.disabled && /^(cancelar|fechar)$/i.test((button.textContent || '').trim()),
  )
  if (cancel) {
    cancel.click()
    return true
  }
  return false
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
    if (backdrop) {
      const dialog = backdrop.querySelector<HTMLElement>('[role="dialog"], [class*="modal"], [class*="dialog"]')
      if (dialog && clickClose(dialog)) {
        event.preventDefault()
        event.stopPropagation()
        return
      }
      event.preventDefault()
      event.stopPropagation()
      backdrop.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
      backdrop.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
      return
    }

    // Alguns formulários antigos foram convertidos visualmente em dialogs durante
    // a padronização. Até todos usarem backdrop React, ESC continua previsível.
    const floating = Array.from(
      document.querySelectorAll<HTMLElement>('.contract-form, .inspection-form, .capture-form-modal'),
    ).filter(visible).at(-1)
    if (floating && clickClose(floating)) {
      event.preventDefault()
      event.stopPropagation()
    }
  }

  window.addEventListener('keydown', onKeyDown, true)
  return () => window.removeEventListener('keydown', onKeyDown, true)
}
