import { Eye, RotateCcw, Save, Sparkles } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './site-settings.css'

type SiteFont = 'playfair' | 'lora' | 'merriweather' | 'inter' | 'manrope' | 'montserrat' | 'poppins' | 'dm-sans' | 'georgia'
type HeroSize = 'compact' | 'standard' | 'expanded'

type SiteTheme = {
  companyShortName: string
  logoUrl: string
  faviconUrl: string
  primary: string
  primaryStrong: string
  primarySoft: string
  background: string
  surface: string
  text: string
  textMuted: string
  border: string
  headingFont: SiteFont
  bodyFont: SiteFont
  heroSize: HeroSize
  heroKicker: string
  heroTitle: string
  heroSubtitle: string
}

const fontOptions: Array<{ value: SiteFont; label: string }> = [
  { value: 'playfair', label: 'Playfair · editorial elegante' },
  { value: 'lora', label: 'Lora · clássica suave' },
  { value: 'merriweather', label: 'Merriweather · tradicional' },
  { value: 'georgia', label: 'Georgia · clássica nativa' },
  { value: 'inter', label: 'Inter · moderna limpa' },
  { value: 'manrope', label: 'Manrope · contemporânea' },
  { value: 'montserrat', label: 'Montserrat · geométrica' },
  { value: 'poppins', label: 'Poppins · amigável' },
  { value: 'dm-sans', label: 'DM Sans · minimalista' },
]

const fontStack: Record<SiteFont, string> = {
  playfair: '"Playfair Display", Georgia, "Times New Roman", serif',
  lora: 'Lora, Georgia, "Times New Roman", serif',
  merriweather: 'Merriweather, Georgia, serif',
  georgia: 'Georgia, "Times New Roman", serif',
  inter: 'Inter, Aptos, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  manrope: 'Manrope, Inter, Aptos, sans-serif',
  montserrat: 'Montserrat, Inter, Aptos, sans-serif',
  poppins: 'Poppins, Inter, Aptos, sans-serif',
  'dm-sans': '"DM Sans", Inter, Aptos, sans-serif',
}

const defaultTheme: SiteTheme = {
  companyShortName: 'Imob', logoUrl: '', faviconUrl: '',
  primary: '#123a6b', primaryStrong: '#0d2d55', primarySoft: '#edf4fb',
  background: '#ffffff', surface: '#ffffff', text: '#11213a', textMuted: '#657187', border: '#e3e8ef',
  headingFont: 'playfair', bodyFont: 'inter', heroSize: 'compact',
  heroKicker: 'ENCONTRE O SEU LUGAR',
  heroTitle: 'Viva o próximo capítulo da sua história',
  heroSubtitle: 'Casas, apartamentos e imóveis especiais para alugar nas melhores regiões.',
}

function ColorField({ label, value, disabled, onChange }: { label: string; value: string; disabled: boolean; onChange: (value: string) => void }) {
  return <label className="site-color-field"><span>{label}</span><div><input aria-label={`${label} - seletor`} type="color" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}/><input aria-label={label} value={value} disabled={disabled} maxLength={7} onChange={(event) => onChange(event.target.value)}/></div></label>
}

