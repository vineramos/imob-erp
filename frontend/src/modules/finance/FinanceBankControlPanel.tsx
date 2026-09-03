import { BadgeCheck, Building2, CircleAlert, CloudCog, LockKeyhole, RefreshCw, Send, ShieldCheck, WalletCards } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './finance-bank-control.css'

type Scope = 'operating'|'third_party'
type Area = 'closing'|'automation'
type BankAccount = {id:string;code:string;name:string;bank_name:string;fund_scope:Scope;current_balance:number;is_active:boolean;provider:string}
type ProviderCapability = {bank_account_id:string;bank_account_name:string;provider:string;configured:boolean;statement:boolean;balance:boolean;billing:boolean;pix_payment:boolean}
type DailyClosePreview = {bank_account_id:string;bank_account_name:string;closing_date:string;fund_scope:Scope;provider:string;erp_balance:number;bank_balance:number;difference:number;pending_transactions_count:number;balance_source:'manual'|'provider';can_close:boolean;message:string}
type DailyClose = DailyClosePreview & {id:string;code:string;status:string;notes:string|null;closed_at:string}
type PaymentBatch = {id:string;code:string;bank_account_id:string;bank_account_name:string;scheduled_date:string;fund_scope:Scope;payment_method:string;status:string;total_amount:number;item_count:number;provider_status:string|null}
type ProviderInstruction = {id:string;payment_batch_item_id:string;target_code:string;recipient_name:string;amount:number;provider:string;provider_reference:string|null;provider_status:string;last_error:string|null;submitted_at:string|null;confirmed_at:string|null}
type ProviderBatch = {payment_batch_id:string;batch_code:string;batch_status:string;provider:string;provider_status:string|null;instructions:ProviderInstruction[]}

