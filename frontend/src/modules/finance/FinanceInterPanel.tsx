import { CalendarRange, CheckCircle2, Landmark, RefreshCw, ShieldCheck, TriangleAlert, WalletCards } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './finance-inter.css'

type InterStatus = {
  configured:boolean
  environment:string
  client_id_configured:boolean
  certificate_configured:boolean
  account_header_configured:boolean
  billing_api:string
  banking_api:string
}

type BankAccount = {
  id:string
  code:string
  name:string
  bank_name:string
  bank_code:string|null
  account_number:string|null
  fund_scope:'operating'|'third_party'
  provider:string
  current_balance:number
  is_active:boolean
  last_sync_at:string|null
}

type SyncResult = {
  account_id:string
  start_date:string
  end_date:string
  created:number
  duplicates:number
  external_balance:number|null
  synced_at:string
}

function localIsoDate(value:Date){
  const offset=value.getTimezoneOffset()
  return new Date(value.getTime()-offset*60000).toISOString().slice(0,10)
}
function defaultStart(){const now=new Date();return localIsoDate(new Date(now.getFullYear(),now.getMonth(),1))}
function today(){return localIsoDate(new Date())}
function money(value:number|null|undefined){return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function dateTime(value:string|null|undefined){return value?new Date(value).toLocaleString('pt-BR'):'Nunca sincronizado'}

export function FinanceInterPanel({permissions}:{permissions:string[]}){
  const canSync=permissions.includes('finance.reconcile')
  const [status,setStatus]=useState<InterStatus|null>(null)
  const [accounts,setAccounts]=useState<BankAccount[]>([])
  const [accountId,setAccountId]=useState('')
  const [startDate,setStartDate]=useState(defaultStart())
  const [endDate,setEndDate]=useState(today())
  const [lastResult,setLastResult]=useState<SyncResult|null>(null)
  const [loading,setLoading]=useState(true)
  const [syncing,setSyncing]=useState(false)
  const [error,setError]=useState('')
  const [success,setSuccess]=useState('')

  const interAccounts=useMemo(()=>accounts.filter(item=>item.provider==='inter'&&item.is_active),[accounts])
  const selected=interAccounts.find(item=>item.id===accountId)||null

  const load=useCallback(async()=>{
    setLoading(true);setError('')
    try{
      const [providerStatus,bankAccounts]=await Promise.all([
        apiRequest<InterStatus>('/finance/advanced/inter/status'),
        apiRequest<BankAccount[]>('/finance/banking/accounts'),
      ])
      setStatus(providerStatus)
      setAccounts(bankAccounts)
      const valid=bankAccounts.filter(item=>item.provider==='inter'&&item.is_active)
      setAccountId(current=>current&&valid.some(item=>item.id===current)?current:(valid[0]?.id||''))
    }catch(cause){
      setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar o status do Banco Inter.')
    }finally{setLoading(false)}
  },[])

  useEffect(()=>{void load()},[load])

  async function sync(event:FormEvent){
    event.preventDefault()
    if(!selected)return
    if(startDate>endDate){setError('A data inicial deve ser anterior à data final.');return}
    const span=(new Date(`${endDate}T12:00:00`).getTime()-new Date(`${startDate}T12:00:00`).getTime())/86400000
    if(span>90){setError('O período de sincronização do Inter deve ter no máximo 90 dias.');return}
    setSyncing(true);setError('');setSuccess('')
    try{
      const result=await apiRequest<SyncResult>(`/finance/advanced/inter/accounts/${selected.id}/sync?start_date=${startDate}&end_date=${endDate}`,{method:'POST'})
      setLastResult(result)
      setSuccess(`${result.created} movimento(s) novo(s) importado(s); ${result.duplicates} duplicado(s) ignorado(s).`)
      await load()
    }catch(cause){
      setError(cause instanceof ApiError?cause.detail:'Não foi possível sincronizar o extrato do Banco Inter.')
    }finally{setSyncing(false)}
  }

  const configured=status?.configured===true
  const checks=[
    {label:'Client ID',ok:status?.client_id_configured===true},
    {label:'Certificado mTLS',ok:status?.certificate_configured===true},
    {label:'Conta corrente',ok:status?.account_header_configured===true},
  ]

  return <section className="workspace finance-inter-workspace">
    <div className="page-heading finance-heading">
      <div><span className="eyebrow">Financeiro · Banco Inter</span><h1>Integração Banco Inter</h1><p>Diagnóstico seguro da conexão, saldo de referência e sincronização do extrato para a conciliação bancária.</p></div>
      <button className="button secondary" type="button" onClick={()=>void load()} disabled={loading||syncing}><RefreshCw size={14}/> Atualizar status</button>
    </div>

    {error&&<div className="form-alert danger-alert">{error}</div>}
    {success&&<div className="form-alert success-alert">{success}</div>}

    <div className="finance-inter-status-grid">
      <article className={`panel finance-inter-status ${configured?'ok':'warning'}`}><span>Integração</span><strong>{configured?'Configurada':'Aguardando configuração'}</strong><small>{configured?'Credenciais mínimas disponíveis no ambiente.':'Nenhum segredo é armazenado no ERP.'}</small></article>
      <article className="panel finance-inter-status"><span>Ambiente</span><strong>{status?.environment||'—'}</strong><small>Ambiente informado pelo provider.</small></article>
      <article className={`panel finance-inter-status ${status?.certificate_configured?'ok':'warning'}`}><span>Segurança</span><strong>{status?.certificate_configured?'mTLS pronto':'Certificado pendente'}</strong><small>Certificado e chave permanecem fora do banco do ERP.</small></article>
      <article className={`panel finance-inter-status ${status?.account_header_configured?'ok':'warning'}`}><span>Conta API</span><strong>{status?.account_header_configured?'Identificada':'Identificador pendente'}</strong><small>Usado apenas na comunicação autenticada com o Inter.</small></article>
    </div>

    {!configured&&!loading&&<article className="panel finance-inter-warning"><TriangleAlert size={22}/><div><strong>O conector está pronto, mas o ambiente ainda não possui todos os segredos necessários.</strong><span>Client ID, Client Secret, certificado/chave mTLS e identificação da conta devem ser provisionados no ambiente seguro do Cloud Run. A tela mostra somente o estado da configuração, nunca os valores.</span></div></article>}

    <div className="finance-inter-layout">
      <form className="panel finance-inter-sync" onSubmit={sync}>
        <div className="finance-inter-section-title"><div><span className="eyebrow">Extrato</span><h2>Sincronizar movimentações</h2></div><Landmark size={20}/></div>
        {interAccounts.length===0?<div className="finance-empty compact"><WalletCards size={26}/><strong>Nenhuma conta do Banco Inter cadastrada.</strong><span>Cadastre a conta em Bancos e selecione o provider Banco Inter para habilitar a sincronização.</span></div>:<>
          <label><span>Conta bancária</span><select value={accountId} onChange={event=>setAccountId(event.target.value)}>{interAccounts.map(item=><option key={item.id} value={item.id}>{item.code} · {item.name} · {item.fund_scope==='third_party'?'Terceiros':'Operacional'}</option>)}</select></label>
          {selected&&<div className="finance-inter-account"><div><strong>{selected.bank_name}</strong><span>{selected.name}</span></div><div><span>Saldo no ERP</span><strong>{money(selected.current_balance)}</strong></div><div><span>Última sincronização</span><strong>{dateTime(selected.last_sync_at)}</strong></div></div>}
          <div className="form-grid two-columns"><label><span>Data inicial</span><input type="date" value={startDate} max={endDate} onChange={event=>setStartDate(event.target.value)} required/></label><label><span>Data final</span><input type="date" value={endDate} min={startDate} max={today()} onChange={event=>setEndDate(event.target.value)} required/></label></div>
          <div className="finance-inter-hint"><CalendarRange size={14}/><span>O Inter é consultado em janelas de até <strong>90 dias</strong>. Movimentos já existentes são identificados e ignorados.</span></div>
          <button className="button primary" type="submit" disabled={!configured||!canSync||syncing||!selected}><RefreshCw size={14}/>{syncing?' Sincronizando...':' Sincronizar extrato'}</button>
          {!canSync&&<small>Seu perfil não possui permissão para sincronizar/conciliar extratos.</small>}
        </>}
      </form>

      <article className="panel finance-inter-diagnostics">
        <div className="finance-inter-section-title"><div><span className="eyebrow">Diagnóstico</span><h2>Condições da integração</h2></div><ShieldCheck size={20}/></div>
        <div className="finance-inter-checks">{checks.map(item=><div key={item.label} className={item.ok?'ok':'pending'}>{item.ok?<CheckCircle2 size={17}/>:<TriangleAlert size={17}/>}<div><strong>{item.label}</strong><span>{item.ok?'Configurado no ambiente':'Pendente de configuração'}</span></div></div>)}</div>
        <div className="finance-inter-api-note"><strong>APIs habilitadas no provider</strong><span>Cobrança: {status?.billing_api||'—'}</span><span>Banking: {status?.banking_api||'—'}</span></div>
        {lastResult&&<div className="finance-inter-last-result"><strong>Última sincronização desta sessão</strong><span>{lastResult.created} novo(s) · {lastResult.duplicates} duplicado(s)</span><span>Saldo informado pelo Inter: {lastResult.external_balance==null?'não retornado':money(lastResult.external_balance)}</span><span>{dateTime(lastResult.synced_at)}</span></div>}
      </article>
    </div>
  </section>
}
