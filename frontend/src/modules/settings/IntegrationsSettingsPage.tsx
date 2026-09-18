import { Banknote, CheckCircle2, CircleAlert, FileSignature, Mail, RefreshCw, Save, ShieldCheck, Webhook } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { IntegrationReadiness, IntegrationsConfig, SignatureIntegrationStatus } from '../../api/types'
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
  <i className={`status-badge ${enabled ? 'success' : 'neutral'}`}>{enabled ? 'Provider selecionado' : 'Desativado'}</i>
)

function signatureBadge(statusValue: SignatureIntegrationStatus | null) {
  if (!statusValue) return <i className="status-badge neutral">Status não consultado</i>
  if (!statusValue.configured) return <i className="status-badge warning">Credencial pendente</i>
  if (statusValue.reachable === true) return <i className="status-badge success">Conectado</i>
  if (statusValue.reachable === false) return <i className="status-badge danger">Falha de conexão</i>
  return <i className="status-badge neutral">Credencial presente</i>
}

export function IntegrationsSettingsPage({ canEdit }: Props) {
  const [form, setForm] = useState<IntegrationsConfig>(defaults)
  const [signatureStatus, setSignatureStatus] = useState<SignatureIntegrationStatus | null>(null)
  const [readiness, setReadiness] = useState<IntegrationReadiness | null>(null)
  const [loading, setLoading] = useState(authConfigured)
  const [saving, setSaving] = useState(false)
  const [testingSignature, setTestingSignature] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (!authConfigured) return
    let active = true
    void Promise.all([
      apiRequest<IntegrationsConfig>('/settings/integrations'),
      apiRequest<SignatureIntegrationStatus>('/integrations/signature/status').catch(() => null),
      apiRequest<IntegrationReadiness>('/integrations/readiness').catch(() => null),
    ])
      .then(([data, statusData, readinessData]) => {
        if (!active) return
        setForm(data)
        setSignatureStatus(statusData)
        setReadiness(readinessData)
      })
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
      if (authConfigured) {
        setSignatureStatus(await apiRequest<SignatureIntegrationStatus>('/integrations/signature/status').catch(() => null))
        setReadiness(await apiRequest<IntegrationReadiness>('/integrations/readiness').catch(() => null))
      }
      setSuccess('Configuração de integrações salva e registrada na auditoria.')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar as integrações.')
    } finally {
      setSaving(false)
    }
  }

  async function testSignatureConnection() {
    if (!canEdit || !authConfigured) return
    setTestingSignature(true)
    setError('')
    setSuccess('')
    try {
      const result = await apiRequest<SignatureIntegrationStatus>('/integrations/signature/test', { method: 'POST' })
      setSignatureStatus(result)
      if (result.reachable) setSuccess('Conexão com a Clicksign validada com sucesso.')
      else setError(result.message)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível testar a Clicksign.')
    } finally {
      setTestingSignature(false)
    }
  }

  if (loading) return <section className="workspace settings-workspace"><article className="panel settings-loading">Carregando integrações...</article></section>

  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Conectividade</span>
          <h1>Integrações</h1>
          <p>Escolha os provedores e acompanhe o estado real de conexão. Credenciais e chaves sensíveis continuam fora desta tela.</p>
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

          <article className="panel integration-card integration-card-expanded">
            <div className="integration-icon"><FileSignature size={19} /></div>
            <div className="integration-content"><strong>Assinatura eletrônica</strong><span>Contratos e documentos assináveis</span></div>
            <select disabled={!canEdit} value={form.signature_provider} onChange={(e) => setForm((current) => ({ ...current, signature_provider: e.target.value as IntegrationsConfig['signature_provider'] }))}><option value="clicksign">Clicksign</option><option value="none">Nenhum</option></select>
            {form.signature_provider === 'clicksign' ? signatureBadge(signatureStatus) : providerStatus(false)}
            {form.signature_provider === 'clicksign' && (
              <div className="integration-health">
                <div className="integration-health-copy">
                  {signatureStatus?.reachable ? <CheckCircle2 size={16}/> : <CircleAlert size={16}/>} 
                  <div><strong>{signatureStatus ? `Ambiente ${signatureStatus.environment}` : 'Clicksign'}</strong><span>{signatureStatus?.message ?? 'Consulte o status para saber se a credencial segura já está disponível.'}</span></div>
                </div>
                <button className="button secondary compact-button" disabled={!canEdit || testingSignature} type="button" onClick={() => void testSignatureConnection()}><RefreshCw size={14}/>{testingSignature ? 'Testando...' : 'Testar conexão'}</button>
              </div>
            )}
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
              <label className="field checkbox-field"><input disabled={!canEdit} type="checkbox" checked={form.public_site_enabled} onChange={(e) => setForm((current) => ({ ...current, public_site_enabled: e.target.checked }))} /><span>Site público habilitado</span></label>
              <label className="field"><span>Observações internas</span><textarea disabled={!canEdit} rows={4} maxLength={1000} value={form.notes} onChange={(e) => setForm((current) => ({ ...current, notes: e.target.value }))} /></label>
            </div>
          </article>
        </div>

        <div className="settings-column">
          <article className="panel form-panel">
            <div className="panel-heading panel-heading-row">
              <div>
                <span className="eyebrow">Readiness operacional</span>
                <h2>{readiness?.ready ? 'Ambiente pronto' : 'Pendências de integração'}</h2>
              </div>
              {readiness?.ready ? <CheckCircle2 size={21} /> : <CircleAlert size={21} />}
            </div>
            <p className="muted-copy">
              {readiness
                ? readiness.ready
                  ? 'Todas as integrações selecionadas possuem a configuração mínima necessária.'
                  : `${readiness.pending_count} integração(ões) selecionada(s) ainda precisa(m) de configuração segura.`
                : 'Status consolidado ainda não disponível.'}
            </p>
            <div className="settings-column">
              {readiness?.items.map((item) => (
                <div className="integration-health" key={item.key}>
                  <div className="integration-health-copy">
                    {item.status === 'ready' ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
                    <div>
                      <strong>{item.label}{item.environment ? ` · ${item.environment}` : ''}</strong>
                      <span>{item.message}</span>
                    </div>
                  </div>
                  <i className={`status-badge ${item.status === 'ready' ? 'success' : item.status === 'disabled' ? 'neutral' : 'warning'}`}>
                    {item.status === 'ready' ? 'Pronto' : item.status === 'disabled' ? 'Desativado' : 'Atenção'}
                  </i>
                </div>
              ))}
            </div>
          </article>

          <article className="panel governance-note-card">
            <ShieldCheck size={22} />
            <div><span className="eyebrow">Segurança</span><h2>Segredos ficam fora do banco operacional</h2><p>Esta tela guarda somente escolha de provider e parâmetros não sensíveis. Token e HMAC Secret da Clicksign entram pela configuração segura do Cloud Run/Secret Manager e nunca aparecem de volta na interface.</p></div>
          </article>
          <article className="panel governance-note-card">
            <Webhook size={22}/>
            <div><span className="eyebrow">Clicksign</span><h2>Webhook com validação HMAC</h2><p>O endpoint do ERP rejeita eventos sem HMAC válido. Mesmo quando a Clicksign informar que o envelope foi concluído, o contrato não vira “assinado” até o documento final ser arquivado com sucesso.</p></div>
          </article>
          <button className="button primary settings-save-button" disabled={!canEdit || saving} type="submit"><Save size={16} /> {saving ? 'Salvando...' : 'Salvar integrações'}</button>
          {!canEdit && <div className="read-only-note">Seu perfil pode consultar os providers, mas somente Administradores podem alterar a arquitetura de integrações.</div>}
        </div>
      </form>
    </section>
  )
}
