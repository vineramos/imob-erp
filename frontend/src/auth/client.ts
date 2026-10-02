import { runtimeConfig } from '../config/runtime'

type AuthError = { message: string }
type AuthResult<T> = { data: T | null; error: AuthError | null }
type SignInPayload = { email: string; password: string }
type SignUpPayload = SignInPayload & { name: string }
type PasswordResetRequest = { email: string; redirectTo: string }
type ResetPasswordRequest = { newPassword: string; token: string }
export type InvitationDetails = { name: string; email: string; expires_at: string }

const API_URL = runtimeConfig.apiUrl
const authEndpoint = (path: string) => `${API_URL}/auth${path.startsWith('/') ? path : `/${path}`}`

export const authConfigured = Boolean(runtimeConfig.neonAuthUrl)

let cachedAccessToken: string | null = null
let cachedAccessTokenExpiresAt = 0

function apiErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback
  const source = payload as Record<string, unknown>
  if (typeof source.detail === 'string' && source.detail.trim()) return source.detail
  if (typeof source.message === 'string' && source.message.trim()) return source.message
  if (typeof source.error === 'string' && source.error.trim()) return source.error
  return fallback
}

async function authRequest<T>(path: string, init: RequestInit): Promise<AuthResult<T>> {
  const response = await fetch(authEndpoint(path), {
    ...init,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init.headers || {}),
    },
  })

  let payload: unknown = null
  try { payload = await response.json() } catch { /* resposta sem JSON */ }

  if (!response.ok) {
    return { data: null, error: { message: apiErrorMessage(payload, `Erro ${response.status}`) } }
  }
  return { data: (payload ?? {}) as T, error: null }
}

function jwtExpiresAt(token: string): number {
  try {
    const part = token.split('.')[1]
    if (!part) return 0
    const normalized = part.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    const payload = JSON.parse(atob(padded)) as { exp?: unknown }
    return typeof payload.exp === 'number' ? payload.exp : 0
  } catch {
    return 0
  }
}

function cacheToken(token: string | undefined | null) {
  if (!token) return
  cachedAccessToken = token
  cachedAccessTokenExpiresAt = jwtExpiresAt(token)
}

function clearTokenCache() {
  cachedAccessToken = null
  cachedAccessTokenExpiresAt = 0
}

async function token(): Promise<AuthResult<{ token: string }>> {
  const now = Math.floor(Date.now() / 1000)
  if (cachedAccessToken && (!cachedAccessTokenExpiresAt || cachedAccessTokenExpiresAt > now + 30)) {
    return { data: { token: cachedAccessToken }, error: null }
  }

  clearTokenCache()
  const result = await authRequest<{ token: string }>('/token', { method: 'GET' })
  if (result.data?.token) cacheToken(result.data.token)
  return result
}

export const authClient = authConfigured ? {
  signIn: {
    email: async (payload: SignInPayload) => {
      const result = await authRequest<{ ok: boolean; token?: string }>('/sign-in', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      if (result.data?.token) cacheToken(result.data.token)
      return result
    },
  },
  signUp: {
    email: async (payload: SignUpPayload) => {
      const result = await authRequest<{ ok: boolean; token?: string }>('/sign-up', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      if (result.data?.token) cacheToken(result.data.token)
      return result
    },
  },
  requestPasswordReset: (payload: PasswordResetRequest) => authRequest<{ ok: boolean }>('/request-password-reset', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  resetPassword: (payload: ResetPasswordRequest) => authRequest<{ ok: boolean }>('/reset-password', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  invitation: (inviteToken: string) => authRequest<InvitationDetails>(`/invitations/${encodeURIComponent(inviteToken)}`, { method: 'GET' }),
  acceptInvitation: async (payload: { token: string; password: string }) => {
    const result = await authRequest<{ ok: boolean; token?: string }>('/accept-invitation', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    if (result.data?.token) cacheToken(result.data.token)
    return result
  },
  token,
  signOut: async () => {
    try {
      return await authRequest<{ ok: boolean }>('/sign-out', { method: 'POST' })
    } finally {
      clearTokenCache()
    }
  },
} : null
