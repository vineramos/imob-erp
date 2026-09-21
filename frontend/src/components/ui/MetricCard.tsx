import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

type MetricCardProps = { label: string; value: ReactNode; detail?: ReactNode; icon?: LucideIcon; tone?: 'neutral' | 'info' | 'positive' | 'attention' }

export function MetricCard({ label, value, detail, icon: Icon, tone = 'neutral' }: MetricCardProps) {
  return <article className={`ui-metric ui-metric--${tone}`}>
    <div className="ui-metric__copy"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>
    {Icon && <span className="ui-metric__icon" aria-hidden="true"><Icon size={18} /></span>}
  </article>
}