export function SiteSettingsPage({ canEdit }: { canEdit: boolean }) {
  const [form, setForm] = useState<SiteTheme>(defaultTheme)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let active = true
    apiRequest<SiteTheme>('/settings/appearance/site')
      .then((data) => { if (active) setForm(data) })
      .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar a identidade do site.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const previewStyle = useMemo(() => ({
    '--preview-primary': form.primary,
    '--preview-primary-strong': form.primaryStrong,
    '--preview-primary-soft': form.primarySoft,
    '--preview-bg': form.background,
    '--preview-surface': form.surface,
    '--preview-text': form.text,
    '--preview-muted': form.textMuted,
    '--preview-border': form.border,
    '--preview-heading': fontStack[form.headingFont],
    '--preview-body': fontStack[form.bodyFont],
  }) as React.CSSProperties, [form])

  function patch<K extends keyof SiteTheme>(key: K, value: SiteTheme[K]) { setForm((current) => ({ ...current, [key]: value })); setSuccess('') }

  async function save(event: FormEvent) {
    event.preventDefault(); if (!canEdit) return
    setSaving(true); setError(''); setSuccess('')
    try {
      const saved = await apiRequest<SiteTheme>('/settings/appearance/site', { method: 'PUT', body: JSON.stringify(form) })
      setForm(saved); setSuccess('Identidade do site salva. A página pública passa a usar estas definições.')
    } catch (cause) { setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar a identidade do site.') }
    finally { setSaving(false) }
  }

  function restoreLocal() { if (!canEdit) return; setForm(defaultTheme); setSuccess('Visual padrão carregado na prévia. Clique em Salvar para aplicar.') }

  if (loading) return <section className="workspace settings-workspace"><div className="settings-loading">Carregando identidade do site...</div></section>

  return <section className="workspace settings-workspace site-settings-page">
    <div className="settings-page-heading">
      <div><span className="eyebrow">Site público</span><h1>Editor da presença pública</h1><p>Ajuste conteúdo e identidade em um único estúdio. Nenhuma definição abaixo altera a aparência interna do ERP.</p></div>
      <div className="site-settings-heading-actions"><span className="status-badge neutral">Prévia em tempo real</span></div>
    </div>
    {error && <div className="form-alert danger-alert">{error}</div>}{success && <div className="form-alert success-alert">{success}</div>}
    {!canEdit && <div className="form-alert">Seu perfil pode visualizar, mas apenas Administradores autorizados podem alterar a identidade pública.</div>}

    <form id="site-theme-form" className="site-editor-studio" onSubmit={save}>
      <section className="panel site-preview-stage" style={previewStyle}>
        <div className="site-preview-stage-head"><div><Eye size={15}/><div><strong>Home pública</strong><span>Prévia compacta do que o visitante verá</span></div></div><span className="site-preview-status">Somente visualização</span></div>
        <div className="site-preview-browser">
          <div className="site-preview-nav">
            {form.logoUrl ? <img className="site-preview-brand-logo" src={form.logoUrl} alt={form.companyShortName || 'Logo do site'}/> : <strong>{form.companyShortName || 'Imob'}</strong>}
            <span>Alugar</span><span>Bairros</span><span>Serviços</span><button type="button">Anunciar imóvel</button>
          </div>
          <div className={`site-preview-hero site-preview-hero-${form.heroSize}`}>
            <div className="site-preview-photo"/>
            <div className="site-preview-copy"><small>{form.heroKicker}</small><h3>{form.heroTitle}</h3><p>{form.heroSubtitle}</p></div>
            <div className="site-preview-search"><span>Cidade ou bairro</span><span>Tipo de imóvel</span><span>Faixa de preço</span><button type="button">Buscar imóveis</button></div>
          </div>
        </div>
      </section>

      <div className="site-editor-controls">
        <div className="site-editor-main">
          <article className="panel site-settings-section">
            <div className="site-settings-section-head site-settings-section-head--icon"><span className="section-icon"><Sparkles size={15}/></span><div><span className="eyebrow">Conteúdo</span><h2>Marca e mensagem principal</h2><p>O essencial da primeira dobra, sem campos técnicos disputando atenção.</p></div></div>
            <div className="site-settings-grid site-settings-grid--content">
              <label><span>Nome curto</span><input disabled={!canEdit} value={form.companyShortName} maxLength={40} onChange={(e) => patch('companyShortName', e.target.value)}/></label>
              <label><span>Chamada superior</span><input disabled={!canEdit} value={form.heroKicker} maxLength={80} onChange={(e) => patch('heroKicker', e.target.value)}/></label>
              <label className="span-2"><span>Título principal</span><textarea disabled={!canEdit} rows={2} value={form.heroTitle} maxLength={160} onChange={(e) => patch('heroTitle', e.target.value)}/></label>
              <label className="span-2"><span>Subtítulo</span><textarea disabled={!canEdit} rows={2} value={form.heroSubtitle} maxLength={260} onChange={(e) => patch('heroSubtitle', e.target.value)}/></label>
            </div>
          </article>

          <article className="panel site-settings-section">
            <div className="site-settings-section-head"><div><span className="eyebrow">Arquivos</span><h2>Logo e favicon</h2><p>Mantenha os ativos públicos separados da identidade interna do ERP.</p></div></div>
            <div className="site-settings-grid site-settings-grid--assets">
              <label><span>URL do logo · opcional</span><input disabled={!canEdit} value={form.logoUrl} maxLength={500} placeholder="https://..." onChange={(e) => patch('logoUrl', e.target.value)}/></label>
              <label><span>URL do favicon · opcional</span><input disabled={!canEdit} value={form.faviconUrl} maxLength={500} placeholder="https://..." onChange={(e) => patch('faviconUrl', e.target.value)}/></label>
            </div>
          </article>
        </div>

        <div className="site-editor-side">
          <article className="panel site-settings-section">
            <div className="site-settings-section-head"><div><span className="eyebrow">Composição</span><h2>Banner e tipografia</h2><p>Ajustes rápidos que preservam a estrutura pública.</p></div></div>
            <div className="site-compact-row">
              <label className="field"><span>Tamanho do banner</span><select disabled={!canEdit} value={form.heroSize} onChange={(e) => patch('heroSize', e.target.value as HeroSize)}><option value="compact">Compacto · padrão</option><option value="standard">Padrão</option><option value="expanded">Expandido</option></select></label>
              <label className="field"><span>Fonte dos títulos</span><select disabled={!canEdit} value={form.headingFont} onChange={(e) => patch('headingFont', e.target.value as SiteFont)}>{fontOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
            </div>
            <div className="site-settings-grid" style={{marginTop: 9}}>
              <label className="span-2"><span>Fonte dos textos</span><select disabled={!canEdit} value={form.bodyFont} onChange={(e) => patch('bodyFont', e.target.value as SiteFont)}>{fontOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
            </div>
          </article>

          <article className="panel site-settings-section">
            <div className="site-settings-section-head"><div><span className="eyebrow">Paleta</span><h2>Cores do site</h2><p>Paleta isolada do ERP.</p></div><div className="site-palette-summary" aria-hidden="true"><i style={{background:form.primary}}/><i style={{background:form.primaryStrong}}/><i style={{background:form.primarySoft}}/><i style={{background:form.background}}/></div></div>
            <div className="site-colors-grid">
              <ColorField label="Principal" value={form.primary} disabled={!canEdit} onChange={(v) => patch('primary', v)}/><ColorField label="Principal escura" value={form.primaryStrong} disabled={!canEdit} onChange={(v) => patch('primaryStrong', v)}/><ColorField label="Principal suave" value={form.primarySoft} disabled={!canEdit} onChange={(v) => patch('primarySoft', v)}/><ColorField label="Fundo" value={form.background} disabled={!canEdit} onChange={(v) => patch('background', v)}/><ColorField label="Superfícies" value={form.surface} disabled={!canEdit} onChange={(v) => patch('surface', v)}/><ColorField label="Títulos e textos" value={form.text} disabled={!canEdit} onChange={(v) => patch('text', v)}/><ColorField label="Texto secundário" value={form.textMuted} disabled={!canEdit} onChange={(v) => patch('textMuted', v)}/><ColorField label="Bordas" value={form.border} disabled={!canEdit} onChange={(v) => patch('border', v)}/>
            </div>
          </article>
        </div>
      </div>

      <div className="site-editor-footer"><span>As alterações só chegam ao site público depois de salvar.</span><div><button className="button secondary" type="button" onClick={restoreLocal} disabled={!canEdit || saving}><RotateCcw size={14}/> Restaurar padrão</button><button className="button primary" type="submit" disabled={!canEdit || saving}><Save size={14}/>{saving ? ' Salvando...' : ' Salvar alterações'}</button></div></div>
    </form>
  </section>
}
