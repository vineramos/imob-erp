import {
  AlertTriangle, ArrowRight, Building2, CalendarDays, CheckCircle2, ClipboardCheck, Copy,
  Download, FileText, Home, KeyRound, LifeBuoy, LockKeyhole, LogOut, ReceiptText,
  RefreshCw, ShieldCheck, UserRound, WalletCards, Wrench, XCircle,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, publicApiRequest, publicBlobRequest } from '../api/client'
import { TenantPortalExperience } from './TenantPortalExperience'
import './tenant-portal.css'
import './tenant-portal-polish.css'

type Tab = 'home' | 'payments' | 'contract' | 'documents' | 'inspections' | 'maintenance' | 'account'
type Me = { person_id:string; person_name:string; email:string; document_number:string|null; organization_name:string; organization_email:string|null; organization_phone:string|null }
type Lease = { id:string; code:string; status:string; property_id:string; property_code:string; property_address:Record<string,string>; rent_amount:number; due_day:number; start_date:string; end_date:string; operational_end_date:string|null; adjustment_index:string; adjustment_period_months:number; next_adjustment_date:string; guarantee_type:string; signed_at:string|null }
type Charge = { id:string; code:string; lease_contract_id:string; competence:string; due_date:string; amount:number; status:string; paid_at:string|null; paid_amount:number|null; boleto_line:string|null; pix_copy_paste:string|null; billing_pdf_available:boolean }
type ChargeRule = { key:string; kind:string; label:string; amount:number; active:boolean; payer:string; frequency:'monthly'|'annual'|'one_time'; include_in_invoice:boolean; start_date:string|null; end_date:string|null }
type ChargeItem = { key:string; kind:string; label:string; amount:number; frequency:string }
type ChargeComposition = { leases:Record<string,ChargeRule[]>; charges:Record<string,ChargeItem[]> }
type DocumentItem = { key:string; title:string; category:string; filename:string; content_type:string; status:string; entity_label:string|null; updated_at:string; download_path:string }
type Inspection = { id:string; code:string; lease_contract_id:string; inspection_type:string; status:string; scheduled_at:string|null; performed_at:string|null; contest_deadline:string|null; finalized_at:string|null; report_available:boolean }
type Maintenance = { id:string; code:string; lease_contract_id:string|null; title:string; category:string; priority:string; status:string; description:string; reported_at:string; scheduled_at:string|null; completed_at:string|null }
type Overview = {
  person:{id:string;name:string;email:string;document_number:string|null}; organization:{name:string;email:string|null;phone:string|null};
  metrics:{active_leases:number;open_amount:number;open_charges:number;maintenance_open:number;next_due_date:string|null};
  leases:Lease[];charges:Charge[];documents:DocumentItem[];inspections:Inspection[];maintenance:Maintenance[]
}
type Flash = { kind:'success'|'danger'; text:string } | null
type PlannedInstallment = { key:string; competence:string; dueDate:string; amountLabel:string; note:string; status:string|null; adjustment:boolean; extras:ChargeRule[] }

const money=(value:number)=>Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
const localDate=(value:string)=>new Date(`${value.slice(0,10)}T12:00:00`)
const dateLabel=(value:string|null)=>value?localDate(value).toLocaleDateString('pt-BR'):'—'
const dateTimeLabel=(value:string|null)=>value?new Date(value).toLocaleString('pt-BR'):'—'
const monthLabel=(value:string)=>localDate(`${value.slice(0,7)}-01`).toLocaleDateString('pt-BR',{month:'2-digit',year:'numeric'})
const monthKey=(date:Date)=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}`
const addressLabel=(address:Record<string,string>)=>[address.street||address.logradouro,address.number||address.numero,address.complement||address.complemento,address.neighborhood||address.bairro,address.city||address.cidade,address.state||address.uf].filter(Boolean).join(', ')||'Endereço não informado'
const chargeStatus=(value:string)=>value==='paid'?'Pago':value==='overdue'?'Em atraso':value==='cancelled'?'Cancelado':value==='sent'?'Enviado':'Em aberto'
const leaseStatus=(value:string)=>({signed:'Ativo',closed:'Encerrado',draft:'Rascunho',review:'Em revisão',approved:'Aprovado',cancelled:'Cancelado'} as Record<string,string>)[value]||value
const maintenanceStatus=(value:string)=>({requested:'Solicitado',triage:'Em análise',quoted:'Orçamento',approved:'Aprovado',scheduled:'Agendado',in_progress:'Em execução',completed:'Concluído',cancelled:'Cancelado'} as Record<string,string>)[value]||value
const priorityLabel=(value:string)=>({low:'Baixa',normal:'Normal',high:'Alta',urgent:'Urgente'} as Record<string,string>)[value]||value
const inspectionType=(value:string)=>value==='initial'?'Vistoria de entrada':value==='final'?'Vistoria de saída':value
const documentCategory=(value:string)=>({contract:'Contrato',inspection:'Vistoria',maintenance:'Manutenção',finance:'Financeiro',property:'Imóvel',identity:'Cadastro',legal:'Jurídico',general:'Geral',other:'Outro'} as Record<string,string>)[value]||value
const frequencyLabel=(value:string)=>value==='annual'?'Anual':value==='one_time'?'Parcela única':'Mensal'
function openBlob(blob:Blob){const url=URL.createObjectURL(blob);window.open(url,'_blank','noopener,noreferrer');setTimeout(()=>URL.revokeObjectURL(url),60000)}
function dueDateFor(year:number,month:number,dueDay:number){const last=new Date(year,month+1,0).getDate();return new Date(year,month,Math.min(dueDay,last),12)}
function isoDate(date:Date){return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`}
function monthDelta(anchor:string,key:string){const [ay,am]=anchor.slice(0,7).split('-').map(Number);const [ky,km]=key.split('-').map(Number);return (ky-ay)*12+km-am}
function ruleApplies(rule:ChargeRule,lease:Lease,key:string){
  if(!rule.active||!rule.include_in_invoice||rule.payer!=='tenant'||Number(rule.amount)<=0)return false
  if(rule.start_date&&key<rule.start_date.slice(0,7))return false
  if(rule.end_date&&key>rule.end_date.slice(0,7))return false
  const anchor=(rule.start_date||lease.start_date).slice(0,7)
  const delta=monthDelta(anchor,key)
  if(delta<0)return false
  if(rule.frequency==='one_time')return delta===0
  if(rule.frequency==='annual')return delta%12===0
  return true
}
function chargeBreakdown(items:ChargeItem[]|undefined){
  if(!items?.length)return null
  return <div className="tenant-charge-breakdown">{items.map((item,index)=><div key={`${item.key}-${index}`}><span>{item.label}{item.frequency!=='monthly'?` · ${frequencyLabel(item.frequency)}`:''}</span><strong>{money(item.amount)}</strong></div>)}</div>
}

