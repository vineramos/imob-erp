import {
  ArrowDownCircle,
  ArrowUpCircle,
  Building2,
  CheckCircle2,
  FileUp,
  Landmark,
  Link2,
  Plus,
  RefreshCw,
  Search,
  WalletCards,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './finance-banking.css'

type FundScope='operating'|'third_party'
type Account={
  id:string;code:string;name:string;bank_name:string;bank_code:string|null;branch:string|null;account_number:string|null;account_digit:string|null
  account_type:string;fund_scope:FundScope;provider:string;pix_key:string|null;opening_balance:number;current_balance:number;is_active:boolean;last_sync_at:string|null;created_at:string
}
type Allocation={id:string;target_type:string;target_id:string;target_code:string;target_direction:string;amount:number;notes:string|null;reconciled_at:string}
type Transaction={
  id:string;code:string;bank_account_id:string;transaction_date:string;posted_at:string|null;direction:'credit'|'debit';amount:number;description:string
  document:string|null;counterparty_name:string|null;bank_reference:string|null;balance_after:number|null;source:string;status:string
  reconciled_amount:number;remaining_amount:number;reconciliations:Allocation[];created_at:string
}
type Overview={
  account:Account;competence:string;credits_amount:number;debits_amount:number;pending_credits_amount:number;pending_debits_amount:number
  reconciled_amount:number;pending_count:number;reconciled_count:number;transactions:Transaction[]
}
type Candidate={
  target_type:string;target_id:string;target_code:string;direction:'receivable'|'payable';fund_scope:FundScope;description:string
  counterparty_name:string;due_date:string|null;remaining_amount:number;score:number
}

const statusLabel:Record<string,string>={pending:'Pendente',partial:'Parcial',reconciled:'Conciliado'}
const targetLabel:Record<string,string>={rent:'Locação',owner_repasse:'Repasse',maintenance:'Manutenção',manual:'Manual'}

function money(value:number|null|undefined){return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function dateLabel(value:string|null|undefined){if(!value)return '—';return new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString('pt-BR')}
function currentMonth(){const now=new Date();return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`}
function today(){const now=new Date();const offset=now.getTimezoneOffset();return new Date(now.getTime()-offset*60000).toISOString().slice(0,10)}

export function FinanceBankingPanel({permissions}:{permissions:string[]}){
  const canReconcile=permissions.includes('finance.reconcile')
  const canApprovePayment=permissions.includes('finance.payment.approve')
  const [month,setMonth]=useState(currentMonth())
  const [accounts,setAccounts]=useState<Account[]>([])
  const [selectedId,setSelectedId]=useState('')
  const [overview,setOverview]=useState<Overview|null>(null)
  const [loading,setLoading]=useState(true)
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')
  const [filter,setFilter]=useState<'all'|'pending'|'credit'|'debit'>('all')

  const [accountOpen,setAccountOpen]=useState(false)
  const [accountName,setAccountName]=useState('')
  const [bankName,setBankName]=useState('Banco Inter')
  const [bankCode,setBankCode]=useState('077')
  const [branch,setBranch]=useState('')
  const [accountNumber,setAccountNumber]=useState('')
  const [accountDigit,setAccountDigit]=useState('')
  const [accountScope,setAccountScope]=useState<FundScope>('operating')
  const [openingBalance,setOpeningBalance]=useState('0')

  const [moveOpen,setMoveOpen]=useState(false)
  const [moveDate,setMoveDate]=useState(today())
  const [moveDirection,setMoveDirection]=useState<'credit'|'debit'>('credit')
  const [moveAmount,setMoveAmount]=useState('')
  const [moveDescription,setMoveDescription]=useState('')
  const [moveReference,setMoveReference]=useState('')

  const [importOpen,setImportOpen]=useState(false)
  const [importFile,setImportFile]=useState<File|null>(null)

  const [reconcileTx,setReconcileTx]=useState<Transaction|null>(null)
  const [candidates,setCandidates]=useState<Candidate[]>([])
  const [candidateLoading,setCandidateLoading]=useState(false)
  const [candidateQuery,setCandidateQuery]=useState('')

  const competence=`${month}-01`

  const loadAccounts=useCallback(async(preferredId?:string)=>{
    const items=await apiRequest<Account[]>('/finance/banking/accounts')
    setAccounts(items)
    const next=preferredId||selectedId||items[0]?.id||''
    if(next&&items.some(item=>item.id===next))setSelectedId(next)
    else setSelectedId(items[0]?.id||'')
    return next
  },[selectedId])

  const loadOverview=useCallback(async(accountId?:string)=>{
    const id=accountId||selectedId
    if(!id){setOverview(null);setLoading(false);return}
    setLoading(true);setError('')
    try{
      setOverview(await apiRequest<Overview>(`/finance/banking/overview?account_id=${id}&competence=${competence}`))
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o extrato bancário.')}
    finally{setLoading(false)}
  },[selectedId,competence])

  useEffect(()=>{
    void (async()=>{
      setLoading(true)
      try{const id=await loadAccounts();if(id)await loadOverview(id)}
      catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar as contas bancárias.');setLoading(false)}
    })()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[])

  useEffect(()=>{if(selectedId)void loadOverview(selectedId)},[selectedId,competence,loadOverview])

  const selected=useMemo(()=>accounts.find(item=>item.id===selectedId)||overview?.account||null,[accounts,selectedId,overview])
  const transactions=useMemo(()=>{
    const all=overview?.transactions||[]
    if(filter==='all')return all
    if(filter==='pending')return all.filter(item=>item.remaining_amount>0)
    return all.filter(item=>item.direction===filter)
  },[overview,filter])

  const visibleCandidates=useMemo(()=>{
    const query=candidateQuery.trim().toLowerCase()
    if(!query)return candidates
    return candidates.filter(item=>`${item.target_code} ${item.description} ${item.counterparty_name}`.toLowerCase().includes(query))
  },[candidates,candidateQuery])

  async function refresh(){
    try{await loadAccounts(selectedId);await loadOverview(selectedId);setSuccess('Dados bancários atualizados.')}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível atualizar os dados bancários.')}
  }

  async function createAccount(event:FormEvent){
    event.preventDefault();setSaving(true);setError('');setSuccess('')
    try{
      const created=await apiRequest<Account>('/finance/banking/accounts',{method:'POST',body:JSON.stringify({
        name:accountName,bank_name:bankName,bank_code:bankCode||null,branch:branch||null,account_number:accountNumber||null,account_digit:accountDigit||null,
        account_type:'checking',fund_scope:accountScope,provider:bankName.toLowerCase().includes('inter')?'inter':'manual',opening_balance:Number(openingBalance.replace(',','.'))||0,
      })})
      setAccountOpen(false);setAccountName('');setBranch('');setAccountNumber('');setAccountDigit('');setOpeningBalance('0')
      await loadAccounts(created.id);setSelectedId(created.id);await loadOverview(created.id)
      setSuccess(`${created.name} cadastrada.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível cadastrar a conta bancária.')}
    finally{setSaving(false)}
  }

  async function createMovement(event:FormEvent){
    event.preventDefault();if(!selectedId)return
    setSaving(true);setError('');setSuccess('')
    try{
      await apiRequest(`/finance/banking/accounts/${selectedId}/transactions`,{method:'POST',body:JSON.stringify({
        transaction_date:moveDate,direction:moveDirection,amount:Number(moveAmount.replace(',','.')),description:moveDescription,bank_reference:moveReference||null,
      })})
      setMoveOpen(false);setMoveAmount('');setMoveDescription('');setMoveReference('');await loadOverview(selectedId);await loadAccounts(selectedId)
      setSuccess('Movimento incluído no extrato.')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível incluir o movimento.')}
    finally{setSaving(false)}
  }

  async function importStatement(event:FormEvent){
    event.preventDefault();if(!selectedId||!importFile)return
    setSaving(true);setError('');setSuccess('')
    try{
      const data=new FormData();data.append('file',importFile)
      const result=await apiRequest<{created_rows:number;duplicate_rows:number;total_rows:number}>(`/finance/banking/accounts/${selectedId}/import`,{method:'POST',body:data})
      setImportOpen(false);setImportFile(null);await loadOverview(selectedId);await loadAccounts(selectedId)
      setSuccess(`${result.created_rows} movimento(s) importado(s). ${result.duplicate_rows} duplicado(s) ignorado(s).`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível importar o extrato.')}
    finally{setSaving(false)}
  }

  async function openReconcile(item:Transaction){
    setReconcileTx(item);setCandidateLoading(true);setCandidates([]);setCandidateQuery('');setError('')
    try{setCandidates(await apiRequest<Candidate[]>(`/finance/banking/transactions/${item.id}/candidates`))}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível buscar títulos para conciliação.')}
    finally{setCandidateLoading(false)}
  }

  async function reconcile(candidate:Candidate){
    if(!reconcileTx)return
    setSaving(true);setError('');setSuccess('')
    try{
      const amount=Math.min(reconcileTx.remaining_amount,candidate.remaining_amount)
      await apiRequest(`/finance/banking/transactions/${reconcileTx.id}/reconcile`,{method:'POST',body:JSON.stringify({
        target_type:candidate.target_type,target_id:candidate.target_id,amount,
      })})
      const code=reconcileTx.code;setReconcileTx(null);setCandidates([]);await loadOverview(selectedId);await loadAccounts(selectedId)
      setSuccess(`${code} conciliado com ${candidate.target_code}.`)
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível concluir a conciliação.')}
    finally{setSaving(false)}
  }

  const canConciliateTx=(item:Transaction)=>item.remaining_amount>0&&(item.direction==='credit'?canReconcile:canApprovePayment)

  return <section className="workspace finance-banking-workspace">
    <div className="page-heading finance-heading">
      <div><span className="eyebrow">Financeiro · Bancos</span><h1>Contas bancárias e conciliação</h1><p>Extrato real, separação entre recursos próprios e de terceiros e baixa financeira ligada à origem do lançamento.</p></div>
      <div className="heading-actions">
        <label className="finance-month"><input type="month" value={month} onChange={event=>setMonth(event.target.value)}/></label>
        <button className="button secondary" type="button" onClick={()=>void refresh()} disabled={loading}><RefreshCw size={14}/> Atualizar</button>
        {canReconcile&&<button className="button secondary" type="button" onClick={()=>setAccountOpen(true)}><Landmark size={14}/> Nova conta</button>}
        {selected&&canReconcile&&<button className="button secondary" type="button" onClick={()=>setImportOpen(true)}><FileUp size={14}/> Importar extrato</button>}
        {selected&&canReconcile&&<button className="button primary" type="button" onClick={()=>{setMoveOpen(true);setMoveDate(today())}}><Plus size={14}/> Movimento</button>}
      </div>
    </div>

    {accounts.length>0&&<div className="finance-bank-account-strip">
      {accounts.map(item=><button type="button" key={item.id} className={`panel finance-bank-account ${selectedId===item.id?'active':''}`} onClick={()=>setSelectedId(item.id)}>
        <div><Building2 size={16}/><span>{item.bank_name}</span></div><strong>{item.name}</strong><small>{item.code} · {item.fund_scope==='third_party'?'Recursos de terceiros':'Caixa operacional'}</small><b>{money(item.current_balance)}</b>
      </button>)}
    </div>}

    {error&&<div className="form-alert danger-alert">{error}</div>}
    {success&&<div className="form-alert success-alert">{success}</div>}

    {!selected&&!loading?<article className="panel finance-bank-empty">
      <Landmark size={32}/><strong>Nenhuma conta bancária cadastrada.</strong><span>Cadastre separadamente a conta operacional e a conta usada para valores de proprietários/locatários.</span>
      {canReconcile&&<button className="button primary" type="button" onClick={()=>setAccountOpen(true)}>Cadastrar primeira conta</button>}
    </article>:overview&&<>
      <div className="finance-bank-metrics">
        <article className="panel"><span>Saldo da conta</span><strong>{money(overview.account.current_balance)}</strong><small>{overview.account.fund_scope==='third_party'?'Recursos de terceiros':'Operacional'}</small></article>
        <article className="panel credit"><span>Créditos no mês</span><strong>{money(overview.credits_amount)}</strong><small>{money(overview.pending_credits_amount)} a conciliar</small></article>
        <article className="panel debit"><span>Débitos no mês</span><strong>{money(overview.debits_amount)}</strong><small>{money(overview.pending_debits_amount)} a conciliar</small></article>
        <article className="panel"><span>Conciliação</span><strong>{overview.reconciled_count}</strong><small>{overview.pending_count} movimento(s) pendente(s)</small></article>
      </div>

      <div className="panel finance-bank-toolbar">
        <div className="finance-filter">
          <button className={filter==='all'?'active':''} onClick={()=>setFilter('all')}>Todos</button>
          <button className={filter==='pending'?'active':''} onClick={()=>setFilter('pending')}>A conciliar</button>
          <button className={filter==='credit'?'active':''} onClick={()=>setFilter('credit')}>Entradas</button>
          <button className={filter==='debit'?'active':''} onClick={()=>setFilter('debit')}>Saídas</button>
        </div>
        <span>{transactions.length} movimento(s)</span>
      </div>

      {loading?<article className="panel settings-loading">Carregando extrato...</article>:<div className="finance-bank-list">
        {transactions.map(item=><article className={`panel finance-bank-row ${item.remaining_amount<=0?'reconciled':''}`} key={item.id}>
          <div className={`finance-bank-direction ${item.direction}`}>{item.direction==='credit'?<ArrowDownCircle size={18}/>:<ArrowUpCircle size={18}/>}</div>
          <div className="finance-bank-main"><div><strong>{item.code}</strong><i className={`status-badge ${item.remaining_amount<=0?'success':'warning'}`}>{statusLabel[item.status]||item.status}</i></div><h3>{item.description}</h3><p>{item.counterparty_name||item.bank_reference||'Sem contraparte informada'} · {item.source.toUpperCase()}</p></div>
          <div className="finance-bank-date"><span>Data</span><strong>{dateLabel(item.transaction_date)}</strong></div>
          <div className="finance-bank-value"><span>{item.direction==='credit'?'Entrada':'Saída'}</span><strong>{money(item.amount)}</strong>{item.reconciled_amount>0&&<small>{money(item.reconciled_amount)} conciliado</small>}</div>
          <div className="finance-bank-links">{item.reconciliations.slice(0,2).map(link=><span key={link.id}><Link2 size={11}/>{link.target_code} · {money(link.amount)}</span>)}</div>
          <div className="finance-bank-actions">{canConciliateTx(item)&&<button className="button primary compact" type="button" onClick={()=>void openReconcile(item)}><CheckCircle2 size={13}/> Conciliar</button>}</div>
        </article>)}
        {transactions.length===0&&<article className="panel finance-empty"><WalletCards size={28}/><strong>Nenhum movimento nesta competência.</strong><span>Importe um CSV/OFX ou registre um movimento bancário.</span></article>}
      </div>}
    </>}

    {accountOpen&&<div className="finance-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target)setAccountOpen(false)}}>
      <form className="panel finance-modal" onSubmit={createAccount}>
        <div className="finance-modal-header"><div><span className="eyebrow">Conta bancária</span><h2>Nova conta</h2><p>A natureza da conta controla quais títulos podem ser conciliados nela.</p></div><button type="button" onClick={()=>setAccountOpen(false)}><X size={17}/></button></div>
        <div className="form-grid two-columns">
          <label><span>Nome da conta</span><input required value={accountName} onChange={e=>setAccountName(e.target.value)} placeholder="Ex.: Inter · Operacional"/></label>
          <label><span>Natureza</span><select value={accountScope} onChange={e=>setAccountScope(e.target.value as FundScope)}><option value="operating">Operacional</option><option value="third_party">Recursos de terceiros</option></select></label>
          <label><span>Banco</span><input required value={bankName} onChange={e=>setBankName(e.target.value)}/></label>
          <label><span>Código</span><input value={bankCode} onChange={e=>setBankCode(e.target.value)} placeholder="077"/></label>
          <label><span>Agência</span><input value={branch} onChange={e=>setBranch(e.target.value)}/></label>
          <label><span>Conta</span><div className="finance-bank-account-number"><input value={accountNumber} onChange={e=>setAccountNumber(e.target.value)}/><input value={accountDigit} onChange={e=>setAccountDigit(e.target.value)} placeholder="DV"/></div></label>
          <label className="full"><span>Saldo inicial</span><input inputMode="decimal" value={openingBalance} onChange={e=>setOpeningBalance(e.target.value)}/></label>
        </div>
        <div className="form-actions"><button className="button secondary" type="button" onClick={()=>setAccountOpen(false)}>Cancelar</button><button className="button primary" disabled={saving}>Salvar conta</button></div>
      </form>
    </div>}

    {moveOpen&&<div className="finance-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target)setMoveOpen(false)}}>
      <form className="panel finance-modal" onSubmit={createMovement}>
        <div className="finance-modal-header"><div><span className="eyebrow">Extrato</span><h2>Novo movimento</h2><p>Use para lançamentos bancários ainda não importados pelo arquivo ou integração.</p></div><button type="button" onClick={()=>setMoveOpen(false)}><X size={17}/></button></div>
        <div className="form-grid two-columns">
          <label><span>Data</span><input type="date" required value={moveDate} onChange={e=>setMoveDate(e.target.value)}/></label>
          <label><span>Tipo</span><select value={moveDirection} onChange={e=>setMoveDirection(e.target.value as 'credit'|'debit')}><option value="credit">Entrada</option><option value="debit">Saída</option></select></label>
          <label className="full"><span>Descrição</span><input required value={moveDescription} onChange={e=>setMoveDescription(e.target.value)} placeholder="Histórico do extrato"/></label>
          <label><span>Valor</span><input required inputMode="decimal" value={moveAmount} onChange={e=>setMoveAmount(e.target.value)} placeholder="0,00"/></label>
          <label><span>Referência bancária</span><input value={moveReference} onChange={e=>setMoveReference(e.target.value)}/></label>
        </div>
        <div className="form-actions"><button className="button secondary" type="button" onClick={()=>setMoveOpen(false)}>Cancelar</button><button className="button primary" disabled={saving}>Adicionar</button></div>
      </form>
    </div>}

    {importOpen&&<div className="finance-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target)setImportOpen(false)}}>
      <form className="panel finance-modal" onSubmit={importStatement}>
        <div className="finance-modal-header"><div><span className="eyebrow">Extrato bancário</span><h2>Importar CSV ou OFX</h2><p>Movimentos repetidos são identificados e ignorados automaticamente.</p></div><button type="button" onClick={()=>setImportOpen(false)}><X size={17}/></button></div>
        <div className="finance-bank-import-box"><FileUp size={28}/><input type="file" required accept=".csv,.ofx,text/csv,application/x-ofx" onChange={e=>setImportFile(e.target.files?.[0]||null)}/><span>{importFile?importFile.name:'Selecione o arquivo do banco'}</span><small>Até 5 MB. Para CSV, use colunas de data, descrição e valor; o sinal do valor identifica entrada/saída quando não houver coluna de tipo.</small></div>
        <div className="form-actions"><button className="button secondary" type="button" onClick={()=>setImportOpen(false)}>Cancelar</button><button className="button primary" disabled={saving||!importFile}>Importar</button></div>
      </form>
    </div>}

    {reconcileTx&&<div className="finance-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target)setReconcileTx(null)}}>
      <div className="panel finance-modal finance-reconcile-modal">
        <div className="finance-modal-header"><div><span className="eyebrow">Conciliação bancária</span><h2>{reconcileTx.code} · {money(reconcileTx.remaining_amount)}</h2><p>{reconcileTx.description}</p></div><button type="button" onClick={()=>setReconcileTx(null)}><X size={17}/></button></div>
        <div className="finance-reconcile-search"><Search size={14}/><input value={candidateQuery} onChange={e=>setCandidateQuery(e.target.value)} placeholder="Buscar por código, pessoa ou descrição"/></div>
        <div className="finance-reconcile-list">
          {candidateLoading?<div className="settings-loading">Buscando títulos compatíveis...</div>:visibleCandidates.map(item=><button type="button" className="finance-reconcile-candidate" key={`${item.target_type}-${item.target_id}`} disabled={saving} onClick={()=>void reconcile(item)}>
            <div><strong>{item.target_code}</strong><span>{targetLabel[item.target_type]||item.target_type}</span>{item.score>=70&&<i>Melhor correspondência</i>}</div>
            <h3>{item.description}</h3><p>{item.counterparty_name} · vence {dateLabel(item.due_date)}</p><b>{money(item.remaining_amount)}</b>
          </button>)}
          {!candidateLoading&&visibleCandidates.length===0&&<div className="finance-reconcile-empty"><strong>Nenhum título compatível.</strong><span>A conciliação respeita entrada/saída e também impede misturar conta operacional com recursos de terceiros.</span></div>}
        </div>
      </div>
    </div>}
  </section>
}
