import { Bell, ChevronDown, Search } from 'lucide-react'
import { navigation } from './config/navigation'
import { DashboardPage } from './modules/dashboard/DashboardPage'

export default function App() {
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
          {navigation.map(({ label, icon: Icon }, index) => (
            <button className={`nav-item ${index === 0 ? 'active' : ''}`} type="button" key={label}>
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

        <DashboardPage />
      </main>
    </div>
  )
}
