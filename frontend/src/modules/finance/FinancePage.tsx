import { Landmark, ReceiptText } from 'lucide-react'
import { useState } from 'react'
import { FinancePage as FinanceRentPage } from './FinanceRentPage'
import { MaintenanceFinancePanel } from './MaintenanceFinancePanel'

export function FinancePage({permissions}:{permissions:string[]}){
  const [area,setArea]=useState<'rent'|'maintenance'>('rent')
  return <><div className="workspace finance-area-switch"><div className="panel finance-tabs finance-root-tabs"><button type="button" className={area==='rent'?'active':''} onClick={()=>setArea('rent')}><Landmark size={15}/> Locações</button><button type="button" className={area==='maintenance'?'active':''} onClick={()=>setArea('maintenance')}><ReceiptText size={15}/> Manutenções</button></div></div>{area==='rent'?<FinanceRentPage permissions={permissions}/>:<MaintenanceFinancePanel permissions={permissions}/>}</>
}
