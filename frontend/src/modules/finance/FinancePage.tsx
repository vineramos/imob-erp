import { BarChart3, ExternalLink, Landmark, LayoutDashboard, LockKeyhole, Percent, PlugZap, ReceiptText, Send, ShieldCheck, Tags, TrendingUp, WalletCards } from 'lucide-react'
import { useState } from 'react'
import { FinanceBankControlPanel } from './FinanceBankControlPanel'
import { FinanceBankSetupPanel } from './FinanceBankSetupPanel'
import { FinanceBankingPanel } from './FinanceBankingPanel'
import { FinanceBillingPanel } from './FinanceBillingPanel'
import { FinanceClassificationsPanel } from './FinanceClassificationsPanel'
import { FinanceCommissionsPanel } from './FinanceCommissionsPanel'
import { FinanceCorePanel } from './FinanceCorePanel'
import { FinanceInterPanel } from './FinanceInterPanel'
import { FinancePage as FinanceRentPage } from './FinanceRentPage'
import { FinancePortalsPanel } from './FinancePortalsPanel'
import { FinanceReportsPanel } from './FinanceReportsPanel'
import { FinanceTreasuryPanel } from './FinanceTreasuryPanel'
import { MaintenanceFinancePanel } from './MaintenanceFinancePanel'

type Area = 'overview'|'billing'|'treasury'|'banking'|'bank-setup'|'bank-control'|'inter'|'reports'|'commissions'|'classifications'|'portals'|'rent'|'maintenance'

export function FinancePage({permissions}:{permissions:string[]}){
  const [area,setArea]=useState<Area>('overview')
  return <><div className="workspace finance-area-switch"><div className="panel finance-tabs finance-root-tabs">
    <button type="button" className={area==='overview'?'active':''} onClick={()=>setArea('overview')}><LayoutDashboard size={15}/> Visão geral</button>
    <button type="button" className={area==='billing'?'active':''} onClick={()=>setArea('billing')}><Send size={15}/> Cobranças</button>
    <button type="button" className={area==='treasury'?'active':''} onClick={()=>setArea('treasury')}><TrendingUp size={15}/> Tesouraria</button>
    <button type="button" className={area==='banking'?'active':''} onClick={()=>setArea('banking')}><WalletCards size={15}/> Bancos</button>
    <button type="button" className={area==='bank-setup'?'active':''} onClick={()=>setArea('bank-setup')}><PlugZap size={15}/> Contas e APIs</button>
    <button type="button" className={area==='bank-control'?'active':''} onClick={()=>setArea('bank-control')}><LockKeyhole size={15}/> Controle bancário</button>
    <button type="button" className={area==='inter'?'active':''} onClick={()=>setArea('inter')}><ShieldCheck size={15}/> Banco Inter</button>
    {permissions.includes('reports.view')&&<button type="button" className={area==='reports'?'active':''} onClick={()=>setArea('reports')}><BarChart3 size={15}/> Relatórios</button>}
    <button type="button" className={area==='commissions'?'active':''} onClick={()=>setArea('commissions')}><Percent size={15}/> Comissões</button>
    <button type="button" className={area==='classifications'?'active':''} onClick={()=>setArea('classifications')}><Tags size={15}/> Classificações</button>
    <button type="button" className={area==='portals'?'active':''} onClick={()=>setArea('portals')}><ExternalLink size={15}/> Portais</button>
    <button type="button" className={area==='rent'?'active':''} onClick={()=>setArea('rent')}><Landmark size={15}/> Locações</button>
    <button type="button" className={area==='maintenance'?'active':''} onClick={()=>setArea('maintenance')}><ReceiptText size={15}/> Manutenções</button>
  </div></div>
  {area==='overview'?<FinanceCorePanel permissions={permissions} onNavigateSource={source=>setArea(source==='maintenance'?'maintenance':'rent')}/>:area==='billing'?<FinanceBillingPanel permissions={permissions}/>:area==='treasury'?<FinanceTreasuryPanel permissions={permissions}/>:area==='banking'?<FinanceBankingPanel permissions={permissions}/>:area==='bank-setup'?<FinanceBankSetupPanel permissions={permissions}/>:area==='bank-control'?<FinanceBankControlPanel permissions={permissions}/>:area==='inter'?<FinanceInterPanel permissions={permissions}/>:area==='reports'?<FinanceReportsPanel permissions={permissions}/>:area==='commissions'?<FinanceCommissionsPanel permissions={permissions}/>:area==='classifications'?<FinanceClassificationsPanel permissions={permissions}/>:area==='portals'?<FinancePortalsPanel permissions={permissions}/>:area==='rent'?<FinanceRentPage permissions={permissions}/>:<MaintenanceFinancePanel permissions={permissions}/>}</>
}