function buildPaymentPlan(lease:Lease|null,charges:Charge[],composition:ChargeComposition|null):PlannedInstallment[]{
  if(!lease)return[]
  const today=new Date()
  today.setHours(0,0,0,0)
  const leaseStart=localDate(lease.start_date)
  const leaseEnd=localDate(lease.operational_end_date||lease.end_date)
  let cursor=new Date(today.getFullYear(),today.getMonth(),1,12)
  const leaseStartMonth=new Date(leaseStart.getFullYear(),leaseStart.getMonth(),1,12)
  if(leaseStartMonth>cursor)cursor=leaseStartMonth
  const adjustmentKey=lease.next_adjustment_date?.slice(0,7)||''
  const chargeMap=new Map(charges.filter(item=>item.lease_contract_id===lease.id).map(item=>[item.competence.slice(0,7),item]))
  const rules=composition?.leases[lease.id]||[]
  const rows:PlannedInstallment[]=[]
  for(let guard=0;guard<18&&cursor<=leaseEnd;guard+=1){
    const key=monthKey(cursor)
    const due=dueDateFor(cursor.getFullYear(),cursor.getMonth(),lease.due_day)
    const charge=chargeMap.get(key)
    const extras=rules.filter(rule=>ruleApplies(rule,lease,key))
    const extrasTotal=extras.reduce((sum,item)=>sum+Number(item.amount||0),0)
    if((due>=today||(charge&&charge.status!=='paid'))&&charge?.status!=='cancelled'){
      const adjustment=Boolean(adjustmentKey&&key===adjustmentKey)
      let amountLabel=money(lease.rent_amount+extrasTotal)
      let note=extras.length?`Aluguel + ${extras.map(item=>item.label).join(', ')}.`:'Previsão conforme o aluguel vigente.'
      let status:string|null=null
      if(charge){
        amountLabel=money(charge.amount)
        note='Cobrança já gerada no financeiro; veja a composição abaixo.'
        status=charge.status
      }else if(adjustment){
        amountLabel=`${money(lease.rent_amount+extrasTotal)} + reajuste ${lease.adjustment_index} no aluguel`
        note=`Reajuste contratual previsto nesta competência (${lease.adjustment_index}); encargos permanecem separados.`
      }else if(adjustmentKey&&key>adjustmentKey){
        amountLabel=extrasTotal?`Valor após reajuste + ${money(extrasTotal)} em encargos`:'Valor após reajuste'
        note=`O aluguel dependerá do ${lease.adjustment_index} aplicado em ${monthLabel(adjustmentKey)}.`
      }
      rows.push({key,competence:monthLabel(key),dueDate:isoDate(due),amountLabel,note,status,adjustment,extras})
    }
    cursor=new Date(cursor.getFullYear(),cursor.getMonth()+1,1,12)
  }
  return rows
}

function Metric({icon:Icon,label,value,caption}:{icon:typeof Home;label:string;value:string;caption:string}){
  return <article className="tenant-metric"><Icon size={19}/><span>{label}</span><strong>{value}</strong><small>{caption}</small></article>
}

