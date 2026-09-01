import { ArrowLeft, Bath, BedDouble, Building2, Car, CheckCircle2, House, KeyRound, Mail, MapPin, MessageCircle, PawPrint, Phone, Ruler, Search, ShieldCheck, Sparkles } from 'lucide-react'
import { FormEvent, type CSSProperties, useEffect, useMemo, useState } from 'react'
import { ApiError, publicApiRequest } from '../api/client'
import type { PublicProperty, PublicSiteProfile } from '../api/types'
import { PublicPropertyCardMedia, PublicPropertyGallery } from './PublicPropertyMedia'

function money(value: number | null) {
  if (value == null) return 'Consulte'
  return Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2 })
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

type Props = { organizationId: string; slug?: string | null }
type PropertyTypeFilter = 'all' | 'apartment' | 'house' | 'commercial' | 'land' | 'studio' | 'other'

export function PublicSitePage({ organizationId, slug }: Props) {
  const [profile, setProfile] = useState<PublicSiteProfile | null>(null)
  const [items, setItems] = useState<PublicProperty[]>([])
  const [selected, setSelected] = useState<PublicProperty | null>(null)
  const [query, setQuery] = useState('')
  const [purpose, setPurpose] = useState<'all' | 'rent' | 'sale'>('all')
  const [typeFilter, setTypeFilter] = useState<PropertyTypeFilter>('all')
  const [bedrooms, setBedrooms] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    Promise.all([
      publicApiRequest<PublicSiteProfile>(`/public/sites/${organizationId}`),
      slug
        ? publicApiRequest<PublicProperty>(`/public/sites/${organizationId}/properties/${slug}`).then((item) => [item])
        : publicApiRequest<PublicProperty[]>(`/public/sites/${organizationId}/properties`),
    ])
      .then(([loadedProfile, loadedItems]) => {
        if (!active) return
        setProfile(loadedProfile)
        setItems(loadedItems)
        setSelected(slug ? loadedItems[0] ?? null : null)
      })
      .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os imóveis.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [organizationId, slug])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter((item) => {
      if (purpose !== 'all' && item.purpose !== purpose) return false
      if (typeFilter !== 'all' && item.property_type !== typeFilter) return false
      if (bedrooms > 0 && item.bedrooms < bedrooms) return false
      if (!term) return true
      return `${item.title} ${item.description} ${publicLocation(item)} ${propertyType(item.property_type)}`.toLowerCase().includes(term)
    })
  }, [bedrooms, items, purpose, query, typeFilter])

  const neighborhoods = useMemo(() => new Set(items.map((item) => item.address.neighborhood).filter(Boolean)).size, [items])
  const rentals = useMemo(() => items.filter((item) => item.purpose === 'rent').length, [items])
  const sales = items.length - rentals
  const featured = items[0] ?? null

  if (loading) return <main className="public-site public-site-state"><div className="public-brand-mark"><House size={20}/></div><strong>Carregando imóveis...</strong></main>
  if (error || !profile) return <main className="public-site public-site-state"><div className="public-brand-mark"><Building2 size={20}/></div><strong>Site indisponível</strong><span>{error || 'O site público ainda não está habilitado.'}</span></main>

  const theme = profile.theme ?? {}
  const primary = themeString(theme, 'primary', '#123a6b')
  const primaryStrong = themeString(theme, 'primaryStrong', '#0d2d55')
  const primarySoft = themeString(theme, 'primarySoft', '#edf4fb')
  const logoUrl = themeString(theme, 'logoUrl')
  const shortName = themeString(theme, 'companyShortName', profile.display_name)
  const siteStyle = { '--site-primary': primary, '--site-primary-strong': primaryStrong, '--site-primary-soft': primarySoft } as CSSProperties
  const whatsapp = phoneDigits(profile.contact_phone)

  const brand = <a className="public-brand" href={`/site/${organizationId}`}>
    <div className={`public-brand-mark ${logoUrl ? 'has-logo' : ''}`}>{logoUrl ? <img src={logoUrl} alt=""/> : <House size={18}/>}</div>
    <div><strong>{shortName}</strong><span>Imóveis & Administração</span></div>
  </a>

  const contactActions = <div className="public-contact">
    {profile.contact_phone && <a className="public-contact-link" href={`tel:${phoneDigits(profile.contact_phone)}`}><Phone size={14}/>{profile.contact_phone}</a>}
    {whatsapp && <a className="public-contact-cta" href={`https://wa.me/${whatsapp}`} target="_blank" rel="noreferrer"><MessageCircle size={15}/> Falar conosco</a>}
    {!whatsapp && profile.contact_email && <a className="public-contact-cta" href={`mailto:${profile.contact_email}`}><Mail size={15}/> Falar conosco</a>}
  </div>

  if (selected) return <main className="public-site" style={siteStyle}>
    <header className="public-header">{brand}<nav className="public-nav"><a href={`/site/${organizationId}#imoveis`}>Imóveis</a><a href={`/site/${organizationId}#servicos`}>Serviços</a><a href={`/site/${organizationId}#contato`}>Contato</a></nav>{contactActions}</header>
    <section className="public-detail-shell">
      <a className="public-back" href={`/site/${organizationId}#imoveis`}><ArrowLeft size={15}/> Voltar aos imóveis</a>
      <div className="public-detail-grid">
        <PublicPropertyGallery organizationId={organizationId} item={selected}/>
        <aside className="public-detail-copy">
          <div className="public-detail-labels"><span>{selected.purpose === 'rent' ? 'PARA ALUGAR' : 'PARA COMPRAR'}</span><small>Ref. {selected.code}</small></div>
          <h1>{selected.title}</h1><p className="public-location"><MapPin size={15}/>{publicLocation(selected)}</p>
          <strong className="public-price">{money(selected.rent_amount)}</strong><small>{selected.purpose === 'rent' ? 'aluguel mensal' : 'valor do imóvel'}</small>
          <div className="public-facts"><span><BedDouble size={18}/><strong>{selected.bedrooms}</strong> quartos</span><span><Bath size={18}/><strong>{selected.bathrooms}</strong> banheiros</span><span><Car size={18}/><strong>{selected.parking_spaces}</strong> vagas</span><span><Ruler size={18}/><strong>{selected.area_m2 ?? '—'}</strong> m²</span></div>
          <div className="public-costs"><div><span>Condomínio</span><strong>{money(selected.condo_amount)}</strong></div><div><span>IPTU</span><strong>{money(selected.iptu_amount)}</strong></div><div><span>Pets</span><strong>{selected.pets_allowed ? 'Permitidos' : 'Consulte'}</strong></div></div>
          <div className="public-detail-actions">{whatsapp && <a className="public-primary-action" href={`https://wa.me/${whatsapp}?text=${encodeURIComponent(`Olá! Tenho interesse no imóvel ${selected.code}.`)}`} target="_blank" rel="noreferrer"><MessageCircle size={16}/> Tenho interesse</a>}{profile.contact_email && <a className="public-secondary-action" href={`mailto:${profile.contact_email}?subject=Interesse no imóvel ${selected.code}`}><Mail size={16}/> Enviar e-mail</a>}</div>
          <div className="public-security-note"><ShieldCheck size={16}/><span>Por segurança, o endereço completo é apresentado durante o atendimento e a visita.</span></div>
        </aside>
      </div>
      <article className="public-description-panel"><span className="public-kicker">SOBRE O IMÓVEL</span><h2>Detalhes</h2><p>{selected.description || 'Entre em contato para receber mais informações sobre este imóvel.'}</p></article>
    </section>
    <section className="public-detail-contact" id="contato"><div><span className="public-kicker">ATENDIMENTO</span><h2>Quer conhecer este imóvel?</h2><p>Converse com nossa equipe para tirar dúvidas e agendar uma visita.</p></div>{contactActions}</section>
    <footer className="public-footer"><div>{brand}</div><div><strong>Imóveis publicados diretamente pelo ERP</strong><span>Informações sujeitas a confirmação e disponibilidade.</span></div></footer>
  </main>

  function searchSubmit(event: FormEvent) {
    event.preventDefault()
    document.getElementById('imoveis')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return <main className="public-site" style={siteStyle}>
    <header className="public-header">{brand}<nav className="public-nav"><a href="#imoveis">Imóveis</a><a href="#servicos">Serviços</a><a href="#contato">Contato</a></nav>{contactActions}</header>
    <section className="public-hero">
      <div className="public-hero-copy"><span className="public-kicker">IMÓVEIS PARA A SUA PRÓXIMA FASE</span><h1>Encontre seu próximo imóvel com informação clara e atendimento próximo.</h1><p>Locação, compra e administração em uma experiência conectada ao nosso ERP: estoque atualizado, fotos reais e acompanhamento do início ao fim.</p>
        <div className="public-hero-trust"><span><CheckCircle2 size={15}/> Estoque atualizado</span><span><CheckCircle2 size={15}/> Atendimento humano</span><span><CheckCircle2 size={15}/> Gestão completa</span></div>
      </div>
      {featured && <a className="public-featured" href={`/site/${organizationId}/imoveis/${featured.slug}`}><div className="public-featured-media"><PublicPropertyCardMedia organizationId={organizationId} item={featured}/><span>Em destaque</span></div><div className="public-featured-copy"><small>{featured.purpose === 'rent' ? 'Para alugar' : 'Para comprar'} · Ref. {featured.code}</small><strong>{featured.title}</strong><span><MapPin size={13}/>{publicLocation(featured)}</span><b>{money(featured.rent_amount)}</b></div></a>}
    </section>

    <section className="public-search-shell">
      <form className="public-search" onSubmit={searchSubmit}><label className="public-search-main"><Search size={17}/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Bairro, cidade ou tipo de imóvel"/></label><label><span>Finalidade</span><select value={purpose} onChange={(e) => setPurpose(e.target.value as typeof purpose)}><option value="all">Todos</option><option value="rent">Alugar</option><option value="sale">Comprar</option></select></label><label><span>Tipo</span><select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as PropertyTypeFilter)}><option value="all">Todos</option><option value="apartment">Apartamento</option><option value="house">Casa</option><option value="commercial">Comercial</option><option value="land">Terreno</option><option value="studio">Studio</option><option value="other">Outros</option></select></label><label><span>Quartos</span><select value={bedrooms} onChange={(e) => setBedrooms(Number(e.target.value))}><option value={0}>Qualquer</option><option value={1}>1+</option><option value={2}>2+</option><option value={3}>3+</option><option value={4}>4+</option></select></label><button type="submit">Buscar imóveis</button></form>
    </section>

    <section className="public-stats"><div><strong>{items.length}</strong><span>imóveis publicados</span></div><div><strong>{rentals}</strong><span>para locação</span></div><div><strong>{sales}</strong><span>para compra</span></div><div><strong>{neighborhoods}</strong><span>bairros no catálogo</span></div></section>

    <section className="public-catalog" id="imoveis"><div className="public-section-heading"><div><span className="public-kicker">PORTFÓLIO</span><h2>Imóveis disponíveis</h2><p>Somente imóveis liberados para publicação aparecem aqui.</p></div><span>{filtered.length} resultado(s)</span></div>
      <div className="public-property-grid">{filtered.map((item) => <a className="public-property-card" href={`/site/${organizationId}/imoveis/${item.slug}`} key={item.slug}><PublicPropertyCardMedia organizationId={organizationId} item={item}/><div className="public-property-card-copy"><div className="public-card-top"><span className="public-card-purpose">{item.purpose === 'rent' ? 'Para alugar' : 'Para comprar'}</span><small>Ref. {item.code}</small></div><h3>{item.title}</h3><p><MapPin size={13}/>{publicLocation(item)}</p><div className="public-card-facts"><span><BedDouble size={14}/>{item.bedrooms} q.</span><span><Bath size={14}/>{item.bathrooms} b.</span><span><Car size={14}/>{item.parking_spaces} v.</span>{item.area_m2 != null && <span><Ruler size={14}/>{item.area_m2} m²</span>}{item.pets_allowed && <span><PawPrint size={14}/> pet</span>}</div><div className="public-card-price"><strong>{money(item.rent_amount)}</strong>{item.purpose === 'rent' && <span>/ mês</span>}</div></div></a>)}
        {filtered.length === 0 && <div className="public-empty"><Search size={26}/><strong>Nenhum imóvel encontrado.</strong><span>Ajuste os filtros para visualizar outras opções.</span></div>}
      </div>
    </section>

    <section className="public-services" id="servicos"><div className="public-section-heading"><div><span className="public-kicker">NOSSO TRABALHO</span><h2>Mais do que publicar imóveis.</h2><p>A operação continua conectada depois do primeiro contato.</p></div></div><div className="public-service-grid"><article><div><KeyRound size={20}/></div><strong>Locação acompanhada</strong><p>Da visita à assinatura, com informações organizadas e acompanhamento em cada etapa.</p></article><article><div><Building2 size={20}/></div><strong>Administração de imóveis</strong><p>Cobranças, manutenção, repasses e prestação de contas integrados à gestão da imobiliária.</p></article><article><div><ShieldCheck size={20}/></div><strong>Gestão com transparência</strong><p>Processos rastreáveis e informações atualizadas para proprietários e locatários.</p></article></div></section>

    <section className="public-owner-cta" id="contato"><div><span className="public-kicker">TEM UM IMÓVEL?</span><h2>Quer anunciar ou deixar a administração com a gente?</h2><p>Converse com nossa equipe. O imóvel entra no mesmo fluxo organizado que alimenta este site.</p></div><div className="public-owner-actions">{whatsapp && <a className="public-primary-action" href={`https://wa.me/${whatsapp}?text=${encodeURIComponent('Olá! Gostaria de conversar sobre a administração ou anúncio de um imóvel.')}`} target="_blank" rel="noreferrer"><MessageCircle size={16}/> Conversar no WhatsApp</a>}{profile.contact_email && <a className="public-secondary-action" href={`mailto:${profile.contact_email}?subject=Quero anunciar um imóvel`}><Mail size={16}/> Enviar e-mail</a>}</div></section>

    <footer className="public-footer"><div>{brand}</div><div><strong>Catálogo conectado diretamente ao ERP</strong><span>Estoque e disponibilidade atualizados pela operação da imobiliária.</span></div><div className="public-footer-contact">{profile.contact_phone && <span>{profile.contact_phone}</span>}{profile.contact_email && <span>{profile.contact_email}</span>}</div></footer>
  </main>
}
