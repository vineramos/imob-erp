import type { ThemeConfig } from '../theme/theme'

export type CurrentUser = {
  id: string
  name: string
  email: string
  organization_id: string
  organization_name: string
  role_keys: string[]
  permissions: string[]
}

export type OrganizationProfile = {
  id: string
  legal_name: string
  display_name: string
  document_number: string | null
  creci_pj: string | null
  contact_email: string | null
  contact_phone: string | null
  address: Record<string, string>
}

export type OrganizationProfileUpdate = Omit<OrganizationProfile, 'id'>

export type AuditEvent = {
  id: string
  actor_user_id: string | null
  actor_name: string | null
  action: string
  module: string
  entity_type: string
  entity_id: string | null
  before_data: Record<string, unknown> | null
  after_data: Record<string, unknown> | null
  reason: string | null
  ip_address: string | null
  created_at: string
}

export type { ThemeConfig }
