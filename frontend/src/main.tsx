import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ThemeProvider } from './theme/ThemeProvider'
import { installBrazilianInputFormatting } from './utils/brFormat'
import { installGlobalModalEscape } from './utils/modalEscape'
import { installPublicSiteLinkEnhancer } from './utils/publicSiteLinks'
import './styles.css'
import './settings.css'
import './foundation.css'
import './polish.css'
import './settings-foundation-next.css'
import './portfolio.css'
import './canonical-forms.css'
import './contracts.css'
import './commercial.css'
import './lease.css'
import './public-site.css'
import './metric-cards.css'
import './inspections.css'
import './modules/finance/finance.css'
import './modules/maintenance/maintenance-v2-polish.css'
import './modules/properties/property-list-actions.css'

installBrazilianInputFormatting()
installGlobalModalEscape()
installPublicSiteLinkEnhancer()

createRoot(document.getElementById('root')!).render(
  <StrictMode><ThemeProvider><App /></ThemeProvider></StrictMode>,
)
