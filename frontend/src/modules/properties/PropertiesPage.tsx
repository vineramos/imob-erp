import { Building2, Home, Pencil, Plus, Search, Trash2, UserRound, Users, X } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { Address, Person, PersonCreate, Property, PropertyCreate } from '../../api/types'

const emptyAddress = (): Address => ({ street: '', number: '', complement: '', neighborhood: '', city: 'Curitiba', state: 'PR', postal_code: '' })
const emptyPersonForm = (): PersonCreate => ({ person_type: 'individual', name: '', document_number: '', email: '', phone: '', address: emptyAddress(), notes: '', role_keys: ['owner'] })
const emptyPropertyForm = (): PropertyCreate => ({
  property_type: 'apartment', purpose: 'rent', status: 'draft', address: emptyAddress(), rent_amount: null, condo_amount: null, iptu_amount: null,
  area_m2: null, bedrooms: 0, suites: 0, bathrooms: 1, parking_spaces: 0, furnished: false, pets_allowed: false,
  public_title: '', public_description: '', publication_enabled: false, owners: [],
})

const propertyTypes = [
  ['apartment', 'Apartamento'], ['house', 'Casa'], ['commercial', 'Comercial'], ['land', 'Terreno'], ['studio', 'Studio'], ['other', 'Outro'],
] as const

const statusLabel: Record<string, string> = {
  draft: 'Rascunho', available: 'Disponível', reserved: 'Reservado', leased: 'Locado', inactive: 'Inativo',
}

const roleOptions = [
  ['owner', 'Proprietário'], ['tenant', 'Locatário'], ['guarantor', 'Garantidor'], ['broker', 'Corretor'], ['supplier', 'Fornecedor'], ['referrer', 'Angariador'],
] as const

type PersonRoleKey = PersonCreate['role_keys'][number]
type Props = { permissions: string[] }