function EmptyState({icon:Icon,title,text}:{icon:typeof Home;title:string;text:string}){
  return <div className="tenant-empty-state"><Icon size={24}/><strong>{title}</strong><span>{text}</span></div>
}

export function TenantPortalPage(){
  const [me,setMe]=useState<Me|null>(null)
  const [data,setData]=useState<Overview|null>(null)
  const [composition,setComposition]=useState<ChargeComposition|null>(null)
  const [loading,setLoading]=useState(true)
  const [flash,setFlash]=useState<Flash>(null)
  const [tab,setTab]=useState<Tab>('home')
  const [maintenanceOpen,setMaintenanceOpen]=useState(false)

  const load=useCallback(async()=>{
    setLoading(true)
    setFlash(null)
    try{
      const [profile,overview,chargeComposition]=await Promise.all([
        publicApiRequest<Me>('/tenant-portal/me'),
        publicApiRequest<Overview>('/tenant-portal/overview'),
        publicApiRequest<ChargeComposition>('/tenant-portal/charge-composition'),
      ])
      setMe(profile)
      setData(overview)
      setComposition(chargeComposition)
    }catch(cause){
      if(cause instanceof ApiError&&cause.status===401){setMe(null);setData(null)}
      else setFlash({kind:'danger',text:cause instanceof ApiError?cause.detail:'Não foi possível carregar o portal.'})
    }finally{setLoading(false)}
  },[])

  useEffect(()=>{void load()},[load])

  async function logout(){
    try{await publicApiRequest('/tenant-portal/auth/logout',{method:'POST'})}
    finally{setMe(null);setData(null);setTab('home')}
  }
  async function copy(value:string,label:string){
    try{await navigator.clipboard.writeText(value);setFlash({kind:'success',text:`${label} copiado.`});setTimeout(()=>setFlash(null),1800)}
    catch{setFlash({kind:'danger',text:`Não foi possível copiar ${label.toLowerCase()}.`})}
  }
  async function openDocument(item:DocumentItem){
    try{openBlob(await publicBlobRequest(item.download_path))}
    catch(cause){setFlash({kind:'danger',text:cause instanceof ApiError?cause.detail:'Não foi possível abrir o documento.'})}
  }
  async function openBilling(charge:Charge){
    try{openBlob(await publicBlobRequest(`/tenant-portal/charges/${charge.id}/billing.pdf`))}
    catch(cause){setFlash({kind:'danger',text:cause instanceof ApiError?cause.detail:'Não foi possível abrir o boleto.'})}
  }
  async function openReceipt(charge:Charge){
    try{openBlob(await publicBlobRequest(`/tenant-portal/charges/${charge.id}/receipt.pdf`))}
    catch(cause){setFlash({kind:'danger',text:cause instanceof ApiError?cause.detail:'Não foi possível abrir o recibo.'})}
  }

  if(loading&&!data)return <main className="tenant-login-shell"><div className="tenant-loading"><div className="tenant-brand-mark">IM</div><strong>Preparando seu portal...</strong></div></main>
  if(!me||!data)return <main className="tenant-login-shell"><div className="tenant-loading"><div className="tenant-brand-mark">IM</div><strong>Sua sessão terminou.</strong><span>Voltando para a tela de acesso...</span></div></main>

  const activeLeases=data.leases.filter(item=>item.status==='signed')
  const activeLease=activeLeases[0]||null
  const openCharges=[...data.charges].filter(item=>['generated','sent','overdue'].includes(item.status)).sort((a,b)=>a.due_date.localeCompare(b.due_date))
  const paidCharges=[...data.charges].filter(item=>item.status==='paid').sort((a,b)=>(b.paid_at||b.due_date).localeCompare(a.paid_at||a.due_date))
  const paidTotal=paidCharges.reduce((total,item)=>total+Number(item.paid_amount??item.amount??0),0)
  const plan=buildPaymentPlan(activeLease,data.charges,composition)
  const nextPlan=plan[0]||null

  function requestMaintenance(){
    if(activeLeases.length===0){
      setFlash({kind:'danger',text:'Não há uma locação ativa disponível para abertura de chamados.'})
      setTab('maintenance')
      return
    }
    setMaintenanceOpen(true)
  }

  const navigation:[Tab,string,typeof Home][]=[
    ['home','Início',Home],['payments','Pagamentos',WalletCards],['contract','Contrato',Building2],
    ['documents','Documentos',FileText],['inspections','Vistorias',ClipboardCheck],['maintenance','Manutenção',Wrench],['account','Minha conta',UserRound],
  ]

  return <main className="tenant-portal-shell">
    <header className="tenant-topbar">
      <div className="tenant-brand"><div className="tenant-brand-mark">{data.organization.name.trim().slice(0,2).toUpperCase()||'IM'}</div><div><strong>{data.organization.name}</strong><span>Portal do Inquilino</span></div></div>
      <div className="tenant-top-actions"><button onClick={()=>void load()} title="Atualizar"><RefreshCw size={16}/><span>Atualizar</span></button><button onClick={()=>void logout()} title="Sair"><LogOut size={16}/><span>Sair</span></button></div>
    </header>
    <div className="tenant-layout">
      <aside className="tenant-sidebar">
        <div className="tenant-user"><div>{data.person.name.trim().slice(0,2).toUpperCase()}</div><strong>{data.person.name}</strong><span>{data.person.document_number||'Documento não informado'}</span></div>
        <nav>{navigation.map(([key,label,Icon])=><button key={key} className={tab===key?'active':''} onClick={()=>setTab(key)}><Icon size={17}/><span>{label}</span></button>)}</nav>
        <div className="tenant-help"><LifeBuoy size={17}/><strong>Precisa de ajuda?</strong>{data.organization.phone&&<a href={`tel:${data.organization.phone}`}>{data.organization.phone}</a>}{data.organization.email&&<a href={`mailto:${data.organization.email}`}>{data.organization.email}</a>}</div>
      </aside>
      <section className="tenant-content">
        {flash&&<div className={`tenant-alert ${flash.kind}`}>{flash.kind==='success'?<CheckCircle2 size={16}/>:<XCircle size={16}/>}<span>{flash.text}</span></div>}

        {tab==='home'&&<>
          <div className="tenant-heading"><div><span className="tenant-eyebrow">Olá, {data.person.name.split(' ')[0]}</span><h1>Sua locação, sem complicação.</h1><p>Pagamentos, próximos vencimentos, contrato e chamados reunidos em uma visão simples.</p></div>{activeLease?<span className="tenant-status signed">Locação ativa</span>:<span className="tenant-status">Sem locação ativa</span>}</div>
          <div className="tenant-metrics">
            <Metric icon={CalendarDays} label="Próxima mensalidade" value={nextPlan?dateLabel(nextPlan.dueDate):'—'} caption={nextPlan?.amountLabel||'Sem previsão ativa'}/>
            <Metric icon={KeyRound} label="Saldo em aberto" value={money(data.metrics.open_amount)} caption={openCharges.some(item=>item.status==='overdue')?'Existe cobrança em atraso':'Situação financeira atual'}/>
            <Metric icon={ReceiptText} label="Pagamentos realizados" value={String(paidCharges.length)} caption={`${money(paidTotal)} no histórico disponível`}/>
            <Metric icon={Wrench} label="Chamados abertos" value={String(data.metrics.maintenance_open)} caption="Manutenções em andamento"/>
          </div>

          {activeLease?<article className="tenant-card tenant-property-card">
            <div className="tenant-property-hero"><div className="tenant-property-hero-icon"><Home size={24}/></div><div className="tenant-property-hero-copy"><span>{activeLease.code}</span><strong>{addressLabel(activeLease.property_address)}</strong><span>Aluguel {money(activeLease.rent_amount)} · vencimento dia {activeLease.due_day}</span></div><span className="tenant-status signed">Ativo</span></div>
            {activeLease.next_adjustment_date&&<div className="tenant-reajuste-callout"><CalendarDays size={17}/><div><strong>Próximo reajuste previsto para {monthLabel(activeLease.next_adjustment_date)}</strong><span>Nessa competência a previsão separa o aluguel dos encargos e mostra o reajuste de <b>{activeLease.adjustment_index}</b> sem estimar um índice ainda desconhecido.</span></div></div>}
          </article>:<EmptyState icon={Building2} title="Nenhuma locação ativa" text="O portal continua disponível para consultar históricos, mas novos chamados e previsões mensais exigem uma locação ativa."/>}

          <div className="tenant-quick-grid">
            <button className="tenant-quick-action" onClick={()=>setTab('payments')}><div><WalletCards size={17}/></div><span><strong>Pagamentos</strong><small>Histórico e próximos meses</small></span></button>
            <button className="tenant-quick-action" onClick={()=>setTab('documents')}><div><FileText size={17}/></div><span><strong>Documentos</strong><small>Contrato e vistorias</small></span></button>
            <button className="tenant-quick-action" onClick={requestMaintenance} disabled={!activeLease}><div><Wrench size={17}/></div><span><strong>Novo chamado</strong><small>{activeLease?'Solicitar manutenção':'Sem locação ativa'}</small></span></button>
            <button className="tenant-quick-action" onClick={()=>setTab('account')}><div><UserRound size={17}/></div><span><strong>Minha conta</strong><small>Dados e senha</small></span></button>
          </div>

          <div className="tenant-finance-spotlight">
            <article className="tenant-card tenant-finance-hero"><div className="tenant-finance-hero-top"><div><span>Próximas mensalidades</span><h2>{nextPlan?nextPlan.amountLabel:'Sem previsão disponível'}</h2><p>{nextPlan?`Próximo vencimento em ${dateLabel(nextPlan.dueDate)}. A previsão já considera os encargos programados para cada competência.`:'Uma locação ativa é necessária para montar a previsão mensal.'}</p></div><CalendarDays size={23}/></div><div className="tenant-finance-next">{plan.slice(0,3).map(item=><div key={item.key}><span>{item.competence} · vence {dateLabel(item.dueDate)}</span><strong>{item.amountLabel}</strong><small>{item.adjustment?'Reajuste previsto':item.status?chargeStatus(item.status):item.extras.length?`${item.extras.length} encargo(s) previsto(s)`:'Planejado'}</small></div>)}{plan.length===0&&<div><span>Previsão</span><strong>—</strong><small>Sem mensalidades futuras.</small></div>}</div><button className="tenant-text-button" onClick={()=>setTab('payments')}>Abrir visão financeira completa <ArrowRight size={12}/></button></article>
            <div className="tenant-finance-side"><article className="tenant-card"><div className="tenant-card-section-head"><div><span className="tenant-section-kicker">Histórico</span><h2>Últimos pagamentos</h2></div><ReceiptText size={19}/></div><div className="tenant-history-list">{paidCharges.slice(0,4).map(item=><div className="tenant-history-row" key={item.id}><div className="tenant-history-main"><strong>{monthLabel(item.competence)}</strong><span>Pago em {dateTimeLabel(item.paid_at)}</span></div><div className="tenant-history-value"><strong>{money(item.paid_amount??item.amount)}</strong><span>{item.code}</span></div><div className="tenant-open-actions"><button onClick={()=>void openReceipt(item)}><Download size={13}/> Recibo</button></div><small className="tenant-inline-status paid">Pago</small></div>)}{paidCharges.length===0&&<EmptyState icon={ReceiptText} title="Ainda sem pagamentos no histórico" text="Os pagamentos liquidados aparecerão aqui automaticamente."/>}</div></article></div>
          </div>
        </>}

        {tab==='payments'&&<>
          <div className="tenant-heading"><div><span className="tenant-eyebrow">Financeiro</span><h1>Pagamentos e próximas mensalidades</h1><p>Aluguel e encargos aparecem separados para você saber exatamente o que compõe cada cobrança.</p></div></div>
          <div className="tenant-finance-summary tenant-card"><div><span>Total pago no histórico</span><strong>{money(paidTotal)}</strong></div><div><span>Mensalidades pagas</span><strong>{paidCharges.length}</strong></div><div><span>Saldo em aberto</span><strong>{money(data.metrics.open_amount)}</strong></div><div><span>Próximo vencimento</span><strong>{nextPlan?dateLabel(nextPlan.dueDate):'—'}</strong></div></div>
          <div className="tenant-financial-board" style={{marginTop:16}}>
            <article className="tenant-card wide"><div className="tenant-card-section-head"><div><span className="tenant-section-kicker">Planejamento</span><h2>Próximas mensalidades</h2><p>Mensais, anuais e parcelas únicas entram somente na competência programada. Reajustes futuros permanecem identificados sem estimativa artificial.</p></div><CalendarDays size={20}/></div>{plan.length>0?<div className="tenant-plan-list">{plan.map(item=><div className={`tenant-plan-row ${item.adjustment?'adjustment':''}`} key={item.key}><div className="tenant-plan-month"><strong>{item.competence}</strong><span>Vence {dateLabel(item.dueDate)}</span></div><div className="tenant-plan-value"><strong>{item.amountLabel}</strong><span>{item.note}</span>{item.extras.length>0&&<small>{item.extras.map(extra=>`${extra.label} (${frequencyLabel(extra.frequency)}): ${money(extra.amount)}`).join(' · ')}</small>}</div>{item.adjustment?<span className="tenant-adjustment-badge">Reajuste previsto</span>:item.status?<small className={`tenant-inline-status ${item.status}`}>{chargeStatus(item.status)}</small>:<small className="tenant-inline-status">Planejado</small>}</div>)}</div>:<EmptyState icon={CalendarDays} title="Sem próximas mensalidades" text="Não há uma locação ativa com mensalidades futuras para projetar."/>}</article>

            <article className="tenant-card"><div className="tenant-card-section-head"><div><span className="tenant-section-kicker">Pendências</span><h2>Em aberto</h2></div><KeyRound size={19}/></div>{openCharges.length>0?<div className="tenant-open-list">{openCharges.map(charge=><div className="tenant-open-row" key={charge.id}><div className="tenant-open-main"><strong>{monthLabel(charge.competence)} · {money(charge.amount)}</strong><span>Vencimento {dateLabel(charge.due_date)} · {charge.code}</span>{chargeBreakdown(composition?.charges[charge.id])}</div><small className={`tenant-inline-status ${charge.status}`}>{chargeStatus(charge.status)}</small><div className="tenant-open-actions">{charge.pix_copy_paste&&<button onClick={()=>void copy(charge.pix_copy_paste!,'Pix')}><Copy size={13}/> Pix</button>}{charge.boleto_line&&<button onClick={()=>void copy(charge.boleto_line!,'Linha digitável')}><Copy size={13}/> Linha</button>}{charge.billing_pdf_available&&<button onClick={()=>void openBilling(charge)}><Download size={13}/> PDF</button>}</div></div>)}</div>:<EmptyState icon={CheckCircle2} title="Nenhuma cobrança em aberto" text="Não existem cobranças pendentes no histórico disponível."/>}</article>

            <article className="tenant-card"><div className="tenant-card-section-head"><div><span className="tenant-section-kicker">Histórico de pagamento</span><h2>Mensalidades pagas</h2></div><ReceiptText size={19}/></div>{paidCharges.length>0?<div className="tenant-history-list">{paidCharges.map(charge=><div className="tenant-history-row" key={charge.id}><div className="tenant-history-main"><strong>{monthLabel(charge.competence)}</strong><span>Vencimento {dateLabel(charge.due_date)} · pago em {dateTimeLabel(charge.paid_at)}</span>{chargeBreakdown(composition?.charges[charge.id])}</div><div className="tenant-history-value"><strong>{money(charge.paid_amount??charge.amount)}</strong><span>{charge.code}</span></div><div className="tenant-open-actions"><button onClick={()=>void openReceipt(charge)}><Download size={13}/> Recibo</button></div><small className="tenant-inline-status paid">Pago</small></div>)}</div>:<EmptyState icon={ReceiptText} title="Histórico ainda vazio" text="Quando uma mensalidade for liquidada, ela aparecerá aqui com competência, composição, valor e data de pagamento."/>}</article>
          </div>
        </>}

        {tab==='contract'&&<>
          <div className="tenant-heading"><div><span className="tenant-eyebrow">Contrato</span><h1>Dados da locação</h1><p>Condições principais, composição financeira e acompanhamento do encerramento dos contratos vinculados ao seu cadastro.</p></div></div>
          <div className="tenant-stack">{data.leases.map(lease=><article className="tenant-card" key={lease.id}><div className="tenant-card-head"><div><span>{lease.status==='signed'?'Contrato vigente':'Histórico'}</span><h2>{lease.code}</h2></div><span className={`tenant-status ${lease.status}`}>{leaseStatus(lease.status)}</span></div><p className="tenant-address">{addressLabel(lease.property_address)}</p><div className="tenant-detail-grid"><div><span>Aluguel atual</span><strong>{money(lease.rent_amount)}</strong></div><div><span>Vencimento</span><strong>Dia {lease.due_day}</strong></div><div><span>Início</span><strong>{dateLabel(lease.start_date)}</strong></div><div><span>Término previsto</span><strong>{dateLabel(lease.operational_end_date||lease.end_date)}</strong></div><div><span>Índice de reajuste</span><strong>{lease.adjustment_index}</strong></div><div><span>Próximo reajuste</span><strong>{dateLabel(lease.next_adjustment_date)}</strong></div><div><span>Garantia</span><strong>{lease.guarantee_type}</strong></div><div><span>Assinatura</span><strong>{dateTimeLabel(lease.signed_at)}</strong></div></div>{(composition?.leases[lease.id]||[]).filter(item=>item.active).length>0&&<div className="tenant-card" style={{marginTop:14}}><div className="tenant-card-section-head"><div><span className="tenant-section-kicker">Composição financeira</span><h2>Encargos previstos</h2></div><ReceiptText size={18}/></div><div className="tenant-charge-breakdown">{(composition?.leases[lease.id]||[]).filter(item=>item.active).map(item=><div key={item.key}><span>{item.label} · {frequencyLabel(item.frequency)}{item.include_in_invoice?' · junto na cobrança':' · fora da cobrança'}</span><strong>{money(item.amount)}</strong></div>)}</div></div>}{lease.status==='signed'&&lease.next_adjustment_date&&<div className="tenant-reajuste-callout"><CalendarDays size={17}/><div><strong>{monthLabel(lease.next_adjustment_date)} · reajuste {lease.adjustment_index} sobre o aluguel</strong><span>Os encargos são controlados separadamente e não são confundidos com o valor do aluguel.</span></div></div>}</article>)}{data.leases.length===0&&<EmptyState icon={Building2} title="Nenhum contrato vinculado" text="Não encontramos contratos de locação associados a este acesso."/>}</div>
          <TenantPortalExperience leases={data.leases} onChanged={load}/>
        </>}

        {tab==='documents'&&<>
          <div className="tenant-heading"><div><span className="tenant-eyebrow">Documentos</span><h1>Seus documentos</h1><p>Contrato e documentos de vistoria liberados para o seu vínculo.</p></div></div>
          {data.documents.length>0?<div className="tenant-document-grid">{data.documents.map(item=><article className="tenant-card tenant-document" key={item.key}><div className="tenant-document-icon"><FileText size={18}/></div><div><small>{documentCategory(item.category)}</small><strong>{item.title}</strong><span>{item.filename}</span><em>Atualizado em {dateTimeLabel(item.updated_at)}</em></div><button onClick={()=>void openDocument(item)}><Download size={13}/> Abrir</button></article>)}</div>:<EmptyState icon={FileText} title="Nenhum documento disponível" text="Os documentos do contrato e das vistorias aparecerão aqui quando forem liberados."/>}
        </>}

        {tab==='inspections'&&<>
          <div className="tenant-heading"><div><span className="tenant-eyebrow">Vistorias</span><h1>Vistorias do imóvel</h1><p>Acompanhe entrada, saída e prazos relacionados aos laudos.</p></div></div>
          <div className="tenant-stack">{data.inspections.map(item=><article className="tenant-card" key={item.id}><div className="tenant-card-head"><div><span>{inspectionType(item.inspection_type)}</span><h2>{item.code}</h2></div><span className={`tenant-inline-status ${item.status}`}>{item.status}</span></div><div className="tenant-detail-grid"><div><span>Agendada</span><strong>{dateTimeLabel(item.scheduled_at)}</strong></div><div><span>Realizada</span><strong>{dateTimeLabel(item.performed_at)}</strong></div><div><span>Prazo de contestação</span><strong>{dateTimeLabel(item.contest_deadline)}</strong></div><div><span>Finalizada</span><strong>{dateTimeLabel(item.finalized_at)}</strong></div></div></article>)}{data.inspections.length===0&&<EmptyState icon={ClipboardCheck} title="Nenhuma vistoria disponível" text="As vistorias relacionadas à sua locação aparecerão aqui."/>}</div>
        </>}

        {tab==='maintenance'&&<>
          <div className="tenant-heading"><div><span className="tenant-eyebrow">Manutenção</span><h1>Chamados do imóvel</h1><p>Abra um chamado e acompanhe o andamento sem precisar sair do portal.</p></div><button className="tenant-primary compact" onClick={requestMaintenance} disabled={activeLeases.length===0}><Wrench size={14}/> Novo chamado</button></div>
          {activeLeases.length===0&&<div className="tenant-maintenance-banner"><AlertTriangle size={17}/><div><strong>Não há uma locação ativa para abrir chamados.</strong><span>Contratos em rascunho, encerrados ou históricos não podem receber novas solicitações de manutenção.</span></div></div>}
          <div className="tenant-stack">{data.maintenance.map(item=><article className="tenant-card" key={item.id}><div className="tenant-card-head"><div><span>{item.code}</span><h2>{item.title}</h2></div><span className={`tenant-inline-status ${item.status}`}>{maintenanceStatus(item.status)}</span></div><p>{item.description}</p><div className="tenant-maintenance-meta"><span>Prioridade <b>{priorityLabel(item.priority)}</b></span><span>Aberto em <b>{dateTimeLabel(item.reported_at)}</b></span>{item.scheduled_at&&<span>Agendado <b>{dateTimeLabel(item.scheduled_at)}</b></span>}{item.completed_at&&<span>Concluído <b>{dateTimeLabel(item.completed_at)}</b></span>}</div></article>)}{data.maintenance.length===0&&<EmptyState icon={Wrench} title="Nenhum chamado no histórico" text={activeLeases.length?'Quando precisar, use “Novo chamado” para enviar uma solicitação à imobiliária.':'O histórico de chamados aparecerá aqui quando houver registros.'}/>}</div>
        </>}

        {tab==='account'&&<>
          <div className="tenant-heading"><div><span className="tenant-eyebrow">Minha conta</span><h1>Dados e segurança</h1><p>Consulte seus dados de acesso e altere sua senha pessoal quando desejar.</p></div></div>
          <div className="tenant-account-grid"><article className="tenant-card"><div className="tenant-card-section-head"><div><span className="tenant-section-kicker">Cadastro</span><h2>Seus dados</h2></div><UserRound size={19}/></div><div className="tenant-profile-list"><div><span>Nome</span><strong>{data.person.name}</strong></div><div><span>CPF/CNPJ de acesso</span><strong>{data.person.document_number||'Não informado'}</strong></div><div><span>Imobiliária</span><strong>{data.organization.name}</strong></div><div><span>Locações ativas</span><strong>{activeLeases.length}</strong></div></div></article><PasswordCard onSuccess={text=>setFlash({kind:'success',text})}/></div>
        </>}
      </section>
    </div>
    {maintenanceOpen&&<MaintenanceModal leases={activeLeases} onClose={()=>setMaintenanceOpen(false)} onCreated={async()=>{setMaintenanceOpen(false);await load();setTab('maintenance');setFlash({kind:'success',text:'Chamado aberto com sucesso.'})}}/>}
  </main>
}

