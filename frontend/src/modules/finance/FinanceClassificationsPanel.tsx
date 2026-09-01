import { ArrowDownCircle, ArrowUpCircle, LockKeyhole, RefreshCw, Save, Tags } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './finance-classifications.css'

type Rule={key:string;label:string;direction:'receivable'|'payable';fund_scope:'operating'|'third_party';category:string;scope_locked:boolean}
type Response={rules:Rule[]}

export function FinanceClassificationsPanel({permissions}:{permissions:string[]}){
  const canEdit=permissions.includes('finance.payment.prepare')
  const [rules,setRules]=useState<Rule[]>([])
  const [loading,setLoading]=useState(true),[saving,setSaving]=useState(false)
  const [error,setError]=useState(''),[success,setSuccess]=useState('')
  const load=useCallback(async()=>{setLoading(true);setError('');try{setRules((await apiRequest<Response>('/finance/advanced/classifications')).rules)}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar as classificações financeiras.')}finally{setLoading(false)}},[])
  useEffect(()=>{void load()},[load])
  const incoming=useMemo(()=>rules.filter(item=>item.direction==='receivable'),[rules])
  const outgoing=useMemo(()=>rules.filter(item=>item.direction==='payable'),[rules])
  function update(key:string,category:string){setRules(current=>current.map(item=>item.key===key?{...item,category}:item))}
  async function save(){setSaving(true);setError('');setSuccess('');try{const result=await apiRequest<Response>('/finance/advanced/classifications',{method:'PUT',body:JSON.stringify({rules:rules.map(({key,category})=>({key,category}))})});setRules(result.rules);setSuccess('Classificações gerenciais atualizadas.')}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar as classificações.')}finally{setSaving(false)}}
  function group(title:string,items:Rule[],direction:'receivable'|'payable'){return <section className="panel finance-classification-group"><div className="finance-classification-heading"><div className={`finance-classification-icon ${direction}`}>{direction==='receivable'?<ArrowDownCircle size={18}/>:<ArrowUpCircle size={18}/>}</div><div><h2>{title}</h2><p>Defina como os lançamentos automáticos aparecem no fluxo gerencial.</p></div></div><div className="finance-classification-list">{items.map(item=><div className="finance-classification-row" key={item.key}><div><strong>{item.label}</strong><span>{item.fund_scope==='operating'?'Caixa operacional':'Recursos de terceiros'} <LockKeyhole size={11}/></span></div><label><span>Classificação gerencial</span><input value={item.category} disabled={!canEdit} onChange={event=>update(item.key,event.target.value)} /></label></div>)}</div></section>}
  return <section className="workspace finance-classifications-workspace"><div className="page-heading"><div><span className="eyebrow">Financeiro · Cadastros</span><h1>Classificações financeiras</h1><p>Organize entradas e saídas automáticas sem alterar a origem contábil nem misturar recursos próprios com valores de terceiros.</p></div><div className="page-heading-actions"><button className="button secondary" type="button" onClick={()=>void load()} disabled={loading}><RefreshCw size={14}/> Atualizar</button>{canEdit&&<button className="button primary" type="button" onClick={()=>void save()} disabled={saving||loading}><Save size={14}/> {saving?'Salvando...':'Salvar classificações'}</button>}</div></div>{error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}{loading?<article className="panel settings-loading">Carregando classificações...</article>:<><div className="finance-classification-note"><Tags size={16}/><div><strong>O que é configurável?</strong><span>Você escolhe o nome/classificação gerencial. A natureza do recurso permanece protegida pelo ERP; por exemplo, repasses continuam sendo recursos de terceiros.</span></div></div><div className="finance-classifications-grid">{group('Entradas automáticas',incoming,'receivable')}{group('Saídas automáticas',outgoing,'payable')}</div></>}</section>
}
