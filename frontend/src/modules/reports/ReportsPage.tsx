import { CheckCircle2, Download, FileSpreadsheet, FileText, RefreshCw, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiBlobRequest, apiRequest } from '../../api/client'
import './reports.css'

type Person = { id: string; name: string; document_number: string | null }
type AnnualLine = { competence: string; payment_date: string | null; property_code: string; charge_code: string; rent_amount: number; additional_charges: number; total_amount: number; administration_fee: number; owner_net_amount: number }
type Annual = { year: number; party_type: 'owner' | 'tenant'; person_id: string; person_name: string; allocation_method: string; total_rent: number; total_additional_charges: number; total_paid: number; total_administration_fee: number; total_owner_net: number; lines: AnnualLine[] }
type DimobIssue = { severity: 'error' | 'warning'; code: string; scope: string; reference: string | null; message: string }
type Dimob = { year: number; status: 'no_operations' | 'attention_required' | 'ready_for_review'; operation_count: number; lease_count: number; owner_count: number; tenant_count: number; error_count: number; warning_count: number; official_layout_export_available: boolean; issues: DimobIssue[]; note: string }

const currentYear = new Date().getFullYear()
const money = (value: number) => Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const monthLabel = (value: string) => value.slice(0, 7).split('-').reverse().join('/')

