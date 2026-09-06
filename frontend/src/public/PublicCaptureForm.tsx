import { CheckCircle2, Send, ShieldCheck } from 'lucide-react'
import { FormEvent, useState } from 'react'
import { ApiError, publicApiRequest } from '../api/client'
import './public-capture.css'

type CaptureAck = { accepted: boolean; message: string }
type PreferredContact = 'whatsapp' | 'phone' | 'email'
type PropertyType = 'apartment' | 'house' | 'commercial' | 'land' | 'studio' | 'other'

function moneyNumber(value: string) {
  const normalized = value.trim().replace(/\./g, '').replace(',', '.')
  const parsed = Number(normalized || 0)
  return Number.isFinite(parsed) ? parsed : 0
}

export function PublicCaptureForm({ organizationId }: { organizationId: string }) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [preferredContact, setPreferredContact] = useState<PreferredContact>('whatsapp')
  const [propertyType, setPropertyType] = useState<PropertyType>('apartment')
  const [street, setStreet] = useState('')
  const [number, setNumber] = useState('')
  const [complement, setComplement] = useState('')
  const [neighborhood, setNeighborhood] = useState('')
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [postalCode, setPostalCode] = useState('')
  const [estimatedRent, setEstimatedRent] = useState('')
  const [message, setMessage] = useState('')
  const [consent, setConsent] = useState(false)
  const [website, setWebsite] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) { setError('Informe seu nome.'); return }
    if (!phone.trim() && !email.trim()) { setError('Informe telefone ou e-mail para contato.'); return }
    if (preferredContact === 'email' && !email.trim()) { setError('Informe o e-mail escolhido para contato.'); return }
    if ((preferredContact === 'phone' || preferredContact === 'whatsapp') && !phone.trim()) { setError('Informe o telefone escolhido para contato.'); return }
    if (!street.trim() || !neighborhood.trim() || !city.trim() || state.trim().length !== 2) { setError('Informe o endereço do imóvel, incluindo bairro, cidade e UF.'); return }
    if (!consent) { setError('Autorize o contato para enviar os dados do imóvel.'); return }

    setSubmitting(true)
    setError('')
    try {
      const response = await publicApiRequest<CaptureAck>(`/public/sites/${organizationId}/captures`, {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          phone: phone.trim() || null,
          email: email.trim() || null,
          preferred_contact: preferredContact,
          property_type: propertyType,
          address: {
            street: street.trim(),
            number: number.trim(),
            complement: complement.trim(),
            neighborhood: neighborhood.trim(),
            city: city.trim(),
            state: state.trim().toUpperCase(),
            postal_code: postalCode.trim(),
          },
          estimated_rent: estimatedRent.trim() ? moneyNumber(estimatedRent) : null,
          message: message.trim() || null,
          consent,
          website,
        }),
      })
      setSuccess(response.message)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível enviar os dados do imóvel. Tente novamente.')
    } finally { setSubmitting(false) }
  }

  if (success) return <div className="public-capture-success" role="status">
    <CheckCircle2 size={32}/>
    <div>
      <strong>Imóvel enviado para captação</strong>
      <p>{success}</p>
      <small>O envio cria uma oportunidade de captação. O imóvel só entra no catálogo depois da análise e aprovação da imobiliária.</small>
    </div>
  </div>

  return <form className="public-capture-form" onSubmit={submit}>
    <div className="public-capture-heading"><span>CADASTRO PARA CAPTAÇÃO</span><strong>Conte sobre o seu imóvel</strong><small>A equipe recebe esta solicitação diretamente em Captações no Imob ERP.</small></div>

    <div className="public-capture-grid">
      <label><span>Seu nome *</span><input autoComplete="name" maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Nome do proprietário"/></label>
      <label><span>WhatsApp / telefone</span><input autoComplete="tel" maxLength={40} value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="(41) 99999-9999"/></label>
      <label><span>E-mail</span><input autoComplete="email" type="email" maxLength={180} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="voce@email.com"/></label>
      <label><span>Prefiro contato por</span><select value={preferredContact} onChange={(event) => setPreferredContact(event.target.value as PreferredContact)}><option value="whatsapp">WhatsApp</option><option value="phone">Ligação</option><option value="email">E-mail</option></select></label>
      <label><span>Tipo do imóvel *</span><select value={propertyType} onChange={(event) => setPropertyType(event.target.value as PropertyType)}><option value="apartment">Apartamento</option><option value="house">Casa</option><option value="commercial">Comercial</option><option value="land">Terreno</option><option value="studio">Studio</option><option value="other">Outro</option></select></label>
      <label><span>Aluguel pretendido</span><input inputMode="decimal" value={estimatedRent} onChange={(event) => setEstimatedRent(event.target.value)} placeholder="Ex.: 2.500,00"/></label>
      <label className="wide"><span>Rua / avenida *</span><input autoComplete="street-address" maxLength={180} value={street} onChange={(event) => setStreet(event.target.value)} placeholder="Endereço do imóvel"/></label>
      <label><span>Número</span><input maxLength={30} value={number} onChange={(event) => setNumber(event.target.value)} placeholder="Ex.: 123"/></label>
      <label><span>Complemento</span><input maxLength={120} value={complement} onChange={(event) => setComplement(event.target.value)} placeholder="Apto, bloco, sala..."/></label>
      <label><span>Bairro *</span><input maxLength={120} value={neighborhood} onChange={(event) => setNeighborhood(event.target.value)} placeholder="Bairro"/></label>
      <label><span>Cidade *</span><input autoComplete="address-level2" maxLength={120} value={city} onChange={(event) => setCity(event.target.value)} placeholder="Cidade"/></label>
      <label className="state-field"><span>UF *</span><input autoComplete="address-level1" maxLength={2} value={state} onChange={(event) => setState(event.target.value.toUpperCase())} placeholder="PR"/></label>
      <label><span>CEP</span><input autoComplete="postal-code" maxLength={20} value={postalCode} onChange={(event) => setPostalCode(event.target.value)} placeholder="00000-000"/></label>
    </div>

    <label className="public-capture-message"><span>Observações</span><textarea rows={3} maxLength={2000} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Ex.: imóvel desocupado, disponibilidade para visita, diferenciais ou outras informações úteis."/></label>
    <label className="public-capture-honeypot" aria-hidden="true"><span>Site</span><input tabIndex={-1} autoComplete="off" value={website} onChange={(event) => setWebsite(event.target.value)}/></label>
    <label className="public-capture-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)}/><span>Autorizo o uso destes dados para que a imobiliária entre em contato sobre a captação e possível administração deste imóvel.</span></label>
    {error && <div className="public-capture-error" role="alert">{error}</div>}
    <div className="public-capture-submit"><small><ShieldCheck size={13}/> Esta solicitação entra como captação e não publica o imóvel automaticamente.</small><button type="submit" disabled={submitting}><Send size={15}/>{submitting ? 'Enviando...' : 'Enviar meu imóvel'}</button></div>
  </form>
}
