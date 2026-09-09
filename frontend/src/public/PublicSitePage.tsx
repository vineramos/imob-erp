import {
  ArrowLeft,
  ArrowRight,
  Bath,
  BedDouble,
  Building2,
  Car,
  CheckCircle2,
  Headphones,
  House,
  KeyRound,
  Mail,
  MapPin,
  MapPinned,
  MessageCircle,
  Phone,
  Ruler,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { FormEvent, type CSSProperties, useEffect, useMemo, useState } from 'react'
import { ApiError, publicApiRequest } from '../api/client'
import type { PublicProperty, PublicSiteProfile } from '../api/types'
import { PublicCaptureForm } from './PublicCaptureForm'
import { PublicInquiryForm } from './PublicInquiryForm'
import { PublicPropertyCardMedia, PublicPropertyGallery } from './PublicPropertyMedia'

function money(value: number | null) {
  if (value == null) return 'Consulte'
  return Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function publicLocation(item: PublicProperty) {
  return [item.address.neighborhood, item.address.city, item.address.state].filter(Boolean).join(' · ') || 'Localização sob consulta'
}

function propertyType(value: string) {
  const labels: Record<string, string> = { apartment: 'Apartamento', house: 'Casa', commercial: 'Comercial', land: 'Terreno', studio: 'Studio', other: 'Imóvel' }
  return labels[value] ?? value
}

function themeString(theme: Record<string, unknown>, key: string, fallback = '') {
  const value = theme[key]
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

function phoneDigits(value: string | null) {
  let digits = String(value ?? '').replace(/\D/g, '')
  if (!digits) return ''
  if (!digits.startsWith('55') && (digits.length === 10 || digits.length === 11)) digits = `55${digits}`
  return digits
}

function fontStack(value: string, fallback: string) {
  const fonts: Record<string, string> = {
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
  return fonts[value] || fallback
}

type Props = { organizationId: string; slug?: string | null }
type PropertyTypeFilter = 'all' | 'apartment' | 'house' | 'commercial' | 'land' | 'studio' | 'other'
type HeroSize = 'compact' | 'standard' | 'expanded'

function heroSizeValue(theme: Record<string, unknown>): HeroSize {
  const value = themeString(theme, 'heroSize', 'compact')
  return value === 'standard' || value === 'expanded' ? value : 'compact'
}

function PropertyCard({ organizationId, item, badge }: { organizationId: string; item: PublicProperty; badge?: string }) {
  return <a className="public-property-card" href={`/site/${organizationId}/imoveis/${item.slug}`}>
    <div className="public-property-card-media"><PublicPropertyCardMedia organizationId={organizationId} item={item}/>{badge && <span>{badge}</span>}</div>
    <div className="public-property-card-copy">
      <div className="public-card-type">{propertyType(item.property_type)}</div>
      <h3>{item.title}</h3>
      <p>{publicLocation(item)}</p>
      <div className="public-card-price"><strong>{money(item.rent_amount)}</strong><span>/ mês</span></div>
      <div className="public-card-facts">
        <span><BedDouble size={14}/>{item.bedrooms} quartos</span>
        <span><Car size={14}/>{item.parking_spaces} vagas</span>
        {item.area_m2 != null && <span><Ruler size={14}/>{item.area_m2} m²</span>}
      </div>
    </div>
  </a>
}

export function PublicSitePage({ organizationId, slug }: Props) {
  const [profile, setProfile] = useState<PublicSiteProfile | null>(null)
  const [items, setItems] = useState<PublicProperty[]>([])
  const [selected, setSelected] = useState<PublicProperty | null>(null)
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<PropertyTypeFilter>('all')
  const [maxRent, setMaxRent] = useState(0)
  const [bedrooms, setBedrooms] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    Promise.all([
      publicApiRequest<PublicSiteProfile>(`/public/sites/${organizationId}`),
      slug ? publicApiRequest<PublicProperty>(`/public/sites/${organizationId}/properties/${slug}`).then((item) => [item]) : publicApiRequest<PublicProperty[]>(`/public/sites/${organizationId}/properties`),
    ])
      .then(([loadedProfile, loadedItems]) => {
        if (!active) return
        const rentals = loadedItems.filter((item) => item.purpose === 'rent')
        setProfile(loadedProfile); setItems(rentals); setSelected(slug ? rentals[0] ?? null : null)
        if (slug && !rentals.length) setError('Este imóvel não está disponível para locação.')
      })
      .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os imóveis.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [organizationId, slug])

  useEffect(() => {
    if (!profile) return
    const previous = document.title
    document.title = selected ? `${selected.title} | ${profile.display_name}` : `${profile.display_name} | Imóveis para alugar`
    return () => { document.title = previous }
  }, [profile, selected])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter((item) => {
      if (typeFilter !== 'all' && item.property_type !== typeFilter) return false
      if (maxRent > 0 && (item.rent_amount == null || Number(item.rent_amount) > maxRent)) return false
      if (bedrooms > 0 && item.bedrooms < bedrooms) return false
      if (!term) return true
      return `${item.title} ${item.description} ${publicLocation(item)} ${propertyType(item.property_type)}`.toLowerCase().includes(term)
    })
  }, [bedrooms, items, maxRent, query, typeFilter])

  const neighborhoodRanking = useMemo(() => {
    const counts = new Map<string, number>()
    items.forEach((item) => { const name = item.address.neighborhood?.trim(); if (name) counts.set(name, (counts.get(name) ?? 0) + 1) })
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 6)
  }, [items])

  const featured = filtered[0] ?? items[0] ?? null
  const highlights = (filtered.length ? filtered : items).slice(0, 4)

  if (loading) return <main className="public-site public-site-state"><div className="public-brand-mark"><House size={20}/></div><strong>Carregando imóveis...</strong></main>
  if (error || !profile) return <main className="public-site public-site-state"><div className="public-brand-mark"><Building2 size={20}/></div><strong>Site indisponível</strong><span>{error || 'O site público ainda não está habilitado.'}</span></main>

  const theme = profile.theme ?? {}
  const primary = themeString(theme, 'primary', '#123a6b')
  const primaryStrong = themeString(theme, 'primaryStrong', '#0d2d55')
  const primarySoft = themeString(theme, 'primarySoft', '#edf4fb')
  const background = themeString(theme, 'background', '#ffffff')
  const surface = themeString(theme, 'surface', '#ffffff')
  const text = themeString(theme, 'text', '#11213a')
  const textMuted = themeString(theme, 'textMuted', '#657187')
  const border = themeString(theme, 'border', '#e3e8ef')
  const logoUrl = themeString(theme, 'logoUrl')
  const shortName = themeString(theme, 'companyShortName', profile.display_name)
  const heroKicker = themeString(theme, 'heroKicker', 'ENCONTRE O SEU LUGAR')
  const heroTitle = themeString(theme, 'heroTitle', 'Viva o próximo capítulo da sua história')
  const heroSubtitle = themeString(theme, 'heroSubtitle', 'Casas, apartamentos e imóveis especiais para alugar nas melhores regiões.')
  const heroSize = heroSizeValue(theme)
  const headingFont = fontStack(themeString(theme, 'headingFont', 'playfair'), 'Georgia, "Times New Roman", serif')
  const bodyFont = fontStack(themeString(theme, 'bodyFont', 'inter'), 'Inter, Aptos, sans-serif')
  const siteStyle = {
    '--site-primary': primary, '--site-primary-strong': primaryStrong, '--site-primary-soft': primarySoft,
    '--site-bg': background, '--site-surface': surface, '--site-ink': text, '--site-muted': textMuted, '--site-line': border,
    '--site-heading-font': headingFont, '--site-body-font': bodyFont,
  } as CSSProperties
  const whatsapp = phoneDigits(profile.contact_phone)

  const brand = <a className="public-brand" href={`/site/${organizationId}`}>{logoUrl ? <img className="public-brand-logo" src={logoUrl} alt={shortName}/> : <strong>{shortName}</strong>}<span>Mais que imóveis,<br/>novos começos.</span></a>
  const contactActions = <div className="public-contact">{profile.contact_phone && <a className="public-contact-link" href={`tel:${phoneDigits(profile.contact_phone)}`}><Phone size={14}/>{profile.contact_phone}</a>}{whatsapp && <a className="public-contact-cta" href={`https://wa.me/${whatsapp}`} target="_blank" rel="noreferrer"><MessageCircle size={15}/> Falar conosco</a>}{!whatsapp && profile.contact_email && <a className="public-contact-cta" href={`mailto:${profile.contact_email}`}><Mail size={15}/> Falar conosco</a>}</div>

  if (selected) return <main className="public-site public-site-premium" style={siteStyle}>
    <header className="public-header">{brand}<nav className="public-nav"><a href={`/site/${organizationId}#imoveis`}>Alugar</a><a href={`/site/${organizationId}#bairros`}>Bairros</a><a href={`/site/${organizationId}#servicos`}>Serviços</a><a href="#contato">Contato</a></nav><div className="public-header-actions">{contactActions}<a className="public-announce" href={`/site/${organizationId}#anunciar`}>Anunciar imóvel</a></div></header>
    <section className="public-detail-shell"><a className="public-back" href={`/site/${organizationId}#imoveis`}><ArrowLeft size={15}/> Voltar aos imóveis</a><div className="public-detail-grid"><PublicPropertyGallery organizationId={organizationId} item={selected}/><aside className="public-detail-copy"><div className="public-detail-labels"><span>PARA ALUGAR</span><small>Ref. {selected.code}</small></div><h1>{selected.title}</h1><p className="public-location"><MapPin size={15}/>{publicLocation(selected)}</p><strong className="public-price">{money(selected.rent_amount)}</strong><small>aluguel mensal</small><div className="public-facts"><span><BedDouble size={18}/><strong>{selected.bedrooms}</strong> quartos</span><span><Bath size={18}/><strong>{selected.bathrooms}</strong> banheiros</span><span><Car size={18}/><strong>{selected.parking_spaces}</strong> vagas</span><span><Ruler size={18}/><strong>{selected.area_m2 ?? '—'}</strong> m²</span></div><div className="public-costs"><div><span>Condomínio</span><strong>{money(selected.condo_amount)}</strong></div><div><span>IPTU</span><strong>{money(selected.iptu_amount)}</strong></div><div><span>Pets</span><strong>{selected.pets_allowed ? 'Permitidos' : 'Consulte'}</strong></div></div><div className="public-security-note"><ShieldCheck size={16}/><span>Por segurança, o endereço completo é apresentado durante o atendimento e a visita.</span></div></aside></div><article className="public-description-panel"><span className="public-kicker">SOBRE O IMÓVEL</span><h2>Detalhes</h2><p>{selected.description || 'Entre em contato para receber mais informações sobre este imóvel.'}</p></article></section>
    <section className="public-detail-contact public-inquiry-lead" id="contato"><div className="public-inquiry-intro"><span className="public-kicker">AGENDE SUA VISITA</span><h2>Gostou deste imóvel?</h2><p>Deixe seus dados e a equipe recebe este interesse diretamente no CRM, já vinculado ao imóvel.</p>{contactActions}</div><PublicInquiryForm organizationId={organizationId} item={selected}/></section>
    <footer className="public-footer"><div>{brand}</div><div><strong>Catálogo conectado ao Imob ERP</strong><span>Informações sujeitas a confirmação e disponibilidade.</span></div></footer>
  </main>

  function searchSubmit(event: FormEvent) { event.preventDefault(); document.getElementById('imoveis')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
  function pickNeighborhood(name: string) { setQuery(name); window.setTimeout(() => document.getElementById('todos')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50) }

  return <main className="public-site public-site-premium" style={siteStyle}>
    <header className="public-header">{brand}<nav className="public-nav"><a href="#imoveis">Alugar</a><a href="#bairros">Bairros</a><a href="#servicos">Serviços</a><a href="#anunciar">Anunciar</a></nav><div className="public-header-actions">{contactActions}<a className="public-announce" href="#anunciar">Anunciar imóvel</a></div></header>

    <section className={`public-hero public-hero-premium public-hero-size-${heroSize} ${featured ? 'has-featured' : ''}`}>
      {featured && <div className="public-hero-media" aria-hidden="true"><PublicPropertyCardMedia organizationId={organizationId} item={featured}/></div>}
      <div className="public-hero-overlay"/><div className="public-hero-copy"><span className="public-kicker">{heroKicker}</span><h1>{heroTitle}</h1><p>{heroSubtitle}</p><div className="public-hero-trust"><span/><small>MAIS QUE IMÓVEIS, NOVOS COMEÇOS</small></div></div>
      <form className="public-search public-search-premium" onSubmit={searchSubmit}><div className="public-search-tabs"><strong>Alugar</strong><span>Encontre seu próximo lugar</span></div><label className="public-search-main"><MapPin size={17}/><span><small>Cidade ou bairro</small><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ex.: Centro, Curitiba"/></span></label><label><span>Tipo de imóvel</span><select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as PropertyTypeFilter)}><option value="all">Todos</option><option value="apartment">Apartamento</option><option value="house">Casa</option><option value="commercial">Comercial</option><option value="land">Terreno</option><option value="studio">Studio</option><option value="other">Outros</option></select></label><label><span>Faixa de preço</span><select value={maxRent} onChange={(e) => setMaxRent(Number(e.target.value))}><option value={0}>Qualquer valor</option><option value={2000}>Até R$ 2.000</option><option value={3000}>Até R$ 3.000</option><option value={5000}>Até R$ 5.000</option><option value={8000}>Até R$ 8.000</option><option value={10000}>Até R$ 10.000</option></select></label><label><span>Quartos</span><select value={bedrooms} onChange={(e) => setBedrooms(Number(e.target.value))}><option value={0}>Todos</option><option value={1}>1+</option><option value={2}>2+</option><option value={3}>3+</option><option value={4}>4+</option></select></label><button type="submit"><Search size={17}/> Buscar imóveis</button></form>
    </section>

    <section className="public-showcase public-premium-section" id="imoveis"><div className="public-section-title"><div><span className="public-kicker">OPORTUNIDADES REAIS</span><h2>Imóveis em destaque</h2><p>Selecionamos imóveis que merecem sua atenção.</p></div><a href="#todos">Ver todos os imóveis <ArrowRight size={15}/></a></div>{highlights.length ? <div className="public-highlight-grid">{highlights.map((item, index) => <PropertyCard key={item.slug} organizationId={organizationId} item={item} badge={index === 0 ? 'Destaque' : index === 1 ? 'Novo' : undefined}/>)}</div> : <div className="public-empty"><House size={24}/><strong>Nenhum imóvel para os filtros selecionados.</strong><button type="button" onClick={() => { setQuery(''); setTypeFilter('all'); setMaxRent(0); setBedrooms(0) }}>Limpar filtros</button></div>}</section>

    <section className="public-neighborhood-premium public-premium-section" id="bairros"><div className="public-neighborhood-copy"><span className="public-kicker">DESCUBRA NOVOS LUGARES</span><h2>Explore bairros</h2><p>Encontre o lugar que combina com o seu estilo de vida e veja as oportunidades disponíveis em cada região.</p>{neighborhoodRanking.length > 0 && <div className="public-neighborhood-chips">{neighborhoodRanking.map(([name, count]) => <button type="button" key={name} onClick={() => pickNeighborhood(name)}><MapPin size={13}/><span>{name}</span><small>{count} {count === 1 ? 'imóvel' : 'imóveis'}</small></button>)}</div>}</div><div className="public-map-art" aria-label="Mapa ilustrativo dos bairros"><div className="public-map-road one"/><div className="public-map-road two"/><div className="public-map-road three"/>{neighborhoodRanking.slice(0, 4).map(([name], index) => <button type="button" key={name} className={`pin pin-${index + 1}`} onClick={() => pickNeighborhood(name)}><MapPin size={14}/>{name}</button>)}</div></section>

    <section className="public-services-premium public-premium-section" id="servicos"><div className="public-section-title"><div><span className="public-kicker">MAIS QUE IMÓVEIS</span><h2>Soluções para cada momento</h2></div></div><div className="public-service-grid"><article><span><KeyRound size={21}/></span><div><strong>Locação</strong><p>Agilidade e clareza para encontrar o imóvel ideal.</p></div></article><article><span><Building2 size={21}/></span><div><strong>Administração</strong><p>Gestão do patrimônio com transparência e rastreabilidade.</p></div></article><article><span><Headphones size={21}/></span><div><strong>Atendimento humano</strong><p>Uma equipe acompanhando você do interesse até as chaves.</p></div></article><article><span><ShieldCheck size={21}/></span><div><strong>Processo seguro</strong><p>Informações conectadas ao ERP e histórico preservado.</p></div></article></div></section>

    <section className="public-all public-premium-section" id="todos"><div className="public-section-title"><div><span className="public-kicker">NOSSO PORTFÓLIO</span><h2>Todos os imóveis</h2><p>{filtered.length} {filtered.length === 1 ? 'opção encontrada' : 'opções encontradas'}.</p></div>{(query || typeFilter !== 'all' || maxRent || bedrooms) ? <button type="button" className="public-clear" onClick={() => { setQuery(''); setTypeFilter('all'); setMaxRent(0); setBedrooms(0) }}>Limpar filtros</button> : null}</div><div className="public-property-grid">{filtered.map((item) => <PropertyCard key={item.slug} organizationId={organizationId} item={item}/>)}</div></section>

    <section className="public-capture-premium" id="anunciar"><div className="public-capture-intro"><span className="public-kicker">TEM UM IMÓVEL?</span><h2>Seu patrimônio merece uma gestão melhor.</h2><p>Conte um pouco sobre o imóvel. A solicitação entra na operação do Imob para análise da equipe, sem publicação automática.</p><div><span><CheckCircle2 size={15}/> Atendimento personalizado</span><span><CheckCircle2 size={15}/> Processo acompanhado</span><span><CheckCircle2 size={15}/> Nenhum anúncio sem validação</span></div></div><PublicCaptureForm organizationId={organizationId}/></section>

    <section className="public-final-cta"><Sparkles size={20}/><div><span className="public-kicker">PRONTO PARA COMEÇAR?</span><h2>O próximo capítulo pode começar aqui.</h2></div>{contactActions}</section>
    <footer className="public-footer"><div>{brand}</div><nav><a href="#imoveis">Imóveis</a><a href="#bairros">Bairros</a><a href="#servicos">Serviços</a><a href="#anunciar">Anunciar</a></nav><div><strong>{profile.display_name}</strong><span>Informações sujeitas a confirmação e disponibilidade.</span></div></footer>
  </main>
}
