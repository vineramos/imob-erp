import { Building2, HomeKey } from 'lucide-react'
import { useState } from 'react'
import { ContractsPage } from './ContractsPage'
import { LeaseContractsPage } from './LeaseContractsPage'

type Props = { permissions: string[] }

export function ContractsHub({ permissions }: Props) {
  const [tab, setTab] = useState<'administration' | 'lease'>('administration')
  return <div className="contracts-hub">
    <div className="contracts-hub-tabs panel">
      <button className={tab === 'administration' ? 'active' : ''} type="button" onClick={() => setTab('administration')}><Building2 size={15}/><span><strong>Administração</strong><small>Proprietário ↔ imobiliária</small></span></button>
      <button className={tab === 'lease' ? 'active' : ''} type="button" onClick={() => setTab('lease')}><HomeKey size={15}/><span><strong>Locação</strong><small>Imóvel ↔ locatário</small></span></button>
    </div>
    {tab === 'administration' ? <ContractsPage permissions={permissions}/> : <LeaseContractsPage permissions={permissions}/>} 
  </div>
}
