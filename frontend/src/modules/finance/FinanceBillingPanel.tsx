import { AlertTriangle, Banknote, CheckCircle2, ChevronLeft, ChevronRight, FileClock, RefreshCw, Send, ShieldAlert } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import { shiftMonth } from './finance-period'
import './finance-advanced.css'

type BillingItem={id:string;charge_id:string;charge_code:string;lease_code:string;property_code:string;tenant_name:string;due_date:string;amount:number;charge_status:string;provider:string;provider_charge_id:string|null;provider_status:string|null;boleto_line:string|null;pix_copy_paste:string|null;issued_at:string|null;sent_at:string|null;confirmed_at:string|null;last_error:string|null}
type Batch={id:string;code:string;competence:string;status:string;provider:string;generated_count:number;issued_count:number;sent_count:number;confirmed_count:number;error_count:number;started_at:string;completed_at:string|null;items:BillingItem[]}
type Case={id:string;code:string;charge_code:string;lease_code:string;property_code:string;tenant_name:string;due_date:string;amount:number;days_overdue:number;critical:boolean;status:string;insurer_protocol:string|null;next_action_at:string|null;notes:string|null}
type Account={id:string;name:string;bank_name:string;fund_scope:string;provider:string;is_active:boolean}
type InterStatus={configured:boolean;environment:string;client_id_configured:boolean;certificate_configured:boolean;account_header_configured:boolean}

