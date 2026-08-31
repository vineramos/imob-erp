import { Landmark, LayoutDashboard, ReceiptText, WalletCards } from 'lucide-react'
import { useState } from 'react'
import { FinanceBankingPanel } from './FinanceBankingPanel'
import { FinanceCorePanel } from './FinanceCorePanel'
import { FinancePage as FinanceRentPage } from './FinanceRentPage'
import { MaintenanceFinancePanel } from './MaintenanceFinancePanel'

type Area = 'overview' | 'banking' | 'rent' | 'maintenance'

export function FinancePage({permissions}:{permissions:string[]}) {
  const [area,setArea] = useState<Area>('overview')
  return <>
    <div className="workspace finance-area-switch">
      <div className="panel finance-tabs finance-root-tabs">
        <button type="button" className={area==='overview'?'active':''} onClick={()=>setArea('overview')}><LayoutDashboard size={15}/> Visão geral</button>
        <button type="button" className={area==='banking'?'active':''} onClick={()=>setArea('banking')}><WalletCards size={15}/> Bancos</button>
        <button type="button" className={area==='rent'?'active':''} onClick={()=>setArea('rent')}><Landmark size={15}/> Locações</button>
        <button type="button" className={area==='maintenance'?'active':''} onClick={()=>setArea('maintenance')}><ReceiptText size={15}/> Manutenções</button>
      </div>
    </div>
    {area==='overview'
      ? <FinanceCorePanel permissions={permissions} onNavigateSource={source=>setArea(source==='maintenance'?'maintenance':'rent')}/>
      : area==='banking'
        ? <FinanceBankingPanel permissions={permissions}/>
        : area==='rent'
          ? <FinanceRentPage permissions={permissions}/>
          : <MaintenanceFinancePanel permissions={permissions}/>}
  </>
}
