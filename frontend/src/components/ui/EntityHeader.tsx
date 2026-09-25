import type { ReactNode } from 'react'

type EntityHeaderProps = { title: string; subtitle?: string; media?: ReactNode; status?: ReactNode; metadata?: ReactNode; actions?: ReactNode }

export function EntityHeader({ title, subtitle, media, status, metadata, actions }: EntityHeaderProps) {
  return <header className="ui-entity-header">
    {media && <div className="ui-entity-header__media">{media}</div>}
    <div className="ui-entity-header__main"><div className="ui-entity-header__title"><div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{status}</div>{metadata && <div className="ui-entity-header__metadata">{metadata}</div>}</div>
    {actions && <div className="ui-entity-header__actions">{actions}</div>}
  </header>
}
