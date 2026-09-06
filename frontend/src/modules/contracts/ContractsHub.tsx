import { Building2, KeyRound, LogOut } from 'lucide-react'
import { useState } from 'react'
import { ContractsPage } from './ContractsPage'
import { LeaseContractsPage } from './LeaseContractsPage'
import { LeaseExitSettlementPage } from './LeaseExitSettlementPage'

type Props = { permissions: string[] }

type ContractTab = 'administration' | 'lease' | 'exit'

export function ContractsHub({ permissions }: Props) {
  const [tab, setTab] = useState<ContractTab>('administration')
  return <div className="contracts-hub">
    <div className="contracts-hub-tabs panel">
      <button className={tab === 'administration' ? 'active' : ''} type="button" onClick={() => setTab('administration')}><Building2 size={15}/><span><strong>Administração</strong><small>Proprietário e imobiliária</small></span></button>
      <button className={tab === 'lease' ? 'active' : ''} type="button" onClick={() => setTab('lease')}><KeyRound size={15}/><span><strong>Locação</strong><small>Imóvel e locatário</small></span></button>
      <button className={tab === 'exit' ? 'active' : ''} type="button" onClick={() => setTab('exit')}><LogOut size={15}/><span><strong>Encerramentos</strong><small>Vistoria e acerto final</small></span></button>
    </div>
    {tab === 'administration' && <ContractsPage permissions={permissions}/>} 
    {tab === 'lease' && <LeaseContractsPage permissions={permissions}/>} 
    {tab === 'exit' && <LeaseExitSettlementPage permissions={permissions}/>} 
  </div>
}