const money=(v:number)=>Number(v||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
const dateLabel=(v:string)=>new Date(`${v.slice(0,10)}T12:00:00`).toLocaleDateString('pt-BR')
const currentMonth=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`}

export function FinanceBillingPanel({permissions}:{permissions:string[]}){
  const canCharge=permissions.includes('finance.charge.create')
  const canReconcile=permissions.includes('finance.reconcile')
  const canApprove=permissions.includes('finance.payment.approve')
  const [month,setMonth]=useState(currentMonth())
  const [batches,setBatches]=useState<Batch[]>([])
  const [cases,setCases]=useState<Case[]>([])
  const [accounts,setAccounts]=useState<Account[]>([])
  const [inter,setInter]=useState<InterStatus|null>(null)
  const [loading,setLoading]=useState(true);const [saving,setSaving]=useState(false);const [error,setError]=useState('');const [success,setSuccess]=useState('')
  const competence=`${month}-01`
  const batch=batches[0]||null
  const interAccount=useMemo(()=>accounts.find(a=>a.is_active&&a.provider==='inter'&&a.fund_scope==='third_party')||null,[accounts])

  const load=useCallback(async()=>{
    setLoading(true);setError('')
    try{
      const [bs,cs,as,is]=await Promise.all([
        apiRequest<Batch[]>(`/finance/advanced/billing/batches?competence=${competence}`),
        apiRequest<Case[]>('/finance/advanced/delinquency'),
        apiRequest<Account[]>('/finance/banking/accounts'),
        apiRequest<InterStatus>('/finance/advanced/inter/status'),
      ])
      setBatches(bs);setCases(cs);setAccounts(as);setInter(is)
    }catch(e){setError(e instanceof ApiError?e.detail:'Não foi possível carregar cobranças e inadimplência.')}
    finally{setLoading(false)}
  },[competence])
  useEffect(()=>{void load()},[load])

  async function run(){setSaving(true);setError('');setSuccess('');try{const r=await apiRequest<{generated:number;batch:Batch}>('/finance/advanced/billing/run',{method:'POST',body:JSON.stringify({competence})});setSuccess(`${r.generated} cobrança(s) nova(s) gerada(s).`);await load()}catch(e){setError(e instanceof ApiError?e.detail:'Falha ao gerar cobranças.')}finally{setSaving(false)}}
  async function batchAction(action:'mark-sent'|'sync-inter'|'issue-inter'){
    if(!batch)return;setSaving(true);setError('');setSuccess('')
    try{
      const init:RequestInit={method:'POST'}
      if(action==='issue-inter'){if(!interAccount)throw new Error('Cadastre uma conta Banco Inter de recursos de terceiros.');init.body=JSON.stringify({bank_account_id:interAccount.id})}
      await apiRequest(`/finance/advanced/billing/batches/${batch.id}/${action}`,init);setSuccess(action==='mark-sent'?'Pendências marcadas como enviadas.':action==='issue-inter'?'Cobranças encaminhadas ao Banco Inter.':'Situações do Banco Inter atualizadas.');await load()
    }catch(e){setError(e instanceof ApiError?e.detail:e instanceof Error?e.message:'Falha na operação do lote.')}finally{setSaving(false)}
  }
  async function caseAction(item:Case,status:'contacted'|'insurer_triggered'|'negotiating'|'resolved'){
    let protocol:string|null=null;if(status==='insurer_triggered')protocol=window.prompt('Protocolo da seguradora (opcional):')||null
    setSaving(true);setError('');try{await apiRequest(`/finance/advanced/delinquency/${item.id}/action`,{method:'POST',body:JSON.stringify({status,insurer_protocol:protocol,notes:null,next_action_at:null})});await load()}catch(e){setError(e instanceof ApiError?e.detail:'Não foi possível atualizar a inadimplência.')}finally{setSaving(false)}
  }

  const openCases=cases.filter(c=>c.status!=='resolved');const critical=openCases.filter(c=>c.critical)
  return <section className="workspace finance-advanced-workspace">
    <div className="page-heading finance-heading"><div><span className="eyebrow">Financeiro · Cobranças</span><h1>Cobrança mensal e inadimplência</h1><p>Geração em lote, boleto/Pix, envio, confirmação e tratamento de atraso no mesmo ciclo.</p></div><div className="heading-actions"><button className="icon-button" type="button" onClick={()=>setMonth(current=>shiftMonth(current,-1))} aria-label="Competência anterior" title="Competência anterior"><ChevronLeft size={16}/></button><input className="finance-compact-input" type="month" value={month} onChange={e=>setMonth(e.target.value)}/><button className="icon-button" type="button" onClick={()=>setMonth(current=>shiftMonth(current,1))} aria-label="Próxima competência" title="Próxima competência"><ChevronRight size={16}/></button><button className="button secondary" onClick={()=>void load()} disabled={loading}><RefreshCw size={14}/> Atualizar</button>{canCharge&&<button className="button primary" onClick={()=>void run()} disabled={saving}><Banknote size={14}/> Gerar mês</button>}</div></div>
    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}
    <div className="finance-advanced-metrics"><article className="panel"><span>Cobranças do lote</span><strong>{batch?.generated_count||0}</strong><small>{month.split('-').reverse().join('/')}</small></article><article className="panel"><span>Remessa/emitidas</span><strong>{batch?.issued_count||0}</strong><small>{batch?.provider==='inter'?'Banco Inter':'Aguardando emissão'}</small></article><article className="panel"><span>Enviadas</span><strong>{batch?.sent_count||0}</strong><small>Reenvio preserva concluídas</small></article><article className="panel"><span>Confirmadas</span><strong>{batch?.confirmed_count||0}</strong><small>Confirmação do provedor</small></article><article className={`panel ${critical.length?'metric-danger':''}`}><span>Inadimplentes críticos</span><strong>{critical.length}</strong><small>{openCases.length} caso(s) aberto(s)</small></article></div>
    <div className="finance-advanced-grid two">
      <article className="panel finance-advanced-card"><div className="finance-advanced-card-head"><div><span className="eyebrow">Faturamento</span><h2>{batch?.code||'Lote ainda não criado'}</h2></div><FileClock size={20}/></div>
        {!batch?<div className="finance-empty compact"><Banknote size={24}/><strong>Gere as cobranças desta competência.</strong><span>Contratos assinados e arquivados entram automaticamente, sem duplicidade.</span></div>:<><div className="finance-inline-actions">{canCharge&&inter?.configured&&interAccount&&<button className="button secondary compact" onClick={()=>void batchAction('issue-inter')} disabled={saving}><Banknote size={13}/> Emitir Boleto + Pix</button>}{canReconcile&&batch.provider==='inter'&&<button className="button secondary compact" onClick={()=>void batchAction('sync-inter')} disabled={saving}><RefreshCw size={13}/> Sincronizar Inter</button>}{canCharge&&<button className="button primary compact" onClick={()=>void batchAction('mark-sent')} disabled={saving}><Send size={13}/> Marcar pendentes enviadas</button>}</div>{!inter?.configured&&<div className="finance-provider-note"><ShieldAlert size={14}/><span>Banco Inter preparado, mas credenciais/certificado ainda não estão configurados no ambiente. O lote continua operando manualmente.</span></div>}<div className="finance-compact-list">{batch.items.map(i=><div className="finance-compact-row" key={i.id}><div><strong>{i.charge_code} · {i.tenant_name}</strong><span>{i.property_code} · venc. {dateLabel(i.due_date)}</span>{i.last_error&&<small className="negative">{i.last_error}</small>}</div><div><strong>{money(i.amount)}</strong><span>{i.confirmed_at?'Confirmada':i.sent_at?'Enviada':i.issued_at?'Remessa':'Gerada'}</span></div></div>)}</div></>}
      </article>
      <article className="panel finance-advanced-card"><div className="finance-advanced-card-head"><div><span className="eyebrow">Inadimplência</span><h2>Casos em acompanhamento</h2></div><AlertTriangle size={20}/></div>{loading?<div className="settings-loading">Carregando...</div>:openCases.length===0?<div className="finance-empty compact"><CheckCircle2 size={24}/><strong>Nenhuma inadimplência aberta.</strong><span>Casos são abertos automaticamente após o vencimento.</span></div>:<div className="finance-compact-list">{openCases.map(c=><div className={`finance-compact-row delinquency ${c.critical?'critical':''}`} key={c.id}><div><strong>{c.code} · {c.tenant_name}</strong><span>{c.charge_code} · {c.property_code} · {c.days_overdue} dia(s) em atraso</span>{c.insurer_protocol&&<small>Seguradora: {c.insurer_protocol}</small>}</div><div><strong>{money(c.amount)}</strong><div className="finance-mini-actions">{canApprove&&<><button onClick={()=>void caseAction(c,'contacted')}>Contato</button>{c.critical&&<button onClick={()=>void caseAction(c,'insurer_triggered')}>Seguradora</button>}<button onClick={()=>void caseAction(c,'resolved')}>Resolver</button></>}</div></div></div>)}</div>}</article>
    </div>
  </section>
}
