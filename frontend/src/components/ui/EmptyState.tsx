import { Inbox } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

type EmptyStateProps = { title: string; description?: string; action?: ReactNode; icon?: LucideIcon; compact?: boolean }

export function EmptyState({ title, description, action, icon: Icon = Inbox, compact = false }: EmptyStateProps) {
  return <div className={`ui-empty ${compact ? 'ui-empty--compact' : ''}`}><Icon size={compact ? 20 : 26} /><strong>{title}</strong>{description && <p>{description}</p>}{action}</div>
}
