import { Globe2, MessageSquareText } from 'lucide-react'
import { useState } from 'react'
import { CommercialPage } from './CommercialPage'
import { SiteInquiriesPanel } from './SiteInquiriesPanel'
import './site-inquiries.css'

type Props = { permissions: string[]; organizationId: string }

type CommercialView = 'crm' | 'stock'

export function CommercialSiteHub({ permissions, organizationId }: Props) {
  const [view, setView] = useState<CommercialView>('crm')

  return <div className="commercial-site-hub">
    <div className="commercial-hub-switch" aria-label="Área comercial do site">
      <button className={view === 'crm' ? 'active' : ''} type="button" onClick={() => setView('crm')}><MessageSquareText size={15}/> CRM & Funil</button>
      <button className={view === 'stock' ? 'active' : ''} type="button" onClick={() => setView('stock')}><Globe2 size={15}/> Estoque & Publicação</button>
    </div>
    {view === 'crm' ? <SiteInquiriesPanel permissions={permissions}/> : <CommercialPage permissions={permissions} organizationId={organizationId}/>} 
  </div>
}
