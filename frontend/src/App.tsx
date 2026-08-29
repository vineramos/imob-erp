import { Bell, ChevronDown, CircleHelp, Mail, Menu, Search } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from './api/client'
import type { CurrentUser } from './api/types'
import { authConfigured } from './auth/client'
import { LoginPage } from './auth/LoginPage'
import { navigation } from './config/navigation'
import { DashboardPage } from './modules/dashboard/DashboardPage'
import { SettingsPage } from './modules/settings/SettingsPage'
import { useTheme } from './theme/ThemeProvider'
import type { ThemeConfig } from './theme/theme'

type ModuleKey = (typeof navigation)[number]['module']
type AuthState = 'loading' | 'authenticated' | 'unauthenticated' | 'error'

const devBypass = import.meta.env.DEV && !authConfigured

const devUser: CurrentUser = {
  id: 'dev-admin',
  name: 'Administrador',
  email: 'dev@local',
  organization_id: 'dev-organization',
  organization_name: 'Imobiliária',
  role_keys: ['admin'],
  permissions: [
    ...navigation.map((item) => item.permission),
    'settings.company.manage',
    'settings.appearance.manage',
    'users.manage',
    'permissions.manage',
    'approval_rules.manage',
    'audit.view',
  ],
}

function ModulePlaceholder({ module }: { module: ModuleKey }) {
  const item = navigation.find((entry) => entry.module === module)
  return (
    <section className="workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Módulo preparado</span>
          <h1>{item?.label}</h1>
          <p>Este módulo entra em uma das próximas sprints. A navegação já está reservada para manter a arquitetura estável.</p>
        </div>
      </div>
      <article className="panel empty-module">
        <strong>Estrutura pronta para evoluir.</strong>
        <span>O módulo será ativado sobre a mesma base de permissões, auditoria e configurações do ERP.</span>
      </article>
    </section>
  )
}

function BrandMark({ logoUrl, initials }: { logoUrl: string; initials: string }) {
  if (logoUrl) {
    return <div className="brand-mark brand-mark-image"><img src={logoUrl} alt="" /></div>
  }
  return <div className="brand-mark">{initials}</div>
}

function BootScreen({ message = 'Preparando seu ambiente...' }: { message?: string }) {
  const { theme } = useTheme()
  const initials = theme.companyShortName.trim().slice(0, 2).toUpperCase() || 'IM'
  return (
    <main className="boot-screen">
      <BrandMark logoUrl={theme.logoUrl} initials={initials} />
      <strong>{theme.companyShortName || theme.companyName}</strong>
      <span>{message}</span>
    </main>
  )
}

function AccessError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="boot-screen">
      <div className="brand-mark">!</div>
      <strong>Não foi possível abrir o ERP</strong>
      <span>{message}</span>
      <button className="button primary" type="button" onClick={onRetry}>Tentar novamente</button>
    </main>
  )
}

