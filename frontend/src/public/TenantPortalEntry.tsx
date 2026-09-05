import { CheckCircle2, KeyRound, ShieldCheck, XCircle } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, publicApiRequest, TENANT_PORTAL_AUTH_EVENT } from '../api/client'
import { TenantPortalPage } from './TenantPortalPage'
import './tenant-portal.css'
import './tenant-portal-auth.css'

type AuthState = 'checking' | 'anonymous' | 'changing' | 'authenticated'

type LoginResponse = {
  person_name: string
  login_identifier: string | null
  must_change_password: boolean
  change_token?: string
  change_token_expires_in_seconds?: number
}

function messageFrom(cause: unknown, fallback: string) {
  return cause instanceof ApiError ? cause.detail : fallback
}

export function TenantPortalEntry() {
  const [authState, setAuthState] = useState<AuthState>('checking')
  const [identifier, setIdentifier] = useState('')
  const [changeToken, setChangeToken] = useState('')
  const [personName, setPersonName] = useState('')

  useEffect(() => {
    let active = true
    const requireAuth = () => {
      if (!active) return
      setAuthState('anonymous')
      setChangeToken('')
    }
    window.addEventListener(TENANT_PORTAL_AUTH_EVENT, requireAuth)
    void publicApiRequest('/tenant-portal/me')
      .then(() => { if (active) setAuthState('authenticated') })
      .catch(() => { if (active) setAuthState('anonymous') })
    return () => {
      active = false
      window.removeEventListener(TENANT_PORTAL_AUTH_EVENT, requireAuth)
    }
  }, [])

  if (authState === 'checking') {
    return <main className="tenant-login-shell"><div className="tenant-loading"><div className="tenant-brand-mark">IM</div><strong>Preparando seu portal...</strong></div></main>
  }
  if (authState === 'authenticated') return <TenantPortalPage />
  if (authState === 'changing') {
    return <TenantPasswordChange identifier={identifier} changeToken={changeToken} personName={personName} onChanged={() => setAuthState('authenticated')} onBack={() => { setChangeToken(''); setAuthState('anonymous') }}/>
  }
  return <TenantPortalAuth onAuthenticated={() => setAuthState('authenticated')} onTemporaryLogin={(nextIdentifier, token, name) => { setIdentifier(nextIdentifier); setChangeToken(token); setPersonName(name); setAuthState('changing') }}/>
}

function TenantPortalAuth({ onAuthenticated, onTemporaryLogin }: { onAuthenticated: () => void; onTemporaryLogin: (identifier: string, token: string, personName: string) => void }) {
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function login(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const result = await publicApiRequest<LoginResponse>('/tenant-portal/auth/document-login', {
        method: 'POST',
        body: JSON.stringify({ identifier, password }),
      })
      if (result.must_change_password && result.change_token) {
        onTemporaryLogin(identifier, result.change_token, result.person_name)
      } else {
        onAuthenticated()
      }
    } catch (cause) {
      setError(messageFrom(cause, 'Não foi possível entrar no portal.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="tenant-login-shell">
      <section className="tenant-login-card tenant-auth-card">
        <div className="tenant-login-brand">
          <div className="tenant-brand-mark">IM</div>
          <div><strong>Portal do Inquilino</strong><span>Acesso seguro à sua locação</span></div>
        </div>

        <div className="tenant-login-copy">
          <span className="tenant-eyebrow">Bem-vindo</span>
          <h1>Sua locação em um só lugar.</h1>
          <p>Consulte contrato, pagamentos, documentos, vistorias e acompanhe chamados de manutenção.</p>
        </div>

        {error && <div className="tenant-alert danger"><XCircle size={16}/><span>{error}</span></div>}

        <form onSubmit={login}>
          <label>
            <span>CPF ou CNPJ</span>
            <input value={identifier} onChange={event => setIdentifier(event.target.value)} autoComplete="username" inputMode="numeric" required placeholder="Digite seu CPF ou CNPJ"/>
          </label>
          <label>
            <span>Senha</span>
            <input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" minLength={8} maxLength={200} required placeholder="Sua senha"/>
          </label>
          <button className="tenant-primary" disabled={saving}>{saving ? 'Entrando...' : 'Entrar no portal'}</button>
        </form>

        <div className="tenant-alert neutral tenant-auth-guidance">
          <KeyRound size={16}/>
          <span><strong>Primeiro acesso?</strong> Use a senha temporária fornecida pela imobiliária. Você criará sua senha pessoal antes de entrar.</span>
        </div>
        <small>Esqueceu sua senha? Solicite uma nova senha temporária à imobiliária.</small>
      </section>
    </main>
  )
}

function TenantPasswordChange({ identifier, changeToken, personName, onChanged, onBack }: { identifier: string; changeToken: string; personName: string; onChanged: () => void; onBack: () => void }) {
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (newPassword !== confirmPassword) {
      setError('As senhas informadas não coincidem.')
      return
    }
    setSaving(true)
    try {
      await publicApiRequest('/tenant-portal/auth/temporary-change', {
        method: 'POST',
        body: JSON.stringify({ identifier, change_token: changeToken, password: newPassword }),
      })
      onChanged()
    } catch (cause) {
      setError(messageFrom(cause, 'Não foi possível criar sua senha pessoal.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="tenant-login-shell">
      <section className="tenant-login-card tenant-auth-card">
        <div className="tenant-login-brand">
          <div className="tenant-brand-mark">IM</div>
          <div><strong>Portal do Inquilino</strong><span>Acesso seguro à sua locação</span></div>
        </div>

        <div className="tenant-login-copy">
          <span className="tenant-eyebrow">Primeiro acesso</span>
          <h1>Crie sua senha pessoal.</h1>
          <p>{personName ? `${personName}, ` : ''}a senha temporária foi aceita. Escolha agora a senha que você usará nos próximos acessos.</p>
        </div>

        <div className="tenant-alert success"><CheckCircle2 size={16}/><span>Senha temporária validada com segurança.</span></div>
        {error && <div className="tenant-alert danger"><XCircle size={16}/><span>{error}</span></div>}

        <form onSubmit={submit}>
          <label>
            <span>Nova senha</span>
            <input type="password" value={newPassword} onChange={event => setNewPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={200} required placeholder="Mínimo de 8 caracteres"/>
          </label>
          <label>
            <span>Confirmar nova senha</span>
            <input type="password" value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={200} required placeholder="Repita sua nova senha"/>
          </label>
          <button className="tenant-primary" disabled={saving || newPassword.length < 8}>{saving ? 'Salvando...' : 'Criar minha senha'}</button>
        </form>

        <div className="tenant-alert neutral tenant-auth-guidance"><ShieldCheck size={16}/><span>A senha temporária deixará de funcionar assim que sua senha pessoal for criada.</span></div>
        <button type="button" className="tenant-auth-back" disabled={saving} onClick={onBack}>Voltar para entrar</button>
      </section>
    </main>
  )
}
