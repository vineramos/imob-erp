import {
  CalendarCheck2,
  CalendarDays,
  CalendarSearch,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileText,
  Landmark,
  Lock,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Users,
  Wrench,
  X,
  XCircle,
} from 'lucide-react'
import { FormEvent, MouseEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import { AgendaAccessCenter } from './AgendaAccessCenter'
import { AgendaAutomaticHistory } from './AgendaAutomaticHistory'
import { AgendaMeetingCenter } from './AgendaMeetingCenter'
import type { AgendaContext, AgendaEvent, AgendaResponse, AgendaView, ConflictPayload } from './agendaTypes'
import { addDays, dayLabel, eventDay, eventTime, fullDayLabel, localDateValue, money, parseDay, periodRange, periodTitle, priorityLabel, shiftMonth, todayValue, weekDays } from './agendaTypes'
import './agenda.css'

type ModuleTarget = 'contracts' | 'inspections' | 'maintenance' | 'finance' | 'properties' | 'captures'
type Props = { permissions: string[]; onNavigate: (module: ModuleTarget) => void }

type PendingSave = { body: Record<string, unknown>; taskId: string | null }
type ConflictState = { data: ConflictPayload; pending: PendingSave }

const eventLabels: Record<string, string> = {
  task: 'Tarefa', appointment: 'Compromisso', visit: 'Visita', meeting: 'Reunião', inspection: 'Vistoria',
  maintenance: 'Manutenção', contract_expiry: 'Contrato', adjustment: 'Reajuste', billing: 'Cobrança', repasse: 'Repasse',
}
const moduleTargets = new Set<ModuleTarget>(['contracts', 'inspections', 'maintenance', 'finance', 'properties', 'captures'])

function isoFor(date: string, time: string) { return new Date(`${date}T${time}:00`).toISOString() }
function localTime(iso: string) { return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) }
function durationFor(kind: string) { return kind === 'visit' ? 45 : kind === 'task' ? 30 : 60 }