function money(value:number|null|undefined){return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function dateLabel(value:string|null|undefined){if(!value)return '—';return new Date(`${value.slice(0,10)}T12:00:00`).toLocaleDateString('pt-BR')}
function todayInput(){const now=new Date();const offset=now.getTimezoneOffset();return new Date(now.getTime()-offset*60000).toISOString().slice(0,10)}
function parseMoney(value:string){const normalized=value.replace(/\./g,'').replace(',','.').replace(/[^0-9.-]/g,'');return normalized?Number(normalized):null}

export function FinanceBankControlPanel({permissions}:{permissions:string[]}){
  const canReconcile=permissions.includes('finance.reconcile')
  const canApprove=permissions.includes('finance.payment.approve')
  const [area,setArea]=useState<Area>('closing')
  const [accounts,setAccounts]=useState<BankAccount[]>([])
  const [capabilities,setCapabilities]=useState<ProviderCapability[]>([])
  const [accountId,setAccountId]=useState('')
  const [closingDate,setClosingDate]=useState(todayInput())
  const [bankBalance,setBankBalance]=useState('')
  const [notes,setNotes]=useState('')
  const [preview,setPreview]=useState<DailyClosePreview|null>(null)
  const [closes,setCloses]=useState<DailyClose[]>([])
  const [batches,setBatches]=useState<PaymentBatch[]>([])
  const [providerDetails,setProviderDetails]=useState<Record<string,ProviderBatch>>({})
  const [loading,setLoading]=useState(false)
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')

  const selectedAccount=accounts.find(item=>item.id===accountId)||null
  const capability=capabilities.find(item=>item.bank_account_id===accountId)||null
  const automatedBatches=useMemo(()=>batches.filter(item=>['approved','submitted'].includes(item.status)),[batches])

  const loadBase=useCallback(async()=>{setLoading(true);setError('');try{const [accountResult,capabilityResult]=await Promise.all([apiRequest<BankAccount[]>('/finance/banking/accounts'),apiRequest<ProviderCapability[]>('/finance/bank-control/providers')]);const active=accountResult.filter(item=>item.is_active);setAccounts(active);setCapabilities(capabilityResult);setAccountId(current=>current&&active.some(item=>item.id===current)?current:(active[0]?.id||''))}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o controle bancário.')}finally{setLoading(false)}},[])
  const loadCloses=useCallback(async()=>{if(!accountId){setCloses([]);return}try{setCloses(await apiRequest<DailyClose[]>(`/finance/bank-control/daily-closes?account_id=${accountId}`))}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os fechamentos.')}},[accountId])
  const loadBatches=useCallback(async()=>{if(!accountId){setBatches([]);return}try{setBatches(await apiRequest<PaymentBatch[]>(`/finance/treasury/payment-batches?account_id=${accountId}`))}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os lotes aprovados.')}},[accountId])

  useEffect(()=>{void loadBase()},[loadBase])
  useEffect(()=>{setPreview(null);setBankBalance('');setProviderDetails({});if(area==='closing')void loadCloses();else void loadBatches()},[accountId,area,loadCloses,loadBatches])

  async function previewClose(event:FormEvent){event.preventDefault();if(!accountId)return;setSaving(true);setError('');setSuccess('');try{const informed=parseMoney(bankBalance);const result=await apiRequest<DailyClosePreview>('/finance/bank-control/daily-closes/preview',{method:'POST',body:JSON.stringify({bank_account_id:accountId,closing_date:closingDate,bank_balance:informed})});setPreview(result)}catch(cause){setPreview(null);setError(cause instanceof ApiError?cause.detail:'Não foi possível conferir o fechamento.')}finally{setSaving(false)}}
  async function closeDay(){if(!preview?.can_close)return;setSaving(true);setError('');setSuccess('');try{const informed=parseMoney(bankBalance);const result=await apiRequest<DailyClose>('/finance/bank-control/daily-closes',{method:'POST',body:JSON.stringify({bank_account_id:accountId,closing_date:closingDate,bank_balance:informed,notes:notes||null})});setPreview(null);setNotes('');setBankBalance('');setSuccess(`${result.code} confirmado: banco e ERP conciliados em ${dateLabel(result.closing_date)}.`);await loadCloses()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível fechar o dia.')}finally{setSaving(false)}}
  async function submitBatch(batch:PaymentBatch){setSaving(true);setError('');setSuccess('');try{const result=await apiRequest<ProviderBatch>(`/finance/bank-control/payment-batches/${batch.id}/submit`,{method:'POST'});setProviderDetails(current=>({...current,[batch.id]:result}));setSuccess(`${batch.code} enviado ao provider ${result.provider}. A liquidação contábil só ocorrerá pela conciliação do extrato.`);await loadBatches()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível enviar o lote ao banco.')}finally{setSaving(false)}}
  async function syncBatch(batch:PaymentBatch){setSaving(true);setError('');setSuccess('');try{const result=await apiRequest<ProviderBatch>(`/finance/bank-control/payment-batches/${batch.id}/sync`,{method:'POST'});setProviderDetails(current=>({...current,[batch.id]:result}));setSuccess(`${batch.code} sincronizado com o provider.`);await loadBatches()}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível consultar os pagamentos no provider.')}finally{setSaving(false)}}

  return <section className="workspace bank-control-workspace">
    <div className="page-heading finance-heading"><div><span className="eyebrow">Financeiro · Controle bancário</span><h1>Banco × ERP</h1><p>Fechamento diário e automações bancárias sem amarrar o financeiro a uma instituição específica.</p></div><button className="button secondary" type="button" disabled={loading} onClick={()=>void loadBase()}><RefreshCw size={14}/> Atualizar</button></div>
    <div className="panel bank-control-tabs"><button type="button" className={area==='closing'?'active':''} onClick={()=>setArea('closing')}><LockKeyhole size={15}/> Fechamento diário</button><button type="button" className={area==='automation'?'active':''} onClick={()=>setArea('automation')}><CloudCog size={15}/> Automação bancária</button></div>
    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}

    {accounts.length===0?<article className="panel finance-empty"><WalletCards size={28}/><strong>Nenhuma conta bancária ativa.</strong><span>Cadastre a conta em Bancos. O ERP aceita qualquer instituição, mesmo sem API.</span></article>:area==='closing'?<>
      <div className="bank-control-layout">
        <form className="panel bank-close-form" onSubmit={previewClose}>
          <div className="bank-control-title"><div><span className="eyebrow">Conferência</span><h2>Fechar o dia</h2></div><BadgeCheck size={22}/></div>
          <label><span>Conta</span><select value={accountId} onChange={event=>setAccountId(event.target.value)}>{accounts.map(account=><option key={account.id} value={account.id}>{account.code} · {account.name} · {account.fund_scope==='third_party'?'Terceiros':'Operacional'}</option>)}</select></label>
          <div className="form-grid two-columns"><label><span>Data</span><input type="date" max={todayInput()} value={closingDate} onChange={event=>{setClosingDate(event.target.value);setPreview(null)}} required/></label><label><span>Saldo informado pelo banco</span><input inputMode="decimal" value={bankBalance} onChange={event=>{setBankBalance(event.target.value);setPreview(null)}} placeholder={capability?.configured&&capability.balance?'Opcional · consultar pela API':'Ex.: 12.450,90'}/></label></div>
          <div className="bank-provider-hint"><Building2 size={15}/><div><strong>{selectedAccount?.bank_name||selectedAccount?.name}</strong><span>{capability?.configured&&capability.balance?`Provider ${capability.provider} pode consultar o saldo automaticamente.`:'Sem consulta automática: informe o saldo mostrado no banco. O fechamento continua funcionando normalmente.'}</span></div></div>
          <label><span>Observações do fechamento</span><textarea rows={3} maxLength={2000} value={notes} onChange={event=>setNotes(event.target.value)}/></label>
          <button className="button primary" type="submit" disabled={saving||!canReconcile}><ShieldCheck size={14}/> Conferir Banco × ERP</button>
          {!canReconcile&&<small>Seu perfil não possui permissão de conciliação.</small>}
        </form>
        <div className="panel bank-close-result">
          <div className="bank-control-title"><div><span className="eyebrow">Resultado</span><h2>Conciliação</h2></div>{preview?.can_close?<BadgeCheck size={22}/>:<CircleAlert size={22}/>}</div>
          {!preview?<div className="finance-empty compact"><ShieldCheck size={26}/><strong>Aguardando conferência.</strong><span>O fechamento só é liberado com todos os movimentos conciliados e diferença de saldo zerada.</span></div>:<><div className="bank-close-metrics"><div><span>Saldo ERP</span><strong>{money(preview.erp_balance)}</strong></div><div><span>Saldo banco</span><strong>{money(preview.bank_balance)}</strong><small>{preview.balance_source==='provider'?'consultado via provider':'informado manualmente'}</small></div><div className={Math.abs(preview.difference)>.01?'danger':'success'}><span>Diferença</span><strong>{money(preview.difference)}</strong></div><div className={preview.pending_transactions_count?'danger':'success'}><span>Pendências</span><strong>{preview.pending_transactions_count}</strong></div></div><div className={`bank-close-message ${preview.can_close?'success':'warning'}`}>{preview.message}</div><button type="button" className="button primary" disabled={saving||!preview.can_close||!canReconcile} onClick={()=>void closeDay()}><LockKeyhole size={14}/> Confirmar fechamento</button></>}
        </div>
      </div>
      <article className="panel bank-close-history"><div className="bank-control-title"><div><span className="eyebrow">Histórico imutável</span><h2>Fechamentos confirmados</h2></div></div>{closes.length===0?<div className="finance-empty compact"><LockKeyhole size={24}/><strong>Nenhum fechamento desta conta.</strong><span>O primeiro registro aparecerá aqui após Banco × ERP ficar zerado.</span></div>:<div className="bank-close-list">{closes.map(item=><div key={item.id}><div><strong>{item.code}</strong><span>{dateLabel(item.closing_date)} · {item.balance_source==='provider'?'API':'saldo informado'}</span></div><div><span>Saldo confirmado</span><strong>{money(item.bank_balance)}</strong></div><i className="status-badge success">Fechado</i></div>)}</div>}</article>
    </>:<>
      <article className="panel bank-automation-intro"><div><CloudCog size={22}/><div><span className="eyebrow">Provider opcional</span><h2>Automação sem dependência do banco</h2><p>Conta manual funciona com qualquer instituição via OFX/CSV e conciliação. Quando existir um provider compatível, o ERP apenas adiciona automações como Pix e consulta de saldo.</p></div></div></article>
      <div className="panel bank-automation-account"><label><span>Conta</span><select value={accountId} onChange={event=>setAccountId(event.target.value)}>{accounts.map(account=><option key={account.id} value={account.id}>{account.code} · {account.name}</option>)}</select></label><div className="bank-capabilities"><span className={capability?.configured?'ok':''}>Provider: <strong>{capability?.provider||'manual'}</strong></span><span className={capability?.statement?'ok':''}>Extrato</span><span className={capability?.balance?'ok':''}>Saldo</span><span className={capability?.pix_payment?'ok':''}>Pix</span></div></div>
      {!capability?.configured||!capability.pix_payment?<article className="panel finance-empty"><WalletCards size={27}/><strong>Execução bancária manual disponível.</strong><span>Esta conta não possui API Pix configurada. Continue usando Tesouraria → Registrar execução e importe/concilie o extrato normalmente.</span></article>:<div className="bank-provider-batches">{automatedBatches.length===0?<article className="panel finance-empty"><BadgeCheck size={26}/><strong>Nenhum lote aprovado para automação.</strong><span>Prepare e aprove os pagamentos na Tesouraria; eles aparecerão aqui para envio ao provider.</span></article>:automatedBatches.map(batch=>{const detail=providerDetails[batch.id];return <article className="panel bank-provider-batch" key={batch.id}><div className="bank-provider-batch-head"><div><strong>{batch.code}</strong><h3>{batch.bank_account_name}</h3><span>{batch.item_count} pagamento(s) · {dateLabel(batch.scheduled_date)}</span></div><div><strong>{money(batch.total_amount)}</strong><i className={`status-badge ${batch.status==='submitted'?'warning':'success'}`}>{batch.status==='submitted'?'Enviado ao provider':'Aprovado'}</i></div></div><div className="bank-provider-actions">{batch.status==='approved'&&<button className="button primary compact" type="button" disabled={saving||!canApprove} onClick={()=>void submitBatch(batch)}><Send size={13}/> Enviar Pix ao banco</button>}{batch.status==='submitted'&&<button className="button secondary compact" type="button" disabled={saving||!canApprove} onClick={()=>void syncBatch(batch)}><RefreshCw size={13}/> Consultar status</button>}<span>A baixa financeira continua dependendo da conciliação do extrato.</span></div>{detail&&<div className="bank-provider-instructions">{detail.instructions.map(item=><div key={item.id}><span>{item.target_code} · {item.recipient_name}</span><strong>{money(item.amount)}</strong><i>{item.provider_status}</i>{item.last_error&&<small>{item.last_error}</small>}</div>)}</div>}</article>})}</div>}
    </>}
  </section>
}
