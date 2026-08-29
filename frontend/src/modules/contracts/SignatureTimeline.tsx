import { CheckCircle2, Clock3, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'

type SignatureEvent = {
  id: string
  provider: string
  event_name: string
  envelope_id: string | null
  hmac_valid: boolean
  received_at: string
}

export function SignatureTimeline({ contractId, enabled = true }: { contractId: string; enabled?: boolean }) {
  const [events, setEvents] = useState<SignatureEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!enabled) return
    let active = true
    setLoading(true)
    setError('')
    void apiRequest<SignatureEvent[]>(`/administration-contracts/${contractId}/signature/events`)
      .then((data) => { if (active) setEvents(data) })
      .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar a trilha de assinatura.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [contractId, enabled])

  return (
    <div className="signature-timeline">
      <div className="signature-timeline-heading"><span className="eyebrow">Trilha Clicksign</span><ShieldCheck size={15}/></div>
      {loading && <small>Carregando eventos...</small>}
      {error && <small className="signature-timeline-error">{error}</small>}
      {!loading && !error && events.length === 0 && <small>Nenhum webhook de assinatura recebido para este contrato.</small>}
      {events.map((event) => <div className="signature-event" key={event.id}>
        {event.hmac_valid ? <CheckCircle2 size={14}/> : <Clock3 size={14}/>}
        <div><strong>{event.event_name.replaceAll('_', ' ')}</strong><span>{event.provider} · {new Date(event.received_at).toLocaleString('pt-BR')}</span>{event.envelope_id && <small>Envelope {event.envelope_id}</small>}</div>
      </div>)}
    </div>
  )
}
