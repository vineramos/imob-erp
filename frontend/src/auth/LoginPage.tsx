import { Eye, EyeOff, LockKeyhole, Mail, ShieldCheck, UserRound } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { publicApiRequest } from '../api/client'
import { useTheme } from '../theme/ThemeProvider'
import { authClient, authConfigured } from './client'

type LoginPageProps = {
  onAuthenticated: () => void
}

type AccessMode = 'login' | 'bootstrap' | 'forgot' | 'reset' | 'invite'

type BootstrapStatus = {
  bootstrap_open: boolean
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const { theme } = useTheme()
  const [mode, setMode] = useState<AccessMode>('login')
  const [bootstrapOpen, setBootstrapOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirmation, setPasswordConfirmation] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [inviteToken, setInviteToken] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    publicApiRequest<BootstrapStatus>('/bootstrap/status')
      .then((result) => setBootstrapOpen(result.bootstrap_open))
      .catch(() => setBootstrapOpen(false))

    const params = new URLSearchParams(window.location.search)
    const token = params.get('token') || ''
    const invitation = params.get('invite') || ''
    const resetError = params.get('error')

    if (invitation) {
      setInviteToken(invitation)
      setMode('invite')
      setLoading(true)
      authClient?.invitation(invitation)
        .then((result) => {
          if (result.error || !result.data) { setError(result.error?.message || 'Este convite é inválido ou expirou.'); return }
          setName(result.data.name)
          setEmail(result.data.email)
        })
        .catch(() => setError('Não foi possível validar este convite agora.'))
        .finally(() => setLoading(false))
    } else if (token) {
      setResetToken(token)
      setMode('reset')
    } else if (resetError) {
      setError('Este link de recuperação é inválido ou expirou. Solicite um novo link.')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  function switchMode(nextMode: AccessMode) {
    setMode(nextMode)
    setError('')
    setSuccess('')
    setPassword('')
    setPasswordConfirmation('')
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSuccess('')

    if (!authConfigured || !authClient) {
      setError('Neon Auth ainda não foi provisionado neste ambiente.')
      return
    }

    if (mode === 'forgot') {
      setLoading(true)
      try {
        const result = await authClient.requestPasswordReset({
          email: email.trim().toLowerCase(),
          redirectTo: `${window.location.origin}/`,
        })
        if (result.error) {
          setError('Não foi possível solicitar a recuperação agora. Tente novamente em alguns instantes.')
          return
        }
        setSuccess('Se houver uma conta cadastrada com este e-mail, enviaremos um link para redefinir a senha. Confira também a pasta de spam.')
      } catch {
        setError('Não foi possível solicitar a recuperação agora. Tente novamente em alguns instantes.')
      } finally {
        setLoading(false)
      }
      return
    }

    if (mode === 'reset') {
      if (!resetToken) {
        setError('Este link de recuperação é inválido ou expirou. Solicite um novo link.')
        return
      }
      if (password.length < 12) {
        setError('Use uma senha com pelo menos 12 caracteres.')
        return
      }
      if (password !== passwordConfirmation) {
        setError('As senhas não conferem.')
        return
      }

      setLoading(true)
      try {
        const result = await authClient.resetPassword({
          newPassword: password,
          token: resetToken,
        })
        if (result.error) {
          setError('Não foi possível redefinir a senha. O link pode ter expirado; solicite um novo.')
          return
        }
        window.history.replaceState({}, '', window.location.pathname)
        setResetToken('')
        setMode('login')
        setPassword('')
        setPasswordConfirmation('')
        setSuccess('Senha redefinida com sucesso. Agora você já pode entrar com a nova senha.')
      } catch {
        setError('Não foi possível redefinir a senha. O link pode ter expirado; solicite um novo.')
      } finally {
        setLoading(false)
      }
      return
    }

    if (mode === 'invite') {
      if (!inviteToken) { setError('Este convite é inválido ou expirou.'); return }
      if (password.length < 12) { setError('Use uma senha com pelo menos 12 caracteres.'); return }
      if (password !== passwordConfirmation) { setError('As senhas não conferem.'); return }
      setLoading(true)
      try {
        const result = await authClient.acceptInvitation({ token: inviteToken, password })
        if (result.error) { setError(result.error.message || 'Não foi possível ativar o convite.'); return }
        window.history.replaceState({}, '', window.location.pathname)
        onAuthenticated()
      } catch {
        setError('Não foi possível ativar o convite agora. Tente novamente em alguns instantes.')
      } finally { setLoading(false) }
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
      try {
        const result = await authClient.signUp.email({
          name: name.trim(),
          email: email.trim().toLowerCase(),
          password,
        })
        if (result.error) {
          setError(result.error.message || 'Não foi possível concluir o primeiro acesso.')
          return
        }
        onAuthenticated()
      } finally {
        setLoading(false)
      }
      return
    }

    setLoading(true)
    try {
      const result = await authClient.signIn.email({ email: email.trim().toLowerCase(), password })
      if (result.error) {
        setError('Não foi possível entrar. Confira e-mail e senha.')
        return
      }
      onAuthenticated()
    } catch {
      setError('Não foi possível entrar agora. Tente novamente em alguns instantes.')
    } finally {
      setLoading(false)
    }
  }

  const isBootstrap = mode === 'bootstrap'
  const isForgot = mode === 'forgot'
  const isReset = mode === 'reset'
  const isInvite = mode === 'invite'
  const brandName = theme.companyShortName || theme.companyName || 'Imob'
  const brandInitials = brandName.trim().slice(0, 2).toUpperCase() || 'IM'

  const heading = isBootstrap
    ? 'Criar Administrador'
    : isForgot
      ? 'Recuperar acesso'
      : isReset
        ? 'Definir nova senha'
        : isInvite
          ? 'Ativar seu acesso'
        : `Entrar no ${brandName}`

  const description = isBootstrap
    ? 'Este cadastro existe apenas para inicializar o primeiro Administrador do ERP.'
    : isForgot
      ? 'Informe o e-mail utilizado no Imob. Se houver uma conta vinculada, você receberá um link de recuperação.'
      : isReset
        ? 'Crie uma nova senha para voltar a acessar o ERP.'
        : isInvite
          ? `Olá, ${name || 'bem-vindo(a)'}. Crie sua senha para concluir o convite.`
        : 'Use suas credenciais para acessar o ambiente da imobiliária.'

  return (
    <main className="login-page">
      <section className="login-brand-panel">
        <div className="login-brand-content">
          <div className={`brand-mark login-logo ${theme.logoUrl ? 'brand-mark-image' : ''}`}>
            {theme.logoUrl ? <img src={theme.logoUrl} alt="" /> : brandInitials}
          </div>
          <span className="eyebrow login-eyebrow">ERP Imobiliário</span>
          <h1>Gestão imobiliária com clareza e controle.</h1>
          <p>Imóveis, contratos, financeiro e operação em uma base única, modular e auditável.</p>

          <div className="login-feature-list">
            <div><ShieldCheck size={16} /><span>Permissões e alçadas por perfil</span></div>
            <div><ShieldCheck size={16} /><span>Histórico das ações sensíveis</span></div>
            <div><ShieldCheck size={16} /><span>Regras operacionais preservadas por contrato</span></div>
          </div>
        </div>
        <span className="login-brand-signature">{brandName} · ERP Imobiliário</span>
      </section>

      <section className="login-form-panel">
        <div className="login-form-wrap">
          <div className="login-mobile-brand">
            <div className="brand-mark">{brandInitials}</div>
            <div><strong>{brandName}</strong><span>ERP Imobiliário</span></div>
          </div>

          <form className="login-card" onSubmit={handleSubmit}>
            <div className="login-card-heading">
              <span className="eyebrow">{isInvite ? 'Convite de acesso' : isBootstrap ? 'Configuração inicial' : isForgot || isReset ? 'Recuperação de acesso' : 'Acesso restrito'}</span>
              <h2>{heading}</h2>
              <p>{description}</p>
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

            {!isReset && (
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
                    readOnly={isInvite}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </div>
              </label>
            )}

            {!isForgot && (
              <label className="field login-field">
                <span>{isReset ? 'Nova senha' : 'Senha'}</span>
                <div className="input-with-icon">
                  <LockKeyhole size={17} />
                  <input
                    autoComplete={isBootstrap || isReset || isInvite ? 'new-password' : 'current-password'}
                    minLength={isBootstrap || isReset || isInvite ? 12 : undefined}
                    placeholder={isReset || isInvite ? 'Crie uma senha segura' : isBootstrap ? 'Crie uma senha segura' : 'Sua senha'}
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
            )}

            {(isBootstrap || isReset || isInvite) && (
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
            {success && <div className="form-alert">{success}</div>}

            <button className="button primary login-submit" disabled={loading} type="submit">
              {loading
                ? isForgot
                  ? 'Enviando...'
                  : isReset
                    ? 'Redefinindo...'
                    : isInvite
                      ? 'Ativando acesso...'
                    : isBootstrap
                      ? 'Criando acesso...'
                      : 'Entrando...'
                : isForgot
                  ? 'Enviar link de recuperação'
                  : isReset
                    ? 'Salvar nova senha'
                    : isInvite
                      ? 'Ativar meu acesso'
                    : isBootstrap
                      ? 'Criar Administrador'
                      : 'Entrar'}
            </button>

            {mode === 'login' && (
              <button className="text-button" type="button" onClick={() => switchMode('forgot')}>
                Esqueci minha senha
              </button>
            )}

            {(isForgot || isReset) && (
              <button className="text-button" type="button" onClick={() => {
                window.history.replaceState({}, '', window.location.pathname)
                setResetToken('')
                switchMode('login')
              }}>
                Voltar para o login
              </button>
            )}

            {bootstrapOpen && !isForgot && !isReset && !isInvite && (
              <button className="text-button" type="button" onClick={() => switchMode(isBootstrap ? 'login' : 'bootstrap')}>
                {isBootstrap ? 'Já tenho acesso' : 'Configurar primeiro acesso'}
              </button>
            )}

            <small className="login-security-note">
              {isForgot
                ? 'Por segurança, a tela não informa se o e-mail está ou não cadastrado.'
                : isReset || isInvite
                  ? 'A nova senha deve ter pelo menos 12 caracteres.'
                  : bootstrapOpen
                    ? 'Após a criação do primeiro Administrador, esta opção é encerrada automaticamente.'
                    : 'Novos usuários são liberados internamente por um Administrador.'}
            </small>
          </form>
        </div>
      </section>
    </main>
  )
}
