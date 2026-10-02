import type { ReactNode } from 'react'

type StatusTone = 'neutral' | 'info' | 'positive' | 'attention' | 'danger'

export function StatusBadge({ children, tone = 'neutral', dot = true }: { children: ReactNode; tone?: StatusTone; dot?: boolean }) {
  return <span className={`ui-status ui-status--${tone}`}>{dot && <i aria-hidden="true" />}{children}</span>
}
