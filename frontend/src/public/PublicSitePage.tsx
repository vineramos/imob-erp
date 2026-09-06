import {
  ArrowLeft,
  ArrowRight,
  Bath,
  BedDouble,
  Building2,
  Car,
  CheckCircle2,
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
} from 'lucide-react'
import { FormEvent, type CSSProperties, useEffect, useMemo, useState } from 'react'
import { ApiError, publicApiRequest } from '../api/client'
import type { PublicProperty, PublicSiteProfile } from '../api/types'
import { PublicInquiryForm } from './PublicInquiryForm'
import { PublicPropertyCardMedia, PublicPropertyGallery } from './PublicPropertyMedia'

function money(value: number | null) {
  if (value == null) return 'Consulte'
  return Number(value).toLocaleString('pt-BR', {
    style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2,
  })
}

function publicLocation(item: PublicProperty) {
  return [item.address.neighborhood, item.address.city, item.address.state].filter(Boolean).join(' · ') || 'Localização sob consulta'
}

function propertyType(value: string) {
  const labels: Record<string, string> = {
    apartment: 'Apartamento', house: 'Casa', commercial: 'Comercial', land: 'Terreno', studio: 'Studio', other: 'Imóvel',
  }
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

function PropertyCard({ organizationId, item }: { organizationId: string; item: PublicProperty }) {
  return <a className="public-property-card" href={`/site/${organizationId}/imoveis/${item.slug}`}>
    <div className="public-property-card-media"><PublicPropertyCardMedia organizationId={organizationId} item={item}/><span>ALUGUEL</span></div>
    <div className="public-property-card-copy">
      <h3>{item.title}</h3>
      <p>{item.address.neighborhood || item.address.city || 'Localização sob consulta'}</p>
      <div className="public-card-facts">
        <span><BedDouble size={14}/>{item.bedrooms}</span>
        <span><Bath size={14}/>{item.bathrooms}</span>
        <span><Car size={14}/>{item.parking_spaces}</span>
        {item.area_m2 != null && <span><Ruler size={14}/>{item.area_m2} m²</span>}
      </div>
      <div className="public-card-price"><strong>{money(item.rent_amount)}</strong><span>/mês</span></div>
      <div className="public-card-address"><MapPin size={12}/><span>{publicLocation(item)}</span></div>
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    Promise.all([
      publicApiRequest<PublicSiteProfile>(`/public/sites/${organizationId}`),
      slug
        ? publicApiRequest<PublicProperty>(`/public/sites/${organizationId}/properties/${slug}`).then((item) => [item])
        : publicApiRequest<PublicProperty[]>(`/public/sites/${organizationId}/properties`),
    ])
      .then(([loadedProfile, loadedItems]) => {
        if (!active) return
        const rentalItems = loadedItems.filter((item) => item.purpose === 'rent')
        setProfile(loadedProfile)
        setItems(rentalItems)
        setSelected(slug ? rentalItems[0] ?? null : null)
        if (slug && rentalItems.length === 0) setError('Este imóvel não está disponível para locação.')
      })
      .catch((cause) => {
        if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os imóveis.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [organizationId, slug])

  useEffect(() => {
    if (!profile) return
    const previous = document.title
    document.title = selected ? `${selected.title} | ${profile.display_name}` : `Imóveis para alugar | ${profile.display_name}`
    return () => { document.title = previous }
  }, [profile, selected])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter((item) => {
      if (typeFilter !== 'all' && item.property_type !== typeFilter) return false
      if (maxRent > 0 && (item.rent_amount == null || Number(item.rent_amount) > maxRent)) return false
      if (!term) return true
      return `${item.title} ${item.description} ${publicLocation(item)} ${propertyType(item.property_type)}`.toLowerCase().includes(term)
    })
  }, [items, maxRent, query, typeFilter])

  const neighborhoodRanking = useMemo(() => {
    const counts = new Map<string, number>()
    items.forEach((item) => {
      const name = item.address.neighborhood?.trim()
      if (name) counts.set(name, (counts.get(name) ?? 0) + 1)
    })
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 5)
  }, [items])

  const featured = filtered[0] ?? items[0] ?? null
  const highlights = filtered.slice(0, 4)
  const city = featured?.address.city?.trim() || items.find((item) => item.address.city)?.address.city?.trim() || ''
  const regionLabel = city ? `${city} e região` : 'sua região'

  if (loading) return <main className="public-site public-site-state"><div className="public-brand-mark"><House size={20}/></div><strong>Carregando imóveis...</strong></main>
  if (error || !profile) return <main className="public-site public-site-state"><div className="public-brand-mark"><Building2 size={20}/></div><strong>Site indisponível</strong><span>{error || 'O site público ainda não está habilitado.'}</span></main>

  const theme = profile.theme ?? {}
  const primary = themeString(theme, 'primary', '#b67a24')
  const primaryStrong = themeString(theme, 'primaryStrong', '#8d5c17')
  const primarySoft = themeString(theme, 'primarySoft', '#f8f0e4')
  const logoUrl = themeString(theme, 'logoUrl')
  const shortName = themeString(theme, 'companyShortName', profile.display_name)
  const siteStyle = {
    '--site-primary': primary,
    '--site-primary-strong': primaryStrong,
    '--site-primary-soft': primarySoft,
  } as CSSProperties
  const whatsapp = phoneDigits(profile.contact_phone)

  const brand = <a className="public-brand" href={`/site/${organizationId}`}>
    <div className={`public-brand-mark ${logoUrl ? 'has-logo' : ''}`}>{logoUrl ? <img src={logoUrl} alt=""/> : <House size={20}/>}</div>
    <div><strong>{shortName}</strong><span>IMOBILIÁRIA</span></div>
  </a>

  const contactActions = <div className="public-contact">
    {profile.contact_phone && <a className="public-contact-link" href={`tel:${phoneDigits(profile.contact_phone)}`}><Phone size={14}/>{profile.contact_phone}</a>}
    {whatsapp && <a className="public-contact-cta" href={`https://wa.me/${whatsapp}`} target="_blank" rel="noreferrer"><MessageCircle size={15}/> Falar conosco</a>}
    {!whatsapp && profile.contact_email && <a className="public-contact-cta" href={`mailto:${profile.contact_email}`}><Mail size={15}/> Falar conosco</a>}
  </div>

  if (selected) return <main className="public-site" style={siteStyle}>
    <header className="public-header">
      {brand}
      <nav className="public-nav"><a href={`/site/${organizationId}#imoveis`}>Alugar</a><a href={`/site/${organizationId}#bairros`}>Bairros</a><a href={`/site/${organizationId}#servicos`}>Serviços</a><a href="#contato">Contato</a></nav>
      {contactActions}
    </header>
    <section className="public-detail-shell">
      <a className="public-back" href={`/site/${organizationId}#imoveis`}><ArrowLeft size={15}/> Voltar aos imóveis</a>
      <div className="public-detail-grid">
        <PublicPropertyGallery organizationId={organizationId} item={selected}/>
        <aside className="public-detail-copy">
          <div className="public-detail-labels"><span>PARA ALUGAR</span><small>Ref. {selected.code}</small></div>
          <h1>{selected.title}</h1>
          <p className="public-location"><MapPin size={15}/>{publicLocation(selected)}</p>
          <strong className="public-price">{money(selected.rent_amount)}</strong><small>aluguel mensal</small>
          <div className="public-facts">
            <span><BedDouble size={18}/><strong>{selected.bedrooms}</strong> quartos</span>
            <span><Bath size={18}/><strong>{selected.bathrooms}</strong> banheiros</span>
            <span><Car size={18}/><strong>{selected.parking_spaces}</strong> vagas</span>
            <span><Ruler size={18}/><strong>{selected.area_m2 ?? '—'}</strong> m²</span>
          </div>
          <div className="public-costs">
            <div><span>Condomínio</span><strong>{money(selected.condo_amount)}</strong></div>
            <div><span>IPTU</span><strong>{money(selected.iptu_amount)}</strong></div>
            <div><span>Pets</span><strong>{selected.pets_allowed ? 'Permitidos' : 'Consulte'}</strong></div>
          </div>
          <div className="public-detail-actions">
            {whatsapp && <a className="public-primary-action" href={`https://wa.me/${whatsapp}?text=${encodeURIComponent(`Olá! Gostaria de agendar uma visita ao imóvel ${selected.code} — ${selected.title}.`)}`} target="_blank" rel="noreferrer"><MessageCircle size={16}/> Agendar visita</a>}
            {profile.contact_email && <a className="public-secondary-action" href={`mailto:${profile.contact_email}?subject=Interesse no imóvel ${selected.code}`}><Mail size={16}/> Enviar e-mail</a>}
          </div>
          <div className="public-security-note"><ShieldCheck size={16}/><span>Por segurança, o endereço completo é apresentado durante o atendimento e a visita.</span></div>
        </aside>
      </div>
      <article className="public-description-panel"><span className="public-kicker">SOBRE O IMÓVEL</span><h2>Detalhes</h2><p>{selected.description || 'Entre em contato para receber mais informações sobre este imóvel.'}</p></article>
    </section>
    <section className="public-detail-contact public-inquiry-lead" id="contato">
      <div className="public-inquiry-intro"><span className="public-kicker">AGENDE SUA VISITA</span><h2>Gostou deste imóvel?</h2><p>Deixe seus dados e a equipe recebe este interesse diretamente no CRM, já vinculado ao imóvel.</p>{contactActions}</div>
      <PublicInquiryForm organizationId={organizationId} item={selected}/>
    </section>
    <footer className="public-footer"><div>{brand}</div><div><strong>Catálogo conectado ao Imob ERP</strong><span>Informações sujeitas a confirmação e disponibilidade.</span></div></footer>
  </main>

  function searchSubmit(event: FormEvent) {
    event.preventDefault()
    document.getElementById('imoveis')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return <main className="public-site" style={siteStyle}>
    <header className="public-header">
      {brand}
      <nav className="public-nav"><a href="#imoveis">Alugar</a><a href="#bairros">Bairros</a><a href="#servicos">Serviços</a><a href="#contato">Contato</a></nav>
      <div className="public-header-actions">{contactActions}<a className="public-announce" href="#contato">Anunciar imóvel</a></div>
    </header>

    <section className={`public-hero ${featured ? 'has-featured' : ''}`}>
      {featured && <div className="public-hero-media" aria-hidden="true"><PublicPropertyCardMedia organizationId={organizationId} item={featured}/></div>}
      <div className="public-hero-overlay"/>
      <div className="public-hero-copy">
        <span className="public-kicker">ENCONTRE SEU NOVO LAR</span>
        <h1>Os melhores imóveis para alugar em {regionLabel}</h1>
        <p>Imóveis selecionados, informações claras e atendimento próximo do início ao fim.</p>
      </div>
      <form className="public-search" onSubmit={searchSubmit}>
        <label className="public-search-main"><MapPin size={17}/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Bairro, cidade ou região"/></label>
        <label><span>Tipo de imóvel</span><select aria-label="Tipo de imóvel" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as PropertyTypeFilter)}><option value="all">Todos os tipos</option><option value="apartment">Apartamento</option><option value="house">Casa</option><option value="commercial">Comercial</option><option value="land">Terreno</option><option value="studio">Studio</option><option value="other">Outros</option></select></label>
        <label><span>Faixa de preço</span><select aria-label="Faixa de preço" value={maxRent} onChange={(e) => setMaxRent(Number(e.target.value))}><option value={0}>Qualquer valor</option><option value={2000}>Até R$ 2.000</option><option value={3000}>Até R$ 3.000</option><option value={5000}>Até R$ 5.000</option><option value={8000}>Até R$ 8.000</option><option value={10000}>Até R$ 10.000</option></select></label>
        <button type="submit"><Search size={17}/> Buscar imóveis</button>
      </form>
    </section>

    <section className="public-showcase" id="imoveis">
      <div className="public-section-title"><div><span className="public-kicker">SELEÇÃO ATUAL</span><h2>Destaques</h2></div><a href="#todos">Ver todos os imóveis <ArrowRight size={16}/></a></div>
      <div className="public-showcase-grid">
        <div className="public-highlight-grid">
          {highlights.map((item) => <PropertyCard key={item.slug} organizationId={organizationId} item={item}/>)}
          {highlights.length === 0 && <div className="public-empty"><Search size={26}/><strong>Nenhum imóvel encontrado.</strong><span>Ajuste os filtros para visualizar outras opções de locação.</span></div>}
        </div>
        <aside className="public-map-panel">
          <h3>Explore no mapa</h3>
          <div className="public-map-canvas">
            <span className="public-map-road road-a"/><span className="public-map-road road-b"/><span className="public-map-road road-c"/><span className="public-map-road road-d"/>
            {highlights.slice(0, 4).map((item, index) => <span className={`public-map-pin pin-${index + 1}`} key={item.slug}><MapPin size={14}/><b>{item.address.neighborhood || index + 1}</b></span>)}
          </div>
          <a href="#todos"><MapPinned size={16}/> Ver imóveis no mapa</a>
        </aside>
      </div>
    </section>

    {neighborhoodRanking.length > 0 && <section className="public-neighborhoods" id="bairros">
      <div className="public-section-title"><div><span className="public-kicker">LOCALIZAÇÃO</span><h2>Bairros no catálogo</h2></div></div>
      <div className="public-neighborhood-grid">{neighborhoodRanking.map(([name, count], index) => <button type="button" key={name} onClick={() => { setQuery(name); document.getElementById('todos')?.scrollIntoView({ behavior: 'smooth' }) }}><span className={`public-neighborhood-mark mark-${index + 1}`}><MapPin size={17}/></span><span><strong>{name}</strong><small>{count} {count === 1 ? 'imóvel' : 'imóveis'}</small></span></button>)}</div>
    </section>}

    <section className="public-all-properties" id="todos">
      <div className="public-section-title"><div><span className="public-kicker">PARA ALUGAR</span><h2>Todos os imóveis</h2><p>O catálogo é atualizado diretamente pela operação da imobiliária.</p></div><span>{filtered.length} resultado(s)</span></div>
      <div className="public-property-grid">{filtered.map((item) => <PropertyCard key={item.slug} organizationId={organizationId} item={item}/>)}{filtered.length === 0 && <div className="public-empty"><Search size={26}/><strong>Nenhum imóvel encontrado.</strong><span>Ajuste os filtros para visualizar outras opções.</span></div>}</div>
    </section>

    <section className="public-benefits" id="servicos">
      <div className="public-benefits-lead"><span className="public-benefits-icon"><KeyRound size={24}/></span><div><h3>Encontre com tranquilidade</h3><p>Da busca à entrega das chaves, nossa equipe acompanha cada etapa.</p></div></div>
      <div className="public-benefit"><CheckCircle2 size={19}/><div><strong>Atendimento especializado</strong><span>Ajuda para escolher e visitar</span></div></div>
      <div className="public-benefit"><House size={19}/><div><strong>Imóveis verificados</strong><span>Informação atualizada pelo ERP</span></div></div>
      <div className="public-benefit"><ShieldCheck size={19}/><div><strong>Negociação segura</strong><span>Do início ao fim</span></div></div>
    </section>

    <section className="public-owner-cta" id="contato">
      <div><span className="public-kicker">É PROPRIETÁRIO?</span><h2>Quer colocar seu imóvel para alugar?</h2><p>Converse com nossa equipe sobre anúncio e administração. Depois de aprovado, o imóvel entra no mesmo fluxo que alimenta este site.</p></div>
      <div className="public-owner-actions">
        {whatsapp && <a className="public-primary-action" href={`https://wa.me/${whatsapp}?text=${encodeURIComponent('Olá! Tenho um imóvel e gostaria de conversar sobre locação e administração.')}`} target="_blank" rel="noreferrer"><MessageCircle size={16}/> Falar sobre meu imóvel</a>}
        {profile.contact_email && <a className="public-secondary-action" href={`mailto:${profile.contact_email}?subject=Quero colocar meu imóvel para alugar`}><Mail size={16}/> Enviar e-mail</a>}
      </div>
    </section>

    <footer className="public-footer">
      <div>{brand}</div>
      <div><strong>Catálogo de locação conectado ao Imob ERP</strong><span>Estoque e disponibilidade atualizados pela operação da imobiliária.</span></div>
      <div className="public-footer-contact">{profile.contact_phone && <span>{profile.contact_phone}</span>}{profile.contact_email && <span>{profile.contact_email}</span>}</div>
    </footer>
  </main>
}
