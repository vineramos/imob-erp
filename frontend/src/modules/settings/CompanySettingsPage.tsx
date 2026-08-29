import { Save } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { OrganizationProfile, OrganizationProfileUpdate } from '../../api/types'
import { authConfigured } from '../../auth/client'

type Props = {
  canEdit: boolean
}

type CompanyForm = OrganizationProfileUpdate

const emptyForm: CompanyForm = {
  legal_name: 'Imobiliária',
  display_name: 'Imobiliária',
  document_number: null,
  creci_pj: null,
  contact_email: null,
  contact_phone: null,
  address: {
    street: '',
    number: '',
    complement: '',
    neighborhood: '',
    city: '',
    state: '',
    postal_code: '',
  },
}

export function CompanySettingsPage({ canEdit }: Props) {
  const [form, setForm] = useState<CompanyForm>(emptyForm)
  const [loading, setLoading] = useState(authConfigured)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!authConfigured) return

    let active = true
    void apiRequest<OrganizationProfile>('/settings/company')
      .then((company) => {
        if (!active) return
        setForm({
          legal_name: company.legal_name,
          display_name: company.display_name,
          document_number: company.document_number,
          creci_pj: company.creci_pj,
          contact_email: company.contact_email,
          contact_phone: company.contact_phone,
          address: { ...emptyForm.address, ...company.address },
        })
      })
      .catch((cause) => {
        if (!active) return
        setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar os dados da empresa.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => { active = false }
  }, [])

  function update<K extends keyof CompanyForm>(key: K, value: CompanyForm[K]) {
    setMessage('')
    setError('')
    setForm((current) => ({ ...current, [key]: value }))
  }

  function updateAddress(key: string, value: string) {
    setMessage('')
    setError('')
    setForm((current) => ({
      ...current,
      address: { ...current.address, [key]: value },
    }))
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!canEdit) return

    if (!authConfigured) {
      setMessage('Pré-visualização local atualizada. A persistência será ativada com o Neon Auth.')
      return
    }

    setSaving(true)
    setMessage('')
    setError('')
    try {
      const saved = await apiRequest<OrganizationProfile>('/settings/company', {
        method: 'PUT',
        body: JSON.stringify(form),
      })
      setForm({
        legal_name: saved.legal_name,
        display_name: saved.display_name,
        document_number: saved.document_number,
        creci_pj: saved.creci_pj,
        contact_email: saved.contact_email,
        contact_phone: saved.contact_phone,
        address: { ...emptyForm.address, ...saved.address },
      })
      setMessage('Dados da empresa salvos e registrados na auditoria.')
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível salvar os dados da empresa.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="workspace settings-workspace">
      <form onSubmit={handleSubmit}>
        <div className="page-heading settings-heading">
          <div>
            <span className="eyebrow">Configurações · Institucional</span>
            <h1>Dados da empresa</h1>
            <p>Esses dados alimentam cabeçalhos, documentos, integrações e a identidade institucional do ERP.</p>
          </div>
          {canEdit && (
            <button className="button primary" type="submit" disabled={loading || saving}>
              <Save size={16} /> {saving ? 'Salvando...' : 'Salvar alterações'}
            </button>
          )}
        </div>

        {error && <div className="form-alert danger-alert">{error}</div>}
        {message && <div className="form-alert success-alert">{message}</div>}

        <article className="panel form-panel">
          <div className="panel-heading"><span className="eyebrow">Cadastro institucional</span><h2>Imobiliária</h2></div>
          {loading ? (
            <div className="settings-loading">Carregando dados da empresa...</div>
          ) : (
            <div className="form-grid two-columns">
              <label className="field"><span>Razão social</span><input disabled={!canEdit} required value={form.legal_name} onChange={(event) => update('legal_name', event.target.value)} /></label>
              <label className="field"><span>Nome fantasia</span><input disabled={!canEdit} required value={form.display_name} onChange={(event) => update('display_name', event.target.value)} /></label>
              <label className="field"><span>CNPJ</span><input disabled={!canEdit} placeholder="00.000.000/0000-00" value={form.document_number ?? ''} onChange={(event) => update('document_number', event.target.value || null)} /></label>
              <label className="field"><span>CRECI PJ</span><input disabled={!canEdit} placeholder="Registro da empresa" value={form.creci_pj ?? ''} onChange={(event) => update('creci_pj', event.target.value || null)} /></label>
              <label className="field"><span>E-mail institucional</span><input disabled={!canEdit} type="email" placeholder="contato@imobiliaria.com.br" value={form.contact_email ?? ''} onChange={(event) => update('contact_email', event.target.value || null)} /></label>
              <label className="field"><span>Telefone</span><input disabled={!canEdit} placeholder="(41) 0000-0000" value={form.contact_phone ?? ''} onChange={(event) => update('contact_phone', event.target.value || null)} /></label>
            </div>
          )}
        </article>

        {!loading && (
          <article className="panel form-panel company-address-panel">
            <div className="panel-heading"><span className="eyebrow">Localização</span><h2>Endereço</h2></div>
            <div className="form-grid address-grid">
              <label className="field address-street"><span>Logradouro</span><input disabled={!canEdit} value={form.address.street ?? ''} onChange={(event) => updateAddress('street', event.target.value)} /></label>
              <label className="field"><span>Número</span><input disabled={!canEdit} value={form.address.number ?? ''} onChange={(event) => updateAddress('number', event.target.value)} /></label>
              <label className="field"><span>Complemento</span><input disabled={!canEdit} value={form.address.complement ?? ''} onChange={(event) => updateAddress('complement', event.target.value)} /></label>
              <label className="field"><span>Bairro</span><input disabled={!canEdit} value={form.address.neighborhood ?? ''} onChange={(event) => updateAddress('neighborhood', event.target.value)} /></label>
              <label className="field"><span>Cidade</span><input disabled={!canEdit} value={form.address.city ?? ''} onChange={(event) => updateAddress('city', event.target.value)} /></label>
              <label className="field"><span>UF</span><input disabled={!canEdit} maxLength={2} value={form.address.state ?? ''} onChange={(event) => updateAddress('state', event.target.value.toUpperCase())} /></label>
              <label className="field"><span>CEP</span><input disabled={!canEdit} value={form.address.postal_code ?? ''} onChange={(event) => updateAddress('postal_code', event.target.value)} /></label>
            </div>
          </article>
        )}

        {!canEdit && <p className="read-only-note">Seu perfil possui acesso somente para consulta destas configurações.</p>}
      </form>
    </section>
  )
}
