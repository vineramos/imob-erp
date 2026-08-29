import { createAuthClient } from '@neondatabase/auth'

const authUrl = import.meta.env.VITE_NEON_AUTH_URL as string | undefined

export const authConfigured = Boolean(authUrl)
export const authClient = authUrl ? createAuthClient(authUrl) : null
