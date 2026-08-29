import { authClient, authConfigured } from '../auth/client'

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || 'http://localhost:8000/api'

type JwtTokenProvider = {
  getJWTToken?: () => Promise<string | null | undefined>
}

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function getAccessToken(): Promise<string | null> {
  if (!authConfigured || !authClient) return null

  // O método é parte do adapter-base do Neon Auth e está documentado, mas a
  // versão beta atual não o inclui no tipo público retornado por createAuthClient.
  const tokenProvider = authClient as typeof authClient & JwtTokenProvider
  const token = await tokenProvider.getJWTToken?.()
  return token || null
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken()
  const headers = new Headers(init.headers)

  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_URL}${path.startsWith('/') ? path : `/${path}`}`, {
    ...init,
    headers,
  })

  if (!response.ok) {
    let detail = `Erro ${response.status}`
    try {
      const payload = (await response.json()) as { detail?: unknown }
      if (typeof payload.detail === 'string') detail = payload.detail
    } catch {
      // Mantém mensagem HTTP quando a resposta não é JSON.
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
