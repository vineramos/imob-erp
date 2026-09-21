import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from './api/client'
import type { CurrentUser } from './api/types'
import { authConfigured } from './auth/client'
import { LoginPage } from './auth/LoginPage'
import { AppSidebar } from './components/AppSidebar'
import { EntityDeepLink } from './components/EntityDeepLink'
import { TopHeader } from './components/TopHeader'
import { navigation, type ModuleKey } from './config/navigation'
import { AgendaNotifier } from './modules/agenda/AgendaNotifier'
import { useTheme } from './theme/ThemeProvider'
import type { ThemeConfig } from './theme/theme'

const AgendaPage = lazy(() => import('./modules/agenda/AgendaPage').then(module => ({ default: module.AgendaPage })))
const CapturesPage = lazy(() => import('./modules/captures/CapturesPage').then(module => ({ default: module.CapturesPage })))
const CommercialSiteHub = lazy(() => import('./modules/commercial/CommercialSiteHub').then(module => ({ default: module.CommercialSiteHub })))
const CommunicationsPage = lazy(() => import('./modules/communications/CommunicationsPage'))
const ContractsHub = lazy(() => import('./modules/contracts/ContractsHub').then(module => ({ default: module.ContractsHub })))
const DashboardPage = lazy(() => import('./modules/dashboard/DashboardPage').then(module => ({ default: module.DashboardPage })))
const DocumentsPage = lazy(() => import('./modules/documents/DocumentsPage').then(module => ({ default: module.DocumentsPage })))
const FinancePage = lazy(() => import('./modules/finance/FinancePage').then(module => ({ default: module.FinancePage })))
const InspectionsPage = lazy(() => import('./modules/inspections/InspectionsPage').then(module => ({ default: module.InspectionsPage })))
const MaintenancePage = lazy(() => import('./modules/maintenance/MaintenancePage').then(module => ({ default: module.MaintenancePage })))
const BrokersPage = lazy(() => import('./modules/properties/BrokersPage').then(module => ({ default: module.BrokersPage })))
const PropertiesPage = lazy(() => import('./modules/properties/PropertiesPage').then(module => ({ default: module.PropertiesPage })))
const ReportsPage = lazy(() => import('./modules/reports/ReportsPage').then(module => ({ default: module.ReportsPage })))
const SettingsPage = lazy(() => import('./modules/settings/SettingsPage').then(module => ({ default: module.SettingsPage })))
const ExternalPortalPage = lazy(() => import('./public/ExternalPortalPage').then(module => ({ default: module.ExternalPortalPage })))
const PublicSitePage = lazy(() => import('./public/PublicSitePage').then(module => ({ default: module.PublicSitePage })))
const TenantPortalEntry = lazy(() => import('./public/TenantPortalEntry').then(module => ({ default: module.TenantPortalEntry })))

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
/'finance.period.close'/d
    'finance.period.close', 'finance.period.reopen', 'finance.adjustment.create', 'finance.sod.override', 'finance.repasse.execute',
    'communications.manage', 'communications.send',
    'settings.company.manage', 'settings.appearance.manage', 'users.manage', 'permissions.manage', 'approval_rules.manage', 'audit.view',
  ],
}

function ModulePlaceholder({ module }: { module: ModuleKey }) { const item = navigation.find((entry) => entry.module === module); return <section className="workspace"><div className="page-heading"><div><span className="eyebrow">Módulo preparado</span><h1>{item?.label}</h1><p>Este módulo entra em uma das próximas sprints. A navegação já está reservada para manter a arquitetura estável.</p></div></div><article className="panel empty-module"><strong>Estrutura pronta para evoluir.</strong><span>O módulo será ativado sobre a mesma base de permissões, auditoria e configurações do ERP.</span></article></section> }
function BrandMark({ logoUrl, initials }: { logoUrl: string; initials: string }) { return logoUrl ? <div className="brand-mark brand-mark-image"><img src={logoUrl} alt="" /></div> : <div className="brand-mark">{initials}</div> }
function BootScreen({ message = 'Preparando seu ambiente...' }: { message?: string }) { const { theme } = useTheme(); const initials = theme.companyShortName.trim().slice(0, 2).toUpperCase() || 'IM'; return <main className="boot-screen"><BrandMark logoUrl={theme.logoUrl} initials={initials}/><strong>{theme.companyShortName || theme.companyName}</strong><span>{message}</span></main> }
function AccessError({ message, onRetry }: { message: string; onRetry: () => void }) { return <main className="boot-screen"><div className="brand-mark">!</div><strong>Não foi possível abrir o ERP</strong><span>{message}</span><button className="button primary" type="button" onClick={onRetry}>Tentar novamente</button></main> }
function ModuleLoading() { return <article className="panel settings-loading">Carregando módulo...</article> }

