import { authClient, authConfigured } from '../auth/client'
import { runtimeConfig } from '../config/runtime'
import { formatApiPayload, normalizeJsonRequest } from '../utils/brFormat'

const API_URL = runtimeConfig.apiUrl

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
  try {
    const result = await authClient.token()
    if (result.error) return null
    return result.data?.token || null
  } catch { return null }
}

async function errorDetail(response: Response): Promise<string> {
  let detail = `Erro ${response.status}`
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === 'string') detail = payload.detail
  } catch { /* mantém mensagem HTTP */ }
  return detail
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
  if (response.status === 204) return undefined as T
  return formatApiPayload((await response.json()) as T)
}

function apiUrl(path: string): string { return `${API_URL}${path.startsWith('/') ? path : `/${path}`}` }
function applyBodyContentType(headers: Headers, body: BodyInit | null | undefined) {
  if (body && !(body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
}

export async function publicApiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const normalized = normalizeJsonRequest(init)
  const headers = new Headers(normalized.headers)
  applyBodyContentType(headers, normalized.body)
  return parseResponse<T>(await fetch(apiUrl(path), { ...normalized, headers }))
}

export async function publicBlobRequest(path: string, init: RequestInit = {}): Promise<Blob> {
  const normalized = normalizeJsonRequest(init)
  const headers = new Headers(normalized.headers)
  const response = await fetch(apiUrl(path), { ...normalized, headers })
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
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
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
  return response.blob()
}
