import { AlertTriangle, X } from 'lucide-react'
import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import './confirm-dialog.css'

type ConfirmDialogTone = 'default' | 'attention' | 'danger'

type ConfirmDialogProps = {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: ConfirmDialogTone
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirmar',
  cancelLabel = 'Cancelar',
  tone = 'default',
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const timer = window.setTimeout(() => confirmRef.current?.focus(), 0)
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) {
        event.preventDefault()
        event.stopPropagation()
        onCancel()
      }
    }
    window.addEventListener('keydown', handleKeyDown, true)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('keydown', handleKeyDown, true)
      document.body.style.overflow = previousOverflow
    }
  }, [busy, onCancel, open])

  if (!open) return null

  return createPortal(
    <div
      className="confirm-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel()
      }}
    >
      <section
        className={`confirm-dialog confirm-dialog--${tone}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <div className="confirm-dialog__header">
          <span className="confirm-dialog__icon" aria-hidden="true">
            <AlertTriangle size={18} />
          </span>
          <div>
            <span className="eyebrow">Confirmação</span>
            <h2 id={titleId}>{title}</h2>
          </div>
          <button className="confirm-dialog__close" type="button" onClick={onCancel} disabled={busy} aria-label="Fechar">
            <X size={18} />
          </button>
        </div>
        <p id={descriptionId} className="confirm-dialog__description">{description}</p>
        <div className="confirm-dialog__actions">
          <button className="button secondary" type="button" onClick={onCancel} disabled={busy}>{cancelLabel}</button>
          <button ref={confirmRef} className={`button confirm-dialog__confirm confirm-dialog__confirm--${tone}`} type="button" onClick={onConfirm} disabled={busy}>
            {busy ? 'Processando...' : confirmLabel}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  )
}
