import { Plus, Save, ShieldCheck } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { ApprovalRule, ApprovalRulePayload } from '../../api/types'
import { authConfigured } from '../../auth/client'

const emptyDraft: ApprovalRulePayload = {
  name: '',
  scope: 'finance.payment',
  priority: 100,
  min_amount: null,
  max_amount: null,
  required_approvals: 1,
  approver_permission: 'finance.payment.approve',
  is_active: true,
  reason: '',
}

const scopeLabels: Record<string, string> = {
  'finance.payment': 'Pagamentos',
  'finance.repasse': 'Repasses',
  'bank_data.change': 'Dados bancários',
  'contracts.approval': 'Contratos',
  'maintenance.expense': 'Despesas de manutenção',
}

function toDraft(rule: ApprovalRule): ApprovalRulePayload {
  return {
    name: rule.name,
    scope: rule.scope,
    priority: rule.priority,
    min_amount: rule.min_amount,
    max_amount: rule.max_amount,
    required_approvals: rule.required_approvals,
    approver_permission: rule.approver_permission,
    is_active: rule.is_active,
    reason: '',
  }
}

function money(value: number | null) {
  if (value === null) return 'sem limite'
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

export function ApprovalRulesSettingsPage() {
  const [rules, setRules] = useState<ApprovalRule[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<ApprovalRulePayload>(emptyDraft)
  const [loading, setLoading] = useState(authConfigured)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const selectedRule = useMemo(() => rules.find((rule) => rule.id === selectedId) ?? null, [rules, selectedId])

  async function loadRules() {
    if (!authConfigured) {
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const data = await apiRequest<ApprovalRule[]>('/settings/approval-rules')
      setRules(data)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar as alçadas.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadRules() }, [])

  function newRule() {
    setSelectedId(null)
    setDraft({ ...emptyDraft })
    setError('')
    setSuccess('')
  }

  function selectRule(rule: ApprovalRule) {
    setSelectedId(rule.id)
    setDraft(toDraft(rule))
    setError('')
    setSuccess('')
  }

  function amountField(key: 'min_amount' | 'max_amount', value: string) {
    setDraft((current) => ({ ...current, [key]: value === '' ? null : Number(value) }))
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSuccess('')
    if (selectedId && !draft.reason?.trim()) {
      setError('Informe o motivo da alteração da alçada.')
      return
    }
    if (draft.max_amount !== null && draft.min_amount !== null && draft.max_amount < draft.min_amount) {
      setError('O valor máximo não pode ser menor que o valor mínimo.')
      return
    }

    setSaving(true)
    try {
      if (!authConfigured) {
        setSuccess('Pré-visualização local: regra validada.')
        return
      }
      const saved = await apiRequest<ApprovalRule>(
        selectedId ? `/settings/approval-rules/${selectedId}` : '/settings/approval-rules',
        { method: selectedId ? 'PUT' : 'POST', body: JSON.stringify(draft) },
      )
      await loadRules()
      setSelectedId(saved.id)
      setDraft(toDraft(saved))
      setSuccess(selectedId ? 'Alçada atualizada e auditada.' : 'Alçada criada e auditada.')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar a alçada.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Governança</span>
          <h1>Alçadas de aprovação</h1>
          <p>Defina quando uma operação exige aprovação e quantas aprovações são necessárias.</p>
        </div>
        <button className="button primary" type="button" onClick={newRule}><Plus size={16} /> Nova alçada</button>
      </div>

      {error && <div className="form-alert danger-alert">{error}</div>}
      {success && <div className="form-alert success-alert">{success}</div>}

      {loading ? (
        <article className="panel settings-loading">Carregando alçadas...</article>
      ) : (
        <div className="settings-layout approval-layout">
          <article className="panel approval-list-panel">
            <div className="panel-heading panel-heading-row"><div><span className="eyebrow">Regras</span><h2>Ordem de avaliação</h2></div><ShieldCheck size={20} /></div>
            <div className="approval-rule-list">
              {rules.map((rule) => (
                <button type="button" key={rule.id} className={`approval-rule-row ${selectedId === rule.id ? 'selected' : ''}`} onClick={() => selectRule(rule)}>
                  <div><strong>{rule.name}</strong><span>{scopeLabels[rule.scope] ?? rule.scope} · prioridade {rule.priority}</span></div>
                  <div className="approval-rule-meta"><i className={`status-badge ${rule.is_active ? 'success' : 'neutral'}`}>{rule.is_active ? 'Ativa' : 'Inativa'}</i><span>{rule.required_approvals} aprovação(ões)</span></div>
                </button>
              ))}
              {rules.length === 0 && <div className="audit-empty"><strong>Nenhuma alçada cadastrada.</strong><span>Crie a primeira regra para iniciar a governança operacional.</span></div>}
            </div>
          </article>

          <form className="panel form-panel approval-editor" onSubmit={save}>
            <div className="panel-heading"><span className="eyebrow">{selectedRule ? 'Editar regra' : 'Nova regra'}</span><h2>{selectedRule?.name ?? 'Configurar alçada'}</h2></div>
            <div className="form-grid two-columns">
              <label className="field field-wide"><span>Nome da regra</span><input required minLength={2} maxLength={160} value={draft.name} onChange={(e) => setDraft((current) => ({ ...current, name: e.target.value }))} placeholder="Ex.: Pagamentos acima de R$ 5.000" /></label>
              <label className="field"><span>Escopo</span><select value={draft.scope} onChange={(e) => setDraft((current) => ({ ...current, scope: e.target.value }))}><option value="finance.payment">Pagamentos</option><option value="finance.repasse">Repasses</option><option value="bank_data.change">Dados bancários</option><option value="contracts.approval">Contratos</option><option value="maintenance.expense">Despesas de manutenção</option></select></label>
              <label className="field"><span>Prioridade</span><input type="number" min={1} max={999} value={draft.priority} onChange={(e) => setDraft((current) => ({ ...current, priority: Number(e.target.value) }))} /></label>
              <label className="field"><span>Valor mínimo</span><input type="number" min={0} step="0.01" value={draft.min_amount ?? ''} onChange={(e) => amountField('min_amount', e.target.value)} placeholder="Sem mínimo" /></label>
              <label className="field"><span>Valor máximo</span><input type="number" min={0} step="0.01" value={draft.max_amount ?? ''} onChange={(e) => amountField('max_amount', e.target.value)} placeholder="Sem limite" /></label>
              <label className="field"><span>Aprovações exigidas</span><input type="number" min={1} max={5} value={draft.required_approvals} onChange={(e) => setDraft((current) => ({ ...current, required_approvals: Number(e.target.value) }))} /></label>
              <label className="field"><span>Permissão do aprovador</span><select value={draft.approver_permission} onChange={(e) => setDraft((current) => ({ ...current, approver_permission: e.target.value }))}><option value="finance.payment.approve">Aprovar pagamentos</option><option value="contracts.approve">Aprovar contratos</option><option value="approval_rules.manage">Administrador / Governança</option></select></label>
              <label className="field checkbox-field field-wide"><input type="checkbox" checked={draft.is_active} onChange={(e) => setDraft((current) => ({ ...current, is_active: e.target.checked }))} /><span>Regra ativa</span></label>
              {selectedRule && <label className="field field-wide"><span>Motivo da alteração</span><textarea required rows={3} maxLength={500} value={draft.reason ?? ''} onChange={(e) => setDraft((current) => ({ ...current, reason: e.target.value }))} placeholder="Obrigatório para preservar a trilha de auditoria" /></label>}
            </div>
            <div className="approval-range-preview"><span>Faixa atual</span><strong>{money(draft.min_amount)} → {money(draft.max_amount)}</strong></div>
            <button className="button primary" disabled={saving} type="submit"><Save size={16} /> {saving ? 'Salvando...' : selectedRule ? 'Salvar alteração' : 'Criar alçada'}</button>
          </form>
        </div>
      )}
    </section>
  )
}
