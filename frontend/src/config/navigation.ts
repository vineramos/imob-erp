import {
  Building2,
  CalendarDays,
  ChartNoAxesCombined,
  CircleDollarSign,
  ClipboardCheck,
  FileText,
  Gauge,
  Handshake,
  House,
  Settings,
  Users,
  Wrench,
} from 'lucide-react'

export const navigation = [
  { label: 'Dashboard', icon: Gauge, module: 'dashboard', permission: 'dashboard.view' },
  { label: 'Imóveis', icon: House, module: 'properties', permission: 'properties.view' },
  { label: 'Captações', icon: Handshake, module: 'captures', permission: 'captures.view' },
  { label: 'Comercial / CRM', icon: Users, module: 'crm', permission: 'crm.view' },
  { label: 'Contratos', icon: FileText, module: 'contracts', permission: 'contracts.view' },
  { label: 'Financeiro', icon: CircleDollarSign, module: 'finance', permission: 'finance.view' },
  { label: 'Manutenções', icon: Wrench, module: 'maintenance', permission: 'maintenance.view' },
  { label: 'Vistorias', icon: ClipboardCheck, module: 'inspections', permission: 'inspections.view' },
  { label: 'Documentos', icon: Building2, module: 'documents', permission: 'documents.view' },
  { label: 'Agenda / Tarefas', icon: CalendarDays, module: 'agenda', permission: 'agenda.view' },
  { label: 'Relatórios', icon: ChartNoAxesCombined, module: 'reports', permission: 'reports.view' },
  { label: 'Configurações', icon: Settings, module: 'settings', permission: 'settings.view' },
] as const
