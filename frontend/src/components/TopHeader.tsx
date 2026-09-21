import { CircleHelp, Mail, Menu } from 'lucide-react'
import { GlobalSearch } from './GlobalSearch'
import { NotificationCenter } from './NotificationCenter'

type TopHeaderProps = {
  userName: string
  userRole: string
  userInitials: string
  authConfigured: boolean
  onNavigate: (module: string, route?: string) => void
  onToggleSidebar: () => void
}

export function TopHeader({
  userName, userRole, userInitials, authConfigured, onNavigate, onToggleSidebar,
}: TopHeaderProps) {
  return <header className="topbar">
    <div className="topbar-left">
      <button className="sidebar-toggle" type="button" aria-label="Abrir ou recolher menu lateral" onClick={onToggleSidebar}>
        <Menu size={20} />
      </button>
      <GlobalSearch onNavigate={onNavigate} />
    </div>
    <div className="topbar-actions">
      {!authConfigured && <span className="dev-badge">DEV · Auth pendente</span>}
      <NotificationCenter onNavigate={onNavigate} />
      <button className="topbar-icon topbar-secondary-action" type="button" aria-label="Mensagens" onClick={() => onNavigate('communications')}>
        <Mail size={18} />
      </button>
      <button className="topbar-icon topbar-secondary-action" type="button" aria-label="Central de ajuda"><CircleHelp size={18} /></button>
      <span className="topbar-divider" />
      <div className="user-summary" aria-label={`${userName}, ${userRole}`}>
        <div className="avatar avatar-user">{userInitials}</div>
        <div><strong>{userName}</strong><span>{userRole}</span></div>
      </div>
    </div>
  </header>
}
