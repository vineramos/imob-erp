import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { applyTheme, defaultTheme, type ThemeConfig } from './theme'

type ThemeContextValue = {
  theme: ThemeConfig
  setTheme: (theme: ThemeConfig) => void
  resetTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeConfig>(defaultTheme)

  const setTheme = useCallback((nextTheme: ThemeConfig) => {
    setThemeState(nextTheme)
    applyTheme(nextTheme)
  }, [])

  const resetTheme = useCallback(() => {
    setTheme(defaultTheme)
  }, [setTheme])

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  const value = useMemo(() => ({ theme, setTheme, resetTheme }), [theme, setTheme, resetTheme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme deve ser usado dentro de ThemeProvider')
  return context
}
