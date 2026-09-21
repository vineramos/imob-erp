import { AlertTriangle, Bell, CalendarClock, CheckCheck, CircleAlert, FileClock, Landmark, LoaderCircle, RefreshCw, Wrench } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, apiRequest } from '../api/client'
import './notification-center.css'

type NotificationSeverity = 'critical' | 'warning' | 'info'
type NotificationItem = {
  key: string
  severity: NotificationSeverity
  category: string
  title: string
  subtitle: string
  module: string
  route: string
  event_at: string
  action_label: string
  read: boolean
}
type NotificationResponse = {
  items: NotificationItem[]
  unread_count: number
  critical_count: number
  generated_at: string
}
type Filter = 'all' | 'unread' | 'critical'
type Props = { onNavigate: (module: string, route?: string) => void }

const categoryLabel: Record<string, string> = {
  agenda: 'Agenda', contracts: 'Contratos', finance: 'Financeiro', maintenance: 'Manutenções', inspections: 'Vistorias',
}

function ItemIcon({ item }: { item: NotificationItem }) {
  if (item.severity === 'critical') return <AlertTriangle size={17}/>
  if (item.category === 'finance') return <Landmark size={17}/>
  if (item.category === 'maintenance') return <Wrench size={17}/>
  if (item.category === 'contracts') return <FileClock size={17}/>
  if (item.category === 'inspections') return <CalendarClock size={17}/>
  return item.severity === 'warning' ? <CircleAlert size={17}/> : <Bell size={17}/>
}

function eventLabel(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined })
}

function notificationTime(item: NotificationItem) {
  const timestamp = new Date(item.event_at).getTime()
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp
}

export function NotificationCenter({ onNavigate }: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const lastLoadedAt = useRef(0)
  const [data, setData] = useState<NotificationResponse | null>(null)
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    setError('')
    try {
      setData(await apiRequest<NotificationResponse>('/notifications?limit=80'))
      lastLoadedAt.current = Date.now()
    } catch (cause) {
      if (!quiet) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar as notificações.')
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const id = window.setInterval(() => { if (document.visibilityState === 'visible') void load(true) }, 10 * 60_000)
    const refresh = () => { if (document.visibilityState === 'visible' && Date.now() - lastLoadedAt.current >= 5 * 60_000) void load(true) }
    document.addEventListener('visibilitychange', refresh)
    window.addEventListener('focus', refresh)
    return () => {
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', refresh)
      window.removeEventListener('focus', refresh)
    }
  }, [load])

  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) setOpen(false)
    }
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('pointerdown', outside)
    window.addEventListener('keydown', keyboard)
    return () => {
      window.removeEventListener('pointerdown', outside)
      window.removeEventListener('keydown', keyboard)
    }
  }, [])

  const visible = useMemo(() => {
    const items = data?.items ?? []
    const filtered = filter === 'unread'
      ? items.filter(item => !item.read)
      : filter === 'critical'
        ? items.filter(item => item.severity === 'critical')
        : items
    return [...filtered].sort((left, right) => notificationTime(right) - notificationTime(left))
  }, [data, filter])

  function applyRead(keys: Set<string>) {
    setData(current => {
      if (!current) return current
      const changed = current.items.filter(item => keys.has(item.key) && !item.read)
      const criticalChanged = changed.filter(item => item.severity === 'critical').length
      return {
        ...current,
        unread_count: Math.max(0, current.unread_count - changed.length),
        critical_count: Math.max(0, current.critical_count - criticalChanged),
        items: current.items.map(item => keys.has(item.key) ? { ...item, read: true } : item),
      }
    })
  }

  async function openItem(item: NotificationItem) {
    if (!item.read) {
      applyRead(new Set([item.key]))
      try { await apiRequest('/notifications/read', { method: 'POST', body: JSON.stringify({ keys: [item.key] }) }) }
      catch { void load(true) }
    }
    setOpen(false)
    onNavigate(item.module, item.route)
  }

  async function markAllRead() {
    if (!data?.unread_count || saving) return
    setSaving(true); setError('')
    const keys = new Set(data.items.map(item => item.key))
    applyRead(keys)
    try {
      await apiRequest('/notifications/read-all', { method: 'POST' })
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível marcar as notificações como lidas.')
      await load(true)
    } finally { setSaving(false) }
  }

  const unread = data?.unread_count ?? 0
  const critical = data?.critical_count ?? 0

  return <div className="notification-center" ref={wrapperRef}>
    <button
      className={`topbar-icon notification-trigger ${critical ? 'has-critical' : unread ? 'has-unread' : ''}`}
      type="button"
      aria-label={unread ? `Notificações: ${unread} não lida(s)` : 'Notificações'}
      aria-expanded={open}
      onClick={() => { setOpen(value => !value); if (!open) void load(true) }}
    >
      <Bell size={18}/>
      {unread > 0 && <span className="notification-badge">{unread > 99 ? '99+' : unread}</span>}
    </button>

    {open && <section className="notification-popover panel" aria-label="Central de notificações">
      <header className="notification-head">
        <div><span className="eyebrow">Atenção operacional</span><h3>Notificações</h3><small>{unread ? `${unread} não lida(s)` : 'Tudo conferido por aqui'}</small></div>
        <div className="notification-head-actions">
          <button type="button" className="icon-button" onClick={() => void load()} disabled={loading} aria-label="Atualizar notificações"><RefreshCw size={14}/></button>
          <button type="button" className="notification-read-all" onClick={() => void markAllRead()} disabled={!unread || saving}><CheckCheck size={14}/> Marcar lidas</button>
        </div>
      </header>

      <div className="notification-filters" role="tablist" aria-label="Filtros de notificações">
        <button type="button" className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>Todas <span>{data?.items.length ?? 0}</span></button>
        <button type="button" className={filter === 'unread' ? 'active' : ''} onClick={() => setFilter('unread')}>Não lidas <span>{unread}</span></button>
        <button type="button" className={filter === 'critical' ? 'active' : ''} onClick={() => setFilter('critical')}>Críticas <span>{critical}</span></button>
      </div>

      {error && <div className="notification-state error">{error}</div>}
      {loading && !data && <div className="notification-state"><LoaderCircle className="notification-spinner" size={20}/><span>Carregando alertas...</span></div>}
      {!loading && !error && visible.length === 0 && <div className="notification-state"><CheckCheck size={22}/><strong>Nenhum alerta neste filtro.</strong><span>Novas pendências aparecerão aqui automaticamente.</span></div>}

      {visible.length > 0 && <div className="notification-list">{visible.map(item => <button
        type="button"
        className={`notification-item severity-${item.severity} ${item.read ? 'is-read' : 'is-unread'}`}
        key={item.key}
        onClick={() => void openItem(item)}
      >
        <span className="notification-item-icon"><ItemIcon item={item}/></span>
        <span className="notification-item-copy">
          <span className="notification-item-meta"><i>{categoryLabel[item.category] || item.category}</i><small>{eventLabel(item.event_at)}</small></span>
          <strong>{item.title}</strong>
          <small>{item.subtitle}</small>
          <em>{item.action_label}</em>
        </span>
        {!item.read && <span className="notification-unread-dot" aria-label="Não lida"/>}
      </button>)}</div>}

      <footer className="notification-footer"><span>Atualização automática a cada minuto</span><small>{data?.generated_at ? `Última: ${new Date(data.generated_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}` : ''}</small></footer>
    </section>}
  </div>
}
