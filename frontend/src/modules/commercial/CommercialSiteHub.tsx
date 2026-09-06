import { Globe2, MessageSquareText } from 'lucide-react'
import { useState } from 'react'
import { CommercialPage } from './CommercialPage'
import { SiteInquiriesPanel } from './SiteInquiriesPanel'
import './site-inquiries.css'

type Props = { permissions: string[]; organizationId: string }

type CommercialView = 'stock' | 'inquiries'

export function CommercialSiteHub({ permissions, organizationId }: Props) {
  const [view, setView] = useState<CommercialView>('stock')

  return <div className="commercial-site-hub">
    <div className="commercial-hub-switch" aria-label="Área comercial do site">
      <button className={view === 'stock' ? 'active' : ''} type="button" onClick={() => setView('stock')}><Globe2 size={15}/> Estoque e publicação</button>
      <button className={view === 'inquiries' ? 'active' : ''} type="button" onClick={() => setView('inquiries')}><MessageSquareText size={15}/> Leads do site · CRM</button>
    </div>
    {view === 'stock' ? <CommercialPage permissions={permissions} organizationId={organizationId}/> : <SiteInquiriesPanel permissions={permissions}/>} 
  </div>
}
