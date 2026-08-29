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

export type AdjustmentIndex = 'IPCA' | 'IGP-M' | 'INPC' | 'IPC-FIPE' | 'IGP-DI'

export type OperationalDefaults = {
  rent_due_day: number
  owner_repasse_business_days: number
  residential_lease_months: number
  adjustment_index: AdjustmentIndex
  termination_fine_months: number
  inspection_contest_days: number
  default_admin_fee_percent: number
  delinquency_critical_day: number
}

export type IntegrationsConfig = {
  bank_provider: 'none' | 'inter'
  signature_provider: 'none' | 'clicksign'
  email_provider: 'none' | 'smtp'
  public_site_enabled: boolean
  webhook_base_url: string
  notes: string
}

export type ApprovalRule = {
  id: string
  name: string
  scope: string
  priority: number
  min_amount: number | null
  max_amount: number | null
  required_approvals: number
  approver_permission: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ApprovalRulePayload = Omit<ApprovalRule, 'id' | 'created_at' | 'updated_at'> & {
  reason?: string | null
}

export type Role = {
  id: string
  key: string
  name: string
  description: string | null
  is_system: boolean
  is_active: boolean
  permissions: string[]
  user_count: number
}

export type AppUser = {
  id: string
  name: string
  email: string
  is_active: boolean
  blocked_at: string | null
  created_at: string
  role_keys: string[]
}

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
