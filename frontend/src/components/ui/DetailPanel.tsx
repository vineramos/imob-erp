import { X } from 'lucide-react'
import type { ReactNode } from 'react'

type DetailPanelProps = { title: string; subtitle?: string; children: ReactNode; actions?: ReactNode; onClose?: () => void }

export function DetailPanel({ title, subtitle, children, actions, onClose }: DetailPanelProps) {
  return <aside className="ui-detail-panel" aria-label={title}>
    <header><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{onClose && <button type="button" onClick={onClose} aria-label="Fechar painel"><X size={18} /></button>}</header>
    <div className="ui-detail-panel__body">{children}</div>
    {actions && <footer>{actions}</footer>}
  </aside>
}
