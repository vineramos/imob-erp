import {
  CalendarDays,
  CheckCircle2,
  ListChecks,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
  TrendingUp,
  WalletCards,
  XCircle,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import { FinanceCashFlowPanel } from './FinanceCashFlowPanel'
import './finance-treasury.css'

type Scope = 'operating'|'third_party'
type TreasuryArea = 'cashflow'|'payments'
type BankAccount = {id:string;code:string;name:string;bank_name:string;fund_scope:Scope;current_balance:number;is_active:boolean;provider:string}
type PaymentCandidate = {target_type:'owner_repasse'|'maintenance'|'manual';target_id:string;target_code:string;description:string;counterparty_name:string;due_date:string|null;fund_scope:Scope;remaining_amount:number;overdue:boolean}
type PaymentBatchItem = {id:string;target_type:string;target_id:string;target_code:string;description:string;counterparty_name:string;due_date:string|null;fund_scope:Scope;amount:number;status:string;bank_transaction_id:string|null}
type PaymentBatch = {id:string;code:string;bank_account_id:string;bank_account_name:string;name:string;scheduled_date:string;fund_scope:Scope;payment_method:string;status:string;total_amount:number;item_count:number;notes:string|null;provider_batch_id:string|null;provider_status:string|null;execution_reference:string|null;prepared_at:string|null;approved_at:string|null;executed_at:string|null;cancelled_at:string|null;created_at:string;items:PaymentBatchItem[]}

const batchStatus:Record<string,string> = {draft:'Rascunho',ready:'Preparado',approved:'Aprovado',executed:'Executado',cancelled:'Cancelado'}
const sourceLabels:Record<string,string> = {owner_repasse:'Repasse',maintenance:'Manutenção',manual:'Manual'}
const paymentMethodLabels:Record<string,string> = {pix:'Pix',transfer:'Transferência',boleto:'Boleto',other:'Outro'}
function money(value:number|null|undefined){return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function dateLabel(value:string|null|undefined){if(!value)return '—';return new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString('pt-BR')}
function todayInput(){const now=new Date();const offset=now.getTimezoneOffset();return new Date(now.getTime()-offset*60000).toISOString().slice(0,10)}
function candidateKey(item:Pick<PaymentCandidate,'target_type'|'target_id'>){return `${item.target_type}:${item.target_id}`}

export function FinanceTreasuryPanel({permissions}:{permissions:string[]}){
  const canPrepare=permissions.includes('finance.payment.prepare')
  const canApprove=permissions.includes('finance.payment.approve')
  const [area,setArea]=useState<TreasuryArea>('cashflow')
  const [accounts,setAccounts]=useState<BankAccount[]>([])
  const [accountId,setAccountId]=useState('')
  const [scheduledDate,setScheduledDate]=useState(todayInput())
  const [batchName,setBatchName]=useState('Pagamentos programados')
  const [paymentMethod,setPaymentMethod]=useState('pix')
  const [notes,setNotes]=useState('')
  const [candidates,setCandidates]=useState<PaymentCandidate[]>([])
  const [selected,setSelected]=useState<Set<string>>(new Set())
  const [batches,setBatches]=useState<PaymentBatch[]>([])
  const [executeTarget,setExecuteTarget]=useState<PaymentBatch|null>(null)
  const [executionDate,setExecutionDate]=useState(todayInput())
  const [executionReference,setExecutionReference]=useState('')
  const [loading,setLoading]=useState(false)
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')

  const selectedAccount=accounts.find(item=>item.id===accountId)||null
  const selectedCandidates=useMemo(()=>candidates.filter(item=>selected.has(candidateKey(item))),[candidates,selected])
  const selectedAmount=useMemo(()=>selectedCandidates.reduce((sum,item)=>sum+Number(item.remaining_amount||0),0),[selectedCandidates])

  const loadAccounts=useCallback(async()=>{try{const result=await apiRequest<BankAccount[]>('/finance/banking/accounts');setAccounts(result.filter(item=>item.is_active));setAccountId(current=>{if(current&&result.some(item=>item.id===current&&item.is_active))return current;return result.find(item=>item.is_active)?.id||''})}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar as contas bancárias.')}},[])
  const loadPaymentData=useCallback(async()=>{if(!accountId){setCandidates([]);setBatches([]);return}setLoading(true);setError('');try{const [candidateResult,batchResult]=await Promise.all([apiRequest<PaymentCandidate[]>(`/finance/treasury/payment-candidates?account_id=${accountId}&until=${scheduledDate}`),apiRequest<PaymentBatch[]>(`/finance/treasury/payment-batches?account_id=${accountId}`)]);setCandidates(candidateResult);setBatches(batchResult);setSelected(current=>new Set([...current].filter(key=>candidateResult.some(item=>candidateKey(item)===key))))}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os lotes de pagamento.')}finally{setLoading(false)}},[accountId,scheduledDate])
  useEffect(()=>{void loadAccounts()},[loadAccounts])
  useEffect(()=>{if(area==='payments')void loadPaymentData()},[area,loadPaymentData])
  useEffect(()=>{if(area==='cashflow'){setError('');setSuccess('')}},[area])

  function toggleCandidate(item:PaymentCandidate){const key=candidateKey(item);setSelected(current=>{const next=new Set(current);if(next.has(key))next.delete(key);else next.add(key);return next})}
  function selectAll(){setSelected(current=>current.size===candidates.length?new Set():new Set(candidates.map(candidateKey)))}

  async function createBatch(event:FormEvent){event.preventDefault();if(!accountId||selectedCandidates.length===0)return;setSaving(true);setError('');setSuccess('');try{const result=await apiRequest<PaymentBatch>('/finance/treasury/payment-batches',{method:'POST',body:JSON.stringify({name:batchName,bank_account_id:accountId,scheduled_date:scheduledDate,payment_method:paymentMethod,notes:notes||null,items:selectedCandidates.map(item=>({target_type:item.target_type,target_id:item.target_id}))})});setSelected(new Set());setNotes('');setSuccess(`${result.code} criado com ${result.item_count} pagamento(s).`);await loadPaymentData()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível criar o lote de pagamentos.')}finally{setSaving(false)}}
  async function actionBatch(batch:PaymentBatch,action:'prepare'|'approve'|'cancel'){setSaving(true);setError('');setSuccess('');try{const result=await apiRequest<PaymentBatch>(`/finance/treasury/payment-batches/${batch.id}/${action}`,{method:'POST'});const verbs={prepare:'preparado',approve:'aprovado',cancel:'cancelado'};setSuccess(`${result.code} ${verbs[action]} com sucesso.`);await loadPaymentData()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível atualizar o lote.')}finally{setSaving(false)}}
  async function executeBatch(event:FormEvent){event.preventDefault();if(!executeTarget)return;setSaving(true);setError('');setSuccess('');try{const result=await apiRequest<PaymentBatch>(`/finance/treasury/payment-batches/${executeTarget.id}/execute`,{method:'POST',body:JSON.stringify({execution_date:executionDate,reference:executionReference||null})});setExecuteTarget(null);setExecutionReference('');setSuccess(`${result.code} executado e conciliado com o extrato bancário.`);await loadPaymentData()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível registrar a execução do lote.')}finally{setSaving(false)}}
  const statusClass=(status:string)=>status==='executed'||status==='approved'?'success':status==='cancelled'?'neutral':status==='ready'?'warning':'neutral'

  return <section className="workspace treasury-workspace">
    <div className="page-heading finance-heading treasury-heading"><div><span className="eyebrow">Financeiro · Tesouraria</span><h1>Tesouraria</h1><p>Fluxo financeiro diário e programação de pagamentos com separação rígida entre recursos próprios e valores de terceiros.</p></div>{area==='payments'&&<button className="button secondary" type="button" onClick={()=>void loadPaymentData()} disabled={loading}><RefreshCw size={14}/> Atualizar</button>}</div>
    <div className="panel treasury-tabs"><button type="button" className={area==='cashflow'?'active':''} onClick={()=>setArea('cashflow')}><TrendingUp size={15}/> Fluxo financeiro</button><button type="button" className={area==='payments'?'active':''} onClick={()=>setArea('payments')}><ListChecks size={15}/> Lotes de pagamentos</button></div>

    {area==='cashflow'?<FinanceCashFlowPanel/>:<>
      {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}
      <div className="treasury-payment-layout">
        <form className="panel treasury-batch-builder" onSubmit={createBatch}>
          <div className="treasury-section-title"><div><span className="eyebrow">Programação</span><h2>Novo lote</h2></div><CalendarDays size={20}/></div>
          {accounts.length===0?<div className="finance-empty compact"><WalletCards size={24}/><strong>Nenhuma conta bancária ativa.</strong><span>Cadastre a conta na área Bancos antes de programar pagamentos.</span></div>:<>
            <label><span>Conta de pagamento</span><select value={accountId} onChange={event=>{setAccountId(event.target.value);setSelected(new Set())}}>{accounts.map(account=><option key={account.id} value={account.id}>{account.code} · {account.name} · {account.fund_scope==='third_party'?'Terceiros':'Operacional'}</option>)}</select></label>
            {selectedAccount&&<div className="treasury-account-hint"><ShieldCheck size={14}/><span>Este lote aceitará apenas títulos <strong>{selectedAccount.fund_scope==='third_party'?'de terceiros':'operacionais'}</strong>.</span></div>}
            <label><span>Nome do lote</span><input value={batchName} onChange={event=>setBatchName(event.target.value)} maxLength={160} required/></label>
            <div className="form-grid two-columns"><label><span>Data programada</span><input type="date" min={todayInput()} value={scheduledDate} onChange={event=>setScheduledDate(event.target.value)} required/></label><label><span>Forma de pagamento</span><select value={paymentMethod} onChange={event=>setPaymentMethod(event.target.value)}><option value="pix">Pix</option><option value="transfer">Transferência</option><option value="boleto">Boleto</option><option value="other">Outro</option></select></label></div>
            <label><span>Observações</span><textarea value={notes} onChange={event=>setNotes(event.target.value)} rows={3} maxLength={2000}/></label><div className="treasury-selection-total"><span>{selectedCandidates.length} título(s) selecionado(s)</span><strong>{money(selectedAmount)}</strong></div><button className="button primary" type="submit" disabled={saving||!canPrepare||selectedCandidates.length===0}><ListChecks size={14}/> Criar lote</button>{!canPrepare&&<small className="treasury-permission-note">Seu perfil não possui permissão para preparar pagamentos.</small>}
          </>}
        </form>
        <div className="panel treasury-candidates"><div className="treasury-table-heading"><div><strong>Obrigações disponíveis</strong><span>Somente títulos ainda não vinculados a outro lote aberto e compatíveis com a conta escolhida.</span></div>{candidates.length>0&&<button type="button" className="button secondary compact" onClick={selectAll}>{selected.size===candidates.length?'Limpar':'Selecionar todos'}</button>}</div>{loading?<div className="settings-loading">Carregando obrigações...</div>:candidates.length===0?<div className="finance-empty compact"><CheckCircle2 size={25}/><strong>Nenhuma obrigação disponível.</strong><span>Não há títulos elegíveis até {dateLabel(scheduledDate)} para esta conta.</span></div>:<div className="treasury-candidate-list">{candidates.map(item=><label className={`treasury-candidate ${selected.has(candidateKey(item))?'selected':''}`} key={candidateKey(item)}><input type="checkbox" checked={selected.has(candidateKey(item))} onChange={()=>toggleCandidate(item)}/><div><div className="treasury-code-line"><strong>{item.target_code}</strong><span>{sourceLabels[item.target_type]||item.target_type}</span>{item.overdue&&<i className="status-badge danger">Vencido</i>}</div><h3>{item.description}</h3><p>{item.counterparty_name} · venc. {dateLabel(item.due_date)}</p></div><strong>{money(item.remaining_amount)}</strong></label>)}</div>}</div>
      </div>
      <div className="treasury-batches-heading"><div><span className="eyebrow">Controle</span><h2>Lotes de pagamento</h2><p>O lote é preparado, aprovado e só então tem a execução registrada. Até a integração bancária ao vivo, registrar a execução cria e concilia os débitos reais no extrato.</p></div></div>
      <div className="treasury-batch-list">{batches.map(batch=><article className={`panel treasury-batch ${batch.status}`} key={batch.id}><div className="treasury-batch-top"><div><div className="treasury-code-line"><strong>{batch.code}</strong><i className={`status-badge ${statusClass(batch.status)}`}>{batchStatus[batch.status]||batch.status}</i></div><h3>{batch.name}</h3><p>{batch.bank_account_name} · {batch.fund_scope==='third_party'?'Recursos de terceiros':'Operacional'} · {paymentMethodLabels[batch.payment_method]||batch.payment_method}</p></div><div className="treasury-batch-value"><span>Programado para {dateLabel(batch.scheduled_date)}</span><strong>{money(batch.total_amount)}</strong><small>{batch.item_count} pagamento(s)</small></div></div><div className="treasury-batch-items">{batch.items.map(item=><div key={item.id}><span>{item.target_code}</span><strong>{item.counterparty_name}</strong><span>{money(item.amount)}</span></div>)}</div><div className="treasury-batch-actions">{batch.status==='draft'&&canPrepare&&<button className="button primary compact" type="button" disabled={saving} onClick={()=>void actionBatch(batch,'prepare')}><CheckCircle2 size={13}/> Preparar</button>}{batch.status==='ready'&&canApprove&&<button className="button primary compact" type="button" disabled={saving} onClick={()=>void actionBatch(batch,'approve')}><ShieldCheck size={13}/> Aprovar</button>}{batch.status==='approved'&&canApprove&&<button className="button primary compact" type="button" disabled={saving} onClick={()=>{setExecuteTarget(batch);setExecutionDate(todayInput());setExecutionReference('')}}><PlayCircle size={13}/> Registrar execução</button>}{['draft','ready'].includes(batch.status)&&canPrepare&&<button className="button secondary compact" type="button" disabled={saving} onClick={()=>void actionBatch(batch,'cancel')}><XCircle size={13}/> Cancelar</button>}{batch.status==='approved'&&canApprove&&<button className="button secondary compact" type="button" disabled={saving} onClick={()=>void actionBatch(batch,'cancel')}><XCircle size={13}/> Cancelar</button>}{batch.status==='executed'&&<span className="treasury-executed-note"><CheckCircle2 size={13}/> Executado em {dateLabel(batch.executed_at)} · ref. {batch.execution_reference||'—'}</span>}</div></article>)}{!loading&&batches.length===0&&<article className="panel finance-empty"><ListChecks size={28}/><strong>Nenhum lote criado para esta conta.</strong><span>Selecione as obrigações acima para montar a primeira programação.</span></article>}</div>
    </>}

    {executeTarget&&<div className="finance-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target)setExecuteTarget(null)}}><form className="panel finance-modal treasury-execute-modal" onSubmit={executeBatch}><div className="finance-modal-header"><div><span className="eyebrow">Execução do pagamento</span><h2>{executeTarget.code}</h2><p>Registre apenas após confirmar que os pagamentos realmente saíram da conta. O sistema criará os débitos e fará a conciliação automática dos títulos.</p></div><button type="button" onClick={()=>setExecuteTarget(null)}><XCircle size={17}/></button></div><div className="treasury-execute-summary"><span>{executeTarget.item_count} pagamento(s)</span><strong>{money(executeTarget.total_amount)}</strong></div><div className="form-grid two-columns"><label><span>Data da execução</span><input type="date" max={todayInput()} value={executionDate} onChange={event=>setExecutionDate(event.target.value)} required/></label><label><span>Referência bancária</span><input value={executionReference} onChange={event=>setExecutionReference(event.target.value)} maxLength={180} placeholder="Opcional"/></label></div><div className="finance-modal-actions"><button className="button secondary" type="button" onClick={()=>setExecuteTarget(null)}>Voltar</button><button className="button primary" type="submit" disabled={saving}><PlayCircle size={14}/> Confirmar execução</button></div></form></div>}
  </section>
}
