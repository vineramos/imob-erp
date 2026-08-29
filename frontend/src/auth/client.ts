import { createAuthClient } from '@neondatabase/neon-js/auth'

import { runtimeConfig } from '../config/runtime'

const authUrl = runtimeConfig.neonAuthUrl

export const authConfigured = Boolean(authUrl)
export const authClient = authUrl ? createAuthClient(authUrl) : null
