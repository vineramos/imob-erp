import { CheckCircle2, Send, ShieldCheck } from 'lucide-react'
import { FormEvent, useState } from 'react'
import { ApiError, publicApiRequest } from '../api/client'
import type { PublicProperty } from '../api/types'
import './public-inquiry.css'

type InquiryAck = { accepted: boolean; message: string }
type PreferredContact = 'whatsapp' | 'phone' | 'email'

export function PublicInquiryForm({ organizationId, item }: { organizationId: string; item: PublicProperty }) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [preferredContact, setPreferredContact] = useState<PreferredContact>('whatsapp')
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
    if (!consent) { setError('Autorize o contato para enviar seu interesse.'); return }

    setSubmitting(true)
    setError('')
    try {
      const response = await publicApiRequest<InquiryAck>(`/public/sites/${organizationId}/properties/${item.slug}/inquiries`, {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          phone: phone.trim() || null,
          email: email.trim() || null,
          preferred_contact: preferredContact,
          message: message.trim() || null,
          consent,
          website,
        }),
      })
      setSuccess(response.message)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível enviar seu interesse. Tente novamente.')
    } finally { setSubmitting(false) }
  }

  if (success) return <div className="public-inquiry-success" role="status">
    <CheckCircle2 size={30}/>
    <div><strong>Interesse enviado</strong><p>{success}</p></div>
  </div>

  return <form className="public-inquiry-form" onSubmit={submit}>
    <div className="public-inquiry-form-heading"><span>INTERESSE NO IMÓVEL</span><strong>Fale com a nossa equipe</strong><small>Ref. {item.code}</small></div>
    <div className="public-inquiry-grid">
      <label><span>Nome *</span><input autoComplete="name" maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Seu nome"/></label>
      <label><span>WhatsApp / telefone</span><input autoComplete="tel" maxLength={40} value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="(41) 99999-9999"/></label>
      <label><span>E-mail</span><input autoComplete="email" type="email" maxLength={180} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="voce@email.com"/></label>
      <label><span>Prefiro contato por</span><select value={preferredContact} onChange={(event) => setPreferredContact(event.target.value as PreferredContact)}><option value="whatsapp">WhatsApp</option><option value="phone">Ligação</option><option value="email">E-mail</option></select></label>
    </div>
    <label className="public-inquiry-message"><span>Mensagem</span><textarea rows={3} maxLength={2000} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Ex.: gostaria de visitar no período da tarde."/></label>
    <label className="public-inquiry-honeypot" aria-hidden="true"><span>Site</span><input tabIndex={-1} autoComplete="off" value={website} onChange={(event) => setWebsite(event.target.value)}/></label>
    <label className="public-inquiry-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)}/><span>Autorizo o uso destes dados para que a imobiliária entre em contato sobre este imóvel.</span></label>
    {error && <div className="public-inquiry-error" role="alert">{error}</div>}
    <div className="public-inquiry-submit"><small><ShieldCheck size={13}/> Seus dados são enviados somente para o atendimento deste interesse.</small><button type="submit" disabled={submitting}><Send size={15}/>{submitting ? 'Enviando...' : 'Quero falar sobre este imóvel'}</button></div>
  </form>
}
