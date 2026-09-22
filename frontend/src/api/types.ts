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
  delinquency_first_contact_day: number
  delinquency_followup_day: number
  delinquency_critical_day: number
  late_fee_percent: number
  late_interest_percent_monthly: number
  late_interest_type: 'simple' | 'compound'
  late_interest_compounding: 'daily' | 'monthly'
}

export type IntegrationsConfig = {
  bank_provider: 'none' | 'inter'
  signature_provider: 'none' | 'clicksign'
  email_provider: 'none' | 'smtp'
  public_site_enabled: boolean
  webhook_base_url: string
  notes: string
}

export type SignatureIntegrationStatus = {
  provider: string
  environment: string
  configured: boolean
  reachable: boolean | null
  message: string
  checked_at: string
}

export type BankIntegrationStatus = SignatureIntegrationStatus

export type SmtpConfiguration = {
  host: string
  port: number
  username: string
  from_email: string
  from_name: string
  use_tls: boolean
  use_ssl: boolean
  password_configured: boolean
  source: 'erp' | 'environment' | 'none'
}


export type IntegrationReadinessItem = {
  key: string
  label: string
  status: 'ready' | 'attention' | 'disabled'
  selected: boolean
  configured: boolean
  critical: boolean
  message: string
  environment: string | null
}

export type IntegrationReadiness = {
  ready: boolean
  pending_count: number
  items: IntegrationReadinessItem[]
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

export type ApprovalRulePayload = Omit<ApprovalRule, 'id' | 'created_at' | 'updated_at'> & { reason?: string | null }

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
  access_status: 'active' | 'pending' | 'blocked'
}

