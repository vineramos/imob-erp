import {
  CalendarCheck2,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileText,
  Landmark,
  Plus,
  RefreshCw,
  Wrench,
  X,
  XCircle,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './agenda.css'

type AgendaView = 'month' | 'week' | 'day'
type AgendaUser = { id: string; name: string; email: string }
type AgendaEvent = {
  id: string
  event_type: string
  title: string
  description: string | null
  start_at: string
  end_at: string | null
  all_day: boolean
  priority: 'low' | 'normal' | 'high' | 'urgent'
  status: string
  module: string
  source_id: string | null
  source_code: string | null
  responsible_name: string | null
  property_code: string | null
  amount: number | null
  automatic: boolean
  task_id: string | null
}
type AgendaResponse = { start_date: string; end_date: string; events: AgendaEvent[] }
type ModuleTarget = 'contracts' | 'inspections' | 'maintenance' | 'finance' | 'properties' | 'captures'
type Props = { permissions: string[]; onNavigate: (module: ModuleTarget) => void }

const eventLabels: Record<string, string> = {
  task: 'Tarefa', inspection: 'Vistoria', inspection_deadline: 'Vistoria', maintenance: 'Manutenção',
  contract_expiry: 'Contrato', adjustment: 'Reajuste', billing: 'Cobrança', repasse: 'Repasse',
}
const moduleTargets = new Set<ModuleTarget>(['contracts', 'inspections', 'maintenance', 'finance', 'properties', 'captures'])
const weekDays = ['DOM', 'SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SÁB']
const money = (value: number | null) => value == null ? null : value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

function localDateValue(date: Date) {
  const offset = date.getTimezoneOffset()
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 10)
}
function todayValue() { return localDateValue(new Date()) }
function parseDay(value: string) { return new Date(`${value}T12:00:00`) }
function addDays(value: string, amount: number) { const date = parseDay(value); date.setDate(date.getDate() + amount); return localDateValue(date) }
function shiftMonth(value: string, amount: number) { const date = parseDay(value); date.setMonth(date.getMonth() + amount); return localDateValue(date) }
function eventDay(item: AgendaEvent) { return item.all_day ? item.start_at.slice(0, 10) : localDateValue(new Date(item.start_at)) }
function eventTime(item: AgendaEvent) { return item.all_day ? 'Dia todo' : new Date(item.start_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) }
function dayLabel(value: string) { return parseDay(value).toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: 'short' }).replace('.', '') }
function fullDayLabel(value: string) { return parseDay(value).toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' }) }

function periodRange(reference: string, view: AgendaView) {
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
function periodTitle(reference: string, view: AgendaView) {
  const date = parseDay(reference)
  if (view === 'month') return date.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })
  if (view === 'day') return fullDayLabel(reference)
  const range = periodRange(reference, view)
  return `${parseDay(range.start).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })} — ${parseDay(range.end).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' })}`
}
function priorityLabel(value: string) { return value === 'urgent' ? 'Urgente' : value === 'high' ? 'Alta' : value === 'low' ? 'Baixa' : 'Normal' }

