import { RotateCcw, Save, Upload } from 'lucide-react'
import { useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import { authConfigured } from '../../auth/client'
import { useTheme } from '../../theme/ThemeProvider'
import { defaultTheme, type ThemeConfig } from '../../theme/theme'

type Props = {
  canEdit: boolean
}

const colorFields: Array<{ key: keyof ThemeConfig; label: string }> = [
  { key: 'primary', label: 'Cor principal' },
  { key: 'primaryStrong', label: 'Principal escura' },
  { key: 'primarySoft', label: 'Principal suave' },
  { key: 'sidebarBg', label: 'Sidebar' },
  { key: 'appBg', label: 'Fundo do sistema' },
  { key: 'surface', label: 'Cards e painéis' },
  { key: 'text', label: 'Texto principal' },
  { key: 'textMuted', label: 'Texto secundário' },
  { key: 'border', label: 'Bordas' },
  { key: 'success', label: 'Sucesso' },
  { key: 'warning', label: 'Atenção' },
  { key: 'danger', label: 'Erro / crítico' },
]

export function AppearanceSettingsPage({ canEdit }: Props) {
  const { theme, setTheme } = useTheme()
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const previewInitials = useMemo(
    () => theme.companyShortName.trim().slice(0, 2).toUpperCase() || 'IM',
    [theme.companyShortName],
  )

  function update<K extends keyof ThemeConfig>(key: K, value: ThemeConfig[K]) {
    if (!canEdit) return
    setSaved(false)
    setMessage('')
    setError('')
    setTheme({ ...theme, [key]: value })
  }

  function restoreDefault() {
    if (!canEdit) return
    setTheme(defaultTheme)
    setSaved(false)
    setMessage('')
    setError('')
  }

  async function saveTheme() {
    if (!canEdit) return

    if (!authConfigured) {
      setSaved(true)
      setMessage('Tema aplicado na pré-visualização local. A persistência será ativada com o Neon Auth.')
      return
    }

    setSaving(true)
    setMessage('')
    setError('')
    try {
      const persisted = await apiRequest<ThemeConfig>('/settings/appearance/erp', {
        method: 'PUT',
        body: JSON.stringify(theme),
      })
      setTheme(persisted)
      setSaved(true)
      setMessage('Tema salvo e alteração registrada na auditoria.')
    } catch (cause) {
      setSaved(false)
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar o tema do ERP.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Administrador</span>
          <h1>Aparência e marca</h1>
          <p>Personalize a identidade do ERP sem alterar código. Toda mudança é aplicada ao sistema em tempo real antes de salvar.</p>
        </div>
        {canEdit && (
          <div className="heading-actions">
            <button className="button secondary" type="button" onClick={restoreDefault} disabled={saving}>
              <RotateCcw size={16} /> Restaurar padrão
            </button>
            <button className="button primary" type="button" onClick={() => void saveTheme()} disabled={saving}>
              <Save size={16} /> {saving ? 'Salvando...' : saved ? 'Salvo' : 'Salvar alterações'}
            </button>
          </div>
        )}
      </div>

      {error && <div className="form-alert danger-alert">{error}</div>}
      {message && <div className="form-alert success-alert">{message}</div>}

      <div className="settings-layout">
        <div className="settings-column">
          <article className="panel form-panel">
            <div className="panel-heading">
              <span className="eyebrow">Institucional</span>
              <h2>Empresa e logotipo</h2>
            </div>

            <div className="form-grid two-columns">
              <label className="field">
                <span>Nome da empresa</span>
                <input disabled={!canEdit} value={theme.companyName} onChange={(event) => update('companyName', event.target.value)} />
              </label>
              <label className="field">
                <span>Nome curto</span>
                <input disabled={!canEdit} value={theme.companyShortName} onChange={(event) => update('companyShortName', event.target.value)} />
              </label>
              <label className="field field-wide">
                <span>Logo principal</span>
                <div className="upload-field">
                  {theme.logoUrl ? (
                    <div className="brand-mark preview-mark brand-mark-image"><img src={theme.logoUrl} alt="Logo atual" /></div>
                  ) : (
                    <div className="brand-mark preview-mark">{previewInitials}</div>
                  )}
                  <div>
                    <strong>{theme.logoUrl ? 'Logo configurada' : 'Nenhum arquivo enviado'}</strong>
                    <small>PNG, SVG ou WEBP. O upload será ligado ao object storage sem gravar imagens no banco.</small>
                  </div>
                  {canEdit && <button type="button" className="button secondary" disabled><Upload size={15} /> Selecionar</button>}
                </div>
              </label>
            </div>
          </article>

          <article className="panel form-panel">
            <div className="panel-heading">
              <span className="eyebrow">Design System</span>
              <h2>Cores</h2>
            </div>
            <div className="color-grid">
              {colorFields.map(({ key, label }) => (
                <label className="color-field" key={String(key)}>
                  <span>{label}</span>
                  <div>
                    <input
                      aria-label={label}
                      disabled={!canEdit}
                      type="color"
                      value={String(theme[key])}
                      onChange={(event) => update(key, event.target.value as never)}
                    />
                    <code>{String(theme[key])}</code>
                  </div>
                </label>
              ))}
            </div>
          </article>

          <article className="panel form-panel">
            <div className="panel-heading">
              <span className="eyebrow">Interface</span>
              <h2>Tipografia e componentes</h2>
            </div>
            <div className="form-grid two-columns">
              <label className="field field-wide">
                <span>Fonte principal</span>
                <select disabled={!canEdit} value={theme.fontFamily} onChange={(event) => update('fontFamily', event.target.value)}>
                  <option value={'Inter, Aptos, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'}>Inter / Aptos</option>
                  <option value={'Aptos, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'}>Aptos</option>
                  <option value={'Arial, sans-serif'}>Arial</option>
                  <option value={'Georgia, serif'}>Georgia</option>
                </select>
              </label>
              <label className="field">
                <span>Arredondamento · {theme.radius}px</span>
                <input disabled={!canEdit} type="range" min="0" max="24" value={theme.radius} onChange={(event) => update('radius', Number(event.target.value))} />
              </label>
              <label className="field">
                <span>Largura da sidebar · {theme.sidebarWidth}px</span>
                <input disabled={!canEdit} type="range" min="210" max="320" value={theme.sidebarWidth} onChange={(event) => update('sidebarWidth', Number(event.target.value))} />
              </label>
              <label className="field">
                <span>Altura de campos · {theme.fieldHeight}px</span>
                <input disabled={!canEdit} type="range" min="36" max="52" value={theme.fieldHeight} onChange={(event) => update('fieldHeight', Number(event.target.value))} />
              </label>
              <label className="field">
                <span>Densidade das tabelas</span>
                <select disabled={!canEdit} value={theme.tableDensity} onChange={(event) => update('tableDensity', event.target.value as ThemeConfig['tableDensity'])}>
                  <option value="compact">Compacta</option>
                  <option value="normal">Normal</option>
                  <option value="comfortable">Confortável</option>
                </select>
              </label>
            </div>
          </article>
        </div>

        <aside className="theme-preview panel">
          <div className="panel-heading">
            <span className="eyebrow">Pré-visualização</span>
            <h2>Como o ERP ficará</h2>
          </div>
          <div className="mini-app">
            <div className="mini-sidebar">
              <div className="brand-mark">{previewInitials}</div>
              <span className="mini-nav active" />
              <span className="mini-nav" />
              <span className="mini-nav" />
              <span className="mini-nav short" />
            </div>
            <div className="mini-main">
              <div className="mini-topbar" />
              <div className="mini-content">
                <span className="mini-title" />
                <div className="mini-cards"><span /><span /><span /></div>
                <div className="mini-panel">
                  <div className="mini-row"><span /><i /></div>
                  <div className="mini-row"><span /><i /></div>
                  <div className="mini-row"><span /><i /></div>
                </div>
                <button type="button" className="button primary preview-button">Botão principal</button>
              </div>
            </div>
          </div>
          <div className="preview-note">
            <strong>{theme.companyName || 'Sua imobiliária'}</strong>
            <span>O site público terá tema próprio, independente deste tema do ERP.</span>
          </div>
        </aside>
      </div>

      {!canEdit && <p className="read-only-note">Seu perfil possui acesso somente para consulta da identidade visual.</p>}
    </section>
  )
}
