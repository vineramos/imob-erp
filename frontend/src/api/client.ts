import { authClient, authConfigured } from '../auth/client'
import { runtimeConfig } from '../config/runtime'
import { formatApiPayload, normalizeJsonRequest } from '../utils/brFormat'

const API_URL = runtimeConfig.apiUrl
export const TENANT_PORTAL_AUTH_EVENT = 'imob:tenant-portal-auth-required'

export class ApiError extends Error {
  status: number
  detail: string
  payload: unknown

  constructor(status: number, detail: string, payload: unknown = null) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.payload = payload
  }
}

async function getAccessToken(): Promise<string | null> {
  if (!authConfigured || !authClient) return null
  try {
    const result = await authClient.token()
    if (result.error) return null
    return result.data?.token || null
  } catch { return null }
}

async function errorDetail(response: Response): Promise<{ detail: string; payload: unknown }> {
  let detail = `Erro ${response.status}`
  let payload: unknown = null
  try {
    const data = (await response.json()) as { detail?: unknown }
    payload = data.detail ?? data
    if (typeof data.detail === 'string') detail = data.detail
    else if (data.detail && typeof data.detail === 'object') {
      const candidate = data.detail as { reason?: unknown; message?: unknown }
      if (typeof candidate.reason === 'string') detail = candidate.reason
      else if (typeof candidate.message === 'string') detail = candidate.message
    }
  } catch { /* mantém mensagem HTTP */ }
  return { detail, payload }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = await errorDetail(response)
    throw new ApiError(response.status, error.detail, error.payload)
  }
  if (response.status === 204) return undefined as T
  return formatApiPayload((await response.json()) as T)
}

function apiUrl(path: string): string { return `${API_URL}${path.startsWith('/') ? path : `/${path}`}` }
function applyBodyContentType(headers: Headers, body: BodyInit | null | undefined) {
  if (body && !(body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
}
function notifyTenantPortalAuth(path: string, response: Response) {
  if (typeof window === 'undefined' || !path.startsWith('/tenant-portal/')) return
  if (response.status === 401 || response.status === 403 || path === '/tenant-portal/auth/logout') {
    window.dispatchEvent(new Event(TENANT_PORTAL_AUTH_EVENT))
  }
}

export async function publicApiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const normalized = normalizeJsonRequest(init)
  const headers = new Headers(normalized.headers)
  applyBodyContentType(headers, normalized.body)
  const response = await fetch(apiUrl(path), { ...normalized, headers, credentials: normalized.credentials || 'include' })
  notifyTenantPortalAuth(path, response)
  return parseResponse<T>(response)
}

export async function publicBlobRequest(path: string, init: RequestInit = {}): Promise<Blob> {
  const normalized = normalizeJsonRequest(init)
  const headers = new Headers(normalized.headers)
  const response = await fetch(apiUrl(path), { ...normalized, headers, credentials: normalized.credentials || 'include' })
  notifyTenantPortalAuth(path, response)
  if (!response.ok) {
    const error = await errorDetail(response)
    throw new ApiError(response.status, error.detail, error.payload)
  }
  return response.blob()
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken()
  const normalized = normalizeJsonRequest(init)
  const headers = new Headers(normalized.headers)
  applyBodyContentType(headers, normalized.body)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return parseResponse<T>(await fetch(apiUrl(path), { ...normalized, headers }))
}

export async function apiBlobRequest(path: string, init: RequestInit = {}): Promise<Blob> {
  const token = await getAccessToken()
  const normalized = normalizeJsonRequest(init)
  const headers = new Headers(normalized.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(apiUrl(path), { ...normalized, headers })
  if (!response.ok) {
    const error = await errorDetail(response)
    throw new ApiError(response.status, error.detail, error.payload)
  }
  return response.blob()
}