function openBlob(blob: Blob) {
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function ReportsPage({ permissions }: { permissions: string[] }) {
  const canExport = permissions.includes('reports.export')
  const [party, setParty] = useState<'tenant' | 'owner'>('owner')
  const [people, setPeople] = useState<Person[]>([])
  const [personId, setPersonId] = useState('')
  const [annualYear, setAnnualYear] = useState(String(currentYear))
  const [dimobYear, setDimobYear] = useState(String(currentYear - 1))
  const [annual, setAnnual] = useState<Annual | null>(null)
  const [dimob, setDimob] = useState<Dimob | null>(null)
  const [loadingAnnual, setLoadingAnnual] = useState(false)
  const [loadingDimob, setLoadingDimob] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    void (async () => {
      try {
        const rows = await apiRequest<Person[]>(`/people?role=${party}`)
        setPeople(rows)
        setPersonId(current => rows.some(row => row.id === current) ? current : (rows[0]?.id || ''))
        setAnnual(null)
      } catch (cause) {
        setPeople([])
        setPersonId('')
        setAnnual(null)
        setError(cause instanceof ApiError ? cause.detail : 'Não foi possível carregar as pessoas do relatório.')
      }
    })()
  }, [party])

  const selectedPerson = useMemo(() => people.find(row => row.id === personId) || null, [people, personId])

  async function generateAnnual() {
    if (!personId) return
    setLoadingAnnual(true)
    setError('')
    try {
      setAnnual(await apiRequest<Annual>(`/reports/annual-income?year=${annualYear}&party_type=${party}&person_id=${personId}`))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível gerar o informe anual.')
    } finally {
      setLoadingAnnual(false)
    }
  }

  async function exportAnnual(kind: 'pdf' | 'csv') {
    if (!personId || !canExport) return
    setError('')
    try {
      const blob = await apiBlobRequest(`/reports/annual-income.${kind}?year=${annualYear}&party_type=${party}&person_id=${personId}`)
      if (kind === 'pdf') openBlob(blob)
      else downloadBlob(blob, `informe-${party}-${annualYear}.csv`)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível exportar o relatório.')
    }
  }

  async function validateDimob() {
    setLoadingDimob(true)
    setError('')
    try {
      setDimob(await apiRequest<Dimob>(`/reports/dimob/validation?year=${dimobYear}`))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : 'Não foi possível validar a base da DIMOB.')
    } finally {
      setLoadingDimob(false)
    }
  }

  return <section className="workspace reports-workspace reports-workspace-refined">
    <div className="page-heading reports-heading">
      <div>
        <span className="eyebrow">Relatórios</span>
        <h1>Relatórios operacionais</h1>
        <p>Informes anuais e preparação de obrigações imobiliárias usando os mesmos dados da operação, sem cadastros paralelos.</p>
      </div>
    </div>

    {error && <div className="form-alert danger-alert">{error}</div>}

    <div className="reports-grid reports-grid-refined">
      <article className="panel reports-card reports-annual-card reports-card-primary reports-launcher-card">
        <div className="reports-card-head">
          <div><span className="eyebrow">Informe anual</span><h2>Proprietário e locatário</h2><p>Consolida pagamentos por ano a partir das cobranças liquidadas.</p></div>
          <FileText size={22}/>
        </div>
        <div className="reports-form-grid reports-toolbar">
          <label><span>Parte</span><select value={party} onChange={event => setParty(event.target.value as 'tenant' | 'owner')}><option value="owner">Proprietário</option><option value="tenant">Locatário</option></select></label>
          <label><span>Pessoa</span><select value={personId} onChange={event => { setPersonId(event.target.value); setAnnual(null) }}><option value="">Selecione...</option>{people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
          <label><span>Ano</span><input type="number" min="2000" max="2200" value={annualYear} onChange={event => { setAnnualYear(event.target.value); setAnnual(null) }}/></label>
          <button className="button primary reports-generate" type="button" disabled={!personId || loadingAnnual} onClick={() => void generateAnnual()}>{loadingAnnual ? <RefreshCw className="spin" size={14}/> : <FileText size={14}/>} Gerar</button>
        </div>
        {selectedPerson && <div className="reports-person-line"><strong>{selectedPerson.name}</strong><span>{selectedPerson.document_number || 'Documento não informado'}</span></div>}

      </article>

      <article className="panel reports-card reports-card-secondary reports-launcher-card">
        <div className="reports-card-head">
          <div><span className="eyebrow">DIMOB</span><h2>Pré-validação da base</h2><p>Confere os dados mínimos da operação antes da etapa de geração do arquivo oficial.</p></div>
          <ShieldCheck size={22}/>
        </div>
        <div className="reports-dimob-controls reports-toolbar reports-toolbar-dimob"><label><span>Ano-calendário</span><input type="number" min="2000" max="2200" value={dimobYear} onChange={event => { setDimobYear(event.target.value); setDimob(null) }}/></label><button className="button primary" type="button" disabled={loadingDimob} onClick={() => void validateDimob()}>{loadingDimob ? <RefreshCw className="spin" size={14}/> : <ShieldCheck size={14}/>} Validar base</button></div>

      </article>
    </div>

    {annual && <article className="panel reports-result-card reports-annual-result">
          <div className="reports-result-head"><div><span className="eyebrow">Resultado do informe</span><h2>{selectedPerson?.name || 'Informe anual'} · {annualYear}</h2><p>Consolidação dos pagamentos liquidados no período selecionado.</p></div><FileText size={19}/></div>
          <div className="reports-metrics">
            <div><span>Aluguel</span><strong>{money(annual.total_rent)}</strong></div>
            <div><span>Encargos</span><strong>{money(annual.total_additional_charges)}</strong></div>
            <div><span>Total no ano</span><strong>{money(annual.total_paid)}</strong></div>
            {party === 'owner' && <div><span>Administração</span><strong>{money(annual.total_administration_fee)}</strong></div>}
            {party === 'owner' && <div><span>Líquido proprietário</span><strong>{money(annual.total_owner_net)}</strong></div>}
          </div>
          <div className="reports-allocation">Critério: {annual.allocation_method}.</div>
          <div className="reports-table-wrap"><table className="reports-table"><thead><tr><th>Competência</th><th>Imóvel</th><th>Cobrança</th><th>Pagamento</th><th className="number">Total</th></tr></thead><tbody>{annual.lines.length === 0 ? <tr><td colSpan={5} className="reports-empty">Nenhum pagamento encontrado nesse ano.</td></tr> : annual.lines.map((line, index) => <tr key={`${line.charge_code}-${index}`}><td>{monthLabel(line.competence)}</td><td>{line.property_code}</td><td>{line.charge_code}</td><td>{line.payment_date ? new Date(`${line.payment_date}T12:00:00`).toLocaleDateString('pt-BR') : '—'}</td><td className="number">{money(line.total_amount)}</td></tr>)}</tbody></table></div>
          {canExport ? <div className="reports-actions"><button className="button secondary compact" type="button" onClick={() => void exportAnnual('pdf')}><Download size={13}/> PDF</button><button className="button secondary compact" type="button" onClick={() => void exportAnnual('csv')}><FileSpreadsheet size={13}/> CSV</button></div> : <div className="reports-permission-note">Seu perfil permite consultar, mas não exportar relatórios.</div>}
      </article>}

    {dimob && <article className="panel reports-result-card reports-dimob-result">
          <div className="reports-result-head"><div><span className="eyebrow">Resultado DIMOB</span><h2>Pré-validação · {dimob.year}</h2><p>Diagnóstico da base antes da revisão e geração do arquivo oficial.</p></div><ShieldCheck size={19}/></div>
          <div className={`reports-status ${dimob.status}`}>
            {dimob.status === 'ready_for_review' ? <CheckCircle2 size={18}/> : <TriangleAlert size={18}/>}<div><strong>{dimob.status === 'ready_for_review' ? 'Base pronta para revisão' : dimob.status === 'no_operations' ? 'Sem operações no ano' : 'Há pendências para corrigir'}</strong><span>{dimob.error_count} erro(s) · {dimob.warning_count} aviso(s)</span></div>
          </div>
          <div className="reports-dimob-metrics"><div><span>Pagamentos</span><strong>{dimob.operation_count}</strong></div><div><span>Contratos</span><strong>{dimob.lease_count}</strong></div><div><span>Proprietários</span><strong>{dimob.owner_count}</strong></div><div><span>Locatários</span><strong>{dimob.tenant_count}</strong></div></div>
          <div className="reports-issues">{dimob.issues.length === 0 ? <div className="reports-ok"><CheckCircle2 size={16}/> Nenhuma inconsistência encontrada nessa pré-validação.</div> : dimob.issues.map((issue, index) => <div className={`reports-issue ${issue.severity}`} key={`${issue.code}-${issue.reference || index}`}><TriangleAlert size={15}/><div><strong>{issue.reference || 'Cadastro'}</strong><span>{issue.message}</span></div></div>)}</div>
          <div className="reports-official-note"><FileSpreadsheet size={16}/><div><strong>Arquivo oficial ainda não liberado</strong><span>{dimob.note}</span></div></div>
      </article>}
  </section>
}
