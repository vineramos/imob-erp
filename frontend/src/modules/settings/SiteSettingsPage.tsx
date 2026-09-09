import { Eye, RotateCcw, Save, Sparkles } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './site-settings.css'

type SiteFont = 'playfair' | 'lora' | 'merriweather' | 'inter' | 'manrope' | 'montserrat' | 'poppins' | 'dm-sans' | 'georgia'

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
  headingFont: 'playfair', bodyFont: 'inter',
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
    <div className="settings-page-heading"><div><span className="eyebrow">Site público</span><h1>Identidade e Home</h1><p>Controle conteúdo, tipografia e cores do site sem alterar o layout estrutural. O ERP permanece independente.</p></div><div className="site-settings-heading-actions"><button className="button secondary" type="button" onClick={restoreLocal} disabled={!canEdit || saving}><RotateCcw size={15}/> Restaurar visual</button><button className="button primary" type="submit" form="site-theme-form" disabled={!canEdit || saving}><Save size={15}/>{saving ? ' Salvando...' : ' Salvar site'}</button></div></div>
    {error && <div className="form-alert danger-alert">{error}</div>}{success && <div className="form-alert success-alert">{success}</div>}
    {!canEdit && <div className="form-alert">Seu perfil pode visualizar, mas apenas Administradores autorizados podem alterar a identidade pública.</div>}

    <div className="site-settings-layout">
      <form id="site-theme-form" className="site-settings-form" onSubmit={save}>
        <article className="panel site-settings-section"><div className="site-settings-section-head"><div><span className="eyebrow">Conteúdo</span><h2>Mensagem principal</h2></div><Sparkles size={18}/></div><div className="site-settings-grid">
          <label><span>Nome curto da marca</span><input disabled={!canEdit} value={form.companyShortName} maxLength={40} onChange={(e) => patch('companyShortName', e.target.value)}/></label>
          <label><span>Chamada superior</span><input disabled={!canEdit} value={form.heroKicker} maxLength={80} onChange={(e) => patch('heroKicker', e.target.value)}/></label>
          <label className="span-2"><span>Título principal da Home</span><textarea disabled={!canEdit} rows={2} value={form.heroTitle} maxLength={160} onChange={(e) => patch('heroTitle', e.target.value)}/></label>
          <label className="span-2"><span>Subtítulo</span><textarea disabled={!canEdit} rows={3} value={form.heroSubtitle} maxLength={260} onChange={(e) => patch('heroSubtitle', e.target.value)}/></label>
          <label><span>URL do logo · opcional</span><input disabled={!canEdit} value={form.logoUrl} maxLength={500} placeholder="https://..." onChange={(e) => patch('logoUrl', e.target.value)}/></label>
          <label><span>URL do favicon · opcional</span><input disabled={!canEdit} value={form.faviconUrl} maxLength={500} placeholder="https://..." onChange={(e) => patch('faviconUrl', e.target.value)}/></label>
        </div></article>

        <article className="panel site-settings-section"><div className="site-settings-section-head"><div><span className="eyebrow">Tipografia</span><h2>Fontes controladas</h2><p>Uma lista limitada mantém o site consistente e evita combinações ruins.</p></div></div><div className="site-settings-grid">
          <label><span>Fonte dos títulos</span><select disabled={!canEdit} value={form.headingFont} onChange={(e) => patch('headingFont', e.target.value as SiteFont)}>{fontOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label><span>Fonte dos textos</span><select disabled={!canEdit} value={form.bodyFont} onChange={(e) => patch('bodyFont', e.target.value as SiteFont)}>{fontOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        </div></article>

        <article className="panel site-settings-section"><div className="site-settings-section-head"><div><span className="eyebrow">Paleta</span><h2>Cores do site</h2><p>As cores abaixo afetam apenas a presença pública, nunca o ERP.</p></div></div><div className="site-colors-grid">
          <ColorField label="Principal" value={form.primary} disabled={!canEdit} onChange={(v) => patch('primary', v)}/><ColorField label="Principal escura" value={form.primaryStrong} disabled={!canEdit} onChange={(v) => patch('primaryStrong', v)}/><ColorField label="Principal suave" value={form.primarySoft} disabled={!canEdit} onChange={(v) => patch('primarySoft', v)}/><ColorField label="Fundo" value={form.background} disabled={!canEdit} onChange={(v) => patch('background', v)}/><ColorField label="Superfícies" value={form.surface} disabled={!canEdit} onChange={(v) => patch('surface', v)}/><ColorField label="Títulos e textos" value={form.text} disabled={!canEdit} onChange={(v) => patch('text', v)}/><ColorField label="Texto secundário" value={form.textMuted} disabled={!canEdit} onChange={(v) => patch('textMuted', v)}/><ColorField label="Bordas" value={form.border} disabled={!canEdit} onChange={(v) => patch('border', v)}/>
        </div></article>
      </form>

      <aside className="panel site-live-preview" style={previewStyle}><div className="site-preview-title"><Eye size={16}/><div><strong>Prévia ao vivo</strong><span>Representação reduzida da nova Home</span></div></div><div className="site-preview-browser"><div className="site-preview-nav"><strong>{form.companyShortName || 'Imob'}</strong><span>Alugar</span><span>Bairros</span><span>Serviços</span><button type="button">Anunciar imóvel</button></div><div className="site-preview-hero"><div className="site-preview-photo"/><div className="site-preview-copy"><small>{form.heroKicker}</small><h3>{form.heroTitle}</h3><p>{form.heroSubtitle}</p></div><div className="site-preview-search"><span>Cidade ou bairro</span><span>Tipo de imóvel</span><span>Faixa de preço</span><button type="button">Buscar imóveis</button></div></div><div className="site-preview-list"><div className="site-preview-list-head"><h4>Imóveis em destaque</h4><span>Ver todos →</span></div><div className="site-preview-cards">{[1,2,3].map((n) => <div key={n}><i/><strong>Apartamento em destaque</strong><span>R$ 2.800 / mês</span><small>2 quartos · 1 vaga</small></div>)}</div></div></div><p className="site-preview-note">A foto real do topo é a capa de um imóvel publicado. Nenhuma imagem é duplicada nas configurações.</p></aside>
    </div>
  </section>
}