export default function App() {
  const { theme, setTheme } = useTheme()
  const [activeModule, setActiveModule] = useState<ModuleKey>('dashboard')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [authState, setAuthState] = useState<AuthState>(devBypass ? 'authenticated' : 'loading')
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(devBypass ? devUser : null)
  const [authError, setAuthError] = useState('')

  const refreshUser = useCallback(async () => {
    if (devBypass) {
      setCurrentUser(devUser)
      setAuthState('authenticated')
      return
    }

    setAuthState('loading')
    setAuthError('')
    try {
      const user = await apiRequest<CurrentUser>('/me')
      setCurrentUser(user)

      try {
        const branding = await apiRequest<ThemeConfig>('/theme/erp')
        setTheme(branding)
      } catch {
        // O tema padrão mantém o ERP utilizável mesmo se a identidade visual não puder ser carregada.
      }

      setAuthState('authenticated')
    } catch (error) {
      setCurrentUser(null)
      if (error instanceof ApiError && error.status === 401) {
        setAuthState('unauthenticated')
        return
      }
      if (error instanceof ApiError && error.status === 403) {
        setAuthError(error.detail)
      } else {
        setAuthError(error instanceof Error ? error.message : 'Falha inesperada ao iniciar o sistema.')
      }
      setAuthState('error')
    }
  }, [setTheme])

  useEffect(() => {
    if (!devBypass) void refreshUser()
  }, [refreshUser])

  const visibleNavigation = useMemo(() => {
    if (!currentUser) return []
    const granted = new Set(currentUser.permissions)
    return navigation.filter((item) => granted.has(item.permission))
  }, [currentUser])

  useEffect(() => {
    if (visibleNavigation.length > 0 && !visibleNavigation.some((item) => item.module === activeModule)) {
      setActiveModule(visibleNavigation[0].module)
    }
  }, [activeModule, visibleNavigation])

  if (authState === 'loading') return <BootScreen />
  if (authState === 'unauthenticated') return <LoginPage onAuthenticated={() => void refreshUser()} />
  if (authState === 'error') return <AccessError message={authError} onRetry={() => void refreshUser()} />
  if (!currentUser) return <BootScreen message="Carregando usuário..." />

  const initials = currentUser.name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('') || 'AD'
  const primaryRole = currentUser.role_keys.includes('admin') ? 'Administrador' : (currentUser.role_keys[0] || 'Usuário')
  const brandInitials = theme.companyShortName.trim().slice(0, 2).toUpperCase() || 'IM'

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <BrandMark logoUrl={theme.logoUrl} initials={brandInitials} />
          <div className="brand-copy">
            <strong>{theme.companyShortName || theme.companyName}</strong>
            <span>ERP Imobiliário</span>
          </div>
        </div>

        <nav className="nav-list" aria-label="Menu principal">
          {visibleNavigation.map(({ label, icon: Icon, module }) => (
            <button
              className={`nav-item ${activeModule === module ? 'active' : ''}`}
              type="button"
              key={label}
              title={sidebarCollapsed ? label : undefined}
              onClick={() => setActiveModule(module)}
            >
              <Icon size={18} strokeWidth={1.75} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="sidebar-label">Empresa</span>
          <button type="button" className="company-switcher">
            <div className="avatar">{currentUser.organization_name.trim().slice(0, 2).toUpperCase() || brandInitials}</div>
            <div className="company-copy">
              <strong>{currentUser.organization_name}</strong>
              <span>Ambiente principal</span>
            </div>
            <ChevronDown className="company-chevron" size={15} />
          </button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="sidebar-toggle"
              type="button"
              aria-label={sidebarCollapsed ? 'Expandir menu lateral' : 'Recolher menu lateral'}
              onClick={() => setSidebarCollapsed((value) => !value)}
            >
              <Menu size={20} />
            </button>

            <label className="global-search">
              <Search size={17} />
              <input aria-label="Busca global" placeholder="Buscar imóveis, contratos, pessoas, cobranças..." />
              <kbd>Ctrl K</kbd>
            </label>
          </div>

          <div className="topbar-actions">
            {!authConfigured && <span className="dev-badge">DEV · Auth pendente</span>}
            <button className="topbar-icon" type="button" aria-label="Notificações" title="Notificações">
              <Bell size={18} />
            </button>
            <button className="topbar-icon topbar-secondary-action" type="button" aria-label="Mensagens" title="Mensagens">
              <Mail size={18} />
            </button>
            <button className="topbar-icon topbar-secondary-action" type="button" aria-label="Ajuda" title="Ajuda">
              <CircleHelp size={18} />
            </button>
            <span className="topbar-divider" aria-hidden="true" />
            <div className="user-summary">
              <div className="avatar avatar-user">{initials}</div>
              <div>
                <strong>{currentUser.name}</strong>
                <span>{primaryRole}</span>
              </div>
              <ChevronDown size={15} />
            </div>
          </div>
        </header>

        {activeModule === 'dashboard' && <DashboardPage />}
        {activeModule === 'settings' && <SettingsPage permissions={currentUser.permissions} />}
        {activeModule !== 'dashboard' && activeModule !== 'settings' && <ModulePlaceholder module={activeModule} />}
      </main>
    </div>
  )
}
