import { ChevronDown, PanelLeftClose, PanelLeftOpen, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { sidebarNavigation, type ModuleKey, type SidebarSection } from '../config/navigation'

type AppSidebarProps = {
  activeModule: ModuleKey
  currentRoute: string
  permissions: readonly string[]
  collapsed: boolean
  mobileOpen: boolean
  brandName: string
  brandSubtitle: string
  brandInitials: string
  logoUrl: string
  organizationName: string
  onNavigate: (module: string, route?: string) => void
  onToggleCollapsed: () => void
  onCloseMobile: () => void
}

function BrandMark({ logoUrl, initials }: { logoUrl: string; initials: string }) {
  return logoUrl
    ? <span className="brand-mark brand-mark-image"><img src={logoUrl} alt="" /></span>
    : <span className="brand-mark" aria-hidden="true">{initials}</span>
}

function hasVisibleItem(section: SidebarSection, permissions: Set<string>) {
  return permissions.has(section.permission) || section.children?.some(child => permissions.has(child.permission))
}

export function AppSidebar({
  activeModule, currentRoute, permissions, collapsed, mobileOpen, brandName, brandSubtitle,
  brandInitials, logoUrl, organizationName, onNavigate, onToggleCollapsed, onCloseMobile,
}: AppSidebarProps) {
  const granted = useMemo(() => new Set(permissions), [permissions])
  const sections = useMemo(
    () => sidebarNavigation.filter(section => hasVisibleItem(section, granted)),
    [granted],
  )
  const [expanded, setExpanded] = useState<Set<ModuleKey>>(() => new Set([activeModule]))
  const [flyoutModule, setFlyoutModule] = useState<ModuleKey | null>(null)
  const compact = collapsed && !mobileOpen

  useEffect(() => {
    setExpanded(current => current.has(activeModule) ? current : new Set(current).add(activeModule))
  }, [activeModule])

  const navigate = (module: ModuleKey, route: string) => {
    onNavigate(module, route)
    onCloseMobile()
  }

  return <>
    <button
      className={`sidebar-scrim ${mobileOpen ? 'is-visible' : ''}`}
      type="button"
      aria-label="Fechar menu"
      tabIndex={mobileOpen ? 0 : -1}
      onClick={onCloseMobile}
    />
    <aside className={`sidebar ${mobileOpen ? 'is-mobile-open' : ''}`} aria-label="Navegação principal">
      <div className="brand">
        <BrandMark logoUrl={logoUrl} initials={brandInitials} />
        <div className="brand-copy"><strong>{brandName}</strong><span>{brandSubtitle}</span></div>
        <button className="sidebar-mobile-close" type="button" onClick={onCloseMobile} aria-label="Fechar menu"><X size={18} /></button>
      </div>

      <nav className="nav-list" aria-label="Módulos do ERP">
        {sections.map(section => {
          const Icon = section.icon
          const children = section.children?.filter(child => granted.has(child.permission)) ?? []
          const hasChildren = children.length > 0
          const isGroupActive = section.module === activeModule || children.some(child => child.module === activeModule)
          const isExpanded = expanded.has(section.module)
          const childButtons = children.map(child => {
            const childActive = currentRoute === child.route
              || (!currentRoute.includes('?') && child.route === `/app/${activeModule}`)
            return <button
              className={`nav-child ${childActive ? 'active' : ''}`}
              type="button"
              role={compact ? 'menuitem' : undefined}
              key={child.label}
              onClick={() => navigate(child.module, child.route)}
            >
              <span>{child.label}</span>
            </button>
          })
          return <div
            className={`nav-section ${isGroupActive ? 'is-active' : ''}`}
            key={section.label}
            onMouseEnter={() => { if (compact && hasChildren) setFlyoutModule(section.module) }}
            onMouseLeave={() => { if (compact) setFlyoutModule(null) }}
            onFocus={() => { if (compact && hasChildren) setFlyoutModule(section.module) }}
            onBlur={event => {
              if (compact && !event.currentTarget.contains(event.relatedTarget as Node | null)) setFlyoutModule(null)
            }}
          >
            <button
              className={`nav-item nav-item-primary ${isGroupActive ? 'active' : ''}`}
              type="button"
              title={compact && !hasChildren ? section.label : undefined}
              aria-expanded={hasChildren ? isExpanded : undefined}
              onClick={() => {
                if (hasChildren) {
                  if (compact) {
                    setFlyoutModule(current => current === section.module ? null : section.module)
                  } else {
                    setExpanded(current => {
                      const next = new Set(current)
                      next.has(section.module) ? next.delete(section.module) : next.add(section.module)
                      return next
                    })
                  }
                  return
                }
                navigate(section.module, section.route)
              }}
            >
              {Icon && <Icon size={18} strokeWidth={1.75} />}
              <span>{section.label}</span>
              {hasChildren && <ChevronDown className={`nav-chevron ${isExpanded ? 'is-open' : ''}`} size={15} />}
            </button>
            {hasChildren && !compact && <div className={`nav-children-shell ${isExpanded ? 'is-open' : ''}`} aria-hidden={!isExpanded}>
              <div className="nav-children">{childButtons}</div>
            </div>}
            {hasChildren && compact && flyoutModule === section.module && <div className="nav-flyout" role="menu" aria-label={section.label}>
              <strong>{section.label}</strong>
              <div>{childButtons}</div>
            </div>}
          </div>
        })}
      </nav>

      <div className="sidebar-footer">
        <span className="sidebar-label">Ambiente</span>
        <div className="company-switcher">
          <div className="avatar">{organizationName.trim().slice(0, 2).toUpperCase() || brandInitials}</div>
          <div className="company-copy"><strong>{organizationName}</strong><span>Unidade principal</span></div>
          <span className="environment-status" title="Ambiente ativo" />
        </div>
        <button className="sidebar-collapse" type="button" onClick={onToggleCollapsed}>
          {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          <span>{collapsed ? 'Expandir menu' : 'Recolher menu'}</span>
        </button>
      </div>
    </aside>
  </>
}
