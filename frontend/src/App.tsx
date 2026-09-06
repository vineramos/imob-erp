import { ChevronDown, CircleHelp, Mail, Menu } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from './api/client'
import type { CurrentUser } from './api/types'
import { authConfigured } from './auth/client'
import { LoginPage } from './auth/LoginPage'
import { EntityDeepLink } from './components/EntityDeepLink'
import { GlobalSearch } from './components/GlobalSearch'
import { NotificationCenter } from './components/NotificationCenter'
import { navigation } from './config/navigation'
import { AgendaNotifier } from './modules/agenda/AgendaNotifier'
import { AgendaPage } from './modules/agenda/AgendaPage'
import { CapturesPage } from './modules/captures/CapturesPage'
import { CommercialSiteHub } from './modules/commercial/CommercialSiteHub'
import { ContractsHub } from './modules/contracts/ContractsHub'
import { DashboardPage } from './modules/dashboard/DashboardPage'
import { DocumentsPage } from './modules/documents/DocumentsPage'
import { FinancePage } from './modules/finance/FinancePage'
import { InspectionsPage } from './modules/inspections/InspectionsPage'
import { MaintenancePage } from './modules/maintenance/MaintenancePage'
import { BrokersPage } from './modules/properties/BrokersPage'
import { PropertiesPage } from './modules/properties/PropertiesPage'
import { ReportsPage } from './modules/reports/ReportsPage'
import { SettingsPage } from './modules/settings/SettingsPage'
import { ExternalPortalPage } from './public/ExternalPortalPage'
import { PublicSitePage } from './public/PublicSitePage'
import { TenantPortalEntry } from './public/TenantPortalEntry'
import { useTheme } from './theme/ThemeProvider'
import type { ThemeConfig } from './theme/theme'

type ModuleKey = (typeof navigation)[number]['module']
type AuthState = 'loading' | 'authenticated' | 'unauthenticated' | 'error'

const moduleKeys = new Set<string>(navigation.map(item => item.module))
function moduleFromPath(pathname: string): ModuleKey {
  const match = pathname.match(/^\/app\/([^/]+)\/?/)
  const candidate = match?.[1] || ''
  return moduleKeys.has(candidate) ? candidate as ModuleKey : 'dashboard'
}
function routeForModule(module: ModuleKey) { return `/app/${module}` }
function browserRoute() { return `${window.location.pathname}${window.location.search}` }

const devBypass = import.meta.env.DEV && !authConfigured
const devUser: CurrentUser = {
  id: 'dev-admin', name: 'Administrador', email: 'dev@local', organization_id: 'dev-organization', organization_name: 'Imobiliária', role_keys: ['admin'],
  permissions: [
    ...navigation.map((item) => item.permission),
    'properties.create', 'properties.edit', 'properties.publish', 'captures.manage', 'crm.manage',
    'contracts.create', 'contracts.edit', 'contracts.approve', 'contracts.send_signature',
    'inspections.manage', 'maintenance.manage', 'agenda.manage', 'reports.export', 'documents.manage',
    'finance.charge.create', 'finance.reconcile', 'finance.payment.prepare', 'finance.payment.approve', 'finance.repasse.execute',
    'settings.company.manage', 'settings.appearance.manage', 'users.manage', 'permissions.manage', 'approval_rules.manage', 'audit.view',
  ],
}

function ModulePlaceholder({ module }: { module: ModuleKey }) { const item = navigation.find((entry) => entry.module === module); return <section className="workspace"><div className="page-heading"><div><span className="eyebrow">Módulo preparado</span><h1>{item?.label}</h1><p>Este módulo entra em uma das próximas sprints. A navegação já está reservada para manter a arquitetura estável.</p></div></div><article className="panel empty-module"><strong>Estrutura pronta para evoluir.</strong><span>O módulo será ativado sobre a mesma base de permissões, auditoria e configurações do ERP.</span></article></section> }
function BrandMark({ logoUrl, initials }: { logoUrl: string; initials: string }) { return logoUrl ? <div className="brand-mark brand-mark-image"><img src={logoUrl} alt="" /></div> : <div className="brand-mark">{initials}</div> }
function BootScreen({ message = 'Preparando seu ambiente...' }: { message?: string }) { const { theme } = useTheme(); const initials = theme.companyShortName.trim().slice(0, 2).toUpperCase() || 'IM'; return <main className="boot-screen"><BrandMark logoUrl={theme.logoUrl} initials={initials}/><strong>{theme.companyShortName || theme.companyName}</strong><span>{message}</span></main> }
function AccessError({ message, onRetry }: { message: string; onRetry: () => void }) { return <main className="boot-screen"><div className="brand-mark">!</div><strong>Não foi possível abrir o ERP</strong><span>{message}</span><button className="button primary" type="button" onClick={onRetry}>Tentar novamente</button></main> }

