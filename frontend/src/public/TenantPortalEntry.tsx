import { ArrowLeft, CheckCircle2, KeyRound, Mail, XCircle } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, publicApiRequest } from '../api/client'
import { TenantPortalPage } from './TenantPortalPage'
import './tenant-portal.css'
import './tenant-portal-auth.css'

type AuthMode = 'login' | 'request' | 'confirm'
type AccessPurpose = 'first_access' | 'forgot_password'
type AuthState = 'checking' | 'anonymous' | 'authenticated'

type AccessRequestResponse = {
  message: string
  expires_in_seconds: number
  resend_after_seconds: number
}

function messageFrom(cause: unknown, fallback: string) {
  return cause instanceof ApiError ? cause.detail : fallback
}

export function TenantPortalEntry() {
  const [authState, setAuthState] = useState<AuthState>('checking')

  useEffect(() => {
    let active = true
    void publicApiRequest('/tenant-portal/me')
      .then(() => { if (active) setAuthState('authenticated') })
      .catch(() => { if (active) setAuthState('anonymous') })
    return () => { active = false }
  }, [])

  if (authState === 'checking') {
    return <main className="tenant-login-shell"><div className="tenant-loading"><div className="tenant-brand-mark">IM</div><strong>Preparando seu portal...</strong></div></main>
  }
  if (authState === 'authenticated') return <TenantPortalPage />
  return <TenantPortalAuth onAuthenticated={() => setAuthState('authenticated')} />
}

