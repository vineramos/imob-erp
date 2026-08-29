import { Eye, EyeOff, LockKeyhole, Mail } from 'lucide-react'
import { FormEvent, useState } from 'react'
import { authClient, authConfigured } from './client'

type LoginPageProps = {
  onAuthenticated: () => void
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')

    if (!authConfigured || !authClient) {
      setError('Neon Auth ainda não foi provisionado neste ambiente.')
      return
    }

    setLoading(true)
    const result = await authClient.signIn.email({ email, password })
    setLoading(false)

    if (result.error) {
      setError('Não foi possível entrar. Confira e-mail e senha.')
      return
    }

    onAuthenticated()
  }

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
            <span className="eyebrow">Acesso restrito</span>
            <h2>Entrar no Imob</h2>
            <p>Use o e-mail e a senha cadastrados pelo Administrador.</p>
          </div>

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
                autoComplete="current-password"
                placeholder="Sua senha"
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

          {error && <div className="form-alert danger-alert">{error}</div>}

          <button className="button primary login-submit" disabled={loading} type="submit">
            {loading ? 'Entrando...' : 'Entrar'}
          </button>

          <button className="text-button" type="button">Esqueci minha senha</button>

          <small className="login-security-note">Não existe cadastro público. Novos usuários são criados internamente pelo Administrador.</small>
        </form>
      </section>
    </main>
  )
}
