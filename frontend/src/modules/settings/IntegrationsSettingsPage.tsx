import { Banknote, FileSignature, Mail, Save, ShieldCheck, Webhook } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { IntegrationsConfig } from '../../api/types'
import { authConfigured } from '../../auth/client'

const defaults: IntegrationsConfig = {
  bank_provider: 'inter',
  signature_provider: 'clicksign',
  email_provider: 'smtp',
  public_site_enabled: false,
  webhook_base_url: '',
  notes: '',
}

type Props = { canEdit: boolean }

const providerStatus = (enabled: boolean) => (
  <i className={`status-badge ${enabled ? 'success' : 'neutral'}`}>{enabled ? 'Padrão definido' : 'Desativado'}</i>
)

export function IntegrationsSettingsPage({ canEdit }: Props) {
  const [form, setForm] = useState<IntegrationsConfig>(defaults)
  const [loading, setLoading] = useState(authConfigured)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (!authConfigured) return
    let active = true
    void apiRequest<IntegrationsConfig>('/settings/integrations')
      .then((data) => { if (active) setForm(data) })
      .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar as integrações.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!canEdit) return
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const updated = authConfigured
        ? await apiRequest<IntegrationsConfig>('/settings/integrations', { method: 'PUT', body: JSON.stringify(form) })
        : form
      setForm(updated)
      setSuccess('Configuração de integrações salva e registrada na auditoria.')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar as integrações.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <section className="workspace settings-workspace"><article className="panel settings-loading">Carregando integrações...</article></section>

  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Conectividade</span>
          <h1>Integrações</h1>
          <p>Escolha os provedores da arquitetura. Credenciais e chaves sensíveis não são armazenadas nesta tela.</p>
        </div>
      </div>

      {error && <div className="form-alert danger-alert">{error}</div>}
      {success && <div className="form-alert success-alert">{success}</div>}

      <form onSubmit={save} className="settings-layout integrations-layout">
        <div className="settings-column">
          <article className="panel integration-card">
            <div className="integration-icon"><Banknote size={19} /></div>
            <div className="integration-content"><strong>Banco / Cobrança</strong><span>Provider financeiro principal</span></div>
            <select disabled={!canEdit} value={form.bank_provider} onChange={(e) => setForm((current) => ({ ...current, bank_provider: e.target.value as IntegrationsConfig['bank_provider'] }))}><option value="inter">Banco Inter Empresas</option><option value="none">Nenhum</option></select>
            {providerStatus(form.bank_provider !== 'none')}
          </article>

          <article className="panel integration-card">
            <div className="integration-icon"><FileSignature size={19} /></div>
            <div className="integration-content"><strong>Assinatura eletrônica</strong><span>Contratos e documentos assináveis</span></div>
            <select disabled={!canEdit} value={form.signature_provider} onChange={(e) => setForm((current) => ({ ...current, signature_provider: e.target.value as IntegrationsConfig['signature_provider'] }))}><option value="clicksign">Clicksign</option><option value="none">Nenhum</option></select>
            {providerStatus(form.signature_provider !== 'none')}
          </article>

          <article className="panel integration-card">
            <div className="integration-icon"><Mail size={19} /></div>
            <div className="integration-content"><strong>E-mail transacional</strong><span>Comunicações operacionais do ERP</span></div>
            <select disabled={!canEdit} value={form.email_provider} onChange={(e) => setForm((current) => ({ ...current, email_provider: e.target.value as IntegrationsConfig['email_provider'] }))}><option value="smtp">SMTP</option><option value="none">Nenhum</option></select>
            {providerStatus(form.email_provider !== 'none')}
          </article>

          <article className="panel form-panel">
            <div className="panel-heading panel-heading-row"><div><span className="eyebrow">Webhooks</span><h2>Base pública de retorno</h2></div><Webhook size={19} /></div>
            <div className="form-grid">
              <label className="field"><span>URL base de webhooks</span><input disabled={!canEdit} placeholder="https://app.exemplo.com/api/webhooks" value={form.webhook_base_url} onChange={(e) => setForm((current) => ({ ...current, webhook_base_url: e.target.value }))} /></label>
              <label className="field checkbox-field"><input disabled={!canEdit} type="checkbox" checked={form.public_site_enabled} onChange={(e) => setForm((current) => ({ ...current, public_site_enabled: e.target.checked }))} /><span>Site público habilitado para integração futura</span></label>
              <label className="field"><span>Observações internas</span><textarea disabled={!canEdit} rows={4} maxLength={1000} value={form.notes} onChange={(e) => setForm((current) => ({ ...current, notes: e.target.value }))} /></label>
            </div>
          </article>
        </div>

        <div className="settings-column">
          <article className="panel governance-note-card">
            <ShieldCheck size={22} />
            <div><span className="eyebrow">Segurança</span><h2>Segredos ficam fora do banco operacional</h2><p>Esta tela guarda somente escolha de provider e parâmetros não sensíveis. Tokens, certificados e senhas devem permanecer no Secret Manager e entrar na aplicação por configuração segura.</p></div>
          </article>
          <button className="button primary settings-save-button" disabled={!canEdit || saving} type="submit"><Save size={16} /> {saving ? 'Salvando...' : 'Salvar integrações'}</button>
          {!canEdit && <div className="read-only-note">Seu perfil pode consultar os providers, mas somente Administradores podem alterar a arquitetura de integrações.</div>}
        </div>
      </form>
    </section>
  )
}
