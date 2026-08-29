import { Eye, EyeOff, LockKeyhole, Mail, UserRound } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { publicApiRequest } from '../api/client'
import { authClient, authConfigured } from './client'

type LoginPageProps = {
  onAuthenticated: () => void
}

type AccessMode = 'login' | 'bootstrap'

type BootstrapStatus = {
  bootstrap_open: boolean
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [mode, setMode] = useState<AccessMode>('login')
  const [bootstrapOpen, setBootstrapOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirmation, setPasswordConfirmation] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    publicApiRequest<BootstrapStatus>('/bootstrap/status')
      .then((result) => setBootstrapOpen(result.bootstrap_open))
      .catch(() => setBootstrapOpen(false))
  }, [])

  function switchMode(nextMode: AccessMode) {
    setMode(nextMode)
    setError('')
    setPassword('')
    setPasswordConfirmation('')
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')

    if (!authConfigured || !authClient) {
      setError('Neon Auth ainda não foi provisionado neste ambiente.')
      return
    }

    if (mode === 'bootstrap') {
      if (!bootstrapOpen) {
        setError('O primeiro acesso já foi concluído neste ambiente.')
        return
      }
      if (name.trim().length < 2) {
        setError('Informe seu nome.')
        return
      }
      if (password.length < 12) {
        setError('Para o Administrador inicial, use uma senha com pelo menos 12 caracteres.')
        return
      }
      if (password !== passwordConfirmation) {
        setError('As senhas não conferem.')
        return
      }

      setLoading(true)
      const result = await authClient.signUp.email({
        name: name.trim(),
        email: email.trim().toLowerCase(),
        password,
      })
      setLoading(false)

      if (result.error) {
        setError(result.error.message || 'Não foi possível concluir o primeiro acesso.')
        return
      }

      onAuthenticated()
      return
    }

    setLoading(true)
    const result = await authClient.signIn.email({ email: email.trim().toLowerCase(), password })
    setLoading(false)

    if (result.error) {
      setError('Não foi possível entrar. Confira e-mail e senha.')
      return
    }

    onAuthenticated()
  }

  const isBootstrap = mode === 'bootstrap'

  return (
    <main className="login-page">
      <section className="login-brand-panel">
        <div className="login-brand-content">
          <div className="brand-mark login-logo">I</div>
          <span className="eyebrow login-eyebrow">ERP Imobiliário</span>
          <h1>Gestão profissional, sem complicação.</h1>
          <p>Imóveis, contratos, financeiro e operação integrados em uma única base auditável.</p>
          <div className="login-brand-lines" aria-hidden="true"><span /><span /><span /></div>
        </div>
      </section>

      <section className="login-form-panel">
        <form className="login-card" onSubmit={handleSubmit}>
          <div className="login-card-heading">
            <span className="eyebrow">{isBootstrap ? 'Configuração inicial' : 'Acesso restrito'}</span>
            <h2>{isBootstrap ? 'Criar Administrador' : 'Entrar no Imob'}</h2>
            <p>
              {isBootstrap
                ? 'Este cadastro existe apenas para inicializar o primeiro Administrador do ERP.'
                : 'Use o e-mail e a senha cadastrados pelo Administrador.'}
            </p>
          </div>

          {isBootstrap && (
            <label className="field login-field">
              <span>Nome</span>
              <div className="input-with-icon">
                <UserRound size={17} />
                <input
                  autoComplete="name"
                  placeholder="Seu nome"
                  required
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
            </label>
          )}

          <label className="field login-field">
            <span>E-mail</span>
            <div className="input-with-icon">
              <Mail size={17} />
              <input
                autoComplete="email"
                inputMode="email"
                placeholder="nome@empresa.com.br"
                required
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
          </label>

          <label className="field login-field">
            <span>Senha</span>
            <div className="input-with-icon">
              <LockKeyhole size={17} />
              <input
                autoComplete={isBootstrap ? 'new-password' : 'current-password'}
                minLength={isBootstrap ? 12 : undefined}
                placeholder={isBootstrap ? 'Crie uma senha segura' : 'Sua senha'}
                required
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button className="password-toggle" type="button" onClick={() => setShowPassword((value) => !value)} aria-label="Mostrar ou ocultar senha">
                {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
          </label>

          {isBootstrap && (
            <label className="field login-field">
              <span>Confirmar senha</span>
              <div className="input-with-icon">
                <LockKeyhole size={17} />
                <input
                  autoComplete="new-password"
                  minLength={12}
                  placeholder="Repita a senha"
                  required
                  type={showPassword ? 'text' : 'password'}
                  value={passwordConfirmation}
                  onChange={(event) => setPasswordConfirmation(event.target.value)}
                />
              </div>
            </label>
          )}

          {error && <div className="form-alert danger-alert">{error}</div>}

          <button className="button primary login-submit" disabled={loading} type="submit">
            {loading ? (isBootstrap ? 'Criando acesso...' : 'Entrando...') : (isBootstrap ? 'Criar Administrador' : 'Entrar')}
          </button>

          {bootstrapOpen && (
            <button className="text-button" type="button" onClick={() => switchMode(isBootstrap ? 'login' : 'bootstrap')}>
              {isBootstrap ? 'Já tenho acesso' : 'Configurar primeiro acesso'}
            </button>
          )}

          <small className="login-security-note">
            {bootstrapOpen
              ? 'Após a criação do primeiro Administrador, esta opção é encerrada automaticamente.'
              : 'Não existe cadastro público no ERP. Novos usuários são liberados internamente pelo Administrador.'}
          </small>
        </form>
      </section>
    </main>
  )
}