function PasswordCard({onSuccess}:{onSuccess:(text:string)=>void}){
  const [currentPassword,setCurrentPassword]=useState('')
  const [newPassword,setNewPassword]=useState('')
  const [confirmPassword,setConfirmPassword]=useState('')
  const [error,setError]=useState('')
  const [saving,setSaving]=useState(false)
  async function submit(event:FormEvent){
    event.preventDefault()
    setError('')
    if(newPassword!==confirmPassword){setError('As novas senhas não coincidem.');return}
    if(newPassword.length<8){setError('A nova senha precisa ter pelo menos 8 caracteres.');return}
    setSaving(true)
    try{
      await publicApiRequest('/tenant-portal/account/password',{method:'POST',body:JSON.stringify({current_password:currentPassword,new_password:newPassword})})
      setCurrentPassword('');setNewPassword('');setConfirmPassword('');onSuccess('Senha alterada com sucesso.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível alterar sua senha.')}
    finally{setSaving(false)}
  }
  return <article className="tenant-card"><div className="tenant-card-section-head"><div><span className="tenant-section-kicker">Segurança</span><h2>Alterar senha</h2></div><LockKeyhole size={19}/></div>{error&&<div className="tenant-alert danger"><XCircle size={15}/><span>{error}</span></div>}<form className="tenant-password-form" onSubmit={submit}><label><span>Senha atual</span><input type="password" value={currentPassword} onChange={event=>setCurrentPassword(event.target.value)} autoComplete="current-password" required minLength={8}/></label><label><span>Nova senha</span><input type="password" value={newPassword} onChange={event=>setNewPassword(event.target.value)} autoComplete="new-password" required minLength={8}/></label><label><span>Confirmar nova senha</span><input type="password" value={confirmPassword} onChange={event=>setConfirmPassword(event.target.value)} autoComplete="new-password" required minLength={8}/></label><div className="tenant-password-note"><ShieldCheck size={15}/><span>A troca mantém esta sessão aberta e encerra outras sessões que possam existir na sua conta.</span></div><button className="tenant-primary" disabled={saving||!currentPassword||newPassword.length<8}>{saving?'Alterando...':'Alterar minha senha'}</button></form></article>
}