function ErpApp() {
  const { theme, setTheme } = useTheme()
  const [activeModule, setActiveModule] = useState<ModuleKey>(() => moduleFromPath(window.location.pathname))
  const [currentRoute, setCurrentRoute] = useState(() => browserRoute())
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [authState, setAuthState] = useState<AuthState>(devBypass ? 'authenticated' : 'loading')
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(devBypass ? devUser : null)
  const [authError, setAuthError] = useState('')

  const navigateModule = useCallback((module: string, route?: string) => {
    if (!moduleKeys.has(module)) return
    const nextModule = module as ModuleKey
    setActiveModule(nextModule)
    const nextRoute = route || routeForModule(nextModule)
    const current = browserRoute()
    if (current !== nextRoute) window.history.pushState({}, '', nextRoute)
    setCurrentRoute(nextRoute)
  }, [])

  const refreshUser = useCallback(async () => {
    if (devBypass) { setCurrentUser(devUser); setAuthState('authenticated'); return }
    setAuthState('loading'); setAuthError('')
    try { const user = await apiRequest<CurrentUser>('/me'); setCurrentUser(user); try { setTheme(await apiRequest<ThemeConfig>('/theme/erp')) } catch { /* mantém tema padrão */ }; setAuthState('authenticated') }
    catch (error) { setCurrentUser(null); if (error instanceof ApiError && error.status === 401) { setAuthState('unauthenticated'); return }; setAuthError(error instanceof ApiError ? error.detail : error instanceof Error ? error.message : 'Falha inesperada ao iniciar o sistema.'); setAuthState('error') }
  }, [setTheme])

  useEffect(() => { if (!devBypass) void refreshUser() }, [refreshUser])
  useEffect(() => {
    const syncRoute = () => {
      setActiveModule(moduleFromPath(window.location.pathname))
      setCurrentRoute(browserRoute())
    }
    window.addEventListener('popstate', syncRoute)
    return () => window.removeEventListener('popstate', syncRoute)
  }, [])

  const visibleNavigation = useMemo(() => { if (!currentUser) return []; const granted = new Set(currentUser.permissions); return navigation.filter((item) => granted.has(item.permission)) }, [currentUser])
  useEffect(() => {
    if (visibleNavigation.length > 0 && !visibleNavigation.some((item) => item.module === activeModule)) {
      const next = visibleNavigation[0].module
      const nextRoute = routeForModule(next)
      setActiveModule(next)
      window.history.replaceState({}, '', nextRoute)
      setCurrentRoute(nextRoute)
    }
  }, [activeModule, visibleNavigation])

  if (authState === 'loading') return <BootScreen />
  if (authState === 'unauthenticated') return <LoginPage onAuthenticated={() => void refreshUser()} />
  if (authState === 'error') return <AccessError message={authError} onRetry={() => void refreshUser()} />
  if (!currentUser) return <BootScreen message="Carregando usuário..." />

  const initials = currentUser.name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || 'AD'
  const primaryRole = currentUser.role_keys.includes('admin') ? 'Administrador' : (currentUser.role_keys[0] || 'Usuário')
  const brandInitials = theme.companyShortName.trim().slice(0, 2).toUpperCase() || 'IM'
  const implemented = ['dashboard', 'people', 'properties', 'brokers', 'captures', 'crm', 'contracts', 'inspections', 'maintenance', 'finance', 'agenda', 'reports', 'documents', 'settings']

  return <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
    <aside className="sidebar"><div className="brand"><BrandMark logoUrl={theme.logoUrl} initials={brandInitials}/><div className="brand-copy"><strong>{theme.companyShortName || theme.companyName}</strong><span>ERP Imobiliário</span></div></div><nav className="nav-list" aria-label="Menu principal">{visibleNavigation.map(({ label, icon: Icon, module }) => <button className={`nav-item ${activeModule === module ? 'active' : ''}`} type="button" key={label} title={sidebarCollapsed ? label : undefined} onClick={() => navigateModule(module)}><Icon size={18} strokeWidth={1.75}/><span>{label}</span></button>)}</nav><div className="sidebar-footer"><span className="sidebar-label">Empresa</span><button type="button" className="company-switcher"><div className="avatar">{currentUser.organization_name.trim().slice(0, 2).toUpperCase() || brandInitials}</div><div className="company-copy"><strong>{currentUser.organization_name}</strong><span>Ambiente principal</span></div><ChevronDown className="company-chevron" size={15}/></button></div></aside>
    <main className="main-area"><header className="topbar"><div className="topbar-left"><button className="sidebar-toggle" type="button" aria-label={sidebarCollapsed ? 'Expandir menu lateral' : 'Recolher menu lateral'} onClick={() => setSidebarCollapsed((value) => !value)}><Menu size={20}/></button><GlobalSearch onNavigate={navigateModule}/></div><div className="topbar-actions">{!authConfigured && <span className="dev-badge">DEV · Auth pendente</span>}<NotificationCenter onNavigate={navigateModule}/><button className="topbar-icon topbar-secondary-action" type="button" aria-label="Mensagens"><Mail size={18}/></button><button className="topbar-icon topbar-secondary-action" type="button" aria-label="Ajuda"><CircleHelp size={18}/></button><span className="topbar-divider"/><div className="user-summary"><div className="avatar avatar-user">{initials}</div><div><strong>{currentUser.name}</strong><span>{primaryRole}</span></div><ChevronDown size={15}/></div></div></header>
      {currentUser.permissions.includes('agenda.view') && <AgendaNotifier onOpenAgenda={() => navigateModule('agenda')}/>} 
      {activeModule === 'dashboard' && <DashboardPage onNavigate={module => navigateModule(module)}/>}{activeModule === 'people' && <PropertiesPage permissions={currentUser.permissions} initialTab="people"/>}{activeModule === 'properties' && <PropertiesPage permissions={currentUser.permissions} initialTab="properties"/>}{activeModule === 'brokers' && <BrokersPage permissions={currentUser.permissions}/>}{activeModule === 'captures' && <CapturesPage permissions={currentUser.permissions}/>}{activeModule === 'crm' && <CommercialSiteHub permissions={currentUser.permissions} organizationId={currentUser.organization_id}/>}{activeModule === 'contracts' && <ContractsHub permissions={currentUser.permissions}/>}{activeModule === 'inspections' && <InspectionsPage permissions={currentUser.permissions}/>}{activeModule === 'maintenance' && <MaintenancePage permissions={currentUser.permissions}/>}{activeModule === 'finance' && <FinancePage permissions={currentUser.permissions}/>}{activeModule === 'agenda' && <AgendaPage permissions={currentUser.permissions} onNavigate={module => navigateModule(module)}/>}{activeModule === 'reports' && <ReportsPage permissions={currentUser.permissions}/>}{activeModule === 'documents' && <DocumentsPage permissions={currentUser.permissions}/>}{activeModule === 'settings' && <SettingsPage permissions={currentUser.permissions}/>} {!implemented.includes(activeModule) && <ModulePlaceholder module={activeModule}/>} 
      <EntityDeepLink route={currentRoute}/>
    </main>
  </div>
}

export default function App() {
  if (window.location.pathname === '/portal' || window.location.pathname === '/portal/') return <TenantPortalEntry/>
  const portalMatch = window.location.pathname.match(/^\/portal\/([^/]+)\/?$/)
  if (portalMatch) return <ExternalPortalPage token={decodeURIComponent(portalMatch[1])}/>
  const match = window.location.pathname.match(/^\/site\/([^/]+)(?:\/imoveis\/([^/]+))?\/?$/)
  if (match) return <PublicSitePage organizationId={decodeURIComponent(match[1])} slug={match[2] ? decodeURIComponent(match[2]) : null}/>
  return <ErpApp/>
}
