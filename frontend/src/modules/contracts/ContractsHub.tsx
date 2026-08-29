import { Building2, KeyRound } from 'lucide-react'
import { useState } from 'react'
import { ContractsPage } from './ContractsPage'
import { LeaseContractsPage } from './LeaseContractsPage'

type Props = { permissions: string[] }

export function ContractsHub({ permissions }: Props) {
  const [tab, setTab] = useState<'administration' | 'lease'>('administration')
  return <div className="contracts-hub">
    <div className="contracts-hub-tabs panel">
      <button className={tab === 'administration' ? 'active' : ''} type="button" onClick={() => setTab('administration')}><Building2 size={15}/><span><strong>Administração</strong><small>Proprietário e imobiliária</small></span></button>
      <button className={tab === 'lease' ? 'active' : ''} type="button" onClick={() => setTab('lease')}><KeyRound size={15}/><span><strong>Locação</strong><small>Imóvel e locatário</small></span></button>
    </div>
    {tab === 'administration' ? <ContractsPage permissions={permissions}/> : <LeaseContractsPage permissions={permissions}/>} 
  </div>
}
