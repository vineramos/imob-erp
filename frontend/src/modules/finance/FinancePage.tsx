import { Landmark, LayoutDashboard, ReceiptText } from 'lucide-react'
import { useState } from 'react'
import { FinanceCorePanel } from './FinanceCorePanel'
import { FinancePage as FinanceRentPage } from './FinanceRentPage'
import { MaintenanceFinancePanel } from './MaintenanceFinancePanel'

type Area = 'overview' | 'rent' | 'maintenance'

export function FinancePage({permissions}:{permissions:string[]}) {
  const [area,setArea] = useState<Area>('overview')
  return <>
    <div className="workspace finance-area-switch">
      <div className="panel finance-tabs finance-root-tabs">
        <button type="button" className={area==='overview'?'active':''} onClick={()=>setArea('overview')}><LayoutDashboard size={15}/> Visão geral</button>
        <button type="button" className={area==='rent'?'active':''} onClick={()=>setArea('rent')}><Landmark size={15}/> Locações</button>
        <button type="button" className={area==='maintenance'?'active':''} onClick={()=>setArea('maintenance')}><ReceiptText size={15}/> Manutenções</button>
      </div>
    </div>
    {area==='overview'
      ? <FinanceCorePanel permissions={permissions} onNavigateSource={source=>setArea(source==='maintenance'?'maintenance':'rent')}/>
      : area==='rent'
        ? <FinanceRentPage permissions={permissions}/>
        : <MaintenanceFinancePanel permissions={permissions}/>}
  </>
}
