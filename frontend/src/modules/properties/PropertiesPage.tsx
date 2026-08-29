import { Building2, Home, Plus, Search, UserRound, Users } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { Address, Person, PersonCreate, Property, PropertyCreate } from '../../api/types'

const emptyAddress = (): Address => ({ street: '', number: '', complement: '', neighborhood: '', city: 'Curitiba', state: 'PR', postal_code: '' })

const propertyTypes = [
  ['apartment', 'Apartamento'], ['house', 'Casa'], ['commercial', 'Comercial'], ['land', 'Terreno'], ['studio', 'Studio'], ['other', 'Outro'],
] as const

const statusLabel: Record<string, string> = {
  draft: 'Rascunho', available: 'Disponível', reserved: 'Reservado', leased: 'Locado', inactive: 'Inativo',
}

function money(value: number | null) {
  if (value == null) return '—'
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function addressLine(address: Address) {
  return [address.street, address.number, address.neighborhood, address.city].filter(Boolean).join(', ') || 'Endereço não informado'
}

type Props = { permissions: string[] }

export function PropertiesPage({ permissions }: Props) {
  const granted = useMemo(() => new Set(permissions), [permissions])
  const canCreate = granted.has('properties.create')
  const [tab, setTab] = useState<'properties' | 'people'>('properties')
  const [items, setItems] = useState<Property[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showPropertyForm, setShowPropertyForm] = useState(false)
  const [showPersonForm, setShowPersonForm] = useState(false)
  const [saving, setSaving] = useState(false)

  const [personForm, setPersonForm] = useState<PersonCreate>({
    person_type: 'individual', name: '', document_number: '', email: '', phone: '', address: emptyAddress(), notes: '', role_keys: ['owner'],
  })
  const [propertyForm, setPropertyForm] = useState<PropertyCreate>({
    property_type: 'apartment', purpose: 'rent', status: 'draft', address: emptyAddress(), rent_amount: null, condo_amount: null, iptu_amount: null,
    area_m2: null, bedrooms: 0, suites: 0, bathrooms: 1, parking_spaces: 0, furnished: false, pets_allowed: false,
    public_title: '', public_description: '', publication_enabled: false, owners: [],
  })

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [loadedProperties, loadedPeople] = await Promise.all([
        apiRequest<Property[]>('/properties'),
        apiRequest<Person[]>('/people'),
      ])
      setItems(loadedProperties)
      setPeople(loadedPeople)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar imóveis e pessoas.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const filteredProperties = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return items
    return items.filter((item) => `${item.code} ${item.public_title ?? ''} ${addressLine(item.address)}`.toLowerCase().includes(term))
  }, [items, query])

  const filteredPeople = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return people
    return people.filter((person) => `${person.name} ${person.document_number ?? ''} ${person.email ?? ''}`.toLowerCase().includes(term))
  }, [people, query])

  function updateAddress(target: 'person' | 'property', key: keyof Address, value: string) {
    if (target === 'person') setPersonForm((current) => ({ ...current, address: { ...current.address, [key]: value } }))
    else setPropertyForm((current) => ({ ...current, address: { ...current.address, [key]: value } }))
  }

  async function savePerson(event: FormEvent) {
    event.preventDefault()
    if (!canCreate) return
    setSaving(true); setError('')
    try {
      const created = await apiRequest<Person>('/people', { method: 'POST', body: JSON.stringify(personForm) })
      setPeople((current) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)))
      setPersonForm({ person_type: 'individual', name: '', document_number: '', email: '', phone: '', address: emptyAddress(), notes: '', role_keys: ['owner'] })
      setShowPersonForm(false)
      setTab('people')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível cadastrar a pessoa.')
    } finally { setSaving(false) }
  }

  async function saveProperty(event: FormEvent) {
    event.preventDefault()
    if (!canCreate) return
    setSaving(true); setError('')
    try {
      const created = await apiRequest<Property>('/properties', { method: 'POST', body: JSON.stringify(propertyForm) })
      setItems((current) => [created, ...current])
      setPropertyForm({ property_type: 'apartment', purpose: 'rent', status: 'draft', address: emptyAddress(), rent_amount: null, condo_amount: null, iptu_amount: null, area_m2: null, bedrooms: 0, suites: 0, bathrooms: 1, parking_spaces: 0, furnished: false, pets_allowed: false, public_title: '', public_description: '', publication_enabled: false, owners: [] })
      setShowPropertyForm(false)
      setTab('properties')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível cadastrar o imóvel.')
    } finally { setSaving(false) }
  }

  function selectOwner(personId: string) {
    setPropertyForm((current) => ({ ...current, owners: personId ? [{ person_id: personId, ownership_percent: 100 }] : [] }))
  }

  return (
    <section className="workspace portfolio-workspace">
      <div className="page-heading portfolio-heading">
        <div><span className="eyebrow">Carteira imobiliária</span><h1>Imóveis e pessoas</h1><p>Um único cadastro de pessoa pode assumir papéis diferentes ao longo da operação, sem duplicidade.</p></div>
        {canCreate && <div className="heading-actions"><button className="button secondary" type="button" onClick={() => { setShowPersonForm(true); setShowPropertyForm(false) }}><UserRound size={15}/> Nova pessoa</button><button className="button primary" type="button" onClick={() => { setShowPropertyForm(true); setShowPersonForm(false) }}><Plus size={15}/> Novo imóvel</button></div>}
      </div>

      {error && <div className="form-alert danger-alert">{error}</div>}

      <div className="portfolio-toolbar panel">
        <div className="portfolio-tabs"><button className={tab === 'properties' ? 'active' : ''} onClick={() => setTab('properties')} type="button"><Home size={15}/> Imóveis <span>{items.length}</span></button><button className={tab === 'people' ? 'active' : ''} onClick={() => setTab('people')} type="button"><Users size={15}/> Pessoas <span>{people.length}</span></button></div>
        <label className="portfolio-search"><Search size={15}/><input placeholder={tab === 'properties' ? 'Buscar por código, título ou endereço...' : 'Buscar por nome, CPF/CNPJ ou e-mail...'} value={query} onChange={(event) => setQuery(event.target.value)}/></label>
      </div>

      {showPersonForm && <form className="panel portfolio-form" onSubmit={savePerson}><div className="panel-heading panel-heading-row"><div><span className="eyebrow">Cadastro canônico</span><h2>Nova pessoa</h2></div><UserRound size={20}/></div><div className="form-grid three-columns"><label className="field"><span>Tipo</span><select value={personForm.person_type} onChange={(e) => setPersonForm((c) => ({ ...c, person_type: e.target.value as PersonCreate['person_type'] }))}><option value="individual">Pessoa física</option><option value="company">Pessoa jurídica</option></select></label><label className="field field-span-2"><span>Nome / Razão social</span><input required value={personForm.name} onChange={(e) => setPersonForm((c) => ({ ...c, name: e.target.value }))}/></label><label className="field"><span>CPF / CNPJ</span><input value={personForm.document_number ?? ''} onChange={(e) => setPersonForm((c) => ({ ...c, document_number: e.target.value }))}/></label><label className="field"><span>E-mail</span><input type="email" value={personForm.email ?? ''} onChange={(e) => setPersonForm((c) => ({ ...c, email: e.target.value }))}/></label><label className="field"><span>Telefone</span><input value={personForm.phone ?? ''} onChange={(e) => setPersonForm((c) => ({ ...c, phone: e.target.value }))}/></label><label className="field field-span-2"><span>Rua</span><input value={personForm.address.street} onChange={(e) => updateAddress('person', 'street', e.target.value)}/></label><label className="field"><span>Número</span><input value={personForm.address.number} onChange={(e) => updateAddress('person', 'number', e.target.value)}/></label><label className="field"><span>Bairro</span><input value={personForm.address.neighborhood} onChange={(e) => updateAddress('person', 'neighborhood', e.target.value)}/></label><label className="field"><span>Cidade</span><input value={personForm.address.city} onChange={(e) => updateAddress('person', 'city', e.target.value)}/></label><label className="field"><span>UF</span><input maxLength={2} value={personForm.address.state} onChange={(e) => updateAddress('person', 'state', e.target.value.toUpperCase())}/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={() => setShowPersonForm(false)}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : 'Cadastrar pessoa'}</button></div></form>}

      {showPropertyForm && <form className="panel portfolio-form" onSubmit={saveProperty}><div className="panel-heading panel-heading-row"><div><span className="eyebrow">Carteira</span><h2>Novo imóvel</h2></div><Building2 size={20}/></div><div className="form-grid three-columns"><label className="field"><span>Tipo do imóvel</span><select value={propertyForm.property_type} onChange={(e) => setPropertyForm((c) => ({ ...c, property_type: e.target.value as PropertyCreate['property_type'] }))}>{propertyTypes.map(([value,label]) => <option value={value} key={value}>{label}</option>)}</select></label><label className="field"><span>Status inicial</span><select value={propertyForm.status} onChange={(e) => setPropertyForm((c) => ({ ...c, status: e.target.value as PropertyCreate['status'] }))}><option value="draft">Rascunho</option><option value="available">Disponível</option></select></label><label className="field"><span>Proprietário</span><select value={propertyForm.owners[0]?.person_id ?? ''} onChange={(e) => selectOwner(e.target.value)}><option value="">Sem proprietário vinculado</option>{people.filter((p) => p.role_keys.includes('owner')).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label className="field field-span-2"><span>Rua</span><input required value={propertyForm.address.street} onChange={(e) => updateAddress('property', 'street', e.target.value)}/></label><label className="field"><span>Número</span><input value={propertyForm.address.number} onChange={(e) => updateAddress('property', 'number', e.target.value)}/></label><label className="field"><span>Bairro</span><input value={propertyForm.address.neighborhood} onChange={(e) => updateAddress('property', 'neighborhood', e.target.value)}/></label><label className="field"><span>Cidade</span><input value={propertyForm.address.city} onChange={(e) => updateAddress('property', 'city', e.target.value)}/></label><label className="field"><span>CEP</span><input value={propertyForm.address.postal_code} onChange={(e) => updateAddress('property', 'postal_code', e.target.value)}/></label><label className="field"><span>Aluguel</span><input min="0" step="0.01" type="number" value={propertyForm.rent_amount ?? ''} onChange={(e) => setPropertyForm((c) => ({ ...c, rent_amount: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field"><span>Condomínio</span><input min="0" step="0.01" type="number" value={propertyForm.condo_amount ?? ''} onChange={(e) => setPropertyForm((c) => ({ ...c, condo_amount: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field"><span>IPTU mensal</span><input min="0" step="0.01" type="number" value={propertyForm.iptu_amount ?? ''} onChange={(e) => setPropertyForm((c) => ({ ...c, iptu_amount: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field"><span>Área m²</span><input min="0" step="0.01" type="number" value={propertyForm.area_m2 ?? ''} onChange={(e) => setPropertyForm((c) => ({ ...c, area_m2: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field"><span>Quartos</span><input min="0" type="number" value={propertyForm.bedrooms} onChange={(e) => setPropertyForm((c) => ({ ...c, bedrooms: Number(e.target.value) }))}/></label><label className="field"><span>Vagas</span><input min="0" type="number" value={propertyForm.parking_spaces} onChange={(e) => setPropertyForm((c) => ({ ...c, parking_spaces: Number(e.target.value) }))}/></label></div><div className="form-actions"><button className="button secondary" type="button" onClick={() => setShowPropertyForm(false)}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : 'Cadastrar imóvel'}</button></div></form>}

      {loading ? <article className="panel settings-loading">Carregando carteira...</article> : tab === 'properties' ? (
        <div className="portfolio-card-list">{filteredProperties.map((item) => <article className="panel property-row" key={item.id}><div className="property-code"><Home size={17}/><span>IMÓVEL</span><strong>{item.code}</strong></div><div className="property-main"><strong>{item.public_title || `${propertyTypes.find(([key]) => key === item.property_type)?.[1] ?? 'Imóvel'} em ${item.address.neighborhood || item.address.city}`}</strong><span>{addressLine(item.address)}</span><small>{item.owners.length ? item.owners.map((owner) => owner.name).join(' · ') : 'Proprietário ainda não vinculado'}</small></div><div className="property-values"><span>Aluguel</span><strong>{money(item.rent_amount)}</strong></div><div className="property-status"><i className={`status-badge ${item.status === 'available' ? 'success' : item.status === 'leased' ? 'neutral' : 'warning'}`}>{statusLabel[item.status] ?? item.status}</i><span>{item.area_m2 ? `${item.area_m2} m²` : 'Área —'} · {item.bedrooms} qto(s)</span></div></article>)}{filteredProperties.length === 0 && <article className="panel portfolio-empty"><Home size={26}/><strong>Nenhum imóvel encontrado.</strong><span>Cadastre o primeiro imóvel para iniciar a carteira.</span></article>}</div>
      ) : (
        <div className="portfolio-card-list">{filteredPeople.map((person) => <article className="panel person-row" key={person.id}><div className="avatar avatar-user">{person.name.trim().slice(0,2).toUpperCase()}</div><div className="person-main"><strong>{person.name}</strong><span>{person.document_number || 'Documento não informado'} · {person.email || 'E-mail não informado'}</span></div><div className="person-roles">{person.role_keys.length ? person.role_keys.map((role) => <i className="permission-chip" key={role}>{role === 'owner' ? 'Proprietário' : role}</i>) : <span>Sem papel operacional</span>}</div></article>)}{filteredPeople.length === 0 && <article className="panel portfolio-empty"><Users size={26}/><strong>Nenhuma pessoa encontrada.</strong><span>O cadastro de pessoas é único e será reutilizado em contratos, garantias e fornecedores.</span></article>}</div>
      )}
    </section>
  )
}
