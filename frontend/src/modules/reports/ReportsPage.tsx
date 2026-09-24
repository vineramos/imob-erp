import { CheckCircle2, FileText, RefreshCw, ShieldCheck, TriangleAlert, UsersRound } from 'lucide-react'
import { useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import './reports.css'

type DimobIssue = { severity: 'error' | 'warning'; code: string; scope: string; reference: string | null; message: string }
type Dimob = { year: number; status: 'no_operations' | 'attention_required' | 'ready_for_review'; operation_count: number; lease_count: number; owner_count: number; tenant_count: number; error_count: number; warning_count: number; official_layout_export_available: boolean; issues: DimobIssue[]; note: string }
const currentYear = new Date().getFullYear()

function YearField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <label className="reports-admin-year"><span>Ano-calendário</span><select value={value} onChange={event=>onChange(event.target.value)}>
    {Array.from({length:6},(_,index)=>String(currentYear-index)).map(year=><option value={year} key={year}>{year}</option>)}
  </select></label>
}

export function ReportsPage() {
  const [dimobYear,setDimobYear]=useState(String(currentYear-1))
  const [dimob,setDimob]=useState<Dimob|null>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')

  async function validateDimob(){
    setLoading(true);setError('')
    try{setDimob(await apiRequest<Dimob>(`/reports/dimob/validation?year=${dimobYear}`))}
    catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível validar a base da DIMOB.')}
    finally{setLoading(false)}
  }

  return <section className="workspace reports-workspace reports-admin-workspace">
    <div className="page-heading reports-heading"><div><span className="eyebrow">Relatórios</span><h1>Relatórios operacionais</h1><p>Conferências internas e preparação de obrigações da imobiliária.</p></div></div>
    {error&&<div className="form-alert danger-alert">{error}</div>}

    <div className="reports-admin-grid">
      <article className="panel reports-admin-primary">
        <div className="reports-card-head"><div><span className="eyebrow">DIMOB</span><h2>Pré-validação da base</h2><p>Confere pagamentos e cadastros antes da revisão no programa oficial.</p></div><ShieldCheck size={21}/></div>
        <div className="reports-admin-controls"><YearField value={dimobYear} onChange={value=>{setDimobYear(value);setDimob(null)}}/><button className="button primary" type="button" disabled={loading} onClick={()=>void validateDimob()}>{loading?<RefreshCw className="spin" size={14}/>:<ShieldCheck size={14}/>} Validar base</button></div>
        {dimob&&<div className="reports-admin-result">
          <div className={`reports-status ${dimob.status}`}>{dimob.status==='ready_for_review'?<CheckCircle2 size={18}/>:<TriangleAlert size={18}/>}<div><strong>{dimob.status==='ready_for_review'?'Base pronta para revisão':dimob.status==='no_operations'?'Sem operações no ano':'Há pendências para corrigir'}</strong><span>{dimob.error_count} erro(s) · {dimob.warning_count} aviso(s)</span></div></div>
          <div className="reports-dimob-metrics"><div><span>Pagamentos</span><strong>{dimob.operation_count}</strong></div><div><span>Contratos</span><strong>{dimob.lease_count}</strong></div><div><span>Proprietários</span><strong>{dimob.owner_count}</strong></div><div><span>Locatários</span><strong>{dimob.tenant_count}</strong></div></div>
          <div className="reports-issues">{dimob.issues.length===0?<div className="reports-ok"><CheckCircle2 size={16}/> Nenhuma inconsistência encontrada nessa pré-validação.</div>:dimob.issues.map((issue,index)=><div className={`reports-issue ${issue.severity}`} key={`${issue.code}-${issue.reference||index}`}><TriangleAlert size={15}/><div><strong>{issue.reference||'Cadastro'}</strong><span>{issue.message}</span></div></div>)}</div>
          <div className="reports-official-note"><FileText size={16}/><div><strong>Arquivo oficial ainda não liberado</strong><span>{dimob.note}</span></div></div>
        </div>}
      </article>

      <aside className="panel reports-self-service-card">
        <div className="reports-card-head"><div><span className="eyebrow">Autosserviço</span><h2>Documentos anuais nos portais</h2><p>Os informes deixam de ocupar a rotina administrativa e ficam disponíveis diretamente aos clientes.</p></div><UsersRound size={21}/></div>
        <div className="reports-self-service-list">
          <div><FileText size={16}/><span><strong>Proprietário</strong><small>Documentos → Informe anual de rendimentos → PDF por ano-calendário.</small></span></div>
          <div><FileText size={16}/><span><strong>Locatário</strong><small>Documentos → Comprovante anual de pagamentos → PDF por ano-calendário.</small></span></div>
        </div>
        <p className="reports-self-service-note">A geração utiliza os mesmos dados financeiros do ERP. O backend administrativo permanece disponível para conferência excepcional, mas não fica mais em destaque nesta tela.</p>
      </aside>
    </div>
  </section>
}
