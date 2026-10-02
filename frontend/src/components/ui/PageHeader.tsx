import type { ReactNode } from 'react'

type PageHeaderProps = { eyebrow?: string; title: string; description?: string; actions?: ReactNode }

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return <header className="ui-page-header">
    <div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1>{description && <p>{description}</p>}</div>
    {actions && <div className="ui-page-header__actions">{actions}</div>}
  </header>
}