function money(value: number | null) {
  if (value == null) return '—'
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function addressLine(address: Address) {
  return [address.street, address.number, address.neighborhood, address.city].filter(Boolean).join(', ') || 'Endereço não informado'
}

function roleLabel(role: string) {
  return roleOptions.find(([key]) => key === role)?.[1] ?? role
}

export function PropertiesPage({ permissions }: Props) {
  const granted = useMemo(() => new Set(permissions), [permissions])
  const canCreate = granted.has('properties.create')
  const canEdit = granted.has('properties.edit')
  const [tab, setTab] = useState<'properties' | 'people'>('properties')
  const [items, setItems] = useState<Property[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showPropertyForm, setShowPropertyForm] = useState(false)
  const [showPersonForm, setShowPersonForm] = useState(false)
  const [editingPropertyId, setEditingPropertyId] = useState<string | null>(null)
  const [editingPersonId, setEditingPersonId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [personForm, setPersonForm] = useState<PersonCreate>(emptyPersonForm)
  const [propertyForm, setPropertyForm] = useState<PropertyCreate>(emptyPropertyForm)

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

  useEffect(() => {
    if (!showPersonForm && !showPropertyForm) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || saving) return
      setShowPersonForm(false); setShowPropertyForm(false); setEditingPersonId(null); setEditingPropertyId(null); setError('')
    }
    window.addEventListener('keydown', onKeyDown)
    return () => { document.body.style.overflow = previousOverflow; window.removeEventListener('keydown', onKeyDown) }
  }, [showPersonForm, showPropertyForm, saving])

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

  const ownerTotal = useMemo(() => propertyForm.owners.reduce((total, owner) => total + Number(owner.ownership_percent || 0), 0), [propertyForm.owners])

  function closeModals() {
    if (saving) return
    setShowPersonForm(false); setShowPropertyForm(false); setEditingPersonId(null); setEditingPropertyId(null); setError('')
  }

  function openNewPerson() {
    setError(''); setEditingPersonId(null); setPersonForm(emptyPersonForm()); setShowPropertyForm(false); setShowPersonForm(true)
  }

  function openEditPerson(person: Person) {
    if (!canEdit) return
    setError(''); setEditingPersonId(person.id)
    setPersonForm({
      person_type: person.person_type, name: person.name, document_number: person.document_number ?? '', email: person.email ?? '', phone: person.phone ?? '',
      address: { ...emptyAddress(), ...person.address }, notes: person.notes ?? '', role_keys: person.role_keys as PersonRoleKey[],
    })
    setShowPropertyForm(false); setShowPersonForm(true)
  }

  function openNewProperty() {
    setError(''); setEditingPropertyId(null); setPropertyForm(emptyPropertyForm()); setShowPersonForm(false); setShowPropertyForm(true)
  }

  function openEditProperty(item: Property) {
    if (!canEdit) return
    setError(''); setEditingPropertyId(item.id)
    setPropertyForm({
      property_type: item.property_type as PropertyCreate['property_type'], purpose: item.purpose as PropertyCreate['purpose'], status: item.status as PropertyCreate['status'],
      address: { ...emptyAddress(), ...item.address }, rent_amount: item.rent_amount, condo_amount: item.condo_amount, iptu_amount: item.iptu_amount,
      area_m2: item.area_m2, bedrooms: item.bedrooms, suites: item.suites, bathrooms: item.bathrooms, parking_spaces: item.parking_spaces,
      furnished: item.furnished, pets_allowed: item.pets_allowed, public_title: item.public_title ?? '', public_description: '',
      publication_enabled: item.publication_enabled, owners: item.owners.map((owner) => ({ person_id: owner.person_id, ownership_percent: owner.ownership_percent })),
    })
    setShowPersonForm(false); setShowPropertyForm(true)
  }

  function updateAddress(target: 'person' | 'property', key: keyof Address, value: string) {
    if (target === 'person') setPersonForm((current) => ({ ...current, address: { ...current.address, [key]: value } }))
    else setPropertyForm((current) => ({ ...current, address: { ...current.address, [key]: value } }))
  }

  function togglePersonRole(role: PersonRoleKey) {
    setPersonForm((current) => ({ ...current, role_keys: current.role_keys.includes(role) ? current.role_keys.filter((item) => item !== role) : [...current.role_keys, role] }))
  }

  function addOwner() {
    setPropertyForm((current) => {
      const used = new Set(current.owners.map((owner) => owner.person_id))
      const available = people.find((person) => !used.has(person.id))
      if (!available) return current
      const nextCount = current.owners.length + 1
      const equal = Number((100 / nextCount).toFixed(4))
      const redistributed = current.owners.map((owner) => ({ ...owner, ownership_percent: equal }))
      const lastShare = Number((100 - equal * current.owners.length).toFixed(4))
      return { ...current, owners: [...redistributed, { person_id: available.id, ownership_percent: lastShare }] }
    })
  }

  function updateOwner(index: number, key: 'person_id' | 'ownership_percent', value: string) {
    setPropertyForm((current) => ({
      ...current,
      owners: current.owners.map((owner, ownerIndex) => ownerIndex === index ? { ...owner, [key]: key === 'ownership_percent' ? Number(value) : value } : owner),
    }))
  }

  function removeOwner(index: number) {
    setPropertyForm((current) => ({ ...current, owners: current.owners.filter((_, ownerIndex) => ownerIndex !== index) }))
  }

  async function savePerson(event: FormEvent) {
    event.preventDefault()
    const editing = editingPersonId !== null
    if ((editing && !canEdit) || (!editing && !canCreate)) return
    setSaving(true); setError('')
    try {
      const saved = await apiRequest<Person>(editing ? `/people/${editingPersonId}` : '/people', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(personForm) })
      setPeople((current) => (editing ? current.map((item) => item.id === saved.id ? saved : item) : [...current, saved]).sort((a, b) => a.name.localeCompare(b.name)))
      setTab('people'); setShowPersonForm(false); setEditingPersonId(null); setPersonForm(emptyPersonForm())
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : editing ? 'Não foi possível atualizar a pessoa.' : 'Não foi possível cadastrar a pessoa.')
    } finally { setSaving(false) }
  }

  async function saveProperty(event: FormEvent) {
    event.preventDefault()
    const editing = editingPropertyId !== null
    if ((editing && !canEdit) || (!editing && !canCreate)) return
    setSaving(true); setError('')
    try {
      const body = editing ? {
        property_type: propertyForm.property_type, purpose: propertyForm.purpose, status: propertyForm.status, address: propertyForm.address,
        rent_amount: propertyForm.rent_amount, condo_amount: propertyForm.condo_amount, iptu_amount: propertyForm.iptu_amount, area_m2: propertyForm.area_m2,
        bedrooms: propertyForm.bedrooms, suites: propertyForm.suites, bathrooms: propertyForm.bathrooms, parking_spaces: propertyForm.parking_spaces,
        furnished: propertyForm.furnished, pets_allowed: propertyForm.pets_allowed, public_title: propertyForm.public_title, owners: propertyForm.owners,
      } : propertyForm
      const saved = await apiRequest<Property>(editing ? `/properties/${editingPropertyId}` : '/properties', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(body) })
      setItems((current) => editing ? current.map((item) => item.id === saved.id ? saved : item) : [saved, ...current])
      setTab('properties'); setShowPropertyForm(false); setEditingPropertyId(null); setPropertyForm(emptyPropertyForm())
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : editing ? 'Não foi possível atualizar o imóvel.' : 'Não foi possível cadastrar o imóvel.')
    } finally { setSaving(false) }
  }

  return (
    <section className="workspace portfolio-workspace">
      <div className="page-heading portfolio-heading">
        <div><span className="eyebrow">Carteira imobiliária</span><h1>Imóveis e pessoas</h1><p>Um único cadastro de pessoa pode assumir papéis diferentes ao longo da operação, sem duplicidade.</p></div>
        {canCreate && <div className="heading-actions"><button className="button secondary" type="button" onClick={openNewPerson}><UserRound size={15}/> Nova pessoa</button><button className="button primary" type="button" onClick={openNewProperty}><Plus size={15}/> Novo imóvel</button></div>}
      </div>

      {error && !showPersonForm && !showPropertyForm && <div className="form-alert danger-alert">{error}</div>}

      <div className="portfolio-toolbar panel">
        <div className="portfolio-tabs"><button className={tab === 'properties' ? 'active' : ''} onClick={() => setTab('properties')} type="button"><Home size={15}/> Imóveis <span>{items.length}</span></button><button className={tab === 'people' ? 'active' : ''} onClick={() => setTab('people')} type="button"><Users size={15}/> Pessoas <span>{people.length}</span></button></div>
        <label className="portfolio-search"><Search size={15}/><input placeholder={tab === 'properties' ? 'Buscar por código, título ou endereço...' : 'Buscar por nome, CPF/CNPJ ou e-mail...'} value={query} onChange={(event) => setQuery(event.target.value)}/></label>
      </div>

      {loading ? <article className="panel settings-loading">Carregando carteira...</article> : tab === 'properties' ? (
        <div className="portfolio-card-list">{filteredProperties.map((item) => <article className="panel property-row" key={item.id}><div className="property-code"><Home size={17}/><span>IMÓVEL</span><strong>{item.code}</strong></div><div className="property-main"><strong>{item.public_title || `${propertyTypes.find(([key]) => key === item.property_type)?.[1] ?? 'Imóvel'} em ${item.address.neighborhood || item.address.city}`}</strong><span>{addressLine(item.address)}</span><small>{item.owners.length ? item.owners.map((owner) => owner.name).join(' · ') : 'Proprietário ainda não vinculado'}</small></div><div className="property-values"><span>Aluguel</span><strong>{money(item.rent_amount)}</strong></div><div className="property-status"><i className={`status-badge ${item.status === 'available' ? 'success' : item.status === 'leased' ? 'neutral' : 'warning'}`}>{statusLabel[item.status] ?? item.status}</i><span>{item.area_m2 ? `${item.area_m2} m²` : 'Área —'} · {item.bedrooms} qto(s)</span></div>{canEdit && <button className="portfolio-edit-button" type="button" onClick={() => openEditProperty(item)} aria-label={`Editar imóvel ${item.code}`} title="Editar imóvel"><Pencil size={14}/></button>}</article>)}{filteredProperties.length === 0 && <article className="panel portfolio-empty"><Home size={26}/><strong>Nenhum imóvel encontrado.</strong><span>Cadastre o primeiro imóvel para iniciar a carteira.</span></article>}</div>
      ) : (
        <div className="portfolio-card-list">{filteredPeople.map((person) => <article className="panel person-row" key={person.id}><div className="avatar avatar-user">{person.name.trim().slice(0,2).toUpperCase()}</div><div className="person-main"><strong>{person.name}</strong><span>{person.document_number || 'Documento não informado'} · {person.email || 'E-mail não informado'}</span></div><div className="person-roles">{person.role_keys.length ? person.role_keys.map((role) => <i className="permission-chip" key={role}>{roleLabel(role)}</i>) : <span>Sem papel operacional</span>}</div>{canEdit && <button className="portfolio-edit-button" type="button" onClick={() => openEditPerson(person)} aria-label={`Editar ${person.name}`} title="Editar pessoa"><Pencil size={14}/></button>}</article>)}{filteredPeople.length === 0 && <article className="panel portfolio-empty"><Users size={26}/><strong>Nenhuma pessoa encontrada.</strong><span>O cadastro de pessoas é único e será reutilizado em contratos, garantias e fornecedores.</span></article>}</div>
      )}

      {showPersonForm && <div className="portfolio-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeModals() }}><form className="panel portfolio-modal" onSubmit={savePerson} role="dialog" aria-modal="true" aria-labelledby="person-modal-title"><div className="portfolio-modal-header"><div><span className="eyebrow">Cadastro canônico</span><h2 id="person-modal-title">{editingPersonId ? 'Editar pessoa' : 'Nova pessoa'}</h2><p>{editingPersonId ? 'Atualize o cadastro único sem perder os vínculos já existentes.' : 'Cadastre uma pessoa uma única vez e reutilize os papéis ao longo da operação.'}</p></div><button className="portfolio-modal-close" type="button" onClick={closeModals} disabled={saving} aria-label="Fechar"><X size={18}/></button></div><div className="portfolio-modal-body">{error && <div className="form-alert danger-alert">{error}</div>}<div className="form-grid three-columns"><label className="field"><span>Tipo</span><select value={personForm.person_type} onChange={(e) => setPersonForm((c) => ({ ...c, person_type: e.target.value as PersonCreate['person_type'] }))}><option value="individual">Pessoa física</option><option value="company">Pessoa jurídica</option></select></label><label className="field field-span-2"><span>Nome / Razão social</span><input autoFocus required value={personForm.name} onChange={(e) => setPersonForm((c) => ({ ...c, name: e.target.value }))}/></label><label className="field"><span>CPF / CNPJ</span><input value={personForm.document_number ?? ''} onChange={(e) => setPersonForm((c) => ({ ...c, document_number: e.target.value }))}/></label><label className="field"><span>E-mail</span><input type="email" value={personForm.email ?? ''} onChange={(e) => setPersonForm((c) => ({ ...c, email: e.target.value }))}/></label><label className="field"><span>Telefone</span><input value={personForm.phone ?? ''} onChange={(e) => setPersonForm((c) => ({ ...c, phone: e.target.value }))}/></label><label className="field field-span-2"><span>Rua</span><input value={personForm.address.street} onChange={(e) => updateAddress('person', 'street', e.target.value)}/></label><label className="field"><span>Número</span><input value={personForm.address.number} onChange={(e) => updateAddress('person', 'number', e.target.value)}/></label><label className="field"><span>Complemento</span><input value={personForm.address.complement} onChange={(e) => updateAddress('person', 'complement', e.target.value)}/></label><label className="field"><span>Bairro</span><input value={personForm.address.neighborhood} onChange={(e) => updateAddress('person', 'neighborhood', e.target.value)}/></label><label className="field"><span>CEP</span><input value={personForm.address.postal_code} onChange={(e) => updateAddress('person', 'postal_code', e.target.value)}/></label><label className="field"><span>Cidade</span><input value={personForm.address.city} onChange={(e) => updateAddress('person', 'city', e.target.value)}/></label><label className="field"><span>UF</span><input maxLength={2} value={personForm.address.state} onChange={(e) => updateAddress('person', 'state', e.target.value.toUpperCase())}/></label><div className="field field-span-3"><span>Papéis na operação</span><div className="portfolio-role-grid">{roleOptions.map(([key, label]) => <label className="portfolio-role-option" key={key}><input type="checkbox" checked={personForm.role_keys.includes(key)} onChange={() => togglePersonRole(key)}/><span>{label}</span></label>)}</div></div><label className="field field-span-3"><span>Observações</span><textarea rows={3} maxLength={2000} value={personForm.notes ?? ''} onChange={(e) => setPersonForm((c) => ({ ...c, notes: e.target.value }))}/></label></div></div><div className="form-actions portfolio-modal-actions"><button className="button secondary" type="button" onClick={closeModals} disabled={saving}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving ? 'Salvando...' : editingPersonId ? 'Salvar alterações' : 'Cadastrar pessoa'}</button></div></form></div>}

      {showPropertyForm && <div className="portfolio-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeModals() }}><form className="panel portfolio-modal portfolio-property-modal" onSubmit={saveProperty} role="dialog" aria-modal="true" aria-labelledby="property-modal-title"><div className="portfolio-modal-header"><div><span className="eyebrow">Carteira imobiliária</span><h2 id="property-modal-title">{editingPropertyId ? `Editar imóvel ${items.find((item) => item.id === editingPropertyId)?.code ?? ''}` : 'Novo imóvel'}</h2><p>{editingPropertyId ? 'Ajuste os dados cadastrais. Status Locado continua controlado pelo fluxo contratual.' : 'Cadastre os dados principais do imóvel sem sair da carteira.'}</p></div><button className="portfolio-modal-close" type="button" onClick={closeModals} disabled={saving} aria-label="Fechar"><X size={18}/></button></div><div className="portfolio-modal-body">{error && <div className="form-alert danger-alert">{error}</div>}<div className="form-grid three-columns"><label className="field"><span>Tipo do imóvel</span><select value={propertyForm.property_type} onChange={(e) => setPropertyForm((c) => ({ ...c, property_type: e.target.value as PropertyCreate['property_type'] }))}>{propertyTypes.map(([value,label]) => <option value={value} key={value}>{label}</option>)}</select></label><label className="field"><span>Finalidade</span><select value={propertyForm.purpose} onChange={(e) => setPropertyForm((c) => ({ ...c, purpose: e.target.value as PropertyCreate['purpose'] }))}><option value="rent">Locação</option><option value="sale">Venda</option></select></label><label className="field"><span>Status</span><select disabled={editingPropertyId !== null && propertyForm.status === 'leased'} value={propertyForm.status} onChange={(e) => setPropertyForm((c) => ({ ...c, status: e.target.value as PropertyCreate['status'] }))}>{propertyForm.status === 'leased' ? <option value="leased">Locado — controlado pelo contrato</option> : <><option value="draft">Rascunho</option><option value="available">Disponível</option><option value="reserved">Reservado</option><option value="inactive">Inativo</option></>}</select></label><label className="field field-span-3"><span>Título do imóvel</span><input value={propertyForm.public_title ?? ''} onChange={(e) => setPropertyForm((c) => ({ ...c, public_title: e.target.value }))} placeholder="Ex.: Sobrado no Pilarzinho - 3 Quartos"/></label><label className="field field-span-2"><span>Rua</span><input autoFocus required value={propertyForm.address.street} onChange={(e) => updateAddress('property', 'street', e.target.value)}/></label><label className="field"><span>Número</span><input value={propertyForm.address.number} onChange={(e) => updateAddress('property', 'number', e.target.value)}/></label><label className="field"><span>Complemento</span><input value={propertyForm.address.complement} onChange={(e) => updateAddress('property', 'complement', e.target.value)}/></label><label className="field"><span>Bairro</span><input value={propertyForm.address.neighborhood} onChange={(e) => updateAddress('property', 'neighborhood', e.target.value)}/></label><label className="field"><span>CEP</span><input value={propertyForm.address.postal_code} onChange={(e) => updateAddress('property', 'postal_code', e.target.value)}/></label><label className="field"><span>Cidade</span><input value={propertyForm.address.city} onChange={(e) => updateAddress('property', 'city', e.target.value)}/></label><label className="field"><span>UF</span><input maxLength={2} value={propertyForm.address.state} onChange={(e) => updateAddress('property', 'state', e.target.value.toUpperCase())}/></label><label className="field"><span>Aluguel</span><input min="0" step="0.01" type="number" value={propertyForm.rent_amount ?? ''} onChange={(e) => setPropertyForm((c) => ({ ...c, rent_amount: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field"><span>Condomínio</span><input min="0" step="0.01" type="number" value={propertyForm.condo_amount ?? ''} onChange={(e) => setPropertyForm((c) => ({ ...c, condo_amount: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field"><span>IPTU mensal</span><input min="0" step="0.01" type="number" value={propertyForm.iptu_amount ?? ''} onChange={(e) => setPropertyForm((c) => ({ ...c, iptu_amount: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field"><span>Área m²</span><input min="0" step="0.01" type="number" value={propertyForm.area_m2 ?? ''} onChange={(e) => setPropertyForm((c) => ({ ...c, area_m2: e.target.value ? Number(e.target.value) : null }))}/></label><label className="field"><span>Quartos</span><input min="0" type="number" value={propertyForm.bedrooms} onChange={(e) => setPropertyForm((c) => ({ ...c, bedrooms: Number(e.target.value) }))}/></label><label className="field"><span>Suítes</span><input min="0" type="number" value={propertyForm.suites} onChange={(e) => setPropertyForm((c) => ({ ...c, suites: Number(e.target.value) }))}/></label><label className="field"><span>Banheiros</span><input min="0" type="number" value={propertyForm.bathrooms} onChange={(e) => setPropertyForm((c) => ({ ...c, bathrooms: Number(e.target.value) }))}/></label><label className="field"><span>Vagas</span><input min="0" type="number" value={propertyForm.parking_spaces} onChange={(e) => setPropertyForm((c) => ({ ...c, parking_spaces: Number(e.target.value) }))}/></label><div className="field"><span>Características</span><div className="portfolio-checkbox-row"><label><input type="checkbox" checked={propertyForm.furnished} onChange={(e) => setPropertyForm((c) => ({ ...c, furnished: e.target.checked }))}/> Mobiliado</label><label><input type="checkbox" checked={propertyForm.pets_allowed} onChange={(e) => setPropertyForm((c) => ({ ...c, pets_allowed: e.target.checked }))}/> Aceita pets</label></div></div><div className="field field-span-3"><div className="portfolio-section-heading"><div><span>Proprietários</span><small>A participação deve totalizar 100%.</small></div><button className="button secondary compact-button" type="button" onClick={addOwner} disabled={people.length === propertyForm.owners.length}><Plus size={13}/> Adicionar</button></div>{propertyForm.owners.length ? <div className="portfolio-owner-list">{propertyForm.owners.map((owner, index) => <div className="portfolio-owner-row" key={`${owner.person_id}-${index}`}><select required value={owner.person_id} onChange={(e) => updateOwner(index, 'person_id', e.target.value)}>{people.map((person) => <option key={person.id} value={person.id} disabled={propertyForm.owners.some((candidate, candidateIndex) => candidateIndex !== index && candidate.person_id === person.id)}>{person.name}</option>)}</select><label><input min="0.01" max="100" step="0.0001" type="number" value={owner.ownership_percent} onChange={(e) => updateOwner(index, 'ownership_percent', e.target.value)}/><span>%</span></label><button type="button" className="portfolio-owner-remove" onClick={() => removeOwner(index)} aria-label="Remover proprietário"><Trash2 size={14}/></button></div>)}</div> : <div className="portfolio-owner-empty">Nenhum proprietário vinculado.</div>}<div className={`portfolio-owner-total ${propertyForm.owners.length && Math.abs(ownerTotal - 100) > 0.0001 ? 'invalid' : ''}`}><span>Total</span><strong>{ownerTotal.toLocaleString('pt-BR', { maximumFractionDigits: 4 })}%</strong></div></div></div></div><div className="form-actions portfolio-modal-actions"><button className="button secondary" type="button" onClick={closeModals} disabled={saving}>Cancelar</button><button className="button primary" disabled={saving || (propertyForm.owners.length > 0 && Math.abs(ownerTotal - 100) > 0.0001)} type="submit">{saving ? 'Salvando...' : editingPropertyId ? 'Salvar alterações' : 'Cadastrar imóvel'}</button></div></form></div>}
    </section>
  )
}
