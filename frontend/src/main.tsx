import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </StrictMode>,
)