function ErpApp() {
  const { theme, setTheme } = useTheme()
  const [activeModule, setActiveModule] = useState<ModuleKey>(() => moduleFromPath(window.location.pathname))
  const [currentRoute, setCurrentRoute] = useState(() => browserRoute())
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
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
  const implemented = ['dashboard', 'people', 'properties', 'brokers', 'captures', 'crm', 'contracts', 'inspections', 'maintenance', 'finance', 'agenda', 'communications', 'reports', 'documents', 'settings']

  const toggleSidebar = () => {
    if (window.matchMedia('(max-width: 760px)').matches) {
      setMobileSidebarOpen(value => !value)
      return
    }
    setSidebarCollapsed(value => !value)
  }

  return <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
    <AppSidebar
      activeModule={activeModule}
      currentRoute={currentRoute}
      permissions={currentUser.permissions}
      collapsed={sidebarCollapsed}
      mobileOpen={mobileSidebarOpen}
      brandName={theme.companyShortName || theme.companyName}
      brandSubtitle="Gestão imobiliária"
      brandInitials={brandInitials}
      logoUrl={theme.logoUrl}
      organizationName={currentUser.organization_name}
      onNavigate={navigateModule}
      onToggleCollapsed={() => setSidebarCollapsed(value => !value)}
      onCloseMobile={() => setMobileSidebarOpen(false)}
    />
    <main className="main-area"><TopHeader
      userName={currentUser.name}
      userRole={primaryRole}
      userInitials={initials}
      authConfigured={authConfigured}
      onNavigate={navigateModule}
      onToggleSidebar={toggleSidebar}
    />
      {currentUser.permissions.includes('agenda.view') && <AgendaNotifier onOpenAgenda={() => navigateModule('agenda')}/>} 
      <Suspense fallback={<ModuleLoading/>}>
        {activeModule === 'dashboard' && <DashboardPage onNavigate={module => navigateModule(module)}/>}{activeModule === 'people' && <PropertiesPage permissions={currentUser.permissions} initialTab="people"/>}{activeModule === 'properties' && <PropertiesPage permissions={currentUser.permissions} initialTab="properties"/>}{activeModule === 'brokers' && <BrokersPage permissions={currentUser.permissions}/>}{activeModule === 'captures' && <CapturesPage permissions={currentUser.permissions}/>}{activeModule === 'crm' && <CommercialSiteHub permissions={currentUser.permissions} organizationId={currentUser.organization_id}/>}{activeModule === 'contracts' && <ContractsHub permissions={currentUser.permissions}/>}{activeModule === 'inspections' && <InspectionsPage permissions={currentUser.permissions}/>}{activeModule === 'maintenance' && <MaintenancePage permissions={currentUser.permissions}/>}{activeModule === 'finance' && <FinancePage permissions={currentUser.permissions}/>}{activeModule === 'agenda' && <AgendaPage permissions={currentUser.permissions} onNavigate={module => navigateModule(module)}/>}{activeModule === 'communications' && <CommunicationsPage permissions={currentUser.permissions}/>}{activeModule === 'reports' && <ReportsPage permissions={currentUser.permissions}/>}{activeModule === 'documents' && <DocumentsPage permissions={currentUser.permissions}/>}{activeModule === 'settings' && <SettingsPage permissions={currentUser.permissions}/>} {!implemented.includes(activeModule) && <ModulePlaceholder module={activeModule}/>} 
      </Suspense>
      <EntityDeepLink route={currentRoute}/>
    </main>
  </div>
}

export default function App() {
  if (window.location.pathname === '/portal' || window.location.pathname === '/portal/') return <Suspense fallback={<BootScreen message="Carregando portal..."/>}><TenantPortalEntry/></Suspense>
  const portalMatch = window.location.pathname.match(/^\/portal\/([^/]+)\/?$/)
  if (portalMatch) return <Suspense fallback={<BootScreen message="Carregando portal..."/>}><ExternalPortalPage token={decodeURIComponent(portalMatch[1])}/></Suspense>
  const match = window.location.pathname.match(/^\/site\/([^/]+)(?:\/imoveis\/([^/]+))?\/?$/)
  if (match) return <Suspense fallback={<BootScreen message="Carregando site..."/>}><PublicSitePage organizationId={decodeURIComponent(match[1])} slug={match[2] ? decodeURIComponent(match[2]) : null}/></Suspense>
  return <ErpApp/>
}