function TenantPortalAuth({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [mode, setMode] = useState<AuthMode>('login')
  const [purpose, setPurpose] = useState<AccessPurpose>('first_access')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [saving, setSaving] = useState(false)

  function resetMessages() {
    setError('')
    setSuccess('')
  }

  function beginAccess(nextPurpose: AccessPurpose) {
    setPurpose(nextPurpose)
    setMode('request')
    setCode('')
    setNewPassword('')
    setConfirmPassword('')
    resetMessages()
  }

  function backToLogin() {
    setMode('login')
    setPassword('')
    setCode('')
    setNewPassword('')
    setConfirmPassword('')
    resetMessages()
  }

  async function login(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    resetMessages()
    try {
      await publicApiRequest('/tenant-portal/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      onAuthenticated()
    } catch (cause) {
      setError(messageFrom(cause, 'Não foi possível entrar no portal.'))
    } finally {
      setSaving(false)
    }
  }

  async function requestCode(event?: FormEvent) {
    event?.preventDefault()
    setSaving(true)
    resetMessages()
    try {
      const result = await publicApiRequest<AccessRequestResponse>('/tenant-portal/auth/access/request', {
        method: 'POST',
        body: JSON.stringify({ email, purpose }),
      })
      setMode('confirm')
      setSuccess(`${result.message} O código vale por 10 minutos.`)
    } catch (cause) {
      setError(messageFrom(cause, 'Não foi possível enviar o código de acesso.'))
    } finally {
      setSaving(false)
    }
  }

  async function confirmAccess(event: FormEvent) {
    event.preventDefault()
    resetMessages()
    if (newPassword !== confirmPassword) {
      setError('As senhas informadas não coincidem.')
      return
    }
    setSaving(true)
    try {
      await publicApiRequest('/tenant-portal/auth/access/confirm', {
        method: 'POST',
        body: JSON.stringify({ email, code, password: newPassword }),
      })
      setMode('login')
      setPassword('')
      setCode('')
      setNewPassword('')
      setConfirmPassword('')
      setSuccess(
        purpose === 'first_access'
          ? 'Senha criada com sucesso. Agora entre no portal.'
          : 'Senha redefinida com sucesso. Agora entre no portal.',
      )
    } catch (cause) {
      setError(messageFrom(cause, 'Não foi possível concluir a criação da senha.'))
    } finally {
      setSaving(false)
    }
  }

  const title = mode === 'login'
    ? 'Sua locação em um só lugar.'
    : purpose === 'first_access'
      ? 'Crie seu acesso.'
      : 'Recupere seu acesso.'

  const description = mode === 'login'
    ? 'Consulte contrato, pagamentos, documentos, vistorias e acompanhe chamados de manutenção.'
    : mode === 'request'
      ? 'Informe o mesmo e-mail cadastrado no seu contrato. Enviaremos um código de confirmação.'
      : `Digite o código enviado para ${email} e escolha sua nova senha.`

  return (
    <main className="tenant-login-shell">
      <section className="tenant-login-card tenant-auth-card">
        <div className="tenant-login-brand">
          <div className="tenant-brand-mark">IM</div>
          <div><strong>Portal do Inquilino</strong><span>Acesso seguro à sua locação</span></div>
        </div>

        <div className="tenant-login-copy">
          <span className="tenant-eyebrow">
            {mode === 'login' ? 'Bem-vindo' : purpose === 'first_access' ? 'Primeiro acesso' : 'Esqueci minha senha'}
          </span>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>

        {error && <div className="tenant-alert danger"><XCircle size={16}/><span>{error}</span></div>}
        {success && <div className="tenant-alert success"><CheckCircle2 size={16}/><span>{success}</span></div>}

        {mode === 'login' && (
          <form onSubmit={login}>
            <label>
              <span>E-mail</span>
              <input type="email" value={email} onChange={event => setEmail(event.target.value)} autoComplete="email" required placeholder="voce@email.com"/>
            </label>
            <label>
              <span>Senha</span>
              <input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" minLength={8} required placeholder="Sua senha"/>
            </label>
            <button className="tenant-primary" disabled={saving}>{saving ? 'Entrando...' : 'Entrar no portal'}</button>
            <div className="tenant-auth-actions">
              <button type="button" className="tenant-auth-link" onClick={() => beginAccess('forgot_password')}>Esqueci minha senha</button>
              <button type="button" className="tenant-auth-link strong" onClick={() => beginAccess('first_access')}>Primeiro acesso</button>
            </div>
          </form>
        )}

        {mode === 'request' && (
          <form onSubmit={event => void requestCode(event)}>
            <label>
              <span>E-mail cadastrado</span>
              <div className="tenant-auth-input-icon"><Mail size={16}/><input type="email" value={email} onChange={event => setEmail(event.target.value)} autoComplete="email" required placeholder="voce@email.com"/></div>
            </label>
            <button className="tenant-primary" disabled={saving}>{saving ? 'Enviando...' : 'Enviar código'}</button>
            <button type="button" className="tenant-auth-back" onClick={backToLogin}><ArrowLeft size={14}/> Voltar para entrar</button>
          </form>
        )}

        {mode === 'confirm' && (
          <form onSubmit={confirmAccess}>
            <label>
              <span>Código de 6 dígitos</span>
              <div className="tenant-auth-input-icon"><KeyRound size={16}/><input className="tenant-code-input" value={code} onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" minLength={6} maxLength={6} required placeholder="000000"/></div>
            </label>
            <label>
              <span>Nova senha</span>
              <input type="password" value={newPassword} onChange={event => setNewPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={200} required placeholder="Mínimo de 8 caracteres"/>
            </label>
            <label>
              <span>Confirmar nova senha</span>
              <input type="password" value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={200} required placeholder="Repita a nova senha"/>
            </label>
            <button className="tenant-primary" disabled={saving || code.length !== 6 || newPassword.length < 8}>{saving ? 'Salvando...' : purpose === 'first_access' ? 'Criar minha senha' : 'Redefinir minha senha'}</button>
            <div className="tenant-auth-actions">
              <button type="button" className="tenant-auth-link" disabled={saving} onClick={() => void requestCode()}>Reenviar código</button>
              <button type="button" className="tenant-auth-link" disabled={saving} onClick={backToLogin}>Voltar para entrar</button>
            </div>
          </form>
        )}

        <small>
          {mode === 'login'
            ? 'Use o e-mail cadastrado no seu contrato. No primeiro acesso, você mesmo cria sua senha.'
            : 'Por segurança, não informamos se um e-mail está ou não cadastrado no sistema.'}
        </small>
      </section>
    </main>
  )
}
