export type AgendaView = 'month' | 'week' | 'day'
export type AgendaPriority = 'low' | 'normal' | 'high' | 'urgent'
export type AgendaLevel = 'collaborator' | 'manager' | 'director' | 'admin'

export type AgendaDirectoryUser = {
  id: string
  name: string
  email: string
  department_id: string | null
  department_name: string | null
  access_level: AgendaLevel
  can_view_calendar: boolean
  can_view_details: boolean
  can_create: boolean
  can_reschedule: boolean
  access_reason: string | null
}

export type AgendaContext = {
  current_user_id: string
  current_user_name: string
  access_level: AgendaLevel
  department_id: string | null
  department_name: string | null
  work_start: string
  work_end: string
  lunch_start: string | null
  lunch_end: string | null
  work_days: number[]
  buffer_minutes: number
  default_duration_minutes: number
  timezone: string
  departments: { id: string; name: string }[]
  directory: AgendaDirectoryUser[]
}

export type AgendaEvent = {
  id: string
  event_type: string
  title: string
  description: string | null
  start_at: string
  end_at: string | null
  all_day: boolean
  priority: AgendaPriority
  status: string
  module: string
  source_id: string | null
  source_code: string | null
  responsible_name: string | null
  owner_user_id: string | null
  department_id: string | null
  department_name: string | null
  property_code: string | null
  amount: number | null
  automatic: boolean
  mandatory_action: boolean
  task_id: string | null
  privacy: 'normal' | 'private'
  masked: boolean
  needs_justification: boolean
  original_scheduled_at: string | null
  reschedule_sequence: number
  missed_justification: string | null
  location: string | null
}

export type AgendaResponse = { start_date: string; end_date: string; events: AgendaEvent[] }

export type Delegation = {
  id: string
  owner_user_id: string
  owner_name: string
  delegate_user_id: string
  delegate_name: string
  can_view_availability: boolean
  can_view_details: boolean
  can_create: boolean
  can_reschedule: boolean
}

export type AvailabilityResponse = {
  all_available: boolean
  users: { user_id: string; user_name: string; available: boolean; reason: string | null; next_available_at: string | null }[]
}

export type MeetingOption = {
  id: string
  starts_at: string
  ends_at: string
  status: string
  proposed_by_user_id: string
  my_vote: string | null
  votes: Record<string, string>
  all_available: boolean
  availability: { user_id: string; user_name: string; available: boolean; reason: string | null }[]
}

export type MeetingRequest = {
  id: string
  code: string
  title: string
  description: string | null
  duration_minutes: number
  privacy: string
  status: string
  selected_option_id: string | null
  organizer: { id: string; name: string }
  participants: { id: string; name: string; status: string }[]
  options: MeetingOption[]
  direction: 'incoming' | 'outgoing'
  created_at: string
}

export type SystemPendingTask = {
  id: string
  code: string
  title: string
  description: string | null
  starts_at: string
  original_scheduled_at: string | null
  reschedule_sequence: number
  department_name: string | null
}

export type TodaySummary = {
  date: string
  show_popup: boolean
  events: AgendaEvent[]
  pending_justifications: SystemPendingTask[]
  pending_invites: number
}

export type ConflictPayload = {
  code?: string
  self_conflict?: boolean
  user_id?: string
  user_name?: string
  reason?: string
  next_available_at?: string | null
}

export const weekDays = ['DOM', 'SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SÁB']

export function localDateValue(date: Date) {
  const offset = date.getTimezoneOffset()
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 10)
}
export function todayValue() { return localDateValue(new Date()) }
export function parseDay(value: string) { return new Date(`${value}T12:00:00`) }
export function addDays(value: string, amount: number) { const date = parseDay(value); date.setDate(date.getDate() + amount); return localDateValue(date) }
export function shiftMonth(value: string, amount: number) { const date = parseDay(value); date.setMonth(date.getMonth() + amount); return localDateValue(date) }
export function eventDay(item: AgendaEvent) { return item.all_day ? item.start_at.slice(0, 10) : localDateValue(new Date(item.start_at)) }
export function eventTime(item: AgendaEvent) { return item.all_day ? 'Dia todo' : new Date(item.start_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) }
export function dayLabel(value: string) { return parseDay(value).toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: 'short' }).replace('.', '') }
export function fullDayLabel(value: string) { return parseDay(value).toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' }) }

export function periodRange(reference: string, view: AgendaView) {
  const base = parseDay(reference)
  if (view === 'day') return { start: reference, end: reference }
  if (view === 'week') {
    const start = new Date(base); start.setDate(start.getDate() - start.getDay())
    const end = new Date(start); end.setDate(end.getDate() + 6)
    return { start: localDateValue(start), end: localDateValue(end) }
  }
  const first = new Date(base.getFullYear(), base.getMonth(), 1, 12)
  const start = new Date(first); start.setDate(start.getDate() - start.getDay())
  const last = new Date(base.getFullYear(), base.getMonth() + 1, 0, 12)
  const end = new Date(last); end.setDate(end.getDate() + (6 - end.getDay()))
  return { start: localDateValue(start), end: localDateValue(end) }
}

export function periodTitle(reference: string, view: AgendaView) {
  const date = parseDay(reference)
  if (view === 'month') return date.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })
  if (view === 'day') return fullDayLabel(reference)
  const range = periodRange(reference, view)
  return `${parseDay(range.start).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })} — ${parseDay(range.end).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' })}`
}

export function priorityLabel(value: string) { return value === 'urgent' ? 'Urgente' : value === 'high' ? 'Alta' : value === 'low' ? 'Baixa' : 'Normal' }
export function money(value: number | null) { return value == null ? null : value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) }
export function toLocalDateTimeInput(iso: string) { const d = new Date(iso); const offset = d.getTimezoneOffset(); return new Date(d.getTime() - offset * 60000).toISOString().slice(0, 16) }
export function humanDateTime(iso: string) { return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) }
