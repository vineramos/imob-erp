export type ThemeConfig = {
  companyName: string
  companyShortName: string
  logoUrl: string
  faviconUrl: string
  primary: string
  primaryStrong: string
  primarySoft: string
  sidebarBg: string
  appBg: string
  surface: string
  text: string
  textMuted: string
  border: string
  success: string
  warning: string
  danger: string
  fontFamily: string
  radius: number
  fieldHeight: number
  sidebarWidth: number
  tableDensity: 'compact' | 'normal' | 'comfortable'
}

export const defaultTheme: ThemeConfig = {
  companyName: 'Imobiliária',
  companyShortName: 'Imob',
  logoUrl: '',
  faviconUrl: '',
  primary: '#123a6b',
  primaryStrong: '#0d2d55',
  primarySoft: '#edf4fb',
  sidebarBg: '#111923',
  appBg: '#f3f5f7',
  surface: '#ffffff',
  text: '#172033',
  textMuted: '#6a7485',
  border: '#dfe4ea',
  success: '#2d8b57',
  warning: '#d98b24',
  danger: '#c84444',
  fontFamily: 'Inter, Aptos, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  radius: 12,
  fieldHeight: 42,
  sidebarWidth: 248,
  tableDensity: 'normal',
}

function applyFavicon(url: string) {
  let favicon = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (!url) {
    favicon?.remove()
    return
  }
  if (!favicon) {
    favicon = document.createElement('link')
    favicon.rel = 'icon'
    document.head.appendChild(favicon)
  }
  favicon.href = url
}

export function applyTheme(theme: ThemeConfig) {
  const root = document.documentElement
  const values: Record<string, string> = {
    '--brand-primary': theme.primary,
    '--brand-primary-strong': theme.primaryStrong,
    '--brand-primary-soft': theme.primarySoft,
    '--sidebar-bg': theme.sidebarBg,
    '--app-bg': theme.appBg,
    '--surface': theme.surface,
    '--text': theme.text,
    '--text-muted': theme.textMuted,
    '--border': theme.border,
    '--success': theme.success,
    '--warning': theme.warning,
    '--danger': theme.danger,
    '--radius': `${theme.radius}px`,
    '--field-height': `${theme.fieldHeight}px`,
    '--sidebar-width': `${theme.sidebarWidth}px`,
  }

  Object.entries(values).forEach(([key, value]) => root.style.setProperty(key, value))
  root.style.fontFamily = theme.fontFamily
  root.dataset.tableDensity = theme.tableDensity
  document.title = `${theme.companyShortName || theme.companyName} · ERP Imobiliário`
  applyFavicon(theme.faviconUrl)
}
