import {
  AlertTriangle,
  ArrowDownCircle,
  ArrowUpCircle,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  FilePlus2,
  RefreshCw,
  Search,
  ShieldCheck,
  WalletCards,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './finance-core.css'

type Direction = 'receivable'|'payable'
type FundScope = 'operating'|'third_party'
type CoreItem = {
  id:string
  code:string
  source_type:string
  source_id:string
  direction:Direction
  fund_scope:FundScope
  category:string
  description:string
  counterparty_name:string
  property_id:string|null
  lease_contract_id:string|null
  competence:string
  due_date:string|null
  amount:number
  settled_amount:number
  remaining_amount:number
  margin_amount:number
  status:string
  overdue:boolean
  settled_at:string|null
  payment_method:string|null
  payment_reference:string|null
  manual:boolean
}
type Overview = {
  competence:string
  receivable_open_amount:number
  payable_open_amount:number
  overdue_receivable_amount:number
  overdue_payable_amount:number
  received_amount:number
  paid_amount:number
  operating_open_amount:number
  third_party_open_amount:number
  receivable_open_count:number
  payable_open_count:number
  overdue_count:number
  items:CoreItem[]
}
type Props = {
  permissions:string[]
  onNavigateSource:(source:'rent'|'maintenance')=>void
}
type Filter = 'all'|'receivable'|'payable'|'overdue'|'third_party'|'operating'

const statusLabels:Record<string,string> = {
  pending:'Pendente', partial:'Parcial', overdue:'Vencido', settled:'Liquidado', cancelled:'Cancelado', settled_zero:'Compensado',
}
const sourceLabels:Record<string,string> = {
  rent:'Locação',
  owner_repasse:'Repasse',
  maintenance:'Manutenção',
  manual:'Manual',
  lease_exit_adjustment:'Acerto de saída',
  lease_termination_fine:'Multa rescisória',
  lease_charge_component:'Encargo da locação',
  commission:'Comissão',
}

function money(value:number|null|undefined){ return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'}) }
function dateLabel(value:string|null|undefined){ if(!value)return '—'; return new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString('pt-BR') }
function currentMonth(){ const now=new Date(); return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}` }
function todayInput(){ const now=new Date(); const offset=now.getTimezoneOffset(); return new Date(now.getTime()-offset*60000).toISOString().slice(0,10) }
function localDateTime(){ const now=new Date(); const offset=now.getTimezoneOffset(); return new Date(now.getTime()-offset*60000).toISOString().slice(0,16) }

export function FinanceCorePanel({permissions,onNavigateSource}:Props){
  const canCreateReceivable=permissions.includes('finance.charge.create')
  const canCreatePayable=permissions.includes('finance.payment.prepare')
  const canSettleReceivable=permissions.includes('finance.reconcile')
  const canSettlePayable=permissions.includes('finance.payment.approve')

  const [month,setMonth]=useState(currentMonth())
  const [overview,setOverview]=useState<Overview|null>(null)
  const [overdueItems,setOverdueItems]=useState<CoreItem[]>([])
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [filter,setFilter]=useState<Filter>('all')
  const [query,setQuery]=useState('')
  const [selectedKey,setSelectedKey]=useState<string|null>(null)
  const [createOpen,setCreateOpen]=useState(false)
  const [settleTarget,setSettleTarget]=useState<CoreItem|null>(null)

  const [direction,setDirection]=useState<Direction>('payable')
  const [fundScope,setFundScope]=useState<FundScope>('operating')
  const [category,setCategory]=useState('Despesa operacional')
  const [description,setDescription]=useState('')
  const [counterparty,setCounterparty]=useState('')
  const [dueDate,setDueDate]=useState(todayInput())
  const [amount,setAmount]=useState('')
  const [notes,setNotes]=useState('')

  const [settleAt,setSettleAt]=useState(localDateTime())
  const [settleMethod,setSettleMethod]=useState('pix')
  const [settleReference,setSettleReference]=useState('')

  const competence=`${month}-01`

  const load=useCallback(async()=>{
    setLoading(true);setError('')
    try{
      const [monthly,overdue]=await Promise.all([
        apiRequest<Overview>(`/finance/core/overview?competence=${competence}`),
        apiRequest<CoreItem[]>('/finance/core/overdue'),
      ])
      setOverview(monthly);setOverdueItems(overdue)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar a visão financeira consolidada.')}
    finally{setLoading(false)}
  },[competence])

  useEffect(()=>{void load()},[load])

  const items=useMemo(()=>{
    const base=filter==='overdue'
      ? overdueItems
      : (()=>{const all=overview?.items||[];if(filter==='all')return all;if(filter==='third_party'||filter==='operating')return all.filter(item=>item.fund_scope===filter);return all.filter(item=>item.direction===filter)})()
    const term=query.trim().toLocaleLowerCase('pt-BR')
    if(!term)return base
    return base.filter(item=>[item.code,item.description,item.counterparty_name,item.category,sourceLabels[item.source_type]||item.source_type].join(' ').toLocaleLowerCase('pt-BR').includes(term))
  },[overview,overdueItems,filter,query])
  useEffect(()=>{
    if(items.length===0){setSelectedKey(null);return}
    if(!selectedKey||!items.some(item=>`${item.source_type}:${item.id}`===selectedKey))setSelectedKey(`${items[0].source_type}:${items[0].id}`)
  },[items,selectedKey])
  const selectedItem=useMemo(()=>items.find(item=>`${item.source_type}:${item.id}`===selectedKey)??null,[items,selectedKey])

  const overdueReceivable=useMemo(()=>overdueItems.filter(item=>item.direction==='receivable').reduce((total,item)=>total+item.remaining_amount,0),[overdueItems])
  const overduePayable=useMemo(()=>overdueItems.filter(item=>item.direction==='payable').reduce((total,item)=>total+item.remaining_amount,0),[overdueItems])
  const manualOpen=useMemo(()=>items.filter(item=>item.manual&&!['settled','cancelled','settled_zero'].includes(item.status)).length,[items])

  function moveMonth(directionValue:number){
    const [year,monthNumber]=month.split('-').map(Number)
    const next=new Date(year,monthNumber-1+directionValue,1)
    setMonth(`${next.getFullYear()}-${String(next.getMonth()+1).padStart(2,'0')}`)
  }
  function resetCreate(nextDirection:Direction='payable'){
    setDirection(nextDirection);setFundScope('operating');setCategory(nextDirection==='payable'?'Despesa operacional':'Receita operacional');setDescription('');setCounterparty('');setDueDate(todayInput());setAmount('');setNotes('')
  }
  async function createTitle(event:FormEvent){
    event.preventDefault();setSaving(true);setError('');setSuccess('')
    try{
      await apiRequest('/finance/core/manual',{method:'POST',body:JSON.stringify({direction,fund_scope:fundScope,category,description,counterparty_name:counterparty,competence,due_date:dueDate,amount:Number(amount.replace(',','.')),notes:notes||null})})
      setCreateOpen(false);resetCreate(direction);await load();setSuccess(direction==='receivable'?'Conta a receber criada.':'Conta a pagar criada.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível criar o título financeiro.')}
    finally{setSaving(false)}
  }
  async function settle(event:FormEvent){
    event.preventDefault();if(!settleTarget)return;setSaving(true);setError('');setSuccess('')
    try{
      await apiRequest(`/finance/core/manual/${settleTarget.id}/settle`,{method:'POST',body:JSON.stringify({amount:settleTarget.remaining_amount,settled_at:new Date(settleAt).toISOString(),payment_method:settleMethod,payment_reference:settleReference||null})})
      const code=settleTarget.code;setSettleTarget(null);setSettleReference('');await load();setSuccess(`${code} liquidado com sucesso.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível liquidar o título.')}
    finally{setSaving(false)}
  }
  function openCreate(nextDirection:Direction){resetCreate(nextDirection);setCreateOpen(true)}
  function openSource(item:CoreItem){if(item.source_type==='maintenance')onNavigateSource('maintenance');else if(item.source_type==='rent'||item.source_type==='owner_repasse')onNavigateSource('rent')}
  const canNavigateSource=(item:CoreItem)=>['rent','owner_repasse','maintenance'].includes(item.source_type)
  const canSettle=(item:CoreItem)=>item.manual&&(item.direction==='receivable'?canSettleReceivable:canSettlePayable)&&!['settled','cancelled','settled_zero'].includes(item.status)

  return <section className="workspace finance-core-workspace">
    <div className="page-heading finance-heading finance-core-heading">
      <div><span className="eyebrow">Financeiro · Central</span><h1>Visão financeira</h1><p>Recebimentos, pagamentos e valores de terceiros consolidados em uma única visão, sem perder a origem de cada lançamento.</p></div>
      <div className="heading-actions">
        <button className="icon-button" type="button" onClick={()=>moveMonth(-1)} aria-label="Mês anterior"><ChevronLeft size={16}/></button>
        <label className="finance-month"><CalendarDays size={15}/><input type="month" value={month} onChange={event=>setMonth(event.target.value)}/></label>
        <button className="icon-button" type="button" onClick={()=>moveMonth(1)} aria-label="Próximo mês"><ChevronRight size={16}/></button>
        <button className="button secondary" type="button" onClick={()=>void load()} disabled={loading}><RefreshCw size={14}/> Atualizar</button>
        {(canCreatePayable||canCreateReceivable)&&<div className="finance-core-create-actions">{canCreatePayable&&<button className="button secondary" type="button" onClick={()=>openCreate('payable')}><ArrowUpCircle size={14}/> Nova conta a pagar</button>}{canCreateReceivable&&<button className="button primary" type="button" onClick={()=>openCreate('receivable')}><FilePlus2 size={14}/> Nova conta a receber</button>}</div>}
      </div>
    </div>

    {overview&&<div className="finance-core-metrics">
      <article className="panel finance-core-metric receivable"><div><ArrowDownCircle size={17}/><span>A receber</span></div><strong>{money(overview.receivable_open_amount)}</strong><small>{overview.receivable_open_count} título(s) na competência</small></article>
      <article className="panel finance-core-metric payable"><div><ArrowUpCircle size={17}/><span>A pagar</span></div><strong>{money(overview.payable_open_amount)}</strong><small>{overview.payable_open_count} obrigação(ões) na competência</small></article>
      <article className={`panel finance-core-metric ${overdueItems.length?'danger':''}`}><div><AlertTriangle size={17}/><span>Vencidos</span></div><strong>{money(overdueReceivable+overduePayable)}</strong><small>{overdueItems.length} lançamento(s) vencido(s) em todas as competências</small></article>
      <article className="panel finance-core-metric"><div><ShieldCheck size={17}/><span>Valores de terceiros</span></div><strong>{money(overview.third_party_open_amount)}</strong><small>Separados do caixa operacional</small></article>
      <article className="panel finance-core-metric"><div><WalletCards size={17}/><span>Operacional em aberto</span></div><strong>{money(overview.operating_open_amount)}</strong><small>Receitas e despesas próprias</small></article>
      <article className="panel finance-core-metric settled"><div><CheckCircle2 size={17}/><span>Movimentado</span></div><strong>{money(overview.received_amount+overview.paid_amount)}</strong><small>{money(overview.received_amount)} recebido · {money(overview.paid_amount)} pago</small></article>
    </div>}

    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}

    <div className="panel finance-core-toolbar">
      <div className="finance-core-toolbar-main"><div className="finance-filter">
        <button className={filter==='all'?'active':''} onClick={()=>setFilter('all')}>Todos</button><button className={filter==='receivable'?'active':''} onClick={()=>setFilter('receivable')}>A receber</button><button className={filter==='payable'?'active':''} onClick={()=>setFilter('payable')}>A pagar</button><button className={filter==='overdue'?'active':''} onClick={()=>setFilter('overdue')}>Vencidos <span>{overdueItems.length}</span></button><button className={filter==='third_party'?'active':''} onClick={()=>setFilter('third_party')}>Terceiros</button><button className={filter==='operating'?'active':''} onClick={()=>setFilter('operating')}>Operacional</button>
      </div><label className="finance-core-search"><Search size={13}/><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Buscar lançamento..."/></label></div>
      <span>{items.length} lançamento(s) · {manualOpen} manual(is) pendente(s)</span>
    </div>

    {loading?<article className="panel settings-loading">Carregando financeiro...</article>:<div className="finance-core-master-detail">
      <div className="finance-core-list">
        {items.map(item=>{const key=`${item.source_type}:${item.id}`;return <button type="button" className={`panel finance-core-row ${item.overdue?'overdue':''} ${selectedKey===key?'active':''}`} key={key} onClick={()=>setSelectedKey(key)}>
          <div className={`finance-core-direction ${item.direction}`} title={item.direction==='receivable'?'Entrada':'Saída'}>{item.direction==='receivable'?<ArrowDownCircle size={18}/>:<ArrowUpCircle size={18}/>}</div>
          <div className="finance-core-main"><div className="finance-core-code-line"><strong>{item.code}</strong><span>{sourceLabels[item.source_type]||item.source_type}</span><i className={`status-badge ${item.status==='settled'?'success':item.overdue?'danger':item.status==='cancelled'?'neutral':'warning'}`}>{statusLabels[item.status]||item.status}</i></div><h3>{item.description}</h3><p>{item.counterparty_name} · venc. {dateLabel(item.due_date)}</p></div>
          <div className="finance-core-value"><span>{item.direction==='receivable'?'A receber':'A pagar'}</span><strong>{money(item.remaining_amount||item.amount)}</strong>{item.settled_amount>0&&<small>{money(item.settled_amount)} liquidado</small>}</div>
        </button>})}
        {items.length===0&&<article className="panel finance-empty"><CircleDollarSign size={28}/><strong>{filter==='overdue'?'Nenhum título vencido em aberto.':'Nenhum lançamento nesta competência.'}</strong><span>{filter==='overdue'?'A consulta de vencidos considera todas as competências.':'As cobranças de locação e os lançamentos de manutenção aparecerão aqui automaticamente.'}</span></article>}
      </div>
      <aside className="panel finance-core-detail">
        {selectedItem?<><div className="finance-core-detail-head"><div><span className="eyebrow">{sourceLabels[selectedItem.source_type]||selectedItem.source_type}</span><h2>{selectedItem.description}</h2><p>{selectedItem.code} · {selectedItem.counterparty_name}</p></div><i className={`status-badge ${selectedItem.status==='settled'?'success':selectedItem.overdue?'danger':selectedItem.status==='cancelled'?'neutral':'warning'}`}>{statusLabels[selectedItem.status]||selectedItem.status}</i></div>
          <div className="finance-core-detail-amount"><span>Saldo atual</span><strong>{money(selectedItem.remaining_amount)}</strong><small>Valor original {money(selectedItem.amount)}</small></div>
          <div className="finance-core-detail-grid"><div><span>Vencimento</span><strong>{dateLabel(selectedItem.due_date)}</strong></div><div><span>Competência</span><strong>{selectedItem.competence.slice(0,7).split('-').reverse().join('/')}</strong></div><div><span>Natureza</span><strong>{selectedItem.fund_scope==='third_party'?'Terceiros':'Operacional'}</strong></div><div><span>Categoria</span><strong>{selectedItem.category}</strong></div><div><span>Liquidação</span><strong>{selectedItem.settled_at?dateLabel(selectedItem.settled_at):'Pendente'}</strong></div><div><span>Origem</span><strong>{selectedItem.manual?'Manual':'Automática'}</strong></div></div>
          {selectedItem.overdue&&<div className="finance-core-alert"><AlertTriangle size={15}/><div><strong>Lançamento vencido</strong><span>Saldo em aberto de {money(selectedItem.remaining_amount)}.</span></div></div>}
          <div className="finance-core-detail-actions">{canNavigateSource(selectedItem)&&<button className="button secondary" type="button" onClick={()=>openSource(selectedItem)}>Ver origem</button>}{canSettle(selectedItem)&&<button className="button primary" type="button" onClick={()=>{setSettleTarget(selectedItem);setSettleAt(localDateTime());setSettleMethod('pix');setSettleReference('')}}><CheckCircle2 size={13}/> Liquidar</button>}</div>
        </>:<div className="finance-core-detail-empty"><CircleDollarSign size={26}/><strong>Selecione um lançamento</strong><span>Os detalhes operacionais aparecerão aqui.</span></div>}
      </aside>
    </div>}

    {createOpen&&<div className="finance-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target)setCreateOpen(false)}}><form className="panel finance-modal finance-core-modal" onSubmit={createTitle}>
      <div className="finance-modal-header"><div><span className="eyebrow">Lançamento manual</span><h2>{direction==='receivable'?'Nova conta a receber':'Nova conta a pagar'}</h2><p>Use apenas para obrigações que não nascem automaticamente de outro módulo.</p></div><button type="button" onClick={()=>setCreateOpen(false)}><X size={17}/></button></div>
      <div className="form-grid two-columns finance-core-form"><label><span>Tipo</span><select value={direction} onChange={event=>{const next=event.target.value as Direction;setDirection(next);setCategory(next==='payable'?'Despesa operacional':'Receita operacional')}}><option value="payable">Conta a pagar</option><option value="receivable">Conta a receber</option></select></label><label><span>Natureza do recurso</span><select value={fundScope} onChange={event=>setFundScope(event.target.value as FundScope)}><option value="operating">Operacional da imobiliária</option><option value="third_party">Valor de terceiros</option></select></label><label><span>Categoria</span><input value={category} onChange={event=>setCategory(event.target.value)} required/></label><label><span>Contraparte</span><input value={counterparty} onChange={event=>setCounterparty(event.target.value)} placeholder="Fornecedor, cliente, órgão..." required/></label><label className="span-2"><span>Descrição</span><input value={description} onChange={event=>setDescription(event.target.value)} placeholder="Ex.: Honorários jurídicos, taxa bancária..." required/></label><label><span>Vencimento</span><input type="date" value={dueDate} onChange={event=>setDueDate(event.target.value)} required/></label><label><span>Valor</span><input inputMode="decimal" value={amount} onChange={event=>setAmount(event.target.value)} placeholder="0,00" required/></label><label className="span-2"><span>Observações</span><textarea rows={3} value={notes} onChange={event=>setNotes(event.target.value)}/></label></div>
      <div className="form-actions"><button className="button secondary" type="button" onClick={()=>setCreateOpen(false)}>Cancelar</button><button className="button primary" type="submit" disabled={saving}>{saving?'Salvando...':'Criar lançamento'}</button></div>
    </form></div>}

    {settleTarget&&<div className="finance-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target)setSettleTarget(null)}}><form className="panel finance-modal finance-core-modal" onSubmit={settle}>
      <div className="finance-modal-header"><div><span className="eyebrow">{settleTarget.code}</span><h2>Liquidar {settleTarget.direction==='receivable'?'recebimento':'pagamento'}</h2><p>{settleTarget.description}</p></div><button type="button" onClick={()=>setSettleTarget(null)}><X size={17}/></button></div><div className="finance-modal-amount"><span>Saldo a liquidar</span><strong>{money(settleTarget.remaining_amount)}</strong><small>{settleTarget.counterparty_name}</small></div>
      <div className="form-grid two-columns finance-core-form"><label><span>Data e hora</span><input type="datetime-local" value={settleAt} onChange={event=>setSettleAt(event.target.value)} required/></label><label><span>Forma</span><select value={settleMethod} onChange={event=>setSettleMethod(event.target.value)}><option value="pix">Pix</option><option value="boleto">Boleto</option><option value="transfer">Transferência</option><option value="cash">Dinheiro</option><option value="card">Cartão</option><option value="other">Outro</option></select></label><label className="span-2"><span>Referência / comprovante</span><input value={settleReference} onChange={event=>setSettleReference(event.target.value)} placeholder="Opcional"/></label></div>
      <div className="form-actions"><button className="button secondary" type="button" onClick={()=>setSettleTarget(null)}>Cancelar</button><button className="button primary" type="submit" disabled={saving}>{saving?'Liquidando...':'Confirmar liquidação'}</button></div>
    </form></div>}
  </section>
}