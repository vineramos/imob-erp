import { CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, Download, FileText, Landmark, RefreshCw, Search, WalletCards, X } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import { shiftMonth } from './finance-period'
import './finance-repasses.css'

type Repasse={
 id:string;charge_id:string;charge_code:string;lease_contract_id:string;lease_code:string;property_id:string;property_code:string;
 competence:string;owner_person_id:string;owner_name:string;ownership_percent:number;amount:number;due_date:string;
 status:string;paid_at:string|null;payment_reference:string|null
}
type Tab='overview'|'payment'
const money=(n:number|null|undefined)=>Number(n||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
const date=(v:string|null|undefined)=>v?new Date(v.slice(0,10)+'T12:00:00').toLocaleDateString('pt-BR'):'—'
const datetime=(v:string|null|undefined)=>v?new Date(v).toLocaleString('pt-BR'):'—'
const thisMonth=()=>{const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')}
const localNow=()=>{const d=new Date();return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16)}
const label:Record<string,string>={pending:'Pendente',paid:'Pago',settled_zero:'Sem valor'}
const tone=(v:string)=>v==='paid'?'success':'neutral'

export function FinanceRepassesPanel({permissions}:{permissions:string[]}){
 const canPay=permissions.includes('finance.repasse.execute')
 const [month,setMonth]=useState(thisMonth()),[rows,setRows]=useState<Repasse[]>([]),[loading,setLoading]=useState(true)
 const [selectedId,setSelectedId]=useState<string|null>(null),[filter,setFilter]=useState('all'),[search,setSearch]=useState(''),[tab,setTab]=useState<Tab>('overview')
 const [error,setError]=useState(''),[success,setSuccess]=useState(''),[saving,setSaving]=useState(false)
 const [modal,setModal]=useState(false),[paidAt,setPaidAt]=useState(localNow()),[reference,setReference]=useState('')
 const competence=month+'-01'
 const load=useCallback(async()=>{
  setLoading(true);setError('')
  try{setRows(await apiRequest<Repasse[]>('/finance/repasses?competence='+competence))}
  catch(e){setError(e instanceof ApiError?e.detail:'Não foi possível carregar os repasses.')}
  finally{setLoading(false)}
 },[competence])
 useEffect(()=>{void load()},[load])
 const filtered=useMemo(()=>{
  const q=search.trim().toLocaleLowerCase('pt-BR')
  return rows.filter(r=>(filter==='all'||r.status===filter)&&(!q||[r.owner_name,r.property_code,r.charge_code,r.lease_code].join(' ').toLocaleLowerCase('pt-BR').includes(q)))
 },[rows,filter,search])
 useEffect(()=>{
  if(!filtered.length){setSelectedId(null);return}
  if(!selectedId||!filtered.some(r=>r.id===selectedId))setSelectedId(filtered[0].id)
 },[filtered,selectedId])
 const selected=filtered.find(r=>r.id===selectedId)||null
 useEffect(()=>{setModal(false)},[selectedId,month])
 const totals=useMemo(()=>({
  pending:rows.filter(r=>r.status==='pending').reduce((n,r)=>n+Number(r.amount||0),0),
  paid:rows.filter(r=>r.status==='paid').reduce((n,r)=>n+Number(r.amount||0),0),
  pendingCount:rows.filter(r=>r.status==='pending').length,
  paidCount:rows.filter(r=>r.status==='paid').length
 }),[rows])
 async function pay(event:FormEvent){
  event.preventDefault();if(!selected)return
  if(!paidAt||new Date(paidAt).getTime()>Date.now()){setError('Informe uma data de pagamento válida, que não esteja no futuro.');return}
  setSaving(true);setError('');setSuccess('')
  try{
   await apiRequest('/finance/repasses/'+selected.id+'/payment',{method:'POST',body:JSON.stringify({paid_at:new Date(paidAt).toISOString(),payment_reference:reference.trim()||null})})
   setModal(false);await load();setSuccess('Repasse de '+selected.owner_name+' registrado como pago.')
  }catch(e){setError(e instanceof ApiError?e.detail:'Não foi possível registrar o repasse.')}
  finally{setSaving(false)}
 }
 async function statement(row:Repasse){
  setError('')
  try{
   const blob=await apiBlobRequest('/finance/statements/'+row.owner_person_id+'/pdf?competence='+competence+'&property_id='+row.property_id)
   const url=URL.createObjectURL(blob)
   const anchor=document.createElement('a')
   anchor.href=url;anchor.download='prestacao-contas-'+row.property_code+'-'+month+'.pdf';anchor.click()
   setTimeout(()=>URL.revokeObjectURL(url),1000)
  }catch(e){setError(e instanceof ApiError?e.detail:'Não foi possível obter a prestação de contas.')}
 }
 return <section className="workspace repasses-workspace">
  <div className="page-heading finance-heading">
   <div><span className="eyebrow">FINANCEIRO · PROPRIETÁRIOS</span><h1>Repasses</h1><p>Acompanhamento de valores, previsão, pagamentos e prestação de contas por proprietário e imóvel.</p></div>
   <div className="heading-actions">
    <button type="button" className="icon-button" aria-label="Competência anterior" onClick={()=>setMonth(m=>shiftMonth(m,-1))}><ChevronLeft size={16}/></button>
    <label className="finance-month"><CalendarDays size={15}/><input type="month" value={month} onChange={e=>setMonth(e.target.value)}/></label>
    <button type="button" className="icon-button" aria-label="Próxima competência" onClick={()=>setMonth(m=>shiftMonth(m,1))}><ChevronRight size={16}/></button>
    <button type="button" className="button secondary" onClick={()=>void load()} disabled={loading||saving}><RefreshCw size={14}/> Atualizar</button>
   </div>
  </div>
  {error&&<div className="form-alert danger-alert" role="alert">{error}</div>}
  {success&&<div className="form-alert success-alert" role="status">{success}</div>}
  <div className="repasse-metrics">
   <article className="panel"><span>A repassar</span><strong>{money(totals.pending)}</strong><small>{totals.pendingCount} repasse(s) pendente(s)</small></article>
   <article className="panel"><span>Pago</span><strong>{money(totals.paid)}</strong><small>{totals.paidCount} repasse(s) pago(s)</small></article>
   <article className="panel"><span>Total de repasses</span><strong>{rows.length}</strong><small>Na competência selecionada</small></article>
  </div>
  <div className="repasse-master-detail">
   <aside className="panel repasse-directory">
    <label className="repasse-search"><Search size={15}/><input aria-label="Buscar repasse" placeholder="Proprietário, imóvel ou cobrança..." value={search} onChange={e=>setSearch(e.target.value)}/></label>
    <select aria-label="Filtrar por situação" value={filter} onChange={e=>setFilter(e.target.value)}>
     <option value="all">Todos os status</option><option value="pending">Pendentes</option><option value="paid">Pagos</option><option value="settled_zero">Sem repasse</option>
    </select>
    <small>{filtered.length} de {rows.length} repasse(s)</small>
    <div className="repasse-list">
     {filtered.map(row=><button key={row.id} type="button" className={'repasse-entry '+(selectedId===row.id?'active':'')} aria-pressed={selectedId===row.id} onClick={()=>{setSelectedId(row.id);setTab('overview')}}>
      <span className="repasse-entry-heading"><strong>{row.owner_name}</strong><i className={'status-badge '+tone(row.status)}>{label[row.status]||row.status}</i></span>
      <small>Imóvel #{row.property_code} · {row.charge_code}</small>
      <span className="repasse-entry-heading"><b>{money(row.amount)}</b><small>Previsto: {date(row.due_date)}</small></span>
     </button>)}
     {!loading&&!filtered.length&&<div className="repasse-empty">Nenhum repasse encontrado neste filtro.</div>}
    </div>
   </aside>
   <section className="panel repasse-detail" aria-label="Ficha do repasse">
    {loading?<div className="repasse-empty">Carregando repasses...</div>:!selected?<div className="repasse-empty">Selecione um repasse para consultar os detalhes.</div>:<>
     <header className="repasse-header">
      <div><span className="eyebrow">REPASSE AO PROPRIETÁRIO</span><h2>{selected.owner_name} <i className={'status-badge '+tone(selected.status)}>{label[selected.status]||selected.status}</i></h2><p>Imóvel #{selected.property_code} · {selected.lease_code} · {selected.charge_code}</p></div>
      <div className="repasse-actions">
       <button type="button" className="button secondary" onClick={()=>void statement(selected)}><Download size={14}/> Prestação de contas</button>
       {canPay&&selected.status==='pending'&&<button type="button" className="button primary" disabled={saving} onClick={()=>{setPaidAt(localNow());setReference('');setModal(true)}}><CheckCircle2 size={14}/> Registrar pagamento</button>}
      </div>
     </header>
     <div className="repasse-strip">
      <div><span>Valor</span><strong>{money(selected.amount)}</strong></div>
      <div><span>Competência</span><strong>{date(selected.competence)}</strong></div>
      <div><span>Previsão</span><strong>{date(selected.due_date)}</strong></div>
      <div><span>Participação</span><strong>{Number(selected.ownership_percent).toLocaleString('pt-BR')}%</strong></div>
     </div>
     <nav className="repasse-tabs" aria-label="Abas do repasse">
      <button type="button" className={tab==='overview'?'active':''} onClick={()=>setTab('overview')}><Landmark size={14}/> Visão geral</button>
      <button type="button" className={tab==='payment'?'active':''} onClick={()=>setTab('payment')}><WalletCards size={14}/> Pagamento e documentos</button>
     </nav>
     <div className="repasse-body">
      {tab==='overview'&&<div className="repasse-panels">
       <article className="repasse-card"><h3>Condições do repasse</h3><div className="repasse-facts">
        <div><span>Proprietário</span><strong>{selected.owner_name}</strong></div><div><span>Participação</span><strong>{Number(selected.ownership_percent).toLocaleString('pt-BR')}%</strong></div>
        <div><span>Imóvel</span><strong>#{selected.property_code}</strong></div><div><span>Contrato de locação</span><strong>{selected.lease_code}</strong></div>
        <div><span>Cobrança de origem</span><strong>{selected.charge_code}</strong></div><div><span>Previsão de repasse</span><strong>{date(selected.due_date)}</strong></div>
       </div></article>
       <article className="repasse-card"><h3>Situação financeira</h3><div className="repasse-lines">
        <div><span>Valor devido</span><strong>{money(selected.amount)}</strong></div><div><span>Situação</span><strong>{label[selected.status]||selected.status}</strong></div>
        <div><span>Pagamento</span><strong>{datetime(selected.paid_at)}</strong></div>
       </div></article>
      </div>}
      {tab==='payment'&&<article className="repasse-card">
       <h3>Pagamento registrado</h3><div className="repasse-facts">
        <div><span>Situação</span><strong>{label[selected.status]||selected.status}</strong></div>
        <div><span>Data da baixa</span><strong>{datetime(selected.paid_at)}</strong></div>
        <div><span>Referência</span><strong>{selected.payment_reference||'Não informada'}</strong></div>
        <div><span>Valor</span><strong>{money(selected.amount)}</strong></div>
       </div>
       <div className="repasse-document-note"><FileText size={18}/><div><strong>Prestação de contas em PDF</strong><p>Documento financeiro por proprietário, imóvel e competência. A referência do pagamento não substitui comprovante bancário.</p><button type="button" className="button secondary" onClick={()=>void statement(selected)}><Download size={14}/> Gerar PDF</button></div></div>
      </article>}
     </div>
    </>}
   </section>
  </div>
  {modal&&selected&&<div className="finance-modal-backdrop"><form className="panel finance-modal repasse-payment-modal" aria-label="Registrar repasse" onSubmit={pay}>
   <div className="finance-modal-header"><div><span className="eyebrow">BAIXA FINANCEIRA</span><h2>Registrar repasse</h2><p>{selected.owner_name} · {money(selected.amount)}</p></div><button type="button" aria-label="Fechar" disabled={saving} onClick={()=>setModal(false)}><X size={18}/></button></div>
   <div className="repasse-payment-fields">
    <label>Data e hora do pagamento<input type="datetime-local" required value={paidAt} onChange={e=>setPaidAt(e.target.value)}/></label>
    <label>Referência ou número da transação<input value={reference} onChange={e=>setReference(e.target.value)} placeholder="Opcional"/></label>
   </div>
   <div className="form-actions"><button type="button" className="button secondary" disabled={saving} onClick={()=>setModal(false)}>Cancelar</button><button type="submit" className="button primary" disabled={saving}>{saving?'Registrando...':'Confirmar pagamento'}</button></div>
  </form></div>}
 </section>
}
