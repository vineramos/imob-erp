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
  MessageCircle,
  Phone,
  Ruler,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  X,
} from 'lucide-react'
import { FormEvent, type CSSProperties, useEffect, useMemo, useState } from 'react'
import { ApiError, publicApiRequest } from '../api/client'
import type { PublicProperty, PublicSiteProfile } from '../api/types'
import { PublicCaptureForm } from './PublicCaptureForm'
import { PublicInquiryForm } from './PublicInquiryForm'
import { PublicPropertyCardMedia, PublicPropertyGallery } from './PublicPropertyMedia'
import { formatBedroomSummary } from '../utils/propertyRooms'

function money(value: number | null) {
  if (value == null) return 'Consulte'
  return Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function publicLocation(item: PublicProperty) {
  return [item.address.neighborhood, item.address.city, item.address.state].filter(Boolean).join(' · ') || 'Localização sob consulta'
}

function publicMapAddress(item: PublicProperty) {
  return [
    item.address.street,
    item.address.number,
    item.address.complement,
    item.address.neighborhood,
    item.address.city,
    item.address.state,
    item.address.postal_code,
    'Brasil',
  ].filter(Boolean).join(', ')
}

const publicFeatureLabels:Record<string,string>={balcony:'Sacada',barbecue:'Churrasqueira',air_conditioning:'Ar-condicionado',planned_kitchen:'Cozinha planejada',closet:'Closet',lavabo:'Lavabo',office:'Escritório',laundry:'Lavanderia',heating:'Aquecimento',garden:'Jardim',private_pool:'Piscina privativa',service_area:'Área de serviço'}
const publicCondominiumFeatureLabels:Record<string,string>={elevator:'Elevador',doorman_24h:'Portaria 24h',pool:'Piscina',gym:'Academia',party_room:'Salão de festas',playground:'Playground',gourmet_space:'Espaço gourmet',security:'Segurança',bike_rack:'Bicicletário',coworking:'Coworking'}
const publicSolarLabels:Record<string,string>={north:'Norte',south:'Sul',east:'Leste',west:'Oeste',northeast:'Nordeste',northwest:'Noroeste',southeast:'Sudeste',southwest:'Sudoeste'}

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
type PublicSort = 'relevance' | 'price_asc' | 'price_desc' | 'bedrooms_desc' | 'newest'
type HeroSize = 'compact' | 'standard' | 'expanded'

type RentRangeProps = {
  minRent: number
  maxRent: number
  ceiling: number
  includeCondo: boolean
  onMinRent: (value: number) => void
  onMaxRent: (value: number) => void
  onIncludeCondo: (value: boolean) => void
}

function heroSizeValue(theme: Record<string, unknown>): HeroSize {
  const value = themeString(theme, 'heroSize', 'compact')
  return value === 'standard' || value === 'expanded' ? value : 'compact'
}

function propertySearchValue(item: PublicProperty, includeCondo: boolean) {
  if (item.rent_amount == null) return null
  return Number(item.rent_amount) + (includeCondo ? Number(item.condo_amount ?? 0) : 0)
}

function RentRangeControl({ minRent, maxRent, ceiling, onMinRent, onMaxRent }: RentRangeProps) {
  const options = useMemo(() => {
    const values = [0, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000, 6000, 7500, 10000]
      .filter((value, index, list) => value <= ceiling && list.indexOf(value) === index)
    if (!values.includes(ceiling)) values.push(ceiling)
    return values.sort((a, b) => a - b)
  }, [ceiling])
  return <div className="public-rent-range public-rent-range-selects">
    <span className="public-rent-range-label">Valor do aluguel</span>
    <div className="public-rent-range-select-grid">
      <label><small>Mínimo</small><select aria-label="Valor mínimo" value={minRent} onChange={(event) => {
        const value = Number(event.target.value)
        onMinRent(value)
        if (maxRent > 0 && value > maxRent) onMaxRent(0)
      }}><option value={0}>Sem mínimo</option>{options.filter(value => value > 0).map(value => <option key={value} value={value}>{money(value)}</option>)}</select></label>
      <label><small>Máximo</small><select aria-label="Valor máximo" value={maxRent} onChange={(event) => onMaxRent(Number(event.target.value))}><option value={0}>Sem máximo</option>{options.filter(value => value > 0 && value >= minRent).map(value => <option key={value} value={value}>{money(value)}</option>)}</select></label>
    </div>
  </div>
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
        <span><BedDouble size={14}/>{formatBedroomSummary(item.bedrooms,item.suites)}</span>
        <span><Car size={14}/>{item.parking_spaces} vagas</span>
        {item.area_m2 != null && <span><Ruler size={14}/>{item.area_m2} m²</span>}
      </div>
    </div>
  </a>
}

function SearchResultCard({ organizationId, item, includeCondo }: { organizationId: string; item: PublicProperty; includeCondo: boolean }) {
  const searchedValue = propertySearchValue(item, includeCondo)
  return <a className="public-search-result-card" href={`/site/${organizationId}/imoveis/${item.slug}`}>
    <div className="public-search-result-media"><PublicPropertyCardMedia organizationId={organizationId} item={item}/></div>
    <div className="public-search-result-copy">
      <div className="public-search-result-main"><span className="public-card-type">{propertyType(item.property_type)}</span><h3>{item.title}</h3><p className="public-search-result-location"><MapPin size={13}/>{publicLocation(item)}</p></div>
      <p className="public-search-result-description">{item.description || 'Entre em contato para receber mais informações sobre este imóvel.'}</p>
      <div className="public-search-result-price"><small>{includeCondo ? 'Aluguel + condomínio' : 'Aluguel mensal'}</small><strong>{money(searchedValue)}</strong><div className="public-search-result-costs"><span>Aluguel <b>{money(item.rent_amount)}</b></span><span>Condomínio <b>{money(item.condo_amount)}</b></span><span>IPTU <b>{money(item.iptu_amount)}</b></span></div></div>
      <div className="public-search-result-footer"><div className="public-search-result-facts"><span><BedDouble size={14}/>{item.bedrooms} quartos</span><span><Bath size={14}/>{item.bathrooms} banheiros</span><span><Car size={14}/>{item.parking_spaces} vagas</span>{item.area_m2 != null && <span><Ruler size={14}/>{item.area_m2} m²</span>}</div><span className="public-search-result-action">Ver imóvel <ArrowRight size={14}/></span></div>
    </div>
  </a>
}

export function PublicSitePage({ organizationId, slug }: Props) {
  const [profile, setProfile] = useState<PublicSiteProfile | null>(null)
  const [items, setItems] = useState<PublicProperty[]>([])
  const [selected, setSelected] = useState<PublicProperty | null>(null)
  const [similarProperties, setSimilarProperties] = useState<PublicProperty[]>([])
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<PropertyTypeFilter>('all')
  const [minRent, setMinRent] = useState(0)
  const [maxRent, setMaxRent] = useState(0)
  const [includeCondo, setIncludeCondo] = useState(false)
  const [bedrooms, setBedrooms] = useState(0)
  const [furnishedFilter, setFurnishedFilter] = useState(false)
  const [petsFilter, setPetsFilter] = useState(false)
  const [featureFilters, setFeatureFilters] = useState<string[]>([])
  const [searchSort, setSearchSort] = useState<PublicSort>('relevance')
  const [moreFiltersOpen, setMoreFiltersOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [mapPosition, setMapPosition] = useState<{ latitude: number; longitude: number; precision: 'exact' | 'street' | 'postal_code' } | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    Promise.all([
      publicApiRequest<PublicSiteProfile>(`/public/sites/${organizationId}`),
      slug ? publicApiRequest<PublicProperty>(`/public/sites/${organizationId}/properties/${slug}`).then((item) => [item]) : publicApiRequest<PublicProperty[]>(`/public/sites/${organizationId}/properties`),
      slug ? publicApiRequest<PublicProperty[]>(`/public/sites/${organizationId}/properties/${slug}/similar`).catch(() => []) : Promise.resolve([] as PublicProperty[]),
    ])
      .then(([loadedProfile, loadedItems, similarItems]) => {
        if (!active) return
        const rentals = loadedItems.filter((item) => item.purpose === 'rent')
        setProfile(loadedProfile); setItems(rentals); setSelected(slug ? rentals[0] ?? null : null); setSimilarProperties(similarItems.filter((item) => item.purpose === 'rent'))
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

  useEffect(() => {
    if (!selected) {
      setMapPosition(null)
      return
    }
    let active = true
    setMapPosition(null)
    publicApiRequest<{ latitude: number; longitude: number; precision: 'exact' | 'street' | 'postal_code' }>(
      `/public/sites/${organizationId}/properties/${selected.slug}/map-position`,
    )
      .then((position) => { if (active) setMapPosition(position) })
      .catch(() => { if (active) setMapPosition(null) })
    return () => { active = false }
  }, [organizationId, selected])

  useEffect(() => {
    if (!searchOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setSearchOpen(false) }
    window.addEventListener('keydown', closeOnEscape)
    return () => { document.body.style.overflow = previousOverflow; window.removeEventListener('keydown', closeOnEscape) }
  }, [searchOpen])

  const priceCeiling = useMemo(() => {
    const highest = items.reduce((current, item) => Math.max(current, Number(item.rent_amount ?? 0) + Number(item.condo_amount ?? 0)), 0)
    return Math.max(10000, Math.ceil(highest / 500) * 500)
  }, [items])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    const result=items.filter((item) => {
      if (typeFilter !== 'all' && item.property_type !== typeFilter) return false
      const searchValue = propertySearchValue(item, includeCondo)
      if ((minRent > 0 || maxRent > 0) && searchValue == null) return false
      if (minRent > 0 && searchValue != null && searchValue < minRent) return false
      if (maxRent > 0 && searchValue != null && searchValue > maxRent) return false
      if (bedrooms > 0 && item.bedrooms < bedrooms) return false
      if (furnishedFilter && !item.furnished) return false
      if (petsFilter && !item.pets_allowed) return false
      const featureSet=new Set([...(item.features.property??[]),...(item.features.condominium??[])])
      if(featureFilters.some(feature=>!featureSet.has(feature))) return false
      if (!term) return true
      return (item.title+' '+item.description+' '+publicLocation(item)+' '+propertyType(item.property_type)).toLowerCase().includes(term)
    })
    if(searchSort==='price_asc')return [...result].sort((a,b)=>Number(a.rent_amount??Number.MAX_SAFE_INTEGER)-Number(b.rent_amount??Number.MAX_SAFE_INTEGER))
    if(searchSort==='price_desc')return [...result].sort((a,b)=>Number(b.rent_amount??-1)-Number(a.rent_amount??-1))
    if(searchSort==='bedrooms_desc')return [...result].sort((a,b)=>b.bedrooms-a.bedrooms||b.suites-a.suites)
    return result
  }, [bedrooms, furnishedFilter, petsFilter, featureFilters, searchSort, includeCondo, items, maxRent, minRent, query, typeFilter])

  const neighborhoodRanking = useMemo(() => {
    const counts = new Map<string, number>()
    items.forEach((item) => { const name = item.address.neighborhood?.trim(); if (name) counts.set(name, (counts.get(name) ?? 0) + 1) })
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 6)
  }, [items])

  const featured = items[0] ?? null
  const highlights = items.slice(0, 4)
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
    <section className="public-detail-shell"><a className="public-back" href={`/site/${organizationId}#imoveis`}><ArrowLeft size={15}/> Voltar aos imóveis</a><div className="public-detail-grid"><PublicPropertyGallery organizationId={organizationId} item={selected}/><aside className="public-detail-copy"><div className="public-detail-labels"><span>PARA ALUGAR</span><small>Ref. {selected.code}</small></div><h1>{selected.title}</h1><p className="public-location"><MapPin size={15}/>{publicLocation(selected)}</p><strong className="public-price">{money(selected.rent_amount)}</strong><small>aluguel mensal</small><div className="public-facts"><span><BedDouble size={18}/><strong>{formatBedroomSummary(selected.bedrooms,selected.suites)}</strong></span><span><Bath size={18}/><strong>{selected.bathrooms}</strong> banheiros</span><span><Car size={18}/><strong>{selected.parking_spaces}</strong> vagas</span><span><Ruler size={18}/><strong>{selected.area_m2 ?? '—'}</strong> m²</span></div><div className="public-costs"><div><span>Condomínio</span><strong>{money(selected.condo_amount)}</strong></div><div><span>IPTU</span><strong>{money(selected.iptu_amount)}</strong></div><div><span>Pets</span><strong>{selected.pets_allowed ? 'Permitidos' : 'Consulte'}</strong></div></div><div className="public-security-note"><ShieldCheck size={16}/><span>Por segurança, o endereço completo é apresentado durante o atendimento e a visita.</span></div></aside></div><article className="public-description-panel"><span className="public-kicker">SOBRE O IMÓVEL</span><h2>Detalhes</h2><p>{selected.description || 'Entre em contato para receber mais informações sobre este imóvel.'}</p>
      {(selected.furnished||selected.features.property.length>0||selected.features.condominium.length>0||selected.features.floor!=null||selected.features.total_floors!=null||selected.features.elevators!=null||selected.features.solar_orientation||selected.features.year_built!=null)&&<section className="public-property-features" aria-label="Características do imóvel"><div className="public-property-features-heading"><span className="public-kicker">CARACTERÍSTICAS</span><h2>Diferenciais do imóvel</h2></div><div className="public-property-feature-columns">{(selected.furnished||selected.features.property.length>0)&&<article><h3>Imóvel</h3><div>{selected.furnished&&<span><CheckCircle2 size={13}/>Mobiliado</span>}{selected.features.property.map(key=><span key={key}><CheckCircle2 size={13}/>{publicFeatureLabels[key]??key}</span>)}</div></article>}{selected.features.condominium.length>0&&<article><h3>Condomínio</h3><div>{selected.features.condominium.map(key=><span key={key}><CheckCircle2 size={13}/>{publicCondominiumFeatureLabels[key]??key}</span>)}</div></article>}</div><div className="public-property-feature-meta">{selected.features.floor!=null&&<span><small>Andar</small><strong>{selected.features.floor}</strong></span>}{selected.features.total_floors!=null&&<span><small>Total de andares</small><strong>{selected.features.total_floors}</strong></span>}{selected.features.elevators!=null&&<span><small>Elevadores</small><strong>{selected.features.elevators}</strong></span>}{selected.features.solar_orientation&&<span><small>Posição solar</small><strong>{publicSolarLabels[selected.features.solar_orientation]??selected.features.solar_orientation}</strong></span>}{selected.features.year_built!=null&&<span><small>Ano de construção</small><strong>{selected.features.year_built}</strong></span>}</div></section>}
      <section className="public-property-map-section" aria-label="Localização do imóvel">
        <div className="public-property-map-heading"><div><span className="public-kicker">LOCALIZAÇÃO</span><h2>{selected.address.neighborhood || selected.address.city || 'Localização'}</h2><p>{publicLocation(selected)}{mapPosition?.precision === 'exact' ? ' · ponto exato do imóvel' : ''}</p></div><a href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(mapPosition ? `${mapPosition.latitude},${mapPosition.longitude}` : publicMapAddress(selected))}`} target="_blank" rel="noreferrer">Abrir no Google Maps <ArrowRight size={14}/></a></div>
        <iframe title={`Mapa do imóvel ${selected.code}`} loading="lazy" allowFullScreen referrerPolicy="no-referrer-when-downgrade" src={`https://www.google.com/maps?q=${encodeURIComponent(mapPosition ? `${mapPosition.latitude},${mapPosition.longitude}` : publicMapAddress(selected))}&z=${mapPosition?.precision === 'exact' ? 17 : 14}&output=embed`}/>
      </section>
    </article></section>
    {similarProperties.length>0&&<section className="public-similar-properties"><div className="public-section-title"><div><span className="public-kicker">VOCÊ TAMBÉM PODE GOSTAR</span><h2>Imóveis semelhantes</h2><p>Opções próximas em perfil, localização e faixa de valor.</p></div><a href={`/site/${organizationId}#todos`}>Ver todos <ArrowRight size={14}/></a></div><div className="public-property-grid">{similarProperties.map(item=><PropertyCard key={item.slug} organizationId={organizationId} item={item}/>)}</div></section>}
    <section className="public-detail-contact public-inquiry-lead" id="contato"><div className="public-inquiry-intro"><span className="public-kicker">AGENDE SUA VISITA</span><h2>Gostou deste imóvel?</h2><p>Deixe seus dados e a equipe recebe este interesse diretamente no CRM, já vinculado ao imóvel.</p>{contactActions}</div><PublicInquiryForm organizationId={organizationId} item={selected}/></section>
    <footer className="public-footer"><div>{brand}</div><div><strong>Catálogo conectado ao Imob ERP</strong><span>Informações sujeitas a confirmação e disponibilidade.</span></div></footer>
  </main>

  function clearFilters() { setQuery(''); setTypeFilter('all'); setMinRent(0); setMaxRent(0); setIncludeCondo(false); setBedrooms(0); setFurnishedFilter(false); setPetsFilter(false); setFeatureFilters([]); setSearchSort('relevance'); setMoreFiltersOpen(false) }
  function togglePublicFeature(key:string){setFeatureFilters(current=>current.includes(key)?current.filter(item=>item!==key):[...current,key])}
  function searchSubmit(event: FormEvent) { event.preventDefault(); setSearchOpen(true) }
  function pickNeighborhood(name: string) { setQuery(name); setSearchOpen(true) }
  function openAllProperties() { clearFilters(); setSearchOpen(true) }

  const rentRangeProps: RentRangeProps = { minRent, maxRent, ceiling: priceCeiling, includeCondo, onMinRent: setMinRent, onMaxRent: setMaxRent, onIncludeCondo: setIncludeCondo }

  return <main className="public-site public-site-premium" style={siteStyle}>
    <header className="public-header">{brand}<nav className="public-nav"><a href="#imoveis">Alugar</a><a href="#bairros">Bairros</a><a href="#servicos">Serviços</a><a href="#anunciar">Anunciar</a></nav><div className="public-header-actions">{contactActions}<a className="public-announce" href="#anunciar">Anunciar imóvel</a></div></header>

    <section className={`public-hero public-hero-premium public-hero-size-${heroSize} ${featured ? 'has-featured' : ''}`}>
      {featured && <div className="public-hero-media" aria-hidden="true"><PublicPropertyCardMedia organizationId={organizationId} item={featured}/></div>}
      <div className="public-hero-overlay"/><div className="public-hero-copy"><span className="public-kicker">{heroKicker}</span><h1>{heroTitle}</h1><p>{heroSubtitle}</p><div className="public-hero-trust"><span/><small>MAIS QUE IMÓVEIS, NOVOS COMEÇOS</small></div></div>
      <form className="public-search public-search-premium" onSubmit={searchSubmit}><div className="public-search-tabs"><strong>Alugar</strong><span>Encontre seu próximo lugar</span></div><label className="public-search-main"><MapPin size={17}/><span><small>Cidade ou bairro</small><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ex.: Centro, Curitiba"/></span></label><label><span>Tipo de imóvel</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as PropertyTypeFilter)}><option value="all">Todos</option><option value="apartment">Apartamento</option><option value="house">Casa</option><option value="commercial">Comercial</option><option value="land">Terreno</option><option value="studio">Studio</option><option value="other">Outros</option></select></label><RentRangeControl {...rentRangeProps}/><label><span>Quartos</span><select value={bedrooms} onChange={(event) => setBedrooms(Number(event.target.value))}><option value={0}>Todos</option><option value={1}>1+</option><option value={2}>2+</option><option value={3}>3+</option><option value={4}>4+</option></select></label><button type="submit"><Search size={17}/> Buscar imóveis</button></form>
    </section>

    <section className="public-showcase public-premium-section" id="imoveis"><div className="public-section-title"><div><span className="public-kicker">OPORTUNIDADES REAIS</span><h2>Imóveis em destaque</h2><p>Selecionamos imóveis que merecem sua atenção.</p></div><button type="button" className="public-search-open-all" onClick={openAllProperties}>Ver todos os imóveis <ArrowRight size={15}/></button></div>{highlights.length ? <div className="public-highlight-grid">{highlights.map((item, index) => <PropertyCard key={item.slug} organizationId={organizationId} item={item} badge={index === 0 ? 'Destaque' : index === 1 ? 'Novo' : undefined}/>)}</div> : <div className="public-empty"><House size={24}/><strong>Nenhum imóvel publicado no momento.</strong></div>}</section>

    <section className="public-neighborhood-premium public-premium-section" id="bairros"><div className="public-neighborhood-copy"><span className="public-kicker">DESCUBRA NOVOS LUGARES</span><h2>Explore bairros</h2><p>Encontre o lugar que combina com o seu estilo de vida e veja as oportunidades disponíveis em cada região.</p>{neighborhoodRanking.length > 0 && <div className="public-neighborhood-chips">{neighborhoodRanking.map(([name, count]) => <button type="button" key={name} onClick={() => pickNeighborhood(name)}><MapPin size={13}/><span>{name}</span><small>{count} {count === 1 ? 'imóvel' : 'imóveis'}</small></button>)}</div>}</div><div className="public-map-art" aria-label="Mapa ilustrativo dos bairros"><div className="public-map-road one"/><div className="public-map-road two"/><div className="public-map-road three"/>{neighborhoodRanking.slice(0, 4).map(([name], index) => <button type="button" key={name} className={`pin pin-${index + 1}`} onClick={() => pickNeighborhood(name)}><MapPin size={14}/>{name}</button>)}</div></section>

    <section className="public-services-premium public-premium-section" id="servicos"><div className="public-section-title"><div><span className="public-kicker">MAIS QUE IMÓVEIS</span><h2>Soluções para cada momento</h2></div></div><div className="public-service-grid"><article><span><KeyRound size={21}/></span><div><strong>Locação</strong><p>Agilidade e clareza para encontrar o imóvel ideal.</p></div></article><article><span><Building2 size={21}/></span><div><strong>Administração</strong><p>Gestão do patrimônio com transparência e rastreabilidade.</p></div></article><article><span><Headphones size={21}/></span><div><strong>Atendimento humano</strong><p>Uma equipe acompanhando você do interesse até as chaves.</p></div></article><article><span><ShieldCheck size={21}/></span><div><strong>Processo seguro</strong><p>Informações conectadas ao ERP e histórico preservado.</p></div></article></div></section>

    <section className="public-all public-premium-section" id="todos"><div className="public-section-title"><div><span className="public-kicker">NOSSO PORTFÓLIO</span><h2>Todos os imóveis</h2><p>{items.length} {items.length === 1 ? 'imóvel disponível' : 'imóveis disponíveis'}.</p></div><button type="button" className="public-search-open-all" onClick={openAllProperties}>Abrir busca completa <Search size={14}/></button></div><div className="public-property-grid">{items.map((item) => <PropertyCard key={item.slug} organizationId={organizationId} item={item}/>)}</div></section>

    <section className="public-capture-premium" id="anunciar"><div className="public-capture-intro"><span className="public-kicker">TEM UM IMÓVEL?</span><h2>Seu patrimônio merece uma gestão melhor.</h2><p>Conte um pouco sobre o imóvel. A solicitação entra na operação do Imob para análise da equipe, sem publicação automática.</p><div><span><CheckCircle2 size={15}/> Atendimento personalizado</span><span><CheckCircle2 size={15}/> Processo acompanhado</span><span><CheckCircle2 size={15}/> Nenhum anúncio sem validação</span></div></div><PublicCaptureForm organizationId={organizationId}/></section>

    <section className="public-final-cta"><Sparkles size={20}/><div><span className="public-kicker">PRONTO PARA COMEÇAR?</span><h2>O próximo capítulo pode começar aqui.</h2></div>{contactActions}</section>
    <footer className="public-footer"><div>{brand}</div><nav><a href="#imoveis">Imóveis</a><a href="#bairros">Bairros</a><a href="#servicos">Serviços</a><a href="#anunciar">Anunciar</a></nav><div><strong>{profile.display_name}</strong><span>Informações sujeitas a confirmação e disponibilidade.</span></div></footer>

    {searchOpen && <div className="public-search-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSearchOpen(false) }}><section className="public-search-modal" role="dialog" aria-modal="true" aria-labelledby="public-search-modal-title"><div className="public-search-modal-header"><div className="public-search-modal-title"><div><span className="public-kicker">BUSCA DE IMÓVEIS</span><h2 id="public-search-modal-title">Encontre o imóvel ideal</h2></div><button type="button" className="public-search-modal-close" aria-label="Fechar busca" onClick={() => setSearchOpen(false)}><X size={18}/></button></div><div className="public-search-modal-filters"><label className="public-search-modal-field public-search-location-field"><span>Cidade ou bairro</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ex.: Centro, Curitiba"/></label><label className="public-search-modal-field"><span>Tipo de imóvel</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as PropertyTypeFilter)}><option value="all">Todos</option><option value="apartment">Apartamento</option><option value="house">Casa</option><option value="commercial">Comercial</option><option value="land">Terreno</option><option value="studio">Studio</option><option value="other">Outros</option></select></label><RentRangeControl {...rentRangeProps}/><label className="public-search-modal-field"><span>Quartos</span><select value={bedrooms} onChange={(event) => setBedrooms(Number(event.target.value))}><option value={0}>Todos</option><option value={1}>1+</option><option value={2}>2+</option><option value={3}>3+</option><option value={4}>4+</option></select></label><label className="public-search-modal-field"><span>Ordenar por</span><select value={searchSort} onChange={(event)=>setSearchSort(event.target.value as PublicSort)}><option value="relevance">Relevância</option><option value="price_asc">Menor valor</option><option value="price_desc">Maior valor</option><option value="bedrooms_desc">Mais quartos</option></select></label><button type="button" className={'public-more-filters-trigger'+(moreFiltersOpen?' active':'')} onClick={()=>setMoreFiltersOpen(value=>!value)}><SlidersHorizontal size={14}/><span>Mais filtros</span>{(includeCondo||furnishedFilter||petsFilter||featureFilters.length>0)&&<b>{[includeCondo,furnishedFilter,petsFilter].filter(Boolean).length+featureFilters.length}</b>}</button></div>{moreFiltersOpen&&<div className="public-search-advanced-panel"><div className="public-search-advanced-top"><div className="public-search-quick-filters"><button type="button" className={includeCondo?'active':''} onClick={()=>setIncludeCondo(value=>!value)}>Incluir condomínio</button><button type="button" className={furnishedFilter?'active':''} onClick={()=>setFurnishedFilter(value=>!value)}>Mobiliado</button><button type="button" className={petsFilter?'active':''} onClick={()=>setPetsFilter(value=>!value)}>Aceita pets</button></div><button type="button" className="public-search-modal-clear" onClick={clearFilters}>Limpar filtros</button></div><div className="public-search-feature-filters"><span>Diferenciais</span><div>{Object.entries({...publicFeatureLabels,...publicCondominiumFeatureLabels}).map(([key,label])=><button type="button" key={key} className={featureFilters.includes(key)?'active':''} onClick={()=>togglePublicFeature(key)}>{label}</button>)}</div></div></div>}</div><div className="public-search-modal-body"><div className="public-search-modal-summary"><strong>{filtered.length} {filtered.length === 1 ? 'imóvel encontrado' : 'imóveis encontrados'}</strong><span>{includeCondo ? 'Valor considerando aluguel + condomínio' : 'Valor considerando apenas o aluguel'}{furnishedFilter?' · mobiliados':''}{petsFilter?' · aceita pets':''}{featureFilters.length?` · ${featureFilters.length} diferenciais`:''}</span></div>{filtered.length ? <div className="public-search-results-list">{filtered.map((item) => <SearchResultCard key={item.slug} organizationId={organizationId} item={item} includeCondo={includeCondo}/>)}</div> : <div className="public-search-modal-empty"><House size={30}/><strong>Nenhum imóvel corresponde à pesquisa.</strong><span>Ajuste os filtros ou limpe a pesquisa para ver outras opções.</span><button type="button" className="public-clear" onClick={clearFilters}>Limpar filtros</button></div>}</div></section></div>}
  </main>
}