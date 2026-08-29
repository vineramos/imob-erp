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
  { label: 'Dashboard', icon: Gauge, module: 'dashboard' },
  { label: 'Imóveis', icon: House, module: 'properties' },
  { label: 'Captações', icon: Handshake, module: 'captures' },
  { label: 'Comercial / CRM', icon: Users, module: 'crm' },
  { label: 'Contratos', icon: FileText, module: 'contracts' },
  { label: 'Financeiro', icon: CircleDollarSign, module: 'finance' },
  { label: 'Manutenções', icon: Wrench, module: 'maintenance' },
  { label: 'Vistorias', icon: ClipboardCheck, module: 'inspections' },
  { label: 'Documentos', icon: Building2, module: 'documents' },
  { label: 'Agenda / Tarefas', icon: CalendarDays, module: 'agenda' },
  { label: 'Relatórios', icon: ChartNoAxesCombined, module: 'reports' },
  { label: 'Configurações', icon: Settings, module: 'settings' },
] as const
