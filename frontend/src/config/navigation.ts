import {
  CalendarDays, ChartNoAxesCombined, CircleDollarSign, ClipboardCheck, FileText,
  Gauge, House, MessagesSquare, Settings, ShieldCheck, Target, UserRoundCheck,
  Users, Wrench, type LucideIcon,
} from 'lucide-react'

/** Mapa técnico estável usado por autenticação, permissões, busca e deep links. */
export const navigation = [
  { label: 'Início', icon: Gauge, module: 'dashboard', permission: 'dashboard.view' },
  { label: 'Clientes', icon: Users, module: 'people', permission: 'properties.view' },
  { label: 'Imóveis', icon: House, module: 'properties', permission: 'properties.view' },
  { label: 'Corretores', icon: UserRoundCheck, module: 'brokers', permission: 'properties.view' },
  { label: 'Captações', icon: Target, module: 'captures', permission: 'captures.view' },
  { label: 'Comercial', icon: Target, module: 'crm', permission: 'crm.view' },
  { label: 'Contratos', icon: FileText, module: 'contracts', permission: 'contracts.view' },
  { label: 'Vistorias', icon: ClipboardCheck, module: 'inspections', permission: 'inspections.view' },
  { label: 'Manutenções', icon: Wrench, module: 'maintenance', permission: 'maintenance.view' },
  { label: 'Financeiro', icon: CircleDollarSign, module: 'finance', permission: 'finance.view' },
  { label: 'Agenda / Tarefas', icon: CalendarDays, module: 'agenda', permission: 'agenda.view' },
  { label: 'Comunicações', icon: MessagesSquare, module: 'communications', permission: 'communications.view' },
  { label: 'Relatórios', icon: ChartNoAxesCombined, module: 'reports', permission: 'reports.view' },
  { label: 'Documentos', icon: FileText, module: 'documents', permission: 'documents.view' },
  { label: 'Configurações', icon: Settings, module: 'settings', permission: 'settings.view' },
] as const

export type ModuleKey = (typeof navigation)[number]['module']

export type SidebarItem = {
  label: string
  icon?: LucideIcon
  module: ModuleKey
  permission: string
  route: string
}

export type SidebarSection = SidebarItem & { children?: readonly SidebarItem[] }

const item = (label: string, module: ModuleKey, permission: string, icon: LucideIcon): SidebarItem => ({
  label, module, permission, icon, route: `/app/${module}`,
})

/**
 * Navegação canônica Imob 8.1:
 * a sidebar expõe somente módulos. Listas, fichas, filtros e subáreas vivem
 * dentro do respectivo workspace para evitar crescimento indefinido do menu.
 */
export const sidebarNavigation: readonly SidebarSection[] = [
  item('Início', 'dashboard', 'dashboard.view', Gauge),
  item('Imóveis', 'properties', 'properties.view', House),
  item('Clientes', 'people', 'properties.view', Users),
  item('Comercial', 'crm', 'crm.view', Target),
  item('Corretores', 'brokers', 'properties.view', UserRoundCheck),
  item('Contratos', 'contracts', 'contracts.view', FileText),
  item('Vistorias', 'inspections', 'inspections.view', ClipboardCheck),
  item('Manutenções', 'maintenance', 'maintenance.view', Wrench),
  item('Financeiro', 'finance', 'finance.view', CircleDollarSign),
  item('Documentos', 'documents', 'documents.view', FileText),
  item('Relatórios', 'reports', 'reports.view', ChartNoAxesCombined),
  item('Configurações', 'settings', 'settings.view', ShieldCheck),
] as const
