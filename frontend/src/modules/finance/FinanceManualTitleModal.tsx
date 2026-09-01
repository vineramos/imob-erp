import { FileSearch, FileUp, Plus, UserPlus, X } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { Person } from '../../api/types'
import './finance-manual-title.css'

type Direction='receivable'|'payable'
type Scope='operating'|'third_party'
type Lease={id:string;code:string;property_code:string;tenants:Array<{name?:string}>;owners:Array<{name?:string}>;status:string}
type Parsed={filename:string;extracted:{due_date:string|null;amount:number|null;boleto_line:string|null;document_number:string|null;counterparty_name:string|null};warnings:string[]}
type Created={id:string;code:string}

type Props={direction:Direction;onClose:()=>void;onCreated:(message:string)=>void}

const payableCategories=['Colaboradores','Aluguel da sede','Energia elétrica','Água','Internet / telefonia','Insumos','Impostos e taxas','Serviços de terceiros','Comissões','Angariações','Reembolsos','Outras despesas']
const receivableCategories=['Serviços','Reembolso','Cobrança adicional','Honorários / taxas','Manutenção','Outras receitas']
function today(){const now=new Date();const offset=now.getTimezoneOffset();return new Date(now.getTime()-offset*60000).toISOString().slice(0,10)}
function currentMonth(){return today().slice(0,7)}
function parseMoney(value:string){const parsed=Number(value.trim().replace(/\./g,'').replace(',','.'));return Number.isFinite(parsed)?parsed:0}
function formatInput(value:number){return Number(value||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}
function digits(value:string|null|undefined){return String(value||'').replace(/\D/g,'')}

export function FinanceManualTitleModal({direction,onClose,onCreated}:Props){
  const categories=direction==='payable'?payableCategories:receivableCategories
  const [scope,setScope]=useState<Scope>('operating')
  const [category,setCategory]=useState(categories[0])
  const [description,setDescription]=useState('')
  const [people,setPeople]=useState<Person[]>([])
  const [personId,setPersonId]=useState('')
  const [counterparty,setCounterparty]=useState('')
  const [leases,setLeases]=useState<Lease[]>([])
  const [leaseId,setLeaseId]=useState('')
  const [competence,setCompetence]=useState(currentMonth())
  const [dueDate,setDueDate]=useState(today())
  const [amount,setAmount]=useState('0,00')
  const [notes,setNotes]=useState('')
  const [boletoLine,setBoletoLine]=useState('')
  const [file,setFile]=useState<File|null>(null)
  const [parsing,setParsing]=useState(false)
  const [parseWarnings,setParseWarnings]=useState<string[]>([])
  const [quickOpen,setQuickOpen]=useState(false)
  const [quickName,setQuickName]=useState('')
  const [quickDocument,setQuickDocument]=useState('')
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')

  useEffect(()=>{
    void apiRequest<Person[]>('/people').then(setPeople).catch(()=>setPeople([]))
    void apiRequest<Lease[]>('/lease-contracts').then(setLeases).catch(()=>setLeases([]))
  },[])

  const selectedPerson=useMemo(()=>people.find(item=>item.id===personId)||null,[people,personId])
  useEffect(()=>{if(selectedPerson)setCounterparty(selectedPerson.name)},[selectedPerson])

  async function parseDocument(next:File|null){
    setFile(next);setParseWarnings([])
    if(!next)return
    setParsing(true);setError('')
    try{
      const data=new FormData();data.append('file',next)
      const result=await apiRequest<Parsed>('/finance/treasury/manual-titles/parse-document',{method:'POST',body:data})
      setParseWarnings(result.warnings||[])
      if(result.extracted.due_date)setDueDate(result.extracted.due_date)
      if(result.extracted.amount!=null)setAmount(formatInput(result.extracted.amount))
      if(result.extracted.boleto_line)setBoletoLine(result.extracted.boleto_line)
      const document=result.extracted.document_number
      const byDocument=document?people.find(person=>digits(person.document_number)===digits(document)):null
      const byName=result.extracted.counterparty_name?people.find(person=>person.name.toLowerCase().includes(result.extracted.counterparty_name!.toLowerCase())||result.extracted.counterparty_name!.toLowerCase().includes(person.name.toLowerCase())):null
      const found=byDocument||byName
      if(found){setPersonId(found.id);setCounterparty(found.name)}else if(result.extracted.counterparty_name)setCounterparty(result.extracted.counterparty_name)
      if(!description) setDescription(direction==='payable'?'Pagamento de boleto / documento':'Cobrança vinculada a documento')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível ler o documento.')}finally{setParsing(false)}
  }

  async function quickCreate(){
    if(quickName.trim().length<2)return
    setSaving(true);setError('')
    try{
      const created=await apiRequest<Person>('/people',{method:'POST',body:JSON.stringify({person_type:digits(quickDocument).length>11?'company':'individual',name:quickName.trim(),document_number:quickDocument||null,email:null,phone:null,address:{street:'',number:'',complement:'',neighborhood:'',city:'Curitiba',state:'PR',postal_code:''},notes:direction==='payable'?'Criado a partir do contas a pagar.':'Criado a partir do contas a receber.',role_keys:direction==='payable'?['supplier']:[]})})
      setPeople(current=>[created,...current]);setPersonId(created.id);setCounterparty(created.name);setQuickOpen(false);setQuickName('');setQuickDocument('')
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível cadastrar a contraparte.')}finally{setSaving(false)}
  }

  async function submit(event:FormEvent){
    event.preventDefault();if(parseMoney(amount)<=0)return
    setSaving(true);setError('')
    try{
      const created=await apiRequest<Created>('/finance/treasury/manual-titles',{method:'POST',body:JSON.stringify({direction,fund_scope:scope,category,description,counterparty_name:counterparty||null,counterparty_person_id:personId||null,competence:`${competence}-01`,due_date:dueDate,amount:parseMoney(amount),lease_contract_id:leaseId||null,property_id:null,notes:notes||null,boleto_line:boletoLine||null})})
      if(file){const data=new FormData();data.append('file',file);await apiRequest(`/finance/treasury/manual-titles/${created.id}/attachments`,{method:'POST',body:data})}
      onCreated(`${created.code} criado como ${direction==='payable'?'conta a pagar':'conta a receber'}.`)
      onClose()
    }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível criar o lançamento financeiro.')}finally{setSaving(false)}
  }

  return <div className="finance-modal-backdrop" onMouseDown={event=>{if(event.currentTarget===event.target&&!saving)onClose()}}><form className="panel finance-modal finance-manual-title-modal" onSubmit={submit} role="dialog" aria-modal="true"><div className="finance-modal-header"><div><span className="eyebrow">Tesouraria · lançamento manual</span><h2>{direction==='payable'?'Nova conta a pagar':'Nova conta a receber'}</h2><p>Use somente quando o lançamento não nascer automaticamente de locação, manutenção, comissão ou outro módulo do ERP.</p></div><button type="button" aria-label="Fechar" disabled={saving} onClick={onClose}><X size={17}/></button></div>
    {error&&<div className="form-alert danger-alert">{error}</div>}
    <div className="finance-manual-grid">
      <label><span>Natureza do recurso</span><select value={scope} onChange={e=>setScope(e.target.value as Scope)}><option value="operating">Operacional</option><option value="third_party">Recursos de terceiros</option></select></label>
      <label><span>Categoria</span><select value={category} onChange={e=>setCategory(e.target.value)}>{categories.map(item=><option key={item}>{item}</option>)}</select></label>
      <label className="full"><span>Descrição</span><input required value={description} onChange={e=>setDescription(e.target.value)} placeholder={direction==='payable'?'Ex.: Conta de energia elétrica - escritório':'Ex.: Reembolso de despesa'}/></label>
      <label className="full"><span>{direction==='payable'?'Fornecedor / favorecido':'Cliente / pagador'}</span><div className="finance-manual-inline"><select value={personId} onChange={e=>setPersonId(e.target.value)}><option value="">Sem cadastro vinculado</option>{people.filter(item=>item.is_active).map(person=><option key={person.id} value={person.id}>{person.name}{person.document_number?` · ${person.document_number}`:''}</option>)}</select><button className="button secondary compact" type="button" onClick={()=>setQuickOpen(value=>!value)}><UserPlus size={13}/> Novo</button></div></label>
      {!personId&&<label className="full"><span>Nome da contraparte</span><input value={counterparty} onChange={e=>setCounterparty(e.target.value)} placeholder="Nome do fornecedor, colaborador ou cliente"/></label>}
      {quickOpen&&<div className="finance-manual-quick full"><div><strong>Novo {direction==='payable'?'fornecedor / favorecido':'contato financeiro'}</strong><small>O cadastro ficará disponível na base de Pessoas para os próximos lançamentos.</small></div><input value={quickName} onChange={e=>setQuickName(e.target.value)} placeholder="Nome / razão social"/><input value={quickDocument} onChange={e=>setQuickDocument(e.target.value)} placeholder="CPF ou CNPJ"/><button className="button secondary compact" type="button" disabled={saving||quickName.trim().length<2} onClick={()=>void quickCreate()}><Plus size={13}/> Cadastrar</button></div>}
      <label className="full"><span>Contrato de locação (opcional)</span><select value={leaseId} onChange={e=>setLeaseId(e.target.value)}><option value="">Sem contrato vinculado</option>{leases.map(lease=><option key={lease.id} value={lease.id}>{lease.code} · imóvel {lease.property_code} · {(lease.tenants||[]).map(item=>item.name).filter(Boolean).join(' / ')||'sem locatário'}</option>)}</select></label>
      <label><span>Competência</span><input type="month" required value={competence} onChange={e=>setCompetence(e.target.value)}/></label><label><span>Vencimento</span><input type="date" required value={dueDate} onChange={e=>setDueDate(e.target.value)}/></label>
      <label><span>Valor</span><input inputMode="decimal" data-format="money" required value={amount} onChange={e=>setAmount(e.target.value)} placeholder="0,00"/></label><label><span>Linha digitável / referência</span><input value={boletoLine} onChange={e=>setBoletoLine(e.target.value)} placeholder="Opcional"/></label>
      <label className="full"><span>Documento / boleto</span><div className="finance-manual-file"><FileUp size={18}/><input type="file" accept=".pdf,.txt,.csv,image/*,application/pdf" onChange={e=>void parseDocument(e.target.files?.[0]||null)}/><div><strong>{file?file.name:'Anexar documento'}</strong><small>{parsing?'Lendo dados do arquivo...':'PDF com texto: tenta preencher valor, vencimento, linha digitável e beneficiário.'}</small></div><FileSearch size={16}/></div>{parseWarnings.map(warning=><small className="finance-manual-warning" key={warning}>{warning}</small>)}</label>
      <label className="full"><span>Observações</span><textarea rows={3} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Informações adicionais do lançamento"/></label>
    </div>
    {scope==='third_party'&&<div className="finance-manual-scope-warning">Este lançamento ficará segregado do caixa operacional e aparecerá somente em <strong>Recursos de terceiros</strong>.</div>}
    <div className="form-actions"><button className="button secondary" type="button" disabled={saving} onClick={onClose}>Cancelar</button><button className="button primary" disabled={saving||parsing||parseMoney(amount)<=0}>{saving?'Salvando...':direction==='payable'?'Criar conta a pagar':'Criar conta a receber'}</button></div>
  </form></div>
}
