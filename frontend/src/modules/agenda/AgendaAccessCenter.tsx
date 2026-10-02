import { Clock3, Plus, Save, ShieldCheck, Trash2, UserCog, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { AgendaContext, Delegation } from './agendaTypes'

type Tab = 'availability' | 'delegations' | 'team'
type Props = { open: boolean; onClose: () => void; context: AgendaContext; startTab?: Tab; onContextChanged: () => Promise<void> | void }

export function AgendaAccessCenter({ open, onClose, context, startTab = 'availability', onContextChanged }: Props) {
  const [tab, setTab] = useState<Tab>(startTab)
  const [delegations, setDelegations] = useState<Delegation[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [workStart, setWorkStart] = useState(context.work_start)
  const [workEnd, setWorkEnd] = useState(context.work_end)
  const [lunchStart, setLunchStart] = useState(context.lunch_start || '')
  const [lunchEnd, setLunchEnd] = useState(context.lunch_end || '')
  const [workDays, setWorkDays] = useState<number[]>(context.work_days)
  const [buffer, setBuffer] = useState(context.buffer_minutes)
  const [defaultDuration, setDefaultDuration] = useState(context.default_duration_minutes)
  const [delegateId, setDelegateId] = useState('')
  const [viewDetails, setViewDetails] = useState(false)
  const [canCreate, setCanCreate] = useState(false)
  const [canReschedule, setCanReschedule] = useState(false)
  const [departmentDraft, setDepartmentDraft] = useState('')
  const [teamDraft, setTeamDraft] = useState<Record<string, { department_id: string; access_level: string }>>({})

  const loadDelegations = useCallback(async () => {
    try { setDelegations(await apiRequest<Delegation[]>('/agenda/delegations')) } catch { setDelegations([]) }
  }, [])

  useEffect(() => {
    if (!open) return
    setTab(startTab); setWorkStart(context.work_start); setWorkEnd(context.work_end); setLunchStart(context.lunch_start || ''); setLunchEnd(context.lunch_end || ''); setWorkDays(context.work_days); setBuffer(context.buffer_minutes); setDefaultDuration(context.default_duration_minutes)
    setTeamDraft(Object.fromEntries(context.directory.map(user => [user.id, { department_id: user.department_id || '', access_level: user.access_level }]))); void loadDelegations()
  }, [open, startTab, context, loadDelegations])

  useEffect(() => { if (!open) return; const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && !saving) onClose() }; window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close) }, [open, saving, onClose])

  const ownDelegations = useMemo(() => delegations.filter(item => item.owner_user_id === context.current_user_id), [delegations, context.current_user_id])
  const delegateCandidates = context.directory.filter(user => user.id !== context.current_user_id)

  function toggleDay(day: number) { setWorkDays(current => current.includes(day) ? current.filter(item => item !== day) : [...current, day].sort()) }

  async function saveAvailability() {
    setSaving(true); setError('')
    try {
      await apiRequest('/agenda/profile/me', { method: 'PUT', body: JSON.stringify({ work_start: workStart, work_end: workEnd, lunch_start: lunchStart || null, lunch_end: lunchEnd || null, work_days: workDays, buffer_minutes: buffer, default_duration_minutes: defaultDuration, timezone: context.timezone }) })
      await onContextChanged()
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar sua disponibilidade.') }
    finally { setSaving(false) }
  }

  async function saveDelegation() {
    if (!delegateId) return
    setSaving(true); setError('')
    try {
      await apiRequest('/agenda/delegations', { method: 'POST', body: JSON.stringify({ delegate_user_id: delegateId, can_view_availability: true, can_view_details: viewDetails, can_create: canCreate, can_reschedule: canReschedule }) })
      setDelegateId(''); setViewDetails(false); setCanCreate(false); setCanReschedule(false); await loadDelegations(); await onContextChanged()
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar a delegação.') }
    finally { setSaving(false) }
  }

  async function removeDelegation(id: string) {
    setSaving(true); setError('')
    try { await apiRequest(`/agenda/delegations/${id}`, { method: 'DELETE' }); await loadDelegations(); await onContextChanged() }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível remover a delegação.') }
    finally { setSaving(false) }
  }

  async function saveTeamUser(userId: string) {
    const draft = teamDraft[userId]; if (!draft) return
    setSaving(true); setError('')
    try { await apiRequest(`/agenda/profiles/${userId}`, { method: 'PUT', body: JSON.stringify({ department_id: draft.department_id || null, access_level: draft.access_level }) }); await onContextChanged() }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível alterar o perfil de agenda.') }
    finally { setSaving(false) }
  }

  async function addDepartment() {
    if (!departmentDraft.trim()) return
    setSaving(true); setError('')
    try { await apiRequest('/agenda/departments', { method: 'POST', body: JSON.stringify({ name: departmentDraft.trim() }) }); setDepartmentDraft(''); await onContextChanged() }
    catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível criar o setor.') }
    finally { setSaving(false) }
  }

  if (!open) return null
  return <div className="portfolio-modal-backdrop" onMouseDown={event => { if (event.currentTarget === event.target && !saving) onClose() }}>
    <section className="panel portfolio-modal agenda-smart-modal agenda-access-modal" role="dialog" aria-modal="true">
      <div className="portfolio-modal-header"><div><span className="eyebrow">Agenda inteligente</span><h2>Disponibilidade e acessos</h2><p>Horário de trabalho, delegações e hierarquia sem misturar agendas indevidamente.</p></div><button className="portfolio-modal-close" type="button" onClick={onClose}><X size={17}/></button></div>
      <div className="agenda-smart-tabs"><button className={tab === 'availability' ? 'active' : ''} onClick={() => setTab('availability')}><Clock3 size={13}/> Minha disponibilidade</button><button className={tab === 'delegations' ? 'active' : ''} onClick={() => setTab('delegations')}><ShieldCheck size={13}/> Delegações</button>{context.access_level === 'admin' && <button className={tab === 'team' ? 'active' : ''} onClick={() => setTab('team')}><UserCog size={13}/> Equipe e setores</button>}</div>
      {error && <div className="form-alert danger-alert agenda-modal-alert">{error}</div>}
      <div className="agenda-smart-body">
        {tab === 'availability' && <div className="agenda-availability-form"><div className="form-grid two-columns"><label className="field"><span>Início do expediente</span><input type="time" value={workStart} onChange={event => setWorkStart(event.target.value)}/></label><label className="field"><span>Fim do expediente</span><input type="time" value={workEnd} onChange={event => setWorkEnd(event.target.value)}/></label><label className="field"><span>Início do intervalo</span><input type="time" value={lunchStart} onChange={event => setLunchStart(event.target.value)}/></label><label className="field"><span>Fim do intervalo</span><input type="time" value={lunchEnd} onChange={event => setLunchEnd(event.target.value)}/></label><label className="field"><span>Intervalo entre compromissos</span><select value={buffer} onChange={event => setBuffer(Number(event.target.value))}><option value={0}>Sem intervalo</option><option value={5}>5 minutos</option><option value={10}>10 minutos</option><option value={15}>15 minutos</option><option value={30}>30 minutos</option></select></label><label className="field"><span>Duração padrão</span><select value={defaultDuration} onChange={event => setDefaultDuration(Number(event.target.value))}><option value={30}>30 minutos</option><option value={45}>45 minutos</option><option value={60}>1 hora</option><option value={90}>1h30</option><option value={120}>2 horas</option></select></label></div><div className="agenda-workdays"><span>Dias de trabalho</span><div>{['SEG','TER','QUA','QUI','SEX','SÁB','DOM'].map((label, index) => { const day = index === 6 ? 6 : index; return <button type="button" className={workDays.includes(day) ? 'active' : ''} onClick={() => toggleDay(day)} key={label}>{label}</button> })}</div></div><div className="agenda-inline-note">O motor de disponibilidade respeita expediente, intervalo e o buffer definido aqui ao sugerir próximos horários.</div></div>}

        {tab === 'delegations' && <div className="agenda-delegation-center"><div className="agenda-inline-note"><strong>Exemplo:</strong> sua secretária pode ver apenas quando você está livre, ver detalhes, criar compromissos ou reagendar — você escolhe cada permissão.</div><div className="agenda-delegation-form"><label className="field"><span>Dar acesso para</span><select value={delegateId} onChange={event => setDelegateId(event.target.value)}><option value="">Selecione uma pessoa...</option>{delegateCandidates.map(user => <option value={user.id} key={user.id}>{user.name} · {user.department_name || 'Sem setor'}</option>)}</select></label><div className="agenda-permission-checks"><label><input type="checkbox" checked readOnly/><span>Ver disponibilidade</span></label><label><input type="checkbox" checked={viewDetails} onChange={event => setViewDetails(event.target.checked)}/><span>Ver detalhes dos compromissos</span></label><label><input type="checkbox" checked={canCreate} onChange={event => setCanCreate(event.target.checked)}/><span>Criar compromissos na minha agenda</span></label><label><input type="checkbox" checked={canReschedule} onChange={event => setCanReschedule(event.target.checked)}/><span>Reagendar compromissos</span></label></div><button className="button primary" type="button" disabled={!delegateId || saving} onClick={() => void saveDelegation()}><Plus size={14}/> Adicionar delegação</button></div><div className="agenda-delegation-list">{ownDelegations.map(item => <article key={item.id}><div><strong>{item.delegate_name}</strong><span>{[item.can_view_availability && 'disponibilidade', item.can_view_details && 'detalhes', item.can_create && 'criar', item.can_reschedule && 'reagendar'].filter(Boolean).join(' · ')}</span></div><button className="icon-button" type="button" onClick={() => void removeDelegation(item.id)} title="Remover delegação"><Trash2 size={14}/></button></article>)}{ownDelegations.length === 0 && <div className="agenda-selected-empty"><ShieldCheck size={20}/><span>Ninguém possui acesso delegado à sua agenda.</span></div>}</div></div>}

        {tab === 'team' && context.access_level === 'admin' && <div className="agenda-team-center"><div className="agenda-create-department"><label className="field"><span>Novo setor</span><input value={departmentDraft} onChange={event => setDepartmentDraft(event.target.value)} placeholder="Ex.: Jurídico"/></label><button className="button secondary" type="button" disabled={!departmentDraft.trim() || saving} onClick={() => void addDepartment()}><Plus size={14}/> Criar setor</button></div><div className="agenda-team-table"><div className="agenda-team-head"><span>Pessoa</span><span>Setor</span><span>Nível de agenda</span><span/></div>{context.directory.map(user => { const draft = teamDraft[user.id] || { department_id: user.department_id || '', access_level: user.access_level }; return <div className="agenda-team-row" key={user.id}><div><strong>{user.name}</strong><small>{user.email}</small></div><select value={draft.department_id} onChange={event => setTeamDraft(current => ({ ...current, [user.id]: { ...draft, department_id: event.target.value } }))}><option value="">Sem setor</option>{context.departments.map(department => <option value={department.id} key={department.id}>{department.name}</option>)}</select><select value={draft.access_level} onChange={event => setTeamDraft(current => ({ ...current, [user.id]: { ...draft, access_level: event.target.value } }))}><option value="collaborator">Colaborador</option><option value="manager">Gerente</option><option value="director">Diretor</option><option value="admin">Administrador</option></select><button className="button secondary compact" type="button" disabled={saving} onClick={() => void saveTeamUser(user.id)}><Save size={13}/> Salvar</button></div>})}</div></div>}
      </div>
      <div className="canonical-modal-actions"><button className="button secondary" type="button" onClick={onClose}>Fechar</button>{tab === 'availability' && <button className="button primary" type="button" disabled={saving || workDays.length === 0} onClick={() => void saveAvailability()}><Save size={14}/> Salvar disponibilidade</button>}</div>
    </section>
  </div>
}