export function AgendaPage({ permissions, onNavigate }: Props) {
  const canManage = permissions.includes('agenda.manage')
  const [view, setView] = useState<AgendaView>('month')
  const [reference, setReference] = useState(todayValue())
  const [events, setEvents] = useState<AgendaEvent[]>([])
  const [users, setUsers] = useState<AgendaUser[]>([])
  const [filter, setFilter] = useState('all')
  const [selected, setSelected] = useState<AgendaEvent | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [taskOpen, setTaskOpen] = useState(false)
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null)
  const [taskTitle, setTaskTitle] = useState('')
  const [taskDescription, setTaskDescription] = useState('')
  const [taskDate, setTaskDate] = useState(todayValue())
  const [taskTime, setTaskTime] = useState('09:00')
  const [taskDueDate, setTaskDueDate] = useState('')
  const [taskDueTime, setTaskDueTime] = useState('18:00')
  const [taskAllDay, setTaskAllDay] = useState(false)
  const [taskPriority, setTaskPriority] = useState('normal')
  const [taskAssigned, setTaskAssigned] = useState('')

  const range = useMemo(() => periodRange(reference, view), [reference, view])
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const result = await apiRequest<AgendaResponse>(`/agenda/events?start=${range.start}&end=${range.end}`)
      setEvents(result.events)
      setSelected(current => current ? result.events.find(item => item.id === current.id) || null : null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar a agenda.')
    } finally { setLoading(false) }
  }, [range.start, range.end])
  useEffect(() => { void load() }, [load])
  useEffect(() => { void apiRequest<AgendaUser[]>('/agenda/users').then(items => { setUsers(items); setTaskAssigned(current => current || items[0]?.id || '') }).catch(() => setUsers([])) }, [])
  useEffect(() => {
    if (!taskOpen) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && !saving) setTaskOpen(false) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [taskOpen, saving])

  const filtered = useMemo(() => events.filter(item => {
    if (filter === 'all') return true
    if (filter === 'tasks') return item.event_type === 'task'
    if (filter === 'inspections') return item.event_type.startsWith('inspection')
    if (filter === 'maintenance') return item.event_type === 'maintenance'
    if (filter === 'contracts') return ['contract_expiry', 'adjustment'].includes(item.event_type)
    return ['billing', 'repasse'].includes(item.event_type)
  }), [events, filter])

  const today = todayValue()
  const nextSeven = addDays(today, 7)
  const metrics = useMemo(() => {
    const todayCount = events.filter(item => eventDay(item) === today && item.status !== 'completed').length
    const next = events.filter(item => eventDay(item) >= today && eventDay(item) <= nextSeven && item.status !== 'completed').length
    const overdue = events.filter(item => item.event_type === 'task' && item.status === 'pending' && item.end_at && new Date(item.end_at).getTime() < Date.now()).length
    const contractSources = new Set(events.filter(item => item.event_type === 'contract_expiry' && eventDay(item) >= today && eventDay(item) <= addDays(today, 30)).map(item => item.source_id))
    return { today: todayCount, next, overdue, contracts: contractSources.size }
  }, [events, today, nextSeven])

  const grouped = useMemo(() => {
    const map = new Map<string, AgendaEvent[]>()
    filtered.forEach(item => { const key = eventDay(item); const rows = map.get(key) || []; rows.push(item); map.set(key, rows) })
    return map
  }, [filtered])

  function navigatePeriod(direction: number) {
    if (view === 'month') setReference(current => shiftMonth(current, direction))
    else if (view === 'week') setReference(current => addDays(current, direction * 7))
    else setReference(current => addDays(current, direction))
  }
  function openNewTask(day = reference) {
    setEditingTaskId(null); setTaskTitle(''); setTaskDescription(''); setTaskDate(day); setTaskTime('09:00'); setTaskDueDate(''); setTaskDueTime('18:00'); setTaskAllDay(false); setTaskPriority('normal'); setTaskAssigned(users[0]?.id || ''); setTaskOpen(true); setError('')
  }
  function editTask(item: AgendaEvent) {
    if (!item.task_id) return
    const start = new Date(item.start_at)
    const end = item.end_at ? new Date(item.end_at) : null
    setEditingTaskId(item.task_id); setTaskTitle(item.title); setTaskDescription(item.description || ''); setTaskDate(item.all_day ? item.start_at.slice(0, 10) : localDateValue(start)); setTaskTime(item.all_day ? '09:00' : start.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })); setTaskDueDate(end ? localDateValue(end) : ''); setTaskDueTime(end ? end.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '18:00'); setTaskAllDay(item.all_day); setTaskPriority(item.priority); setTaskAssigned(users.find(user => user.name === item.responsible_name)?.id || users[0]?.id || ''); setTaskOpen(true)
  }
  async function saveTask(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(''); setSuccess('')
    try {
      const start = taskAllDay ? new Date(`${taskDate}T12:00:00`) : new Date(`${taskDate}T${taskTime}:00`)
      const due = taskDueDate ? (taskAllDay ? new Date(`${taskDueDate}T12:00:00`) : new Date(`${taskDueDate}T${taskDueTime}:00`)) : null
      const body = JSON.stringify({ title: taskTitle, description: taskDescription || null, starts_at: start.toISOString(), due_at: due?.toISOString() || null, all_day: taskAllDay, priority: taskPriority, assigned_user_id: taskAssigned || null, source_module: null, source_type: null, source_id: null })
      if (editingTaskId) await apiRequest(`/agenda/tasks/${editingTaskId}`, { method: 'PUT', body })
      else await apiRequest('/agenda/tasks', { method: 'POST', body })
      setTaskOpen(false); setSuccess(editingTaskId ? 'Tarefa atualizada.' : 'Tarefa incluída na agenda.'); await load()
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar a tarefa.') }
    finally { setSaving(false) }
  }
  async function changeTaskStatus(item: AgendaEvent, status: 'pending' | 'completed' | 'cancelled') {
    if (!item.task_id) return
    setSaving(true); setError('')
    try { await apiRequest(`/agenda/tasks/${item.task_id}/status`, { method: 'POST', body: JSON.stringify({ status }) }); setSelected(null); setSuccess(status === 'completed' ? 'Tarefa concluída.' : status === 'cancelled' ? 'Tarefa cancelada.' : 'Tarefa reaberta.'); await load() }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível atualizar a tarefa.') }
    finally { setSaving(false) }
  }
  function openOrigin(item: AgendaEvent) {
    if (moduleTargets.has(item.module as ModuleTarget)) onNavigate(item.module as ModuleTarget)
  }

  const monthDays = useMemo(() => { const rows: string[] = []; let cursor = range.start; while (cursor <= range.end) { rows.push(cursor); cursor = addDays(cursor, 1) } return rows }, [range.start, range.end])
  const visibleDays = view === 'day' ? [reference] : view === 'week' ? monthDays.slice(0, 7) : monthDays

  return <section className="workspace agenda-workspace">
    <div className="page-heading agenda-heading"><div><span className="eyebrow">Agenda · Operação integrada</span><h1>Agenda e tarefas</h1><p>Compromissos do ERP em uma única linha do tempo. Eventos automáticos acompanham a origem sem duplicar informação.</p></div><div className="heading-actions"><button className="button secondary" type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={14}/> Atualizar</button>{canManage && <button className="button primary" type="button" onClick={() => openNewTask()}><Plus size={14}/> Nova tarefa</button>}</div></div>

    <div className="agenda-metrics"><article className="panel"><span>Hoje</span><strong>{metrics.today}</strong><small>compromisso(s) pendente(s)</small></article><article className="panel"><span>Próximos 7 dias</span><strong>{metrics.next}</strong><small>itens previstos</small></article><article className={`panel ${metrics.overdue ? 'danger' : ''}`}><span>Tarefas atrasadas</span><strong>{metrics.overdue}</strong><small>exigem acompanhamento</small></article><article className="panel"><span>Contratos · 30 dias</span><strong>{metrics.contracts}</strong><small>vencimentos próximos</small></article></div>

    {error && <div className="form-alert danger-alert">{error}</div>}{success && <div className="form-alert success-alert">{success}</div>}

    <div className="panel agenda-toolbar"><div className="agenda-period-nav"><button className="icon-button" type="button" onClick={() => navigatePeriod(-1)} aria-label="Período anterior"><ChevronLeft size={17}/></button><button className="agenda-period-label" type="button" onClick={() => setReference(today)} title="Voltar para hoje">{periodTitle(reference, view)}</button><button className="icon-button" type="button" onClick={() => navigatePeriod(1)} aria-label="Próximo período"><ChevronRight size={17}/></button></div><div className="agenda-view-tabs"><button className={view === 'month' ? 'active' : ''} onClick={() => setView('month')}>Mês</button><button className={view === 'week' ? 'active' : ''} onClick={() => setView('week')}>Semana</button><button className={view === 'day' ? 'active' : ''} onClick={() => setView('day')}>Dia</button></div></div>

    <div className="agenda-filter-row"><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>Todos</button><button className={filter === 'tasks' ? 'active' : ''} onClick={() => setFilter('tasks')}>Tarefas</button><button className={filter === 'inspections' ? 'active' : ''} onClick={() => setFilter('inspections')}>Vistorias</button><button className={filter === 'maintenance' ? 'active' : ''} onClick={() => setFilter('maintenance')}>Manutenções</button><button className={filter === 'contracts' ? 'active' : ''} onClick={() => setFilter('contracts')}>Contratos</button><button className={filter === 'finance' ? 'active' : ''} onClick={() => setFilter('finance')}>Financeiro</button></div>

    {loading ? <article className="panel settings-loading">Montando agenda integrada...</article> : view === 'month' ? <div className="panel agenda-calendar"><div className="agenda-week-head">{weekDays.map(day => <span key={day}>{day}</span>)}</div><div className="agenda-month-grid">{visibleDays.map(day => { const rows = grouped.get(day) || []; const outside = parseDay(day).getMonth() !== parseDay(reference).getMonth(); return <div className={`agenda-day ${outside ? 'outside' : ''} ${day === today ? 'today' : ''}`} key={day}><div className="agenda-day-head"><button type="button" onClick={() => { setReference(day); setView('day') }}>{parseDay(day).getDate()}</button>{canManage && <button className="agenda-day-add" type="button" title="Nova tarefa neste dia" onClick={() => openNewTask(day)}>+</button>}</div><div className="agenda-day-events">{rows.slice(0, 4).map(item => <button type="button" className={`agenda-event-chip ${item.event_type} priority-${item.priority} ${item.status === 'completed' ? 'completed' : ''}`} key={item.id} onClick={() => setSelected(item)}><span>{eventTime(item)}</span><strong>{item.title}</strong></button>)}{rows.length > 4 && <button type="button" className="agenda-more" onClick={() => { setReference(day); setView('day') }}>+ {rows.length - 4} item(ns)</button>}</div></div>})}</div></div> : <div className={`agenda-timeline ${view}`}>{visibleDays.map(day => { const rows = grouped.get(day) || []; return <article className="panel agenda-timeline-day" key={day}><div className="agenda-timeline-date"><span>{dayLabel(day)}</span><strong>{day === today ? 'Hoje' : parseDay(day).getDate()}</strong>{canManage && <button className="icon-button" type="button" onClick={() => openNewTask(day)}><Plus size={14}/></button>}</div><div className="agenda-timeline-events">{rows.map(item => <button type="button" className={`agenda-timeline-event priority-${item.priority} ${item.status === 'completed' ? 'completed' : ''}`} onClick={() => setSelected(item)} key={item.id}><div className="agenda-event-time"><Clock3 size={13}/><span>{eventTime(item)}</span></div><div><strong>{item.title}</strong><span>{item.source_code || eventLabels[item.event_type] || item.event_type}{item.property_code ? ` · Imóvel ${item.property_code}` : ''}</span></div><i>{eventLabels[item.event_type] || 'Evento'}</i></button>)}{rows.length === 0 && <div className="agenda-empty-day"><CalendarCheck2 size={18}/><span>Nenhum compromisso neste dia.</span></div>}</div></article>})}</div>}

    <div className="agenda-lower-grid"><article className="panel agenda-selected"><div className="agenda-section-heading"><div><span className="eyebrow">Detalhes</span><h2>{selected ? 'Compromisso selecionado' : 'Selecione um compromisso'}</h2></div>{selected && <button className="icon-button" onClick={() => setSelected(null)}><X size={15}/></button>}</div>{selected ? <div className="agenda-selected-body"><div className={`agenda-selected-icon ${selected.event_type}`}>{selected.event_type === 'maintenance' ? <Wrench size={20}/> : selected.event_type.startsWith('inspection') ? <CalendarCheck2 size={20}/> : ['billing', 'repasse'].includes(selected.event_type) ? <Landmark size={20}/> : <FileText size={20}/>}</div><div className="agenda-selected-copy"><div><i className={`status-badge ${selected.priority === 'urgent' || selected.priority === 'high' ? 'warning' : 'neutral'}`}>{priorityLabel(selected.priority)}</i><span>{eventLabels[selected.event_type] || selected.event_type}</span></div><h3>{selected.title}</h3><p>{selected.description || 'Sem observações adicionais.'}</p><div className="agenda-selected-meta"><span><CalendarDays size={13}/>{fullDayLabel(eventDay(selected))} · {eventTime(selected)}</span>{selected.responsible_name && <span>Responsável: <strong>{selected.responsible_name}</strong></span>}{selected.source_code && <span>Origem: <strong>{selected.source_code}</strong></span>}{selected.amount != null && <span>Valor: <strong>{money(selected.amount)}</strong></span>}</div><div className="agenda-selected-actions">{selected.automatic && moduleTargets.has(selected.module as ModuleTarget) && <button className="button primary compact" type="button" onClick={() => openOrigin(selected)}>Abrir origem</button>}{!selected.automatic && canManage && <><button className="button secondary compact" type="button" onClick={() => editTask(selected)}>Editar tarefa</button>{selected.status === 'completed' ? <button className="button secondary compact" disabled={saving} onClick={() => void changeTaskStatus(selected, 'pending')}>Reabrir</button> : <button className="button primary compact" disabled={saving} onClick={() => void changeTaskStatus(selected, 'completed')}><CheckCircle2 size={13}/> Concluir</button>}<button className="button ghost-danger compact" disabled={saving} onClick={() => void changeTaskStatus(selected, 'cancelled')}><XCircle size={13}/> Cancelar</button></>}</div></div></div> : <div className="agenda-selected-empty"><CircleAlert size={22}/><span>Clique em qualquer item do calendário para ver origem, responsável e ações disponíveis.</span></div>}</article>
      <article className="panel agenda-upcoming"><div className="agenda-section-heading"><div><span className="eyebrow">Próximos passos</span><h2>O que vem pela frente</h2></div></div><div className="agenda-upcoming-list">{events.filter(item => eventDay(item) >= today && item.status !== 'completed').slice(0, 6).map(item => <button type="button" key={item.id} onClick={() => setSelected(item)}><span>{dayLabel(eventDay(item))}</span><div><strong>{item.title}</strong><small>{eventTime(item)} · {eventLabels[item.event_type] || item.event_type}</small></div></button>)}{events.filter(item => eventDay(item) >= today && item.status !== 'completed').length === 0 && <div className="agenda-selected-empty"><CalendarCheck2 size={20}/><span>Nenhum compromisso futuro neste período.</span></div>}</div></article></div>

    {taskOpen && <div className="portfolio-modal-backdrop" onMouseDown={event => { if (event.currentTarget === event.target && !saving) setTaskOpen(false) }}><form className="panel portfolio-modal agenda-task-modal" onSubmit={saveTask} role="dialog" aria-modal="true"><div className="portfolio-modal-header"><div><span className="eyebrow">Agenda</span><h2>{editingTaskId ? 'Editar tarefa' : 'Nova tarefa'}</h2><p>Compromisso interno com responsável, prioridade e prazo.</p></div><button className="portfolio-modal-close" type="button" disabled={saving} onClick={() => setTaskOpen(false)}><X size={17}/></button></div><div className="agenda-task-body"><label className="field"><span>Título</span><input required maxLength={180} value={taskTitle} onChange={event => setTaskTitle(event.target.value)} placeholder="Ex.: Retornar ao proprietário"/></label><label className="field"><span>Descrição</span><textarea rows={3} maxLength={5000} value={taskDescription} onChange={event => setTaskDescription(event.target.value)} placeholder="Contexto, instruções ou observações..."/></label><div className="agenda-task-options"><label className="agenda-check"><input type="checkbox" checked={taskAllDay} onChange={event => setTaskAllDay(event.target.checked)}/><span>Dia todo</span></label></div><div className="form-grid two-columns"><label className="field"><span>Data</span><input type="date" required value={taskDate} onChange={event => setTaskDate(event.target.value)}/></label>{!taskAllDay && <label className="field"><span>Horário</span><input type="time" required value={taskTime} onChange={event => setTaskTime(event.target.value)}/></label>}<label className="field"><span>Prazo final (opcional)</span><input type="date" min={taskDate} value={taskDueDate} onChange={event => setTaskDueDate(event.target.value)}/></label>{!taskAllDay && taskDueDate && <label className="field"><span>Horário do prazo</span><input type="time" value={taskDueTime} onChange={event => setTaskDueTime(event.target.value)}/></label>}<label className="field"><span>Prioridade</span><select value={taskPriority} onChange={event => setTaskPriority(event.target.value)}><option value="low">Baixa</option><option value="normal">Normal</option><option value="high">Alta</option><option value="urgent">Urgente</option></select></label><label className="field"><span>Responsável</span><select value={taskAssigned} onChange={event => setTaskAssigned(event.target.value)}><option value="">Usuário atual</option>{users.map(user => <option value={user.id} key={user.id}>{user.name}</option>)}</select></label></div></div><div className="canonical-modal-actions"><button className="button secondary" type="button" disabled={saving} onClick={() => setTaskOpen(false)}>Cancelar</button><button className="button primary" disabled={saving}>{saving ? 'Salvando...' : editingTaskId ? 'Salvar alterações' : 'Criar tarefa'}</button></div></form></div>}
  </section>
}
