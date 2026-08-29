import { Bell, ChevronDown, Search } from 'lucide-react'
import { useState } from 'react'
import { authConfigured } from './auth/client'
import { LoginPage } from './auth/LoginPage'
import { navigation } from './config/navigation'
import { DashboardPage } from './modules/dashboard/DashboardPage'
import { SettingsPage } from './modules/settings/SettingsPage'

type ModuleKey = (typeof navigation)[number]['module']

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
        <strong>Fundação primeiro.</strong>
        <span>Usuários, permissões, auditoria e configurações serão concluídos antes das regras operacionais deste módulo.</span>
      </article>
    </section>
  )
}

export default function App() {
  const [activeModule, setActiveModule] = useState<ModuleKey>('dashboard')
  const [authenticated, setAuthenticated] = useState(import.meta.env.DEV && !authConfigured)

  if (!authenticated) {
    return <LoginPage onAuthenticated={() => setAuthenticated(true)} />
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">I</div>
          <div>
            <strong>Imob</strong>
            <span>ERP Imobiliário</span>
          </div>
        </div>

        <nav className="nav-list" aria-label="Menu principal">
          {navigation.map(({ label, icon: Icon, module }) => (
            <button
              className={`nav-item ${activeModule === module ? 'active' : ''}`}
              type="button"
              key={label}
              onClick={() => setActiveModule(module)}
            >
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="sidebar-label">Empresa</span>
          <button type="button" className="company-switcher">
            <div className="avatar">IM</div>
            <div>
              <strong>Imobiliária</strong>
              <span>Ambiente principal</span>
            </div>
            <ChevronDown size={16} />
          </button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <label className="global-search">
            <Search size={18} />
            <input aria-label="Busca global" placeholder="Buscar imóveis, contratos, pessoas, cobranças..." />
            <kbd>Ctrl K</kbd>
          </label>

          <div className="topbar-actions">
            {!authConfigured && <span className="dev-badge">DEV · Auth pendente</span>}
            <button className="icon-button" type="button" aria-label="Notificações">
              <Bell size={19} />
            </button>
            <div className="user-summary">
              <div className="avatar avatar-user">AD</div>
              <div>
                <strong>Administrador</strong>
                <span>Acesso total</span>
              </div>
              <ChevronDown size={16} />
            </div>
          </div>
        </header>

        {activeModule === 'dashboard' && <DashboardPage />}
        {activeModule === 'settings' && <SettingsPage />}
        {activeModule !== 'dashboard' && activeModule !== 'settings' && <ModulePlaceholder module={activeModule} />}
      </main>
    </div>
  )
}
