import { RefreshCw, Wrench } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'

type PropertyMaintenance = {
  id: string
  code: string
  property_id: string
  title: string
  status: string
  priority: string
  category: string
  description: string
  requester_name: string | null
  supplier_name: string | null
  estimated_cost: number | null
  approved_cost: number | null
  actual_cost: number | null
  reported_at: string
  scheduled_at: string | null
  completed_at: string | null
}

type Props = { propertyId: string; permissions: string[] }

const statusLabels: Record<string, string> = {
  requested: 'Solicitado', triage: 'Triagem', awaiting_quote: 'Aguardando orçamento', awaiting_approval: 'Aguardando aprovação',
  approved: 'Aprovado', scheduled: 'Agendado', in_progress: 'Em execução', completed: 'Concluído', cancelled: 'Cancelado',
}
const priorityLabels: Record<string, string> = { low: 'Baixa', normal: 'Normal', high: 'Alta', urgent: 'Urgente' }

function money(value: number | null | undefined) { if (value == null) return '—'; return Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) }
function dateLabel(value: string | null | undefined) { if (!value) return '—'; return new Date(value).toLocaleString('pt-BR') }
function statusClass(value: string) {
  if (['approved', 'completed'].includes(value)) return 'success'
  if (value === 'cancelled') return 'danger'
  if (['awaiting_quote', 'awaiting_approval', 'scheduled'].includes(value)) return 'warning'
  if (value === 'in_progress') return 'info'
  return 'neutral'
}

export function PropertyMaintenancePanel({ propertyId, permissions }: Props) {
  const canView = permissions.includes('maintenance.view')
  const [items, setItems] = useState<PropertyMaintenance[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!canView) return
    setLoading(true); setError('')
    try { setItems(await apiRequest<PropertyMaintenance[]>(`/maintenance?property_id=${propertyId}`)) }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar as manutenções deste imóvel.') }
    finally { setLoading(false) }
  }, [canView, propertyId])

  useEffect(() => { void load() }, [load])

  return <article className="panel property-tab-panel">
    <div className="property-panel-heading"><div><span className="eyebrow">Manutenções</span><h2>Ocorrências e serviços</h2></div>{canView && <button className="button secondary compact-button" type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={13}/> {loading ? 'Atualizando...' : 'Atualizar'}</button>}</div>
    {!canView ? <div className="property-inline-empty">Seu perfil não possui acesso às manutenções.</div> : error ? <div className="form-alert danger-alert">{error}</div> : loading && !items.length ? <div className="property-inline-empty">Carregando manutenções vinculadas...</div> : items.length ? <div className="property-record-list">{items.map((item) => {
      const cost = item.actual_cost ?? item.approved_cost ?? item.estimated_cost
      const timeline = item.status === 'completed' ? `Concluída em ${dateLabel(item.completed_at)}` : item.scheduled_at ? `Agendada para ${dateLabel(item.scheduled_at)}` : `Aberta em ${dateLabel(item.reported_at)}`
      return <div className="property-record" key={item.id}><Wrench size={18}/><div><strong>{item.code} · {item.title}</strong><span>{item.supplier_name || item.requester_name || 'Fornecedor ainda não definido'} · Prioridade {priorityLabels[item.priority] ?? item.priority}</span><small>{timeline} · custo {money(cost)}</small></div><i className={`status-badge ${statusClass(item.status)}`}>{statusLabels[item.status] ?? item.status}</i></div>
    })}</div> : <div className="property-inline-empty">Nenhuma manutenção vinculada a este imóvel.</div>}
  </article>
}
