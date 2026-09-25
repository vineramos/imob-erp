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

function activeDialog(): HTMLElement | null {
  const candidates = Array.from(
    document.querySelectorAll<HTMLElement>(
      '[class*="modal-backdrop"], [class*="modal-overlay"], [class*="dialog-backdrop"], [data-modal-backdrop]',
    ),
  ).filter(visible)
  const backdrop = candidates.at(-1)
  if (backdrop) {
    return backdrop.querySelector<HTMLElement>('[role="dialog"], [class*="modal"], [class*="dialog"]')
  }

  // Alguns formulários antigos foram convertidos visualmente em dialogs durante
  // a padronização. Até todos usarem backdrop React, o comportamento de teclado
  // continua previsível nesses formulários também.
  return Array.from(
    document.querySelectorAll<HTMLElement>('.contract-form, .inspection-form, .capture-form-modal'),
  ).filter(visible).at(-1) ?? null
}

function focusableElements(dialog: HTMLElement): HTMLElement[] {
  const selector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',')

  return Array.from(dialog.querySelectorAll<HTMLElement>(selector)).filter((element) => {
    if (!visible(element)) return false
    const style = window.getComputedStyle(element)
    return style.pointerEvents !== 'none'
  })
}

function keepTabInsideDialog(event: KeyboardEvent, dialog: HTMLElement): boolean {
  if (event.key !== 'Tab') return false
  const focusables = focusableElements(dialog)
  if (focusables.length === 0) {
    event.preventDefault()
    if (!dialog.hasAttribute('tabindex')) dialog.setAttribute('tabindex', '-1')
    dialog.focus({ preventScroll: true })
    return true
  }

  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const current = document.activeElement

  if (!dialog.contains(current)) {
    event.preventDefault()
    ;(event.shiftKey ? last : first).focus({ preventScroll: true })
    return true
  }

  if (event.shiftKey && current === first) {
    event.preventDefault()
    last.focus({ preventScroll: true })
    return true
  }
  if (!event.shiftKey && current === last) {
    event.preventDefault()
    first.focus({ preventScroll: true })
    return true
  }
  return false
}

export function installGlobalModalEscape(): () => void {
  const onKeyDown = (event: KeyboardEvent) => {
    const dialog = activeDialog()

    if (dialog && keepTabInsideDialog(event, dialog)) {
      event.stopPropagation()
      return
    }

    if (event.key !== 'Escape' || event.defaultPrevented) return

    if (dialog && clickClose(dialog)) {
      event.preventDefault()
      event.stopPropagation()
      return
    }

    const candidates = Array.from(
      document.querySelectorAll<HTMLElement>(
        '[class*="modal-backdrop"], [class*="modal-overlay"], [class*="dialog-backdrop"], [data-modal-backdrop]',
      ),
    ).filter(visible)
    const backdrop = candidates.at(-1)
    if (backdrop) {
      event.preventDefault()
      event.stopPropagation()
      backdrop.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
      backdrop.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    }
  }

  window.addEventListener('keydown', onKeyDown, true)
  return () => window.removeEventListener('keydown', onKeyDown, true)
}
