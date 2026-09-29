import { Activity, Banknote, CheckCircle2, CircleAlert, Database, FileSignature, Mail, MessageCircle, RadioTower, RefreshCw, Save, ShieldCheck, Webhook } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { BankIntegrationStatus, IntegrationReadiness, IntegrationsConfig, SignatureIntegrationStatus, SmtpConfiguration } from '../../api/types'
import { authConfigured } from '../../auth/client'
import { InstagramIntegrationSettingsPanel } from './InstagramIntegrationSettingsPanel'
import { PortalIntegrationsSettingsPanel } from './PortalIntegrationsSettingsPanel'
import { WhatsAppIntegrationSettingsPanel } from './WhatsAppIntegrationSettingsPanel'

const defaults: IntegrationsConfig = {
  bank_provider: 'inter',
  signature_provider: 'clicksign',
  email_provider: 'smtp',
  public_site_enabled: false,
  webhook_base_url: '',
  notes: '',
}

const smtpDefaults: SmtpConfiguration = { host: '', port: 587, username: '', from_email: '', from_name: '', use_tls: true, use_ssl: false, password_configured: false, source: 'none' }

type Props = { canEdit: boolean }

type IntegrationAuditStatus = 'ok' | 'attention' | 'disabled'
type IntegrationAuditItem = { key:string; label:string; status:IntegrationAuditStatus; detail:string }
type DocumentStorageStatus = { provider:string; configured:boolean; reachable:boolean|null; bucket:string|null; message:string; checked_at:string }
type WhatsAppAuditConfig = { configured:boolean; reachable:boolean|null; last_webhook_at:string|null; last_webhook_status:string; message:string }
type PortalAuditChannel = { key:string; label:string; status:string }
type PortalAuditConfig = { channels:PortalAuditChannel[] }
type PortalValidation = { valid:boolean; selected_count:number; invalid_count:number; xml_valid:boolean }
type PortalValidationResult = PortalAuditChannel & { validation:PortalValidation }

const bankProviderLabel = (key: IntegrationsConfig['bank_provider']) => ({
  inter: 'Banco Inter Empresas',
  itau: 'Itaú Empresas',
  sicredi: 'Sicredi',
  none: 'Banco',
}[key])

const providerStatus = (enabled: boolean) => (
  <i className={`status-badge ${enabled ? 'success' : 'neutral'}`}>{enabled ? 'Provider selecionado' : 'Desativado'}</i>
)

function connectionBadge(statusValue: SignatureIntegrationStatus | BankIntegrationStatus | null) {
  if (!statusValue) return <i className="status-badge neutral">Status não consultado</i>
  if (!statusValue.configured) return <i className="status-badge warning">Credencial pendente</i>
  if (statusValue.reachable === true) return <i className="status-badge success">Conectado</i>
  if (statusValue.reachable === false) return <i className="status-badge danger">Falha de conexão</i>
  return <i className="status-badge neutral">Credencial presente</i>
}

