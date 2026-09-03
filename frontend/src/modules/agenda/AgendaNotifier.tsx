import { BellRing, CalendarDays, CheckCircle2, Clock3, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { AgendaEvent, SystemPendingTask, TodaySummary } from './agendaTypes'
import { eventTime, fullDayLabel, todayValue } from './agendaTypes'


type ReminderRow = { event: AgendaEvent; minutes_until: number }
type Props = { onOpenAgenda: () => void }

export function AgendaNotifier({ onOpenAgenda }: Props) {
  const [summary, setSummary] = useState<TodaySummary | null>(null)
  const [briefOpen, setBriefOpen] = useState(false)
  const [reminder, setReminder] = useState<{ row: ReminderRow; threshold: number } | null>(null)
  const [justifications, setJustifications] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [snoozeUntil, setSnoozeUntil] = useState(0)

  const loadSummary = useCallback(async () => {
    try {
      const next = await apiRequest<TodaySummary>('/agenda/today-summary')
      setSummary(next)
      if (next.show_popup) setBriefOpen(true)
    } catch { /* agenda pode não estar liberada para o perfil */ }
  }, [])

  useEffect(() => { void loadSummary() }, [loadSummary])

  useEffect(() => {
    let cancelled = false
    async function poll() {
      if (Date.now() < snoozeUntil) return
      try {
        const rows = await apiRequest<ReminderRow[]>('/agenda/reminders')
        if (cancelled || reminder) return
        for (const row of rows) {
          const threshold = row.minutes_until <= 5 ? 5 : row.minutes_until <= 10 ? 10 : 15
          const key = `imob-agenda-reminder:${todayValue()}:${row.event.id}:${threshold}`
          if (localStorage.getItem(key)) continue
          localStorage.setItem(key, '1')
          setReminder({ row, threshold })
          break
        }
      } catch { /* silencioso fora de sessão */ }
    }
    void poll()
    const id = window.setInterval(() => void poll(), 30_000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [reminder, snoozeUntil])

  const pending = summary?.pending_justifications ?? []
  const forced = pending.length > 0
  const todayEvents = useMemo(() => (summary?.events ?? []).filter(item => item.status !== 'cancelled'), [summary])

  async function justify(item: SystemPendingTask) {
    const text = (justifications[item.id] || '').trim()
    if (text.length < 3) { setError('Informe uma justificativa para o não cumprimento.'); return }
    setSaving(true); setError('')
    try {
      await apiRequest(`/agenda/tasks/${item.id}/justify-missed`, { method: 'POST', body: JSON.stringify({ justification: text }) })
      await loadSummary()
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível registrar a justificativa.') }
    finally { setSaving(false) }
  }

  async function closeBriefing() {
    if (forced) { setError('Existem ocorrências não cumpridas que exigem justificativa antes de fechar.'); return }
    try { await apiRequest('/agenda/today-summary/seen', { method: 'POST' }) } catch { /* não bloqueia */ }
    setBriefOpen(false)
  }

  return <>
    {briefOpen && summary && <div className="agenda-notifier-backdrop">
      <section className="panel agenda-briefing-modal" role="dialog" aria-modal="true" aria-label="Resumo da agenda de hoje">
        <header><div><span className="eyebrow">Primeiro acesso do dia</span><h2>Olá, {summary.events.length ? 'sua agenda está pronta' : 'dia organizado'}.</h2><p>{fullDayLabel(summary.date)}</p></div>{!forced && <button className="icon-button" type="button" onClick={() => void closeBriefing()} aria-label="Fechar"><X size={16}/></button>}</header>
        {error && <div className="form-alert danger-alert">{error}</div>}
        {forced && <div className="agenda-forced-alert"><BellRing size={18}/><div><strong>{pending.length} ocorrência(s) anterior(es) sem conclusão</strong><span>A justificativa é obrigatória e o histórico original ficará preservado.</span></div></div>}
        {pending.length > 0 && <div className="agenda-justification-list">{pending.map(item => <article key={item.id}><div><span>{item.code}{item.department_name ? ` · ${item.department_name}` : ''}</span><strong>{item.title}</strong><small>Original: {item.original_scheduled_at ? new Date(item.original_scheduled_at).toLocaleDateString('pt-BR') : new Date(item.starts_at).toLocaleDateString('pt-BR')}{item.reschedule_sequence ? ` · ${item.reschedule_sequence}º reagendamento` : ''}</small></div><textarea rows={2} placeholder="Por que não foi cumprido?" value={justifications[item.id] || ''} onChange={event => setJustifications(current => ({ ...current, [item.id]: event.target.value }))}/><button className="button primary compact" disabled={saving} onClick={() => void justify(item)}>Registrar justificativa</button></article>)}</div>}
        <div className="agenda-briefing-section"><div className="agenda-section-heading"><div><span className="eyebrow">Hoje</span><h3>{todayEvents.length} item(ns) na sua agenda</h3></div>{summary.pending_invites > 0 && <span className="agenda-invite-pill">{summary.pending_invites} convite(s)</span>}</div><div className="agenda-briefing-events">{todayEvents.slice(0, 10).map(item => <button type="button" key={item.id} onClick={() => { setBriefOpen(false); onOpenAgenda() }}><span>{item.all_day ? 'Dia todo' : eventTime(item)}</span><div><strong>{item.title}</strong><small>{item.department_name || item.responsible_name || 'Agenda'}</small></div></button>)}{todayEvents.length === 0 && <div className="agenda-empty-day"><CheckCircle2 size={19}/><span>Nenhum compromisso previsto para hoje.</span></div>}</div></div>
        <footer><button className="button secondary" type="button" onClick={() => { if (!forced) { setBriefOpen(false); onOpenAgenda() } else onOpenAgenda() }}><CalendarDays size={14}/> Abrir agenda</button><button className="button primary" type="button" disabled={forced} onClick={() => void closeBriefing()}>{forced ? 'Justifique para continuar' : 'Entendi'}</button></footer>
      </section>
    </div>}

    {reminder && <aside className="panel agenda-reminder-popup" role="status"><div className="agenda-reminder-icon"><Clock3 size={18}/></div><div><span>Em aproximadamente {reminder.threshold} minutos</span><strong>{reminder.row.event.title}</strong><small>{eventTime(reminder.row.event)}</small></div><div className="agenda-reminder-actions"><button type="button" onClick={() => { setReminder(null); onOpenAgenda() }}>Abrir</button><button type="button" onClick={() => { setSnoozeUntil(Date.now() + 5 * 60_000); setReminder(null) }}>+5 min</button><button type="button" aria-label="Fechar" onClick={() => setReminder(null)}><X size={13}/></button></div></aside>}
  </>
}
