import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { MaintenanceMetricFilters } from './modules/maintenance/MaintenanceMetricFilters'
import { MaintenancePartnerModalFeedback } from './modules/maintenance/MaintenancePartnerModalFeedback'
import { ThemeProvider } from './theme/ThemeProvider'
import './styles.css'
import './settings.css'
import './foundation.css'
import './polish.css'
import './settings-foundation-next.css'
import './portfolio.css'
import './contracts.css'
import './commercial.css'
import './lease.css'
import './public-site.css'
import './metric-cards.css'
import './inspections.css'
import './modules/finance/finance.css'
import './modules/properties/property-list-actions.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode><ThemeProvider><><App /><MaintenanceMetricFilters /><MaintenancePartnerModalFeedback /></></ThemeProvider></StrictMode>,
)
