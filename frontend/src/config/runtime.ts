export type ImobRuntimeConfig = {
  apiUrl?: string
  neonAuthUrl?: string
}

declare global {
  interface Window {
    __IMOB_CONFIG__?: ImobRuntimeConfig
  }
}

const runtime = window.__IMOB_CONFIG__ || {}

export const runtimeConfig = {
  apiUrl: (runtime.apiUrl || (import.meta.env.VITE_API_URL as string | undefined) || '/api').replace(/\/$/, ''),
  neonAuthUrl: runtime.neonAuthUrl || (import.meta.env.VITE_NEON_AUTH_URL as string | undefined) || '',
}
