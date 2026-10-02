import { useEffect, useState } from 'react'
import { apiRequest } from '../../api/client'
import './agenda-history.css'

type HistoryEntry = {
  task_id: string
  sequence: number
  starts_at: string
  all_day: boolean
  status: string
  justification: string | null
  missed_at: string | null
  completed_at: string | null
  needs_justification: boolean
  selected: boolean
}

type HistoryResponse = {
  task_id: string
  root_task_id: string
  entries: HistoryEntry[]
}

type Props = {
  taskId: string
  originalScheduledAt: string
  currentSequence: number
  currentJustification: string | null
}

function occurrenceLabel(sequence: number) {
  return sequence === 0 ? 'Ocorrência original' : `${sequence}º reagendamento`
}

function statusLabel(item: HistoryEntry) {
  if (item.status === 'missed') return 'Não cumprido'
  if (item.status === 'completed') return 'Concluído'
  if (item.status === 'cancelled') return 'Cancelado'
  if (item.needs_justification) return 'Justificativa pendente'
  return 'Pendente'
}

function statusClass(item: HistoryEntry) {
  if (item.status === 'missed' || item.needs_justification) return 'danger'
  if (item.status === 'completed') return 'success'
  if (item.status === 'cancelled') return 'muted'
  return 'pending'
}

function dateLabel(item: HistoryEntry) {
  const date = new Date(item.starts_at)
  if (item.all_day) return `${date.toLocaleDateString('pt-BR')} · dia todo`
  return date.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export function AgendaAutomaticHistory({ taskId, originalScheduledAt, currentSequence, currentJustification }: Props) {
  const [history, setHistory] = useState<HistoryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    setFailed(false)
    void apiRequest<HistoryResponse>(`/agenda/tasks/${taskId}/history`)
      .then(result => { if (active) setHistory(result) })
      .catch(() => { if (active) { setHistory(null); setFailed(true) } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [taskId])

  return <div className="agenda-history-note agenda-history-full">
    <div className="agenda-history-header">
      <strong>Histórico automático</strong>
      {history && <span>{history.entries.length} ocorrência(s)</span>}
    </div>

    {loading && <span className="agenda-history-loading">Carregando linha do tempo...</span>}

    {!loading && history && <div className="agenda-history-timeline">
      {history.entries.map(item => <div className={`agenda-history-entry ${item.selected ? 'selected' : ''}`} key={item.task_id}>
        <div className="agenda-history-sequence">{item.sequence}</div>
        <div className="agenda-history-content">
          <div className="agenda-history-entry-head">
            <strong>{occurrenceLabel(item.sequence)}</strong>
            <i className={`agenda-history-status ${statusClass(item)}`}>{statusLabel(item)}</i>
          </div>
          <span>{dateLabel(item)}{item.selected ? ' · evento selecionado' : ''}</span>
          {item.justification && <p><b>Justificativa:</b> {item.justification}</p>}
          {item.needs_justification && !item.justification && <p className="agenda-history-pending"><b>Justificativa:</b> pendente de registro.</p>}
        </div>
      </div>)}
    </div>}

    {!loading && failed && <>
      <span>Ocorrência original: {new Date(originalScheduledAt).toLocaleDateString('pt-BR')}.</span>
      {currentSequence > 0 && <span>Evento selecionado: {currentSequence}º reagendamento.</span>}
      {currentJustification && <span>Justificativa: {currentJustification}</span>}
    </>}
  </div>
}
