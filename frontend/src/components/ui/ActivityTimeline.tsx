import type { LucideIcon } from 'lucide-react'
import { EmptyState } from './EmptyState'

export type TimelineItem = { id: string; title: string; description?: string; timestamp: string; actor?: string; icon?: LucideIcon }

export function ActivityTimeline({ items }: { items: readonly TimelineItem[] }) {
  if (!items.length) return <EmptyState title="Nenhuma atividade registrada" compact />
  return <ol className="ui-timeline">{items.map(item => {
    const Icon = item.icon
    return <li key={item.id}><span className="ui-timeline__marker">{Icon && <Icon size={14} />}</span><div><strong>{item.title}</strong>{item.description && <p>{item.description}</p>}<small>{item.timestamp}{item.actor ? ` · ${item.actor}` : ''}</small></div></li>
  })}</ol>
}