export type UserInvitation = {
  user: AppUser
  token: string
  expires_at: string
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

export type Address = {
  street: string
  number: string
  complement: string
  neighborhood: string
  city: string
  state: string
  postal_code: string
}

export type Person = {
  id: string
  person_type: 'individual' | 'company'
  name: string
  document_number: string | null
  email: string | null
  phone: string | null
  address: Address
  notes: string | null
  is_active: boolean
  role_keys: string[]
  created_at: string
}

export type PersonCreate = {
  person_type: 'individual' | 'company'
  name: string
  document_number?: string | null
  email?: string | null
  phone?: string | null
  address: Address
  notes?: string | null
  role_keys: Array<'owner' | 'tenant' | 'guarantor' | 'broker' | 'supplier' | 'referrer'>
}

export type PropertyOwner = { person_id: string; name: string; ownership_percent: number }
export type PropertyResponsibleBroker = { person_id: string; name: string; email: string | null; phone: string | null }

export type PropertyFeatures = {
  property: string[]
  condominium: string[]
  floor: number | null
  total_floors: number | null
  elevators: number | null
  solar_orientation: '' | 'north' | 'south' | 'east' | 'west' | 'northeast' | 'northwest' | 'southeast' | 'southwest'
  year_built: number | null
}

export type Property = {
  id: string
  internal_number: number
  code: string
  property_type: string
  purpose: string
  status: string
  address: Address
  rent_amount: number | null
  condo_amount: number | null
  iptu_amount: number | null
  area_m2: number | null
  bedrooms: number
  suites: number
  bathrooms: number
  parking_spaces: number
  furnished: boolean
  pets_allowed: boolean
  features: PropertyFeatures
  public_title: string | null
  public_slug?: string | null
  publication_enabled: boolean
  published_at?: string | null
  owners: PropertyOwner[]
  responsible_broker: PropertyResponsibleBroker | null
  created_at: string
  updated_at: string
}

export type PropertyCreate = {
  property_type: 'apartment' | 'house' | 'commercial' | 'land' | 'studio' | 'other'
  purpose: 'rent' | 'sale'
  status: 'draft' | 'available' | 'reserved' | 'leased' | 'inactive'
  address: Address
  rent_amount?: number | null
  condo_amount?: number | null
  iptu_amount?: number | null
  area_m2?: number | null
  bedrooms: number
  suites: number
  bathrooms: number
  parking_spaces: number
  furnished: boolean
  pets_allowed: boolean
  features: PropertyFeatures
  public_title?: string | null
  public_description?: string | null
  publication_enabled: boolean
  owners: Array<{ person_id: string; ownership_percent: number }>
}

export type PublicationChecklistItem = { key: string; label: string; ok: boolean; required: boolean; detail: string }
export type PublicationReadiness = { property_id: string; code: string; ready: boolean; publication_enabled: boolean; public_slug: string | null; checklist: PublicationChecklistItem[] }

export type PublicSiteProfile = {
  organization_id: string
  display_name: string
  contact_email: string | null
  contact_phone: string | null
  theme: Record<string, unknown>
}

export type PublicProperty = {
  code: string
  slug: string
  property_type: string
  purpose: string
  address: Partial<Address>
  rent_amount: number | null
  condo_amount: number | null
  iptu_amount: number | null
  area_m2: number | null
  bedrooms: number
  suites: number
  bathrooms: number
  parking_spaces: number
  furnished: boolean
  pets_allowed: boolean
  features: PropertyFeatures
  title: string
  description: string
  published_at: string | null
}

export type Capture = {
  id: string
  status: string
  source: string
  contact_person_id: string | null
  contact_person_name: string | null
  responsible_user_id: string | null
  converted_property_id: string | null
  property_type: string | null
  property_address: Address
  estimated_rent: number | null
  notes: string | null
  lost_reason: string | null
  created_at: string
  updated_at: string
}

export type CaptureCreate = {
  status: 'new' | 'negotiation' | 'documents' | 'inspection' | 'approved' | 'available' | 'lost'
  source: 'direct' | 'site' | 'referral' | 'broker' | 'campaign' | 'other'
  contact_person_id?: string | null
  responsible_user_id?: string | null
  property_type?: 'apartment' | 'house' | 'commercial' | 'land' | 'studio' | 'other' | null
  property_address: Address
  estimated_rent?: number | null
  notes?: string | null
}

export type EconomicIndexValue = { index_code: AdjustmentIndex; sgs_code: number; competence: string; monthly_rate: number; source: string; fetched_at: string }
export type EconomicIndexSync = { index_code: AdjustmentIndex; status: 'never' | 'synced' | 'awaiting_publication' | 'error'; imported: number; latest_competence: string | null; next_retry_at: string | null; message: string }

export type AdministrationContractStatus = 'draft' | 'review' | 'approved' | 'pending_signature' | 'signed' | 'cancelled'
export type AdministrationPlan = 'essential' | 'complete' | 'custom'
export type ContractFeeType = 'percent' | 'fixed'
export type OperationalPayer = 'tenant' | 'owner' | 'agency'
export type ContractEndOfTermAction = 'end_contract' | 'renew_indefinite'
export type ContractSignerRole = 'owner' | 'tenant' | 'agency' | 'witness' | 'other'
export type ContractSignerCommunication = 'email' | 'sms' | 'whatsapp' | 'none'

export type ContractSigner = {
  role: ContractSignerRole
  person_id?: string | null
  name: string
  email: string
  document_number: string | null
  phone: string | null
  sign_order: number
  communication: ContractSignerCommunication
}

export type AdministrationContractTerms = {
  plan: AdministrationPlan
  admin_fee_type: ContractFeeType
  admin_fee_percent: number | null
  admin_fee_amount: number | null
  intermediation_percent: number
  intermediation_installments: number
  owner_repasse_business_days: number
  condo_operational_payer: OperationalPayer
  iptu_operational_payer: OperationalPayer
  publication_requires_owner_approval: boolean
  maintenance_limit_amount: number | null
  emergency_limit_amount: number | null
  start_date: string | null
  end_date: string | null
  end_of_term_action: ContractEndOfTermAction
  notes: string | null
  signers: ContractSigner[]
}

export type AdministrationContractCreate = AdministrationContractTerms & { property_id: string }
export type AdministrationContractUpdate = AdministrationContractTerms & { change_summary: string }
export type AdministrationContractVersion = { version_number: number; change_summary: string | null; created_by_user_id: string | null; created_at: string }

export type ContractDocument = {
  contract_id: string
  code: string
  version: number
  hash_sha256: string
  reference: string | null
  storage_configured: boolean
  message: string
}

export type AdministrationContract = AdministrationContractTerms & {
  id: string
  internal_number: number
  code: string
  property_id: string
  property_code: string
  property_address: Address
  owners: Array<{ person_id: string; name: string; document_number: string | null; email?: string | null; phone?: string | null; ownership_percent: string | number }>
  status: AdministrationContractStatus
  current_version: number
  generated_document_reference: string | null
  generated_document_hash: string | null
  generated_document_version: number | null
  signing_provider: string
  signing_status: string
  signing_envelope_id: string | null
  signing_document_id: string | null
  approved_at: string | null
  signed_at: string | null
  archive_status: string
  archived_document_reference: string | null
  final_document_hash: string | null
  archived_at: string | null
  versions: AdministrationContractVersion[]
  created_at: string
  updated_at: string
}

export type AdministrationContractWorkflowAction = 'submit_review' | 'approve' | 'prepare_signature' | 'return_draft' | 'cancel'

export type { ThemeConfig }