function MaintenanceModal({leases,onClose,onCreated}:{leases:Lease[];onClose:()=>void;onCreated:()=>Promise<void>}){
  const [leaseId,setLeaseId]=useState(leases[0]?.id||'')
  const [title,setTitle]=useState('')
  const [category,setCategory]=useState('general')
  const [priority,setPriority]=useState('normal')
  const [description,setDescription]=useState('')
  const [error,setError]=useState('')
  const [saving,setSaving]=useState(false)
  const selected=useMemo(()=>leases.find(item=>item.id===leaseId),[leases,leaseId])
  async function submit(event:FormEvent){
    event.preventDefault()
    if(!leaseId){setError('Não há uma locação ativa disponível para abertura de chamados.');return}
    setSaving(true);setError('')
    try{await publicApiRequest('/tenant-portal/maintenance',{method:'POST',body:JSON.stringify({lease_contract_id:leaseId,title,category,priority,description})});await onCreated()}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível abrir o chamado.')}
    finally{setSaving(false)}
  }
  return <div className="tenant-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target&&!saving)onClose()}}><form className="tenant-modal" onSubmit={submit} role="dialog" aria-modal="true"><div className="tenant-modal-head"><div><span className="tenant-eyebrow">Novo chamado</span><h2>Solicitar manutenção</h2><p>Descreva o problema com clareza para facilitar a triagem da imobiliária.</p></div><button type="button" onClick={onClose} disabled={saving}>×</button></div>{leases.length===0?<EmptyState icon={AlertTriangle} title="Sem locação ativa" text="Novos chamados só podem ser abertos para um contrato de locação ativo."/>:<>{error&&<div className="tenant-alert danger"><XCircle size={16}/><span>{error}</span></div>}<label><span>Locação ativa</span><select value={leaseId} onChange={event=>setLeaseId(event.target.value)} required>{leases.map(item=><option key={item.id} value={item.id}>{item.code} · {addressLabel(item.property_address)}</option>)}</select></label>{selected&&<small className="tenant-selected-address">{addressLabel(selected.property_address)}</small>}<div className="tenant-form-grid"><label><span>Título</span><input value={title} onChange={event=>setTitle(event.target.value)} required minLength={3} placeholder="Ex.: Vazamento na cozinha"/></label><label><span>Categoria</span><select value={category} onChange={event=>setCategory(event.target.value)}><option value="general">Geral</option><option value="hydraulic">Hidráulica</option><option value="electrical">Elétrica</option><option value="structural">Estrutural</option><option value="appliance">Equipamento</option><option value="other">Outro</option></select></label><label><span>Prioridade</span><select value={priority} onChange={event=>setPriority(event.target.value)}><option value="low">Baixa</option><option value="normal">Normal</option><option value="high">Alta</option><option value="urgent">Urgente</option></select></label></div><label><span>Descrição</span><textarea value={description} onChange={event=>setDescription(event.target.value)} required minLength={5} rows={5} placeholder="Informe onde ocorre, quando começou e outros detalhes úteis."/></label></>}<div className="tenant-modal-actions"><button type="button" className="tenant-secondary" onClick={onClose} disabled={saving}>Cancelar</button>{leases.length>0&&<button className="tenant-primary" disabled={saving||!leaseId}>{saving?'Enviando...':'Abrir chamado'}</button>}</div></form></div>
}
