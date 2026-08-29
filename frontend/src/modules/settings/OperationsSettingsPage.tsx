import { CalendarClock, Save, ShieldCheck } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { OperationalDefaults } from '../../api/types'
import { authConfigured } from '../../auth/client'

const defaults: OperationalDefaults = {
  rent_due_day: 10,
  owner_repasse_business_days: 2,
  residential_lease_months: 30,
  adjustment_index: 'IPCA',
  termination_fine_months: 3,
  inspection_contest_days: 5,
  default_admin_fee_percent: 10,
  delinquency_critical_day: 5,
}

type Props = { canEdit: boolean }

export function OperationsSettingsPage({ canEdit }: Props) {
  const [form, setForm] = useState<OperationalDefaults>(defaults)
  const [loading, setLoading] = useState(authConfigured)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (!authConfigured) return
    let active = true
    void apiRequest<OperationalDefaults>('/settings/operations')
      .then((data) => { if (active) setForm(data) })
      .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os padrões operacionais.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  function numberField<K extends keyof OperationalDefaults>(key: K, value: string) {
    setForm((current) => ({ ...current, [key]: Number(value) }))
    setSuccess('')
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!canEdit) return
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const updated = authConfigured
        ? await apiRequest<OperationalDefaults>('/settings/operations', { method: 'PUT', body: JSON.stringify(form) })
        : form
      setForm(updated)
      setSuccess('Padrões operacionais salvos. Novos registros passam a usar esta configuração.')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar os padrões operacionais.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <section className="workspace settings-workspace"><article className="panel settings-loading">Carregando padrões operacionais...</article></section>

  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Operação</span>
          <h1>Padrões operacionais</h1>
          <p>Valores usados como ponto de partida em novos contratos e processos. Alterações não são retroativas.</p>
        </div>
      </div>

      {error && <div className="form-alert danger-alert">{error}</div>}
      {success && <div className="form-alert success-alert">{success}</div>}

      <form onSubmit={save} className="settings-layout">
        <div className="settings-column">
          <article className="panel form-panel">
            <div className="panel-heading panel-heading-row">
              <div><span className="eyebrow">Locação</span><h2>Contrato e cobrança</h2></div>
              <CalendarClock size={20} />
            </div>
            <div className="form-grid two-columns">
              <label className="field"><span>Vencimento padrão do aluguel</span><input disabled={!canEdit} min={1} max={28} type="number" value={form.rent_due_day} onChange={(e) => numberField('rent_due_day', e.target.value)} /></label>
              <label className="field"><span>Prazo residencial padrão (meses)</span><input disabled={!canEdit} min={1} max={120} type="number" value={form.residential_lease_months} onChange={(e) => numberField('residential_lease_months', e.target.value)} /></label>
              <label className="field"><span>Índice de reajuste</span><input disabled={!canEdit} maxLength={30} value={form.adjustment_index} onChange={(e) => setForm((current) => ({ ...current, adjustment_index: e.target.value }))} /></label>
              <label className="field"><span>Multa rescisória (aluguéis)</span><input disabled={!canEdit} min={0} max={12} step="0.5" type="number" value={form.termination_fine_months} onChange={(e) => numberField('termination_fine_months', e.target.value)} /></label>
              <label className="field"><span>Taxa de administração padrão (%)</span><input disabled={!canEdit} min={0} max={100} step="0.1" type="number" value={form.default_admin_fee_percent} onChange={(e) => numberField('default_admin_fee_percent', e.target.value)} /></label>
              <label className="field"><span>Repasse ao proprietário (dias úteis)</span><input disabled={!canEdit} min={0} max={20} type="number" value={form.owner_repasse_business_days} onChange={(e) => numberField('owner_repasse_business_days', e.target.value)} /></label>
            </div>
          </article>

          <article className="panel form-panel">
            <div className="panel-heading"><span className="eyebrow">Controle</span><h2>Prazos críticos</h2></div>
            <div className="form-grid two-columns">
              <label className="field"><span>Contestação de vistoria (dias)</span><input disabled={!canEdit} min={1} max={30} type="number" value={form.inspection_contest_days} onChange={(e) => numberField('inspection_contest_days', e.target.value)} /></label>
              <label className="field"><span>Inadimplência crítica a partir do dia</span><input disabled={!canEdit} min={1} max={90} type="number" value={form.delinquency_critical_day} onChange={(e) => numberField('delinquency_critical_day', e.target.value)} /></label>
            </div>
          </article>
        </div>

        <div className="settings-column">
          <article className="panel governance-note-card">
            <ShieldCheck size={22} />
            <div>
              <span className="eyebrow">Princípio estrutural</span>
              <h2>Configuração não reescreve histórico</h2>
              <p>Estes valores servem como padrão para novos registros. Cada contrato guarda sua própria regra, preservando o que foi acordado na data da contratação.</p>
            </div>
          </article>
          <button className="button primary settings-save-button" disabled={!canEdit || saving} type="submit"><Save size={16} /> {saving ? 'Salvando...' : 'Salvar padrões'}</button>
          {!canEdit && <div className="read-only-note">Seu perfil pode consultar estas regras, mas somente Administradores podem alterá-las.</div>}
        </div>
      </form>
    </section>
  )
}