export function AgendaPage({ permissions, onNavigate }: Props) {
  const canManage = permissions.includes('agenda.manage')
  const [context, setContext] = useState<AgendaContext | null>(null)
  const [view, setView] = useState<AgendaView>('month')
  const [reference, setReference] = useState(todayValue())
  const [events, setEvents] = useState<AgendaEvent[]>([])
  const [filter, setFilter] = useState('all')
  const [mineOnly, setMineOnly] = useState(true)
  const [selectedPerson, setSelectedPerson] = useState('')
  const [selectedDepartment, setSelectedDepartment] = useState('')
  const [selected, setSelected] = useState<AgendaEvent | null>(null)
  const [selectedDay, setSelectedDay] = useState<string | null>(todayValue())
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const [taskOpen, setTaskOpen] = useState(false)
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null)
  const [taskKind, setTaskKind] = useState('task')
  const [taskTitle, setTaskTitle] = useState('')
  const [taskDescription, setTaskDescription] = useState('')
  const [taskDate, setTaskDate] = useState(todayValue())
  const [taskTime, setTaskTime] = useState('09:00')
  const [taskEndTime, setTaskEndTime] = useState('09:30')
  const [taskDueDate, setTaskDueDate] = useState('')
  const [taskDueTime, setTaskDueTime] = useState('18:00')
  const [taskAllDay, setTaskAllDay] = useState(false)
  const [taskPriority, setTaskPriority] = useState('normal')
  const [taskPrivacy, setTaskPrivacy] = useState('normal')
  const [taskLocation, setTaskLocation] = useState('')
  const [taskAssigned, setTaskAssigned] = useState('')
  const [taskRecurrence, setTaskRecurrence] = useState('none')
  const [taskRecurrenceUntil, setTaskRecurrenceUntil] = useState('')
  const [conflict, setConflict] = useState<ConflictState | null>(null)

  const [meetingOpen, setMeetingOpen] = useState(false)
  const [meetingMode, setMeetingMode] = useState<'inbox' | 'request' | 'find'>('inbox')
  const [accessOpen, setAccessOpen] = useState(false)
  const [accessTab, setAccessTab] = useState<'availability' | 'delegations' | 'team'>('availability')

  const range = useMemo(() => periodRange(reference, view), [reference, view])

  const loadContext = useCallback(async () => {
    const next = await apiRequest<AgendaContext>('/agenda/context')
    setContext(next)
    setTaskAssigned(current => current || next.current_user_id)
  }, [])

  const queryScope = useMemo(() => {
    if (mineOnly) return 'mine=true'
    if (selectedPerson) return `mine=false&user_id=${encodeURIComponent(selectedPerson)}`
    if (selectedDepartment) return `mine=false&department_id=${encodeURIComponent(selectedDepartment)}`
    return 'mine=false'
  }, [mineOnly, selectedPerson, selectedDepartment])

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const result = await apiRequest<AgendaResponse>(`/agenda/events?start=${range.start}&end=${range.end}&${queryScope}`)
      setEvents(result.events)
      setSelected(current => current ? result.events.find(item => item.id === current.id) || current : null)
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar a agenda.') }
    finally { setLoading(false) }
  }, [range.start, range.end, queryScope])

  useEffect(() => { void loadContext().catch(() => setError('Não foi possível carregar o contexto da agenda.')) }, [loadContext])
  useEffect(() => { void load() }, [load])
  useEffect(() => { if (!taskOpen) return; const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && !saving && !conflict) setTaskOpen(false) }; window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close) }, [taskOpen, saving, conflict])

  const filtered = useMemo(() => events.filter(item => {
    if (filter === 'all') return true
    if (filter === 'tasks') return ['task', 'appointment', 'visit', 'meeting'].includes(item.event_type)
    if (filter === 'inspections') return item.event_type === 'inspection'
    if (filter === 'maintenance') return item.event_type === 'maintenance'
    if (filter === 'contracts') return ['contract_expiry', 'adjustment'].includes(item.event_type)
    return ['billing', 'repasse'].includes(item.event_type)
  }), [events, filter])

  const grouped = useMemo(() => {
    const map = new Map<string, AgendaEvent[]>()
    filtered.forEach(item => { const key = eventDay(item); const rows = map.get(key) || []; rows.push(item); map.set(key, rows) })
    return map
  }, [filtered])

  const today = todayValue(); const nextSeven = addDays(today, 7)
  const metrics = useMemo(() => {
    const todayCount = filtered.filter(item => eventDay(item) === today && !['completed', 'cancelled', 'missed'].includes(item.status)).length
    const next = filtered.filter(item => eventDay(item) >= today && eventDay(item) <= nextSeven && !['completed', 'cancelled', 'missed'].includes(item.status)).length
    const overdue = filtered.filter(item => item.needs_justification).length
    const rescheduled = filtered.filter(item => item.reschedule_sequence > 0).length
    return { today: todayCount, next, overdue, rescheduled }
  }, [filtered, today, nextSeven])

  const accessiblePeople = useMemo(() => context?.directory.filter(user => user.can_view_calendar) ?? [], [context])
  const schedulablePeople = useMemo(() => context?.directory.filter(user => user.can_create) ?? [], [context])
  const departmentPeople = useMemo(() => {
    if (!context) return []
    const department = selectedDepartment || context.department_id
    return accessiblePeople.filter(user => !department || user.department_id === department)
  }, [context, accessiblePeople, selectedDepartment])

  function navigatePeriod(direction: number) {
    if (view === 'month') setReference(current => shiftMonth(current, direction))
    else if (view === 'week') setReference(current => addDays(current, direction * 7))
    else setReference(current => addDays(current, direction))
  }

  function resetTaskTimes(kind: string, date = taskDate, start = '09:00') {
    const base = new Date(`${date}T${start}:00`); base.setMinutes(base.getMinutes() + durationFor(kind))
    setTaskEndTime(base.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }))
  }

  function openNewTask(day = reference) {
    if (!context) return
    setEditingTaskId(null); setTaskKind('task'); setTaskTitle(''); setTaskDescription(''); setTaskDate(day); setTaskTime('09:00'); setTaskEndTime('09:30'); setTaskDueDate(''); setTaskDueTime('18:00'); setTaskAllDay(false); setTaskPriority('normal'); setTaskPrivacy('normal'); setTaskLocation(''); setTaskAssigned(context.current_user_id); setTaskRecurrence('none'); setTaskRecurrenceUntil(''); setTaskOpen(true); setError('')
  }

  function editTask(item: AgendaEvent) {
    if (!item.task_id || item.automatic || item.masked) return
    const start = new Date(item.start_at); const end = item.end_at ? new Date(item.end_at) : null
    setEditingTaskId(item.task_id); setTaskKind(['appointment', 'visit', 'meeting'].includes(item.event_type) ? item.event_type : 'task'); setTaskTitle(item.title); setTaskDescription(item.description || ''); setTaskDate(item.all_day ? item.start_at.slice(0, 10) : localDateValue(start)); setTaskTime(item.all_day ? '09:00' : localTime(item.start_at)); setTaskEndTime(end ? localTime(item.end_at!) : '09:30'); setTaskDueDate(''); setTaskDueTime('18:00'); setTaskAllDay(item.all_day); setTaskPriority(item.priority); setTaskPrivacy(item.privacy); setTaskLocation(item.location || ''); setTaskAssigned(item.owner_user_id || context?.current_user_id || ''); setTaskRecurrence('none'); setTaskRecurrenceUntil(''); setTaskOpen(true)
  }

  function buildTaskBody(allowConflict = false): Record<string, unknown> {
    const startsAt = taskAllDay ? new Date(`${taskDate}T12:00:00`).toISOString() : isoFor(taskDate, taskTime)
    let endsAt: string | null = null
    if (!taskAllDay) {
      let end = new Date(`${taskDate}T${taskEndTime}:00`)
      const start = new Date(`${taskDate}T${taskTime}:00`)
      if (end <= start) end = new Date(start.getTime() + durationFor(taskKind) * 60000)
      endsAt = end.toISOString()
    }
    const dueAt = taskDueDate ? (taskAllDay ? new Date(`${taskDueDate}T12:00:00`).toISOString() : isoFor(taskDueDate, taskDueTime)) : null
    return { title: taskTitle, description: taskDescription || null, kind: taskKind, starts_at: startsAt, ends_at: endsAt, due_at: dueAt, all_day: taskAllDay, priority: taskPriority, privacy: taskPrivacy, location: taskLocation || null, assigned_user_id: taskAssigned || null, recurrence: editingTaskId ? 'none' : taskRecurrence, recurrence_until: editingTaskId || taskRecurrence === 'none' ? null : taskRecurrenceUntil || null, allow_conflict: allowConflict }
  }

  async function persistTask(pending: PendingSave, allowConflict = false) {
    const body = { ...pending.body, allow_conflict: allowConflict }
    try {
      if (pending.taskId) await apiRequest(`/agenda/tasks/${pending.taskId}`, { method: 'PUT', body: JSON.stringify(body) })
      else await apiRequest('/agenda/tasks', { method: 'POST', body: JSON.stringify(body) })
      setConflict(null); setTaskOpen(false); setSuccess(pending.taskId ? 'Agendamento atualizado.' : taskRecurrence !== 'none' ? 'Série de agendamentos criada.' : 'Agendamento incluído.'); await load()
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409 && cause.payload && typeof cause.payload === 'object' && (cause.payload as ConflictPayload).code === 'agenda_conflict') {
        setConflict({ data: cause.payload as ConflictPayload, pending }); return
      }
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar o agendamento.')
    }
  }

  async function saveTask(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(''); setSuccess('')
    try { await persistTask({ body: buildTaskBody(false), taskId: editingTaskId }) } finally { setSaving(false) }
  }

  function useNextConflictTime() {
    const next = conflict?.data.next_available_at
    if (!next) return
    const date = new Date(next); const localDate = localDateValue(date); const start = localTime(next)
    setTaskDate(localDate); setTaskTime(start); resetTaskTimes(taskKind, localDate, start); setConflict(null)
  }

  async function changeTaskStatus(item: AgendaEvent, status: 'pending' | 'completed' | 'cancelled') {
    if (!item.task_id || item.automatic) return
    setSaving(true); setError('')
    try { await apiRequest(`/agenda/tasks/${item.task_id}/status`, { method: 'POST', body: JSON.stringify({ status }) }); setSelected(null); setSuccess(status === 'completed' ? 'Tarefa concluída.' : status === 'cancelled' ? 'Agendamento cancelado.' : 'Tarefa reaberta.'); await load() }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível atualizar o agendamento.') }
    finally { setSaving(false) }
  }

  function openOrigin(item: AgendaEvent) { if (moduleTargets.has(item.module as ModuleTarget)) onNavigate(item.module as ModuleTarget) }
  function dayClick(day: string) { setSelectedDay(day) }
  function stop(event: MouseEvent) { event.stopPropagation() }

  const monthDays = useMemo(() => { const rows: string[] = []; let cursor = range.start; while (cursor <= range.end) { rows.push(cursor); cursor = addDays(cursor, 1) } return rows }, [range.start, range.end])
  const visibleDays = view === 'day' ? [reference] : view === 'week' ? monthDays.slice(0, 7) : monthDays
  const dayRows = selectedDay ? grouped.get(selectedDay) || [] : []

  return <section className="workspace agenda-workspace agenda-v2">
    <div className="page-heading agenda-heading"><div><span className="eyebrow">Agenda · Operação integrada</span><h1>Agenda inteligente</h1><p>Disponibilidade, tarefas, reuniões, alertas do sistema e histórico operacional sem invadir a agenda de outras pessoas.</p></div><div className="heading-actions"><button className="button secondary" onClick={() => { setAccessTab('availability'); setAccessOpen(true) }}><Settings2 size={14}/> Disponibilidade</button><button className="button secondary" onClick={() => { setMeetingMode('find'); setMeetingOpen(true) }}><CalendarSearch size={14}/> Encontrar horário</button><button className="button secondary" onClick={() => { setMeetingMode('inbox'); setMeetingOpen(true) }}><Users size={14}/> Reuniões</button>{canManage && <button className="button primary" onClick={() => openNewTask()}><Plus size={14}/> Novo agendamento</button>}</div></div>

    <div className="agenda-metrics"><article className="panel"><span>Hoje</span><strong>{metrics.today}</strong><small>itens pendentes</small></article><article className="panel"><span>Próximos 7 dias</span><strong>{metrics.next}</strong><small>compromissos previstos</small></article><article className={`panel ${metrics.overdue ? 'danger' : ''}`}><span>Justificativas pendentes</span><strong>{metrics.overdue}</strong><small>histórico não cumprido</small></article><article className="panel"><span>Reagendamentos</span><strong>{metrics.rescheduled}</strong><small>neste período</small></article></div>

    {error && <div className="form-alert danger-alert">{error}</div>}{success && <div className="form-alert success-alert">{success}</div>}

    <div className="panel agenda-scope-bar"><label className="agenda-my-toggle"><input type="checkbox" checked={mineOnly} onChange={event => { setMineOnly(event.target.checked); if (event.target.checked) { setSelectedPerson(''); setSelectedDepartment('') } }}/><span>Minhas Tarefas</span><small>ativado por padrão</small></label>{!mineOnly && context && <div className="agenda-scope-filters">{context.access_level === 'manager' ? <div className="agenda-manager-people"><span>Equipe:</span>{accessiblePeople.filter(user => user.department_id === context.department_id).map(user => <button className={selectedPerson === user.id ? 'active' : ''} key={user.id} onClick={() => { setSelectedPerson(user.id); setSelectedDepartment('') }}>{user.name}</button>)}</div> : context.access_level === 'director' || context.access_level === 'admin' ? <><label><span>Setor</span><select value={selectedDepartment} onChange={event => { setSelectedDepartment(event.target.value); setSelectedPerson('') }}><option value="">Todos os setores</option>{context.departments.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label><span>Pessoa</span><select value={selectedPerson} onChange={event => setSelectedPerson(event.target.value)}><option value="">Todas as pessoas do filtro</option>{departmentPeople.map(user => <option value={user.id} key={user.id}>{user.name}</option>)}</select></label></> : <label><span>Agenda autorizada</span><select value={selectedPerson} onChange={event => setSelectedPerson(event.target.value)}><option value="">Selecione...</option>{accessiblePeople.filter(user => user.id !== context.current_user_id).map(user => <option value={user.id} key={user.id}>{user.name}</option>)}</select></label>}</div>}<div className="agenda-scope-actions"><button className="button ghost compact" onClick={() => { setAccessTab('delegations'); setAccessOpen(true) }}><ShieldCheck size={13}/> Delegações</button>{context?.access_level === 'admin' && <button className="button ghost compact" onClick={() => { setAccessTab('team'); setAccessOpen(true) }}><Users size={13}/> Equipe / Setores</button>}</div></div>

    <div className="panel agenda-toolbar"><div className="agenda-period-nav"><button className="icon-button" onClick={() => navigatePeriod(-1)} aria-label="Período anterior"><ChevronLeft size={17}/></button><button className="agenda-period-label" onClick={() => setReference(today)} title="Voltar para hoje">{periodTitle(reference, view)}</button><button className="icon-button" onClick={() => navigatePeriod(1)} aria-label="Próximo período"><ChevronRight size={17}/></button></div><div className="agenda-view-tabs"><button className={view === 'month' ? 'active' : ''} onClick={() => setView('month')}>Mês</button><button className={view === 'week' ? 'active' : ''} onClick={() => setView('week')}>Semana</button><button className={view === 'day' ? 'active' : ''} onClick={() => setView('day')}>Dia</button></div></div>

    <div className="agenda-filter-row"><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>Todos</button><button className={filter === 'tasks' ? 'active' : ''} onClick={() => setFilter('tasks')}>Tarefas / Reuniões</button><button className={filter === 'inspections' ? 'active' : ''} onClick={() => setFilter('inspections')}>Vistorias</button><button className={filter === 'maintenance' ? 'active' : ''} onClick={() => setFilter('maintenance')}>Manutenções</button><button className={filter === 'contracts' ? 'active' : ''} onClick={() => setFilter('contracts')}>Contratos</button><button className={filter === 'finance' ? 'active' : ''} onClick={() => setFilter('finance')}>Financeiro</button></div>

    {loading ? <article className="panel settings-loading">Montando agenda integrada...</article> : view === 'month' ? <div className="panel agenda-calendar"><div className="agenda-week-head">{weekDays.map(day => <span key={day}>{day}</span>)}</div><div className="agenda-month-grid">{visibleDays.map(day => { const rows = grouped.get(day) || []; const outside = parseDay(day).getMonth() !== parseDay(reference).getMonth(); return <div className={`agenda-day ${outside ? 'outside' : ''} ${day === today ? 'today' : ''} ${selectedDay === day ? 'selected-day' : ''}`} key={day} onClick={() => dayClick(day)} onDoubleClick={() => { setReference(day); setView('day') }}><div className="agenda-day-head"><button type="button" onClick={event => { stop(event); dayClick(day) }}>{parseDay(day).getDate()}</button>{canManage && <button className="agenda-day-add" type="button" title="Novo agendamento neste dia" onClick={event => { stop(event); openNewTask(day) }}>+</button>}</div><div className="agenda-day-events">{rows.slice(0, 4).map(item => <button type="button" className={`agenda-event-chip ${item.event_type} priority-${item.priority} ${['completed','missed'].includes(item.status) ? 'completed' : ''}`} key={item.id} onClick={event => { stop(event); setSelected(item); setSelectedDay(day) }}><span>{eventTime(item)}</span><strong>{item.masked && <Lock size={8}/>} {item.title}</strong>{item.reschedule_sequence > 0 && <i>R{item.reschedule_sequence}</i>}</button>)}{rows.length > 4 && <button type="button" className="agenda-more" onClick={event => { stop(event); setSelectedDay(day) }}>+ {rows.length - 4} item(ns)</button>}</div></div>})}</div></div> : <div className={`agenda-timeline ${view}`}>{visibleDays.map(day => { const rows = grouped.get(day) || []; return <article className="panel agenda-timeline-day" key={day}><div className="agenda-timeline-date"><span>{dayLabel(day)}</span><strong>{day === today ? 'Hoje' : parseDay(day).getDate()}</strong>{canManage && <button className="icon-button" onClick={() => openNewTask(day)}><Plus size={14}/></button>}</div><div className="agenda-timeline-events">{rows.map(item => <button className={`agenda-timeline-event priority-${item.priority} ${['completed','missed'].includes(item.status) ? 'completed' : ''}`} onClick={() => setSelected(item)} key={item.id}><div className="agenda-event-time"><Clock3 size={13}/><span>{eventTime(item)}</span></div><div><strong>{item.masked && <Lock size={10}/>} {item.title}</strong><span>{item.source_code || eventLabels[item.event_type] || item.event_type}{item.reschedule_sequence ? ` · ${item.reschedule_sequence}º reagendamento` : ''}</span></div><i>{eventLabels[item.event_type] || 'Evento'}</i></button>)}{rows.length === 0 && <div className="agenda-empty-day"><CalendarCheck2 size={18}/><span>Nenhum compromisso neste dia.</span></div>}</div></article>})}</div>}

    {view === 'month' && selectedDay && <article className="panel agenda-day-drilldown"><div className="agenda-section-heading"><div><span className="eyebrow">Dia selecionado</span><h2>{fullDayLabel(selectedDay)}</h2><p>{dayRows.length} item(ns) neste dia.</p></div><div className="heading-actions"><button className="button secondary compact" onClick={() => { setReference(selectedDay); setView('day') }}>Abrir visão diária</button>{canManage && <button className="button primary compact" onClick={() => openNewTask(selectedDay)}><Plus size={13}/> Novo</button>}</div></div><div className="agenda-day-list">{dayRows.map(item => <button key={item.id} onClick={() => setSelected(item)}><span>{eventTime(item)}</span><div><strong>{item.title}</strong><small>{eventLabels[item.event_type] || item.event_type}{item.responsible_name ? ` · ${item.responsible_name}` : ''}{item.department_name ? ` · ${item.department_name}` : ''}</small></div><i className={`status-badge ${item.priority === 'urgent' || item.priority === 'high' ? 'warning' : 'neutral'}`}>{item.status === 'missed' ? 'Não cumprido' : item.status === 'completed' ? 'Concluído' : priorityLabel(item.priority)}</i></button>)}{dayRows.length === 0 && <div className="agenda-empty-day"><CalendarCheck2 size={19}/><span>Dia livre. Clique em “Novo” para agendar.</span></div>}</div></article>}

    <div className="agenda-lower-grid"><article className="panel agenda-selected"><div className="agenda-section-heading"><div><span className="eyebrow">Detalhes</span><h2>{selected ? 'Compromisso selecionado' : 'Selecione um compromisso'}</h2></div>{selected && <button className="icon-button" onClick={() => setSelected(null)}><X size={15}/></button>}</div>{selected ? <div className="agenda-selected-body"><div className={`agenda-selected-icon ${selected.event_type}`}>{selected.event_type === 'maintenance' ? <Wrench size={20}/> : selected.event_type === 'inspection' ? <CalendarCheck2 size={20}/> : ['billing','repasse'].includes(selected.event_type) ? <Landmark size={20}/> : <FileText size={20}/>}</div><div className="agenda-selected-copy"><div><i className={`status-badge ${selected.priority === 'urgent' || selected.priority === 'high' ? 'warning' : 'neutral'}`}>{selected.status === 'missed' ? 'Não cumprido' : priorityLabel(selected.priority)}</i><span>{eventLabels[selected.event_type] || selected.event_type}{selected.automatic ? ' · automático' : ''}{selected.privacy === 'private' ? ' · privado' : ''}</span></div><h3>{selected.title}</h3><p>{selected.description || (selected.masked ? 'Os detalhes deste compromisso são privados. Apenas a disponibilidade foi compartilhada.' : 'Sem observações adicionais.')}</p><div className="agenda-selected-meta"><span><CalendarDays size={13}/>{fullDayLabel(eventDay(selected))} · {eventTime(selected)}</span>{selected.responsible_name && <span>Responsável: <strong>{selected.responsible_name}</strong></span>}{selected.department_name && <span>Setor: <strong>{selected.department_name}</strong></span>}{selected.source_code && <span>Origem: <strong>{selected.source_code}</strong></span>}{selected.amount != null && <span>Valor: <strong>{money(selected.amount)}</strong></span>}{selected.location && <span>Local: <strong>{selected.location}</strong></span>}</div>{selected.automatic && selected.task_id && selected.original_scheduled_at && <AgendaAutomaticHistory taskId={selected.task_id} originalScheduledAt={selected.original_scheduled_at} currentSequence={selected.reschedule_sequence} currentJustification={selected.missed_justification}/>}<div className="agenda-selected-actions">{selected.automatic && moduleTargets.has(selected.module as ModuleTarget) && <button className="button primary compact" onClick={() => openOrigin(selected)}>Abrir origem</button>}{!selected.automatic && !selected.masked && canManage && selected.task_id && <><button className="button secondary compact" onClick={() => editTask(selected)}>Editar</button>{selected.status === 'completed' ? <button className="button secondary compact" disabled={saving} onClick={() => void changeTaskStatus(selected, 'pending')}>Reabrir</button> : <button className="button primary compact" disabled={saving} onClick={() => void changeTaskStatus(selected, 'completed')}><CheckCircle2 size={13}/> Concluir</button>}<button className="button ghost-danger compact" disabled={saving} onClick={() => void changeTaskStatus(selected, 'cancelled')}><XCircle size={13}/> Cancelar</button></>}</div></div></div> : <div className="agenda-selected-empty"><CircleAlert size={22}/><span>Clique em um dia para abrir a lista completa ou em um item para ver detalhes.</span></div>}</article><article className="panel agenda-upcoming"><div className="agenda-section-heading"><div><span className="eyebrow">Próximos passos</span><h2>O que vem pela frente</h2></div></div><div className="agenda-upcoming-list">{filtered.filter(item => eventDay(item) >= today && !['completed','missed'].includes(item.status)).slice(0, 6).map(item => <button key={item.id} onClick={() => setSelected(item)}><span>{dayLabel(eventDay(item))}</span><div><strong>{item.title}</strong><small>{eventTime(item)} · {eventLabels[item.event_type] || item.event_type}</small></div></button>)}</div></article></div>

    {taskOpen && context && <div className="portfolio-modal-backdrop" onMouseDown={event => { if (event.currentTarget === event.target && !saving && !conflict) setTaskOpen(false) }}><form className="panel portfolio-modal agenda-task-modal" onSubmit={saveTask} role="dialog" aria-modal="true"><div className="portfolio-modal-header"><div><span className="eyebrow">Agenda</span><h2>{editingTaskId ? 'Editar agendamento' : 'Novo agendamento'}</h2><p>O sistema verifica conflitos e sugere automaticamente o próximo horário livre.</p></div><button className="portfolio-modal-close" type="button" disabled={saving} onClick={() => setTaskOpen(false)}><X size={17}/></button></div><div className="agenda-task-body"><div className="form-grid two-columns"><label className="field"><span>Tipo</span><select value={taskKind} onChange={event => { setTaskKind(event.target.value); resetTaskTimes(event.target.value) }}><option value="task">Tarefa</option><option value="appointment">Compromisso</option><option value="meeting">Reunião</option><option value="visit">Visita</option></select></label><label className="field"><span>Responsável</span><select value={taskAssigned} onChange={event => setTaskAssigned(event.target.value)}>{schedulablePeople.map(user => <option value={user.id} key={user.id}>{user.name}{user.id === context.current_user_id ? ' (eu)' : ''}</option>)}</select></label></div><label className="field"><span>Título</span><input required maxLength={180} value={taskTitle} onChange={event => setTaskTitle(event.target.value)} placeholder="Ex.: Retornar ao proprietário"/></label><label className="field"><span>Descrição</span><textarea rows={3} maxLength={5000} value={taskDescription} onChange={event => setTaskDescription(event.target.value)} placeholder="Contexto, instruções ou observações..."/></label><div className="agenda-task-options"><label className="agenda-check"><input type="checkbox" checked={taskAllDay} onChange={event => setTaskAllDay(event.target.checked)}/><span>Dia todo</span></label><label className="agenda-check"><input type="checkbox" checked={taskPrivacy === 'private'} onChange={event => setTaskPrivacy(event.target.checked ? 'private' : 'normal')}/><span>Privado · terceiros veem apenas “Ocupado”</span></label></div><div className="form-grid two-columns"><label className="field"><span>Data</span><input type="date" required value={taskDate} onChange={event => setTaskDate(event.target.value)}/></label>{!taskAllDay && <label className="field"><span>Início</span><input type="time" required value={taskTime} onChange={event => { setTaskTime(event.target.value); resetTaskTimes(taskKind, taskDate, event.target.value) }}/></label>}{!taskAllDay && <label className="field"><span>Término</span><input type="time" required value={taskEndTime} onChange={event => setTaskEndTime(event.target.value)}/></label>}<label className="field"><span>Prioridade</span><select value={taskPriority} onChange={event => setTaskPriority(event.target.value)}><option value="low">Baixa</option><option value="normal">Normal</option><option value="high">Alta</option><option value="urgent">Urgente</option></select></label><label className="field"><span>Local (opcional)</span><input value={taskLocation} onChange={event => setTaskLocation(event.target.value)} placeholder="Sala, imóvel, endereço..."/></label>{taskKind === 'task' && <label className="field"><span>Prazo final (opcional)</span><input type="date" min={taskDate} value={taskDueDate} onChange={event => setTaskDueDate(event.target.value)}/></label>}{taskKind === 'task' && !taskAllDay && taskDueDate && <label className="field"><span>Horário do prazo</span><input type="time" value={taskDueTime} onChange={event => setTaskDueTime(event.target.value)}/></label>}{!editingTaskId && <label className="field"><span>Recorrência</span><select value={taskRecurrence} onChange={event => setTaskRecurrence(event.target.value)}><option value="none">Não repetir</option><option value="daily">Diariamente</option><option value="weekly">Semanalmente</option><option value="monthly">Mensalmente</option></select></label>}{!editingTaskId && taskRecurrence !== 'none' && <label className="field"><span>Repetir até</span><input type="date" min={taskDate} required value={taskRecurrenceUntil} onChange={event => setTaskRecurrenceUntil(event.target.value)}/></label>}</div></div><div className="canonical-modal-actions"><button className="button secondary" type="button" disabled={saving} onClick={() => setTaskOpen(false)}>Cancelar</button><button className="button primary" disabled={saving}>{saving ? 'Salvando...' : editingTaskId ? 'Salvar alterações' : 'Criar agendamento'}</button></div></form></div>}

    {conflict && <div className="agenda-conflict-backdrop"><section className="panel agenda-conflict-modal" role="alertdialog"><div className="agenda-conflict-icon"><CircleAlert size={22}/></div><div><span className="eyebrow">Conflito de horário</span><h3>{conflict.data.self_conflict ? 'Você já possui algo neste horário.' : `${conflict.data.user_name || 'Esta pessoa'} já possui algo neste horário.`}</h3><p>{conflict.data.reason || 'Horário indisponível.'}</p>{conflict.data.next_available_at && <div className="agenda-next-slot"><Clock3 size={14}/><span>Próximo horário livre: <strong>{new Date(conflict.data.next_available_at).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })}</strong></span></div>}<div className="agenda-conflict-actions">{conflict.data.self_conflict && <button className="button secondary" onClick={() => { setSaving(true); void persistTask(conflict.pending, true).finally(() => setSaving(false)) }}>Agendar mesmo assim</button>}{conflict.data.next_available_at && <button className="button primary" onClick={useNextConflictTime}>Usar próximo horário</button>}<button className="button secondary" onClick={() => setConflict(null)}>Escolher outro horário</button><button className="button ghost-danger" onClick={() => { setConflict(null); setTaskOpen(false) }}>Cancelar agendamento</button></div></div></section></div>}

    {context && <AgendaMeetingCenter open={meetingOpen} onClose={() => setMeetingOpen(false)} context={context} startMode={meetingMode} onChanged={() => void load()}/>} 
    {context && <AgendaAccessCenter open={accessOpen} onClose={() => setAccessOpen(false)} context={context} startTab={accessTab} onContextChanged={async () => { await loadContext(); await load() }}/>} 
  </section>
}