export function IntegrationsSettingsPage({ canEdit }: Props) {
  const [form, setForm] = useState<IntegrationsConfig>(defaults)
  const [bankStatus, setBankStatus] = useState<BankIntegrationStatus | null>(null)
  const [signatureStatus, setSignatureStatus] = useState<SignatureIntegrationStatus | null>(null)
  const [readiness, setReadiness] = useState<IntegrationReadiness | null>(null)
  const [smtp, setSmtp] = useState<SmtpConfiguration>(smtpDefaults)
  const [smtpPassword, setSmtpPassword] = useState('')
  const [testRecipient, setTestRecipient] = useState('')
  const [loading, setLoading] = useState(authConfigured)
  const [saving, setSaving] = useState(false)
  const [testingBank, setTestingBank] = useState(false)
  const [testingSignature, setTestingSignature] = useState(false)
  const [savingSmtp, setSavingSmtp] = useState(false)
  const [testingSmtp, setTestingSmtp] = useState(false)
  const [auditing, setAuditing] = useState(false)
  const [auditItems, setAuditItems] = useState<IntegrationAuditItem[]>([])
  const [auditCheckedAt, setAuditCheckedAt] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (!authConfigured) return
    let active = true
    void Promise.all([
      apiRequest<IntegrationsConfig>('/settings/integrations'),
      apiRequest<BankIntegrationStatus>('/integrations/bank/status').catch(() => null),
      apiRequest<SignatureIntegrationStatus>('/integrations/signature/status').catch(() => null),
      apiRequest<IntegrationReadiness>('/integrations/readiness').catch(() => null),
      apiRequest<SmtpConfiguration>('/integrations/email/config').catch(() => smtpDefaults),
    ])
      .then(([data, bankStatusData, statusData, readinessData, smtpData]) => {
        if (!active) return
        setForm(data)
        setBankStatus(bankStatusData)
        setSignatureStatus(statusData)
        setReadiness(readinessData)
        setSmtp(smtpData)
        setTestRecipient(smtpData.from_email)
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
        setBankStatus(await apiRequest<BankIntegrationStatus>('/integrations/bank/status').catch(() => null))
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

  async function testBankConnection() {
    if (!canEdit || !authConfigured) return
    setTestingBank(true)
    setError('')
    setSuccess('')
    try {
      const result = await apiRequest<BankIntegrationStatus>('/integrations/bank/test', { method: 'POST' })
      setBankStatus(result)
      if (result.reachable) setSuccess(`${bankProviderLabel(form.bank_provider)}: ${result.message}`)
      else setError(result.message)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : `Não foi possível testar ${bankProviderLabel(form.bank_provider)}.`)
    } finally {
      setTestingBank(false)
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

  async function auditAllIntegrations() {
    if (!canEdit || !authConfigured) return
    setAuditing(true); setError(''); setSuccess('')
    const results: IntegrationAuditItem[] = []
    const add = (key:string,label:string,status:IntegrationAuditStatus,detail:string) => results.push({key,label,status,detail})
    const failure = (cause:unknown, fallback:string) => cause instanceof ApiError ? cause.detail : fallback

    add('auth','Neon Auth','ok','Sessão autenticada no ambiente atual; o proxy e a autenticação estão operacionais.')

    try {
      const storage = await apiRequest<DocumentStorageStatus>('/integrations/document-storage/test', { method:'POST' })
      add('storage','Storage de documentos',storage.reachable?'ok':'attention',storage.message)
    } catch (cause) { add('storage','Storage de documentos','attention',failure(cause,'Falha ao testar o storage.')) }

    if (form.bank_provider === 'none') add('bank','Banco / cobrança','disabled','Provider bancário desativado.')
    else {
      const bankLabel=bankProviderLabel(form.bank_provider)
      try {
        const bank = await apiRequest<BankIntegrationStatus>('/integrations/bank/test',{method:'POST'})
        setBankStatus(bank)
        add('bank',bankLabel,bank.reachable?'ok':'attention',bank.message)
      } catch (cause) { add('bank',bankLabel,'attention',failure(cause,`Falha ao testar ${bankLabel}.`)) }
    }

    if (form.signature_provider === 'none') add('signature','Clicksign','disabled','Assinatura eletrônica desativada.')
    else {
      try {
        const signature = await apiRequest<SignatureIntegrationStatus>('/integrations/signature/test',{method:'POST'})
        setSignatureStatus(signature)
        add('signature','Clicksign',signature.reachable?'ok':'attention',signature.message)
      } catch (cause) { add('signature','Clicksign','attention',failure(cause,'Falha ao testar a Clicksign.')) }
    }

    if (form.email_provider === 'none') add('smtp','SMTP','disabled','E-mail transacional desativado.')
    else {
      try {
        const smtpProbe = await apiRequest<{reachable:boolean;message:string}>('/integrations/email/connection-test',{method:'POST'})
        add('smtp','SMTP',smtpProbe.reachable?'ok':'attention',smtpProbe.message)
      } catch (cause) { add('smtp','SMTP','attention',failure(cause,'Falha ao autenticar no SMTP.')) }
    }

    try {
      const whats = await apiRequest<WhatsAppAuditConfig>('/meta-whatsapp/config')
      if (!whats.configured) add('whatsapp','WhatsApp Business','attention','Credenciais da Meta ainda não estão completas.')
      else {
        const [meta,subscription] = await Promise.all([
          apiRequest<{reachable:boolean;message:string}>('/meta-whatsapp/test',{method:'POST'}),
          apiRequest<{subscribed:boolean;message:string}>('/meta-whatsapp/subscription'),
        ])
        const webhookOk = whats.last_webhook_status === 'processed' && Boolean(whats.last_webhook_at)
        const ok = meta.reachable && subscription.subscribed && webhookOk
        add('whatsapp','WhatsApp Business',ok?'ok':'attention',
          `${meta.message} ${subscription.message}${webhookOk?' Webhook com evento processado.':' Webhook ainda sem confirmação recente.'}`)
      }
    } catch (cause) { add('whatsapp','WhatsApp Business','attention',failure(cause,'Falha ao validar a integração com a Meta.')) }

    try {
      const instagram = await apiRequest<{configured:boolean;username:string}>('/meta-instagram/config')
      if (!instagram.configured) add('instagram','Instagram','attention','Token da conta profissional ainda não foi configurado.')
      else {
        const meta = await apiRequest<{reachable:boolean;message:string;username:string}>('/meta-instagram/test',{method:'POST'})
        add('instagram','Instagram',meta.reachable?'ok':'attention',meta.message)
      }
    } catch (cause) { add('instagram','Instagram','attention',failure(cause,'Falha ao validar a integração do Instagram.')) }

    try {
      const portals = await apiRequest<PortalAuditConfig>('/integrations/portals')
      for (const channel of portals.channels) {
        try {
          const validated = await apiRequest<PortalValidationResult>(`/integrations/portals/${channel.key}/validate`,{method:'POST'})
          const technical = validated.validation.valid
          const externalActive = channel.status === 'active'
          add(`portal-${channel.key}`,channel.label,technical&&externalActive?'ok':'attention',
            technical
              ? `${validated.validation.selected_count} imóvel(is) tecnicamente válido(s). ${externalActive?'Portal marcado como homologado externamente.':'Feed pronto; homologação externa ainda não está marcada como ativa.'}`
              : `Feed com pendências: ${validated.validation.invalid_count} imóvel(is) inválido(s) ou XML inconsistente.`)
        } catch (cause) { add(`portal-${channel.key}`,channel.label,'attention',failure(cause,'Falha ao validar o feed XML.')) }
      }
    } catch (cause) { add('portals','Portais imobiliários','attention',failure(cause,'Falha ao carregar os canais imobiliários.')) }

    setAuditItems(results)
    setAuditCheckedAt(new Date().toISOString())
    const pending = results.filter(item=>item.status==='attention').length
    setSuccess(pending===0?'Validação completa: todas as integrações ativas responderam corretamente.':`Validação concluída com ${pending} ponto(s) que ainda exigem atenção.`)
    setAuditing(false)
  }

  async function saveSmtp() {
    if (!canEdit || !authConfigured) return
    setSavingSmtp(true); setError(''); setSuccess('')
    try {
      const updated = await apiRequest<SmtpConfiguration>('/integrations/email/config', {
        method: 'PUT',
        body: JSON.stringify({ ...smtp, password: smtpPassword || null, source: undefined, password_configured: undefined }),
      })
      setSmtp(updated); setSmtpPassword(''); setTestRecipient((current) => current || updated.from_email)
      setReadiness(await apiRequest<IntegrationReadiness>('/integrations/readiness').catch(() => null))
      setSuccess('Configuração SMTP salva com senha protegida e auditoria registrada.')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar a configuração SMTP.')
    } finally { setSavingSmtp(false) }
  }

  async function testSmtpConnection() {
    if (!canEdit || !authConfigured) return
    setTestingSmtp(true); setError(''); setSuccess('')
    try {
      const result = await apiRequest<{message:string;recipient:string}>('/integrations/email/test', { method: 'POST', body: JSON.stringify({ recipient: testRecipient || null }) })
      setSuccess(`${result.message} Destinatário: ${result.recipient}.`)
      setReadiness(await apiRequest<IntegrationReadiness>('/integrations/readiness').catch(() => null))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível enviar o e-mail de teste.')
    } finally { setTestingSmtp(false) }
  }

  if (loading) return <section className="workspace settings-workspace"><article className="panel settings-loading">Carregando integrações...</article></section>

  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Conectividade</span>
          <h1>Integrações</h1>
          <p>Escolha os provedores, valide conexões reais e acompanhe o estado técnico de cada serviço externo.</p>
        </div>
        <button className="button primary" type="button" disabled={!canEdit||auditing} onClick={()=>void auditAllIntegrations()}><Activity size={15}/>{auditing?'Verificando tudo...':'Verificar todas'}</button>
      </div>

      {error && <div className="form-alert danger-alert">{error}</div>}
      {success && <div className="form-alert success-alert">{success}</div>}

      {auditItems.length>0&&<article className="panel integrations-audit-panel">
        <div className="panel-heading panel-heading-row"><div><span className="eyebrow">Diagnóstico ao vivo</span><h2>Validação consolidada</h2><p>{auditCheckedAt?`Executada em ${new Date(auditCheckedAt).toLocaleString('pt-BR')}.`:'Resultados da última validação.'}</p></div><Activity size={19}/></div>
        <div className="integrations-audit-grid">{auditItems.map(item=><div className={'integrations-audit-row '+item.status} key={item.key}>
          <span className="integrations-audit-icon">{item.key==='storage'?<Database size={15}/>:item.key==='whatsapp'?<MessageCircle size={15}/>:item.key==='instagram'?<MessageCircle size={15}/>:item.key.startsWith('portal-')?<RadioTower size={15}/>:item.status==='ok'?<CheckCircle2 size={15}/>:<CircleAlert size={15}/>}</span>
          <div><strong>{item.label}</strong><span>{item.detail}</span></div>
          <i className={'status-badge '+(item.status==='ok'?'success':item.status==='disabled'?'neutral':'warning')}>{item.status==='ok'?'Validado':item.status==='disabled'?'Desativado':'Atenção'}</i>
        </div>)}</div>
        <small className="smtp-security-note">A validação não envia Pix, não cria contratos e não publica anúncios. Bancos usam somente probes não transacionais; no SMTP ela autentica sem enviar e-mail; nos portais valida o XML sem alterar a homologação externa.</small>
      </article>}

      <form onSubmit={save} className="settings-layout integrations-layout">
        <div className="settings-column">
          <article className="panel integration-card integration-card-expanded">
            <div className="integration-icon"><Banknote size={19} /></div>
            <div className="integration-content"><strong>Banco / Cobrança</strong><span>Provider financeiro principal</span></div>
            <select disabled={!canEdit} value={form.bank_provider} onChange={(e) => { setBankStatus(null); setForm((current) => ({ ...current, bank_provider: e.target.value as IntegrationsConfig['bank_provider'] })) }}><option value="inter">Banco Inter Empresas</option><option value="itau">Itaú Empresas · Sandbox</option><option value="sicredi">Sicredi · Sandbox</option><option value="none">Nenhum</option></select>
            {form.bank_provider !== 'none' ? connectionBadge(bankStatus) : providerStatus(false)}
            {form.bank_provider !== 'none' && (
              <div className="integration-health">
                <div className="integration-health-copy">
                  {bankStatus?.reachable ? <CheckCircle2 size={16}/> : <CircleAlert size={16}/>}
                  <div><strong>{bankStatus ? `${bankProviderLabel(form.bank_provider)} · ${bankStatus.environment}` : bankProviderLabel(form.bank_provider)}</strong><span>{bankStatus?.message ?? (form.bank_provider==='itau'?'Sandbox pronto para teste de gateway; a autenticação da API depende da aplicação criada no portal Itaú.':form.bank_provider==='sicredi'?'Para autenticar no Sandbox, configure Client ID, Secret, certificado mTLS e o escopo liberado pela cooperativa.':'Consulte o status para saber se as credenciais e o certificado estão disponíveis.')}</span></div>
                </div>
                <button className="button secondary compact-button" disabled={!canEdit || testingBank} type="button" onClick={() => void testBankConnection()}><RefreshCw size={14}/>{testingBank ? 'Testando...' : 'Testar conexão'}</button>
              </div>
            )}
          </article>

          <article className="panel integration-card integration-card-expanded">
            <div className="integration-icon"><FileSignature size={19} /></div>
            <div className="integration-content"><strong>Assinatura eletrônica</strong><span>Contratos e documentos assináveis</span></div>
            <select disabled={!canEdit} value={form.signature_provider} onChange={(e) => setForm((current) => ({ ...current, signature_provider: e.target.value as IntegrationsConfig['signature_provider'] }))}><option value="clicksign">Clicksign</option><option value="none">Nenhum</option></select>
            {form.signature_provider === 'clicksign' ? connectionBadge(signatureStatus) : providerStatus(false)}
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

          <article className="panel integration-card integration-card-expanded smtp-integration-card">
            <div className="integration-icon"><Mail size={19} /></div>
            <div className="integration-content"><strong>E-mail transacional</strong><span>Comunicações operacionais do ERP</span></div>
            <select disabled={!canEdit} value={form.email_provider} onChange={(e) => setForm((current) => ({ ...current, email_provider: e.target.value as IntegrationsConfig['email_provider'] }))}><option value="smtp">SMTP</option><option value="none">Nenhum</option></select>
            {form.email_provider === 'smtp' ? connectionBadge({ provider: 'smtp', environment: 'smtp', configured: smtp.host !== '' && smtp.from_email !== '' && (!smtp.username || smtp.password_configured), reachable: null, message: '', checked_at: '' }) : providerStatus(false)}
            {form.email_provider === 'smtp' && <div className="smtp-config-panel">
              <div className="form-grid smtp-config-grid">
                <label className="field"><span>Servidor SMTP</span><input disabled={!canEdit} placeholder="smtp.exemplo.com" value={smtp.host} onChange={(e) => setSmtp((current) => ({...current, host:e.target.value}))}/></label>
                <label className="field"><span>Porta</span><input disabled={!canEdit} type="number" min={1} max={65535} value={smtp.port} onChange={(e) => setSmtp((current) => ({...current, port:Number(e.target.value)}))}/></label>
                <label className="field"><span>Usuário</span><input disabled={!canEdit} autoComplete="username" value={smtp.username} onChange={(e) => setSmtp((current) => ({...current, username:e.target.value}))}/></label>
                <label className="field"><span>Senha {smtp.password_configured ? '· cadastrada' : ''}</span><input disabled={!canEdit} type="password" autoComplete="new-password" placeholder={smtp.password_configured ? 'Deixe vazio para manter' : 'Senha ou senha de aplicativo'} value={smtpPassword} onChange={(e) => setSmtpPassword(e.target.value)}/></label>
                <label className="field"><span>E-mail remetente</span><input disabled={!canEdit} type="email" value={smtp.from_email} onChange={(e) => setSmtp((current) => ({...current, from_email:e.target.value}))}/></label>
                <label className="field"><span>Nome do remetente</span><input disabled={!canEdit} placeholder="Imobiliária" value={smtp.from_name} onChange={(e) => setSmtp((current) => ({...current, from_name:e.target.value}))}/></label>
              </div>
              <div className="smtp-security-options">
                <label className="field checkbox-field"><input disabled={!canEdit} type="checkbox" checked={smtp.use_tls} onChange={(e) => setSmtp((current) => ({...current, use_tls:e.target.checked, use_ssl:e.target.checked ? false : current.use_ssl}))}/><span>TLS / STARTTLS</span></label>
                <label className="field checkbox-field"><input disabled={!canEdit} type="checkbox" checked={smtp.use_ssl} onChange={(e) => setSmtp((current) => ({...current, use_ssl:e.target.checked, use_tls:e.target.checked ? false : current.use_tls}))}/><span>SSL direto</span></label>
              </div>
              <div className="smtp-test-row">
                <label className="field"><span>Destinatário do teste</span><input disabled={!canEdit} type="email" placeholder="voce@exemplo.com" value={testRecipient} onChange={(e) => setTestRecipient(e.target.value)}/></label>
                <button className="button secondary compact-button" disabled={!canEdit || testingSmtp || !smtp.password_configured} type="button" onClick={() => void testSmtpConnection()}><RefreshCw size={14}/>{testingSmtp ? 'Enviando...' : 'Enviar teste'}</button>
                <button className="button primary compact-button" disabled={!canEdit || savingSmtp || !smtp.host || !smtp.from_email} type="button" onClick={() => void saveSmtp()}><Save size={14}/>{savingSmtp ? 'Salvando...' : 'Salvar SMTP'}</button>
              </div>
              <small className="smtp-security-note">A senha é criptografada antes de ser armazenada e nunca é exibida novamente.</small>
            </div>}
          </article>

          <WhatsAppIntegrationSettingsPanel canEdit={canEdit} />

          <InstagramIntegrationSettingsPanel canEdit={canEdit} />

          <PortalIntegrationsSettingsPanel canEdit={canEdit} />

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
