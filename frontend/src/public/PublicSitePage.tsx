import { ArrowLeft, Bath, BedDouble, Building2, Car, House, Mail, MapPin, PawPrint, Phone, Ruler, Search } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { ApiError, publicApiRequest } from '../api/client'
import type { PublicProperty, PublicSiteProfile } from '../api/types'

function money(value: number | null) {
  if (value == null) return 'Consulte'
  return Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function publicLocation(item: PublicProperty) {
  return [item.address.neighborhood, item.address.city, item.address.state].filter(Boolean).join(' · ') || 'Localização sob consulta'
}

function propertyType(value: string) {
  const labels: Record<string, string> = { apartment: 'Apartamento', house: 'Casa', commercial: 'Comercial', land: 'Terreno', studio: 'Studio', other: 'Imóvel' }
  return labels[value] ?? value
}

type Props = { organizationId: string; slug?: string | null }

export function PublicSitePage({ organizationId, slug }: Props) {
  const [profile, setProfile] = useState<PublicSiteProfile | null>(null)
  const [items, setItems] = useState<PublicProperty[]>([])
  const [selected, setSelected] = useState<PublicProperty | null>(null)
  const [query, setQuery] = useState('')
  const [purpose, setPurpose] = useState<'all' | 'rent' | 'sale'>('all')
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
        if (slug) setSelected(loadedItems[0] ?? null)
      })
      .catch((cause) => { if (active) setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os imóveis.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [organizationId, slug])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter((item) => {
      if (purpose !== 'all' && item.purpose !== purpose) return false
      if (!term) return true
      return `${item.title} ${item.description} ${publicLocation(item)} ${propertyType(item.property_type)}`.toLowerCase().includes(term)
    })
  }, [items, purpose, query])

  function searchSubmit(event: FormEvent) { event.preventDefault() }

  if (loading) return <main className="public-site public-site-state"><div className="public-brand-mark"><House size={20}/></div><strong>Carregando imóveis...</strong></main>
  if (error || !profile) return <main className="public-site public-site-state"><div className="public-brand-mark"><Building2 size={20}/></div><strong>Catálogo indisponível</strong><span>{error || 'O site público ainda não está habilitado.'}</span></main>

  if (selected) return <main className="public-site">
    <header className="public-header"><a className="public-brand" href={`/site/${organizationId}`}><div className="public-brand-mark"><House size={17}/></div><div><strong>{profile.display_name}</strong><span>Imóveis selecionados</span></div></a><div className="public-contact">{profile.contact_phone && <a href={`tel:${profile.contact_phone}`}><Phone size={14}/>{profile.contact_phone}</a>}{profile.contact_email && <a href={`mailto:${profile.contact_email}`}><Mail size={14}/>Contato</a>}</div></header>
    <section className="public-detail">
      <a className="public-back" href={`/site/${organizationId}`}><ArrowLeft size={15}/> Voltar aos imóveis</a>
      <div className="public-detail-grid">
        <div className="public-detail-visual"><span>{propertyType(selected.property_type)}</span><strong>{selected.title}</strong><small>{publicLocation(selected)}</small></div>
        <div className="public-detail-copy"><span className="public-kicker">{selected.purpose === 'rent' ? 'PARA ALUGAR' : 'PARA COMPRAR'}</span><h1>{selected.title}</h1><p className="public-location"><MapPin size={15}/>{publicLocation(selected)}</p><strong className="public-price">{money(selected.rent_amount)}</strong>{selected.purpose === 'rent' && <small>aluguel mensal</small>}
          <div className="public-facts"><span><BedDouble size={17}/><strong>{selected.bedrooms}</strong> quartos</span><span><Bath size={17}/><strong>{selected.bathrooms}</strong> banheiros</span><span><Car size={17}/><strong>{selected.parking_spaces}</strong> vagas</span><span><Ruler size={17}/><strong>{selected.area_m2 ?? '—'}</strong> m²</span></div>
          <p className="public-description">{selected.description}</p>
          <div className="public-costs"><div><span>Condomínio</span><strong>{money(selected.condo_amount)}</strong></div><div><span>IPTU</span><strong>{money(selected.iptu_amount)}</strong></div><div><span>Pets</span><strong>{selected.pets_allowed ? 'Permitidos' : 'Consulte'}</strong></div></div>
          <div className="public-detail-actions">{profile.contact_phone && <a className="public-primary-action" href={`tel:${profile.contact_phone}`}><Phone size={16}/> Quero saber mais</a>}{profile.contact_email && <a className="public-secondary-action" href={`mailto:${profile.contact_email}?subject=Interesse no imóvel ${selected.code}`}><Mail size={16}/> Enviar e-mail</a>}</div>
        </div>
      </div>
    </section>
    <footer className="public-footer"><strong>{profile.display_name}</strong><span>Informações sujeitas a confirmação. Endereço exato preservado por segurança.</span></footer>
  </main>

  return <main className="public-site">
    <header className="public-header"><a className="public-brand" href={`/site/${organizationId}`}><div className="public-brand-mark"><House size={17}/></div><div><strong>{profile.display_name}</strong><span>Imóveis selecionados</span></div></a><div className="public-contact">{profile.contact_phone && <a href={`tel:${profile.contact_phone}`}><Phone size={14}/>{profile.contact_phone}</a>}{profile.contact_email && <a href={`mailto:${profile.contact_email}`}><Mail size={14}/>Contato</a>}</div></header>
    <section className="public-hero"><div className="public-hero-copy"><span className="public-kicker">IMÓVEIS PARA VIVER BEM</span><h1>Encontre um lugar que combine com a sua próxima fase.</h1><p>Uma seleção enxuta de imóveis administrados com acompanhamento próximo e informações claras.</p></div>
      <form className="public-search" onSubmit={searchSubmit}><label><Search size={17}/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Bairro, cidade ou tipo de imóvel"/></label><select value={purpose} onChange={(e) => setPurpose(e.target.value as typeof purpose)}><option value="all">Todos</option><option value="rent">Alugar</option><option value="sale">Comprar</option></select><button type="submit">Buscar</button></form>
    </section>
    <section className="public-catalog"><div className="public-section-heading"><div><span className="public-kicker">PORTFÓLIO</span><h2>Imóveis disponíveis</h2></div><span>{filtered.length} resultado(s)</span></div>
      <div className="public-property-grid">{filtered.map((item) => <a className="public-property-card" href={`/site/${organizationId}/imoveis/${item.slug}`} key={item.slug}><div className="public-property-visual"><span>{propertyType(item.property_type)}</span><small>#{item.code}</small></div><div className="public-property-card-copy"><span className="public-card-purpose">{item.purpose === 'rent' ? 'Para alugar' : 'Para comprar'}</span><h3>{item.title}</h3><p><MapPin size={13}/>{publicLocation(item)}</p><div className="public-card-facts"><span><BedDouble size={14}/>{item.bedrooms}</span><span><Bath size={14}/>{item.bathrooms}</span><span><Car size={14}/>{item.parking_spaces}</span>{item.pets_allowed && <span><PawPrint size={14}/> pet</span>}</div><div className="public-card-price"><strong>{money(item.rent_amount)}</strong>{item.purpose === 'rent' && <span>/ mês</span>}</div></div></a>)}
        {filtered.length === 0 && <div className="public-empty"><Search size={24}/><strong>Nenhum imóvel neste filtro.</strong><span>Tente outro bairro, tipo ou finalidade.</span></div>}
      </div>
    </section>
    <footer className="public-footer"><strong>{profile.display_name}</strong><span>Catálogo conectado diretamente ao ERP. Somente imóveis aprovados para publicação aparecem aqui.</span></footer>
  </main>
}
