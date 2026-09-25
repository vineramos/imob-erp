import type { ReactNode } from 'react'

export function FilterBar({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return <div className="ui-filter-bar"><div className="ui-filter-bar__fields">{children}</div>{actions && <div className="ui-filter-bar__actions">{actions}</div>}</div>
}
