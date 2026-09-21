import {
  BadgeDollarSign, BriefcaseBusiness, Building2, CalendarCheck2, CalendarDays,
  ChartNoAxesCombined, CircleDollarSign, ClipboardCheck, FileCheck2, FileClock,
  FileText, Gauge, Handshake, House, KeyRound, LayoutDashboard, ListChecks,
  MapPinned, MessagesSquare, ReceiptText, Settings, ShieldCheck, Target,
  UserRound, UserRoundCheck, Users, WalletCards, Wrench, type LucideIcon,
} from 'lucide-react'

/** Mapa técnico estável usado por autenticação, permissões, busca e deep links. */
export const navigation = [
  { label: 'Início', icon: Gauge, module: 'dashboard', permission: 'dashboard.view' },
  { label: 'Clientes', icon: UserRound, module: 'people', permission: 'properties.view' },
  { label: 'Imóveis', icon: House, module: 'properties', permission: 'properties.view' },
  { label: 'Corretores', icon: UserRoundCheck, module: 'brokers', permission: 'properties.view' },
  { label: 'Captações', icon: Handshake, module: 'captures', permission: 'captures.view' },
  { label: 'Comercial', icon: Users, module: 'crm', permission: 'crm.view' },
  { label: 'Contratos', icon: FileText, module: 'contracts', permission: 'contracts.view' },
  { label: 'Vistorias', icon: ClipboardCheck, module: 'inspections', permission: 'inspections.view' },
  { label: 'Manutenções', icon: Wrench, module: 'maintenance', permission: 'maintenance.view' },
  { label: 'Financeiro', icon: CircleDollarSign, module: 'finance', permission: 'finance.view' },
  { label: 'Agenda / Tarefas', icon: CalendarDays, module: 'agenda', permission: 'agenda.view' },
  { label: 'Comunicações', icon: MessagesSquare, module: 'communications', permission: 'communications.view' },
  { label: 'Relatórios', icon: ChartNoAxesCombined, module: 'reports', permission: 'reports.view' },
  { label: 'Documentos', icon: Building2, module: 'documents', permission: 'documents.view' },
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

const item = (label: string, module: ModuleKey, permission: string, icon: LucideIcon, view?: string): SidebarItem => ({
  label, module, permission, icon, route: `/app/${module}${view ? `?view=${view}` : ''}`,
})

/** Hierarquia de produto do Imob 8.1. As subrotas reutilizam os módulos atuais. */
export const sidebarNavigation: readonly SidebarSection[] = [
  item('Início', 'dashboard', 'dashboard.view', LayoutDashboard),
  {
    ...item('Imóveis', 'properties', 'properties.view', House),
    children: [
      item('Todos os imóveis', 'properties', 'properties.view', House),
      item('Captações', 'captures', 'captures.view', Handshake),
      item('Publicações', 'properties', 'properties.view', MapPinned, 'publications'),
    ],
  },
  {
    ...item('Clientes', 'people', 'properties.view', Users),
    children: [
      item('Proprietários', 'people', 'properties.view', UserRound, 'owners'),
      item('Compradores', 'people', 'properties.view', BadgeDollarSign, 'buyers'),
      item('Locatários', 'people', 'properties.view', KeyRound, 'tenants'),
    ],
  },
  {
    ...item('Comercial', 'crm', 'crm.view', Target),
    children: [
      item('Leads', 'crm', 'crm.view', Users, 'leads'),
      item('Oportunidades', 'crm', 'crm.view', Target, 'opportunities'),
      item('Visitas', 'crm', 'crm.view', CalendarCheck2, 'visits'),
      item('Propostas', 'crm', 'crm.view', FileCheck2, 'proposals'),
      item('Funil', 'crm', 'crm.view', ChartNoAxesCombined, 'funnel'),
    ],
  },
  {
    ...item('Corretores', 'brokers', 'properties.view', UserRoundCheck),
    children: [
      item('Equipe', 'brokers', 'properties.view', Users, 'team'),
      item('Carteiras', 'brokers', 'properties.view', BriefcaseBusiness, 'portfolios'),
      item('Metas', 'brokers', 'properties.view', Target, 'goals'),
      item('Comissões', 'brokers', 'properties.view', BadgeDollarSign, 'commissions'),
    ],
  },
  {
    ...item('Contratos', 'contracts', 'contracts.view', FileText),
    children: [
      item('Venda', 'contracts', 'contracts.view', FileCheck2, 'sales'),
      item('Locação', 'contracts', 'contracts.view', KeyRound, 'leases'),
      item('Administração', 'contracts', 'contracts.view', Building2, 'administration'),
      item('Renovações', 'contracts', 'contracts.view', FileClock, 'renewals'),
    ],
  },
  {
    ...item('Vistorias', 'inspections', 'inspections.view', ClipboardCheck),
    children: [
      item('Entrada', 'inspections', 'inspections.view', ClipboardCheck, 'entry'),
      item('Saída', 'inspections', 'inspections.view', ClipboardCheck, 'exit'),
      item('Periódicas', 'inspections', 'inspections.view', CalendarDays, 'periodic'),
      item('Pendências', 'inspections', 'inspections.view', ListChecks, 'pending'),
    ],
  },
  {
    ...item('Manutenções', 'maintenance', 'maintenance.view', Wrench),
    children: [
      item('Chamados', 'maintenance', 'maintenance.view', Wrench, 'calls'),
      item('Ordens de serviço', 'maintenance', 'maintenance.view', ListChecks, 'orders'),
      item('Fornecedores', 'maintenance', 'maintenance.view', Users, 'suppliers'),
      item('Orçamentos', 'maintenance', 'maintenance.view', ReceiptText, 'quotes'),
    ],
  },
  {
    ...item('Financeiro', 'finance', 'finance.view', CircleDollarSign),
    children: [
      item('Contas a receber', 'finance', 'finance.view', ReceiptText, 'receivables'),
      item('Contas a pagar', 'finance', 'finance.view', WalletCards, 'payables'),
      item('Repasses', 'finance', 'finance.view', Handshake, 'transfers'),
      item('Comissões', 'finance', 'finance.view', BadgeDollarSign, 'commissions'),
      item('Fluxo de caixa', 'finance', 'finance.view', ChartNoAxesCombined, 'cash-flow'),
    ],
  },
  item('Documentos', 'documents', 'documents.view', FileText),
  item('Relatórios', 'reports', 'reports.view', ChartNoAxesCombined),
  item('Configurações', 'settings', 'settings.view', ShieldCheck),
] as const
