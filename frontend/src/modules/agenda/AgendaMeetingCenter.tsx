import { CalendarSearch, Check, CheckCircle2, Clock3, Plus, Send, Users, X, XCircle } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { AgendaContext, AvailabilityResponse, MeetingRequest } from './agendaTypes'
import { humanDateTime, localDateValue, todayValue } from './agendaTypes'

type Mode = 'inbox' | 'request' | 'find'
type DraftOption = { value: string; availability: AvailabilityResponse | null; checking: boolean }
type FindOption = { starts_at: string; ends_at: string }
type Props = { open: boolean; onClose: () => void; context: AgendaContext; startMode?: Mode; onChanged: () => void }

function addMinutes(isoLocal: string, minutes: number) {
  const date = new Date(isoLocal)
  date.setMinutes(date.getMinutes() + minutes)
  return date.toISOString()
}

export function AgendaMeetingCenter({ open, onClose, context, startMode = 'inbox', onChanged }: Props) {
  const [mode, setMode] = useState<Mode>(startMode)
  const [requests, setRequests] = useState<MeetingRequest[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [duration, setDuration] = useState(60)
  const [privacy, setPrivacy] = useState('normal')
  const [participants, setParticipants] = useState<string[]>([])
  const [departmentFilter, setDepartmentFilter] = useState('all')
  const [personFilter, setPersonFilter] = useState('')
  const [draftOptions, setDraftOptions] = useState<DraftOption[]>([])
  const [proposalValues, setProposalValues] = useState<Record<string, string>>({})
  const [findStart, setFindStart] = useState(todayValue())
  const [findEnd, setFindEnd] = useState(localDateValue(new Date(Date.now() + 7 * 86400000)))
  const [findResults, setFindResults] = useState<FindOption[]>([])

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setRequests(await apiRequest<MeetingRequest[]>('/agenda/meeting-requests')) }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os convites.') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { if (open) { setMode(startMode); void load() } }, [open, startMode, load])
  useEffect(() => {
    if (!open) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && !saving) onClose() }
    window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close)
  }, [open, saving, onClose])

  const directory = useMemo(() => context.directory.filter(user => user.id !== context.current_user_id && (departmentFilter === 'all' || user.department_id === departmentFilter)), [context, departmentFilter])
  const pendingIncoming = requests.filter(item => item.direction === 'incoming' && item.status === 'pending')

  function invalidateAvailability() {
    setDraftOptions(current => current.map(row => ({ ...row, availability: null })))
    setFindResults([])
  }

  function toggleParticipant(id: string) {
    setPersonFilter('')
    setParticipants(current => current.includes(id) ? current.filter(item => item !== id) : [...current, id])
    invalidateAvailability()
  }

  function changeDepartment(value: string) {
    setDepartmentFilter(value)
    setPersonFilter('')
    invalidateAvailability()
  }

  function choosePeople(value: string) {
    setPersonFilter(value)
    if (!value) return
    setParticipants(value === 'all' ? directory.map(user => user.id) : [value])
    invalidateAvailability()
  }

  function addOption(value = '') { setDraftOptions(current => [...current, { value, availability: null, checking: false }]) }
  function removeOption(index: number) { setDraftOptions(current => current.filter((_, i) => i !== index)) }

  async function checkOption(index: number) {
    const item = draftOptions[index]
    if (!item?.value || participants.length === 0) return
    const starts = new Date(item.value)
    const ends = addMinutes(item.value, duration)
    setDraftOptions(current => current.map((row, i) => i === index ? { ...row, checking: true } : row))
    try {
      const result = await apiRequest<AvailabilityResponse>('/agenda/availability', { method: 'POST', body: JSON.stringify({ user_ids: [context.current_user_id, ...participants], starts_at: starts.toISOString(), ends_at: ends }) })
      setDraftOptions(current => current.map((row, i) => i === index ? { ...row, availability: result, checking: false } : row))
    } catch { setDraftOptions(current => current.map((row, i) => i === index ? { ...row, availability: null, checking: false } : row)) }
  }

  async function sendRequest() {
    if (!title.trim() || participants.length === 0) { setError('Informe o assunto e selecione ao menos um participante.'); return }
    setSaving(true); setError('')
    try {
      await apiRequest('/agenda/meeting-requests', { method: 'POST', body: JSON.stringify({ title: title.trim(), description: description.trim() || null, participant_user_ids: participants, duration_minutes: duration, privacy, options: draftOptions.filter(item => item.value).map(item => ({ starts_at: new Date(item.value).toISOString() })) }) })
      setTitle(''); setDescription(''); setParticipants([]); setDepartmentFilter('all'); setPersonFilter(''); setDraftOptions([]); setMode('inbox'); await load(); onChanged()
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível enviar a solicitação.') }
    finally { setSaving(false) }
  }

  async function respondOption(optionId: string, decision: 'accepted' | 'rejected') {
    setSaving(true); setError('')
    try { await apiRequest(`/agenda/meeting-options/${optionId}/respond`, { method: 'POST', body: JSON.stringify({ decision }) }); await load(); onChanged() }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível responder ao horário.') }
    finally { setSaving(false) }
  }

  async function propose(requestId: string) {
    const value = proposalValues[requestId]
    if (!value) return
    setSaving(true); setError('')
    try { await apiRequest(`/agenda/meeting-requests/${requestId}/options`, { method: 'POST', body: JSON.stringify({ options: [{ starts_at: new Date(value).toISOString() }] }) }); setProposalValues(current => ({ ...current, [requestId]: '' })); await load() }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível sugerir o horário.') }
    finally { setSaving(false) }
  }

  async function decline(requestId: string) {
    setSaving(true); setError('')
    try { await apiRequest(`/agenda/meeting-requests/${requestId}/decline`, { method: 'POST', body: JSON.stringify({ reason: null }) }); await load(); onChanged() }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível recusar a reunião.') }
    finally { setSaving(false) }
  }

  async function findTime() {
    if (participants.length === 0) { setError('Selecione ao menos uma pessoa para encontrar horário.'); return }
    setLoading(true); setError('')
    try {
      setFindResults(await apiRequest<FindOption[]>('/agenda/find-time', { method: 'POST', body: JSON.stringify({ user_ids: [context.current_user_id, ...participants], duration_minutes: duration, start_date: findStart, end_date: findEnd, limit: 16 }) }))
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível localizar horários em comum.') }
    finally { setLoading(false) }
  }

  function useFindOption(item: FindOption) {
    const date = new Date(item.starts_at); const offset = date.getTimezoneOffset(); const local = new Date(date.getTime() - offset * 60000).toISOString().slice(0, 16)
    setDraftOptions(current => [...current, { value: local, availability: { all_available: true, users: [] }, checking: false }]); setMode('request')
  }

  if (!open) return null
  return <div className="portfolio-modal-backdrop" onMouseDown={event => { if (event.currentTarget === event.target && !saving) onClose() }}>
    <section className="panel portfolio-modal agenda-smart-modal agenda-meeting-modal" role="dialog" aria-modal="true">
      <div className="portfolio-modal-header"><div><span className="eyebrow">Agenda inteligente</span><h2>Reuniões e disponibilidade</h2><p>Convites com múltiplas opções e busca automática de horário em comum.</p></div><button className="portfolio-modal-close" type="button" onClick={onClose}><X size={17}/></button></div>
      <div className="agenda-smart-tabs"><button className={mode === 'inbox' ? 'active' : ''} onClick={() => setMode('inbox')}>Convites {pendingIncoming.length > 0 && <span>{pendingIncoming.length}</span>}</button><button className={mode === 'request' ? 'active' : ''} onClick={() => setMode('request')}>Solicitar reunião</button><button className={mode === 'find' ? 'active' : ''} onClick={() => setMode('find')}><CalendarSearch size={13}/> Encontrar horário</button></div>
      {error && <div className="form-alert danger-alert agenda-modal-alert">{error}</div>}
      <div className="agenda-smart-body">
        {mode === 'inbox' && <div className="agenda-inbox-list">{loading ? <div className="settings-loading">Carregando convites...</div> : requests.length === 0 ? <div className="agenda-selected-empty"><CheckCircle2 size={22}/><span>Nenhuma solicitação de reunião.</span></div> : requests.map(request => <article className={`agenda-meeting-request ${request.status}`} key={request.id}><div className="agenda-meeting-head"><div><span>{request.code} · {request.direction === 'incoming' ? `Convite de ${request.organizer.name}` : 'Enviado por você'}</span><strong>{request.title}</strong><small>{request.participants.map(item => item.name).join(', ')}</small></div><i className={`status-badge ${request.status === 'confirmed' ? 'success' : request.status === 'pending' ? 'warning' : 'neutral'}`}>{request.status === 'confirmed' ? 'Confirmada' : request.status === 'pending' ? 'Aguardando' : request.status}</i></div>{request.description && <p>{request.description}</p>}<div className="agenda-option-list">{request.options.map(option => <div className={`agenda-meeting-option ${option.status}`} key={option.id}><div><Clock3 size={14}/><strong>{humanDateTime(option.starts_at)}</strong><span className={option.all_available ? 'availability-ok' : 'availability-no'} title={option.all_available ? 'Todos os participantes estão disponíveis neste horário.' : 'Um ou mais participantes já possuem compromisso neste horário.'}>{option.all_available ? <Check size={13}/> : <X size={13}/>}</span></div><small>{option.status === 'selected' ? 'Horário confirmado' : option.my_vote === 'accepted' ? 'Você aceitou esta opção' : option.my_vote === 'rejected' ? 'Você recusou esta opção' : 'Aguardando sua resposta'}</small>{request.status === 'pending' && option.status === 'open' && request.direction === 'incoming' && <div><button className="button primary compact" disabled={saving} onClick={() => void respondOption(option.id, 'accepted')}><Check size={13}/> Aceitar</button><button className="button secondary compact" disabled={saving} onClick={() => void respondOption(option.id, 'rejected')}><X size={13}/> Não posso</button></div>}</div>)}</div>{request.status === 'pending' && <div className="agenda-reproposal"><label className="field"><span>Sugerir outro horário</span><input type="datetime-local" value={proposalValues[request.id] || ''} onChange={event => setProposalValues(current => ({ ...current, [request.id]: event.target.value }))}/></label><button className="button secondary compact" disabled={!proposalValues[request.id] || saving} onClick={() => void propose(request.id)}>Sugerir</button>{request.direction === 'incoming' && <button className="button ghost-danger compact" disabled={saving} onClick={() => void decline(request.id)}><XCircle size={13}/> Recusar reunião</button>}</div>}</article>)}</div>}

        {(mode === 'request' || mode === 'find') && <div className="agenda-meeting-compose"><div className="agenda-participant-picker"><div className="agenda-section-heading"><div><span className="eyebrow">Participantes</span><h3>{participants.length} selecionado(s)</h3></div><div className="heading-actions"><select aria-label="Filtrar participantes por setor" value={departmentFilter} onChange={event => changeDepartment(event.target.value)}><option value="all">Todos os setores</option>{context.departments.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select><select aria-label="Selecionar pessoas" value={personFilter} onChange={event => choosePeople(event.target.value)}><option value="">Selecionar pessoa...</option><option value="all">{departmentFilter === 'all' ? 'Todas as pessoas' : 'Todas as pessoas do setor'}</option>{directory.map(user => <option value={user.id} key={user.id}>{user.name}</option>)}</select></div></div><div className="agenda-people-grid">{directory.map(user => <label className={participants.includes(user.id) ? 'selected' : ''} key={user.id}><input type="checkbox" checked={participants.includes(user.id)} onChange={() => toggleParticipant(user.id)}/><span>{user.name}</span><small>{user.department_name || 'Sem setor'}</small></label>)}{directory.length === 0 && <div className="agenda-selected-empty"><Users size={18}/><span>Nenhuma pessoa encontrada neste setor.</span></div>}</div></div>
          <div className="form-grid two-columns"><label className="field"><span>Duração</span><select value={duration} onChange={event => { setDuration(Number(event.target.value)); invalidateAvailability() }}><option value={30}>30 minutos</option><option value={45}>45 minutos</option><option value={60}>1 hora</option><option value={90}>1h30</option><option value={120}>2 horas</option></select></label>{mode === 'request' && <label className="field"><span>Privacidade</span><select value={privacy} onChange={event => setPrivacy(event.target.value)}><option value="normal">Normal</option><option value="private">Privado · terceiros veem apenas “Ocupado”</option></select></label>}</div>
          {mode === 'request' ? <><label className="field"><span>Assunto</span><input value={title} maxLength={180} onChange={event => setTitle(event.target.value)} placeholder="Ex.: Reunião sobre contrato do imóvel"/></label><label className="field"><span>Descrição</span><textarea rows={3} value={description} onChange={event => setDescription(event.target.value)} placeholder="Contexto da reunião..."/></label><div className="agenda-proposed-heading"><div><span className="eyebrow">Opções de horário</span><small>Você pode enviar nenhuma, uma ou quantas opções quiser.</small></div><button className="button secondary compact" type="button" onClick={() => addOption()}><Plus size={13}/> Adicionar horário</button></div><div className="agenda-draft-options">{draftOptions.map((option, index) => <div key={index}><input type="datetime-local" value={option.value} onChange={event => setDraftOptions(current => current.map((row, i) => i === index ? { ...row, value: event.target.value, availability: null } : row))} onBlur={() => void checkOption(index)}/><span className={option.availability?.all_available ? 'availability-ok' : option.availability ? 'availability-no' : 'availability-unknown'} title={option.availability?.all_available ? 'Todos estão disponíveis.' : option.availability ? 'Há conflito de agenda.' : 'Saia do campo para verificar disponibilidade.'}>{option.checking ? '…' : option.availability?.all_available ? <Check size={14}/> : option.availability ? <X size={14}/> : '?'}</span><button className="icon-button" type="button" onClick={() => removeOption(index)}><X size={13}/></button></div>)}</div></> : <><div className="form-grid two-columns"><label className="field"><span>Buscar a partir de</span><input type="date" value={findStart} onChange={event => setFindStart(event.target.value)}/></label><label className="field"><span>Até</span><input type="date" min={findStart} value={findEnd} onChange={event => setFindEnd(event.target.value)}/></label></div><button className="button primary" type="button" disabled={loading || participants.length === 0} onClick={() => void findTime()}><CalendarSearch size={14}/> Encontrar horários em comum</button><div className="agenda-find-results">{findResults.map(item => <button type="button" key={item.starts_at} onClick={() => useFindOption(item)}><span className="availability-ok"><Check size={13}/></span><div><strong>{humanDateTime(item.starts_at)}</strong><small>Todos os participantes disponíveis</small></div></button>)}{findResults.length === 0 && !loading && <div className="agenda-selected-empty"><Users size={20}/><span>Selecione participantes e consulte a disponibilidade em comum.</span></div>}</div></>}
        </div>}
      </div>
      <div className="canonical-modal-actions"><button className="button secondary" type="button" onClick={onClose}>Fechar</button>{mode === 'request' && <button className="button primary" type="button" disabled={saving || !title.trim() || participants.length === 0} onClick={() => void sendRequest()}><Send size={14}/> Enviar solicitação</button>}</div>
    </section>
  </div>
}
