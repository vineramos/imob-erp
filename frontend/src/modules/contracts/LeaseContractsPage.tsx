import { CalendarClock, CheckCircle2, FileText, Plus, RotateCcw, Send, ShieldCheck, Users } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiRequest } from '../../api/client'
import type { AdjustmentIndex, OperationalDefaults, Person, Property } from '../../api/types'

type LeaseStatus = 'draft' | 'review' | 'approved' | 'pending_signature' | 'signed' | 'cancelled'
type GuaranteeType = 'insurance' | 'deposit' | 'capitalization' | 'guarantor' | 'none'
type LeaseVersion = { version_number: number; change_summary: string | null; created_at: string }
type Lease = {
  id: string; code: string; property_id: string; property_code: string; property_address: Record<string,string>; owners: Array<{name:string;ownership_percent:string|number}>; tenants: Array<{person_id:string;name:string;document_number:string|null}>;
  status: LeaseStatus; rent_amount: number; due_day: number; adjustment_index: AdjustmentIndex; adjustment_period_months: number; adjustment_base_date: string; next_adjustment_date: string;
  term_months: number; start_date: string; end_date: string; termination_fine_months: number; inspection_contest_days: number; guarantee_type: GuaranteeType; guarantee_details: Record<string,unknown>; notes: string|null; current_version:number; approved_at:string|null; versions:LeaseVersion[];
}
type LeaseForm = {
  property_id: string; tenant_ids: string[]; rent_amount: number|null; due_day:number; adjustment_index:AdjustmentIndex; adjustment_period_months:number; adjustment_base_date:string; next_adjustment_date:string;
  term_months:number; start_date:string; end_date:string; termination_fine_months:number; inspection_contest_days:number; guarantee_type:GuaranteeType; guarantee_details:Record<string,unknown>; notes:string;
}

const indexOptions: AdjustmentIndex[] = ['IPCA','IGP-M','INPC','IPC-FIPE','IGP-DI']
const guaranteeLabels: Record<GuaranteeType,string> = { insurance:'Seguro fiança', deposit:'Caução', capitalization:'Título de capitalização', guarantor:'Fiador (exceção)', none:'Sem garantia (exceção)' }
const statusLabels: Record<LeaseStatus,string> = { draft:'Rascunho', review:'Em revisão', approved:'Aprovado', pending_signature:'Assinatura', signed:'Assinado', cancelled:'Cancelado' }

function isoAddMonths(value: string, months: number) {
  if (!value) return ''
  const [y,m,d] = value.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1 + months, d))
  return date.toISOString().slice(0,10)
}
function addressLine(address: Record<string,string>) { return [address.street,address.number,address.neighborhood,address.city].filter(Boolean).join(', ') || 'Endereço não informado' }
function money(value:number|null) { return value == null ? '—' : Number(value).toLocaleString('pt-BR',{style:'currency',currency:'BRL'}) }
function defaultForm(defaults?:OperationalDefaults):LeaseForm { return { property_id:'',tenant_ids:[],rent_amount:null,due_day:defaults?.rent_due_day??10,adjustment_index:defaults?.adjustment_index??'IPCA',adjustment_period_months:12,adjustment_base_date:'',next_adjustment_date:'',term_months:defaults?.residential_lease_months??30,start_date:'',end_date:'',termination_fine_months:defaults?.termination_fine_months??3,inspection_contest_days:defaults?.inspection_contest_days??5,guarantee_type:'insurance',guarantee_details:{},notes:'' } }

type Props = { permissions:string[] }
export function LeaseContractsPage({permissions}:Props) {
  const granted = useMemo(()=>new Set(permissions),[permissions])
  const canCreate=granted.has('contracts.create'), canEdit=granted.has('contracts.edit'), canApprove=granted.has('contracts.approve')
  const [items,setItems]=useState<Lease[]>([]), [properties,setProperties]=useState<Property[]>([]), [persons,setPersons]=useState<Person[]>([]), [defaults,setDefaults]=useState<OperationalDefaults>()
  const [form,setForm]=useState<LeaseForm>(()=>defaultForm()), [editing,setEditing]=useState<Lease|null>(null), [showForm,setShowForm]=useState(false), [changeSummary,setChangeSummary]=useState('')
  const [loading,setLoading]=useState(true), [saving,setSaving]=useState(false), [error,setError]=useState(''), [success,setSuccess]=useState('')

  const load=useCallback(async()=>{ setLoading(true);setError(''); try { const [contracts,props,people,ops]=await Promise.all([apiRequest<Lease[]>('/lease-contracts'),apiRequest<Property[]>('/properties'),apiRequest<Person[]>('/persons'),apiRequest<OperationalDefaults>('/settings/operations')]); setItems(contracts);setProperties(props);setPersons(people);setDefaults(ops) } catch(cause){ setError(cause instanceof ApiError?cause.detail:'Não foi possível carregar os contratos de locação.') } finally { setLoading(false) } },[])
  useEffect(()=>{void load()},[load])

  const tenantCandidates=useMemo(()=>persons.filter((p)=>p.is_active && (p.role_keys.includes('tenant') || p.role_keys.length===0)),[persons])
  const eligibleProperties=useMemo(()=>properties.filter((p)=>p.owners.length>0 && !items.some((c)=>c.property_id===p.id && c.status!=='cancelled')),[properties,items])

  function openNew(){ setEditing(null);setForm(defaultForm(defaults));setChangeSummary('');setShowForm(true);setError('');setSuccess('') }
  function openEdit(item:Lease){ setEditing(item);setForm({property_id:item.property_id,tenant_ids:item.tenants.map(t=>t.person_id),rent_amount:Number(item.rent_amount),due_day:item.due_day,adjustment_index:item.adjustment_index,adjustment_period_months:item.adjustment_period_months,adjustment_base_date:item.adjustment_base_date,next_adjustment_date:item.next_adjustment_date,term_months:item.term_months,start_date:item.start_date,end_date:item.end_date,termination_fine_months:Number(item.termination_fine_months),inspection_contest_days:item.inspection_contest_days,guarantee_type:item.guarantee_type,guarantee_details:item.guarantee_details,notes:item.notes??''});setChangeSummary('');setShowForm(true) }
  function changeStart(value:string){ setForm((current)=>({...current,start_date:value,adjustment_base_date:value,next_adjustment_date:isoAddMonths(value,current.adjustment_period_months),end_date:isoAddMonths(value,current.term_months)})) }
  function changeTerm(value:number){ setForm((current)=>({...current,term_months:value,end_date:isoAddMonths(current.start_date,value)})) }
  function toggleTenant(id:string){ setForm((current)=>({...current,tenant_ids:current.tenant_ids.includes(id)?current.tenant_ids.filter(x=>x!==id):[...current.tenant_ids,id]})) }

  async function save(event:FormEvent){ event.preventDefault();setSaving(true);setError('');setSuccess(''); try { if(!form.rent_amount||form.tenant_ids.length===0) throw new Error('Informe o aluguel e ao menos um locatário.'); const body=editing?{...form,change_summary:changeSummary}:form; const updated=await apiRequest<Lease>(editing?`/lease-contracts/${editing.id}`:'/lease-contracts',{method:editing?'PUT':'POST',body:JSON.stringify(body)}); setItems((current)=>editing?current.map(i=>i.id===updated.id?updated:i):[updated,...current]);setShowForm(false);setEditing(null);setSuccess(editing?`${updated.code} ganhou a versão ${updated.current_version}.`:`${updated.code} criado como rascunho com ${updated.adjustment_index} congelado no contrato.`) } catch(cause){ setError(cause instanceof ApiError?cause.detail:cause instanceof Error?cause.message:'Não foi possível salvar a locação.') } finally { setSaving(false) } }
  async function workflow(item:Lease,action:'submit_review'|'approve'|'return_draft'|'cancel'){ let reason:string|null=null;if(action==='cancel'){reason=window.prompt('Motivo do cancelamento:');if(!reason?.trim())return} setSaving(true);setError(''); try{const updated=await apiRequest<Lease>(`/lease-contracts/${item.id}/workflow`,{method:'POST',body:JSON.stringify({action,reason})});setItems(c=>c.map(i=>i.id===updated.id?updated:i));setSuccess(`${updated.code}: ${statusLabels[updated.status]}.`)}catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível avançar o contrato.')}finally{setSaving(false)} }

  return <section className="workspace lease-workspace">
    <div className="page-heading portfolio-heading"><div><span className="eyebrow">Contratos · Locação</span><h1>Contratos de locação</h1><p>Índice, data-base, garantia, vencimento e regras ficam próprios do contrato e não mudam retroativamente.</p></div>{canCreate&&<button className="button primary" type="button" onClick={openNew}><Plus size={15}/> Nova locação</button>}</div>
    {error&&<div className="form-alert danger-alert">{error}</div>}{success&&<div className="form-alert success-alert">{success}</div>}
    {showForm&&<form className="panel portfolio-form lease-form" onSubmit={save}><div className="panel-heading panel-heading-row"><div><span className="eyebrow">{editing?`Nova versão · ${editing.code}`:'Nova minuta'}</span><h2>Condições da locação</h2></div><FileText size={20}/></div>
      <div className="form-grid three-columns">
        <label className="field field-span-2"><span>Imóvel</span><select required disabled={Boolean(editing)} value={form.property_id} onChange={e=>{const id=e.target.value;const p=properties.find(x=>x.id===id);setForm(c=>({...c,property_id:id,rent_amount:p?.rent_amount??c.rent_amount}))}}><option value="">Selecione...</option>{(editing?properties:eligibleProperties).map(p=><option value={p.id} key={p.id}>#{p.code} · {addressLine(p.address)}</option>)}</select></label>
        <label className="field"><span>Aluguel</span><input required min="0.01" step="0.01" type="number" value={form.rent_amount??''} onChange={e=>setForm(c=>({...c,rent_amount:e.target.value?Number(e.target.value):null}))}/></label>
        <label className="field"><span>Início</span><input required type="date" value={form.start_date} onChange={e=>changeStart(e.target.value)}/></label>
        <label className="field"><span>Prazo (meses)</span><input min="1" max="240" type="number" value={form.term_months} onChange={e=>changeTerm(Number(e.target.value))}/></label>
        <label className="field"><span>Término</span><input required type="date" value={form.end_date} onChange={e=>setForm(c=>({...c,end_date:e.target.value}))}/></label>
        <label className="field"><span>Vencimento</span><input min="1" max="28" type="number" value={form.due_day} onChange={e=>setForm(c=>({...c,due_day:Number(e.target.value)}))}/></label>
        <label className="field"><span>Índice de reajuste</span><select value={form.adjustment_index} onChange={e=>setForm(c=>({...c,adjustment_index:e.target.value as AdjustmentIndex}))}>{indexOptions.map(index=><option value={index} key={index}>{index}</option>)}</select></label>
        <label className="field"><span>Periodicidade (meses)</span><input min="1" max="36" type="number" value={form.adjustment_period_months} onChange={e=>{const months=Number(e.target.value);setForm(c=>({...c,adjustment_period_months:months,next_adjustment_date:isoAddMonths(c.adjustment_base_date,months)}))}}/></label>
        <label className="field"><span>Data-base</span><input required type="date" value={form.adjustment_base_date} onChange={e=>setForm(c=>({...c,adjustment_base_date:e.target.value,next_adjustment_date:isoAddMonths(e.target.value,c.adjustment_period_months)}))}/></label>
        <label className="field"><span>Próximo reajuste</span><input required type="date" value={form.next_adjustment_date} onChange={e=>setForm(c=>({...c,next_adjustment_date:e.target.value}))}/></label>
        <label className="field"><span>Multa rescisória (aluguéis)</span><input min="0" max="12" step="0.1" type="number" value={form.termination_fine_months} onChange={e=>setForm(c=>({...c,termination_fine_months:Number(e.target.value)}))}/></label>
        <label className="field"><span>Contestação vistoria (dias)</span><input min="1" max="30" type="number" value={form.inspection_contest_days} onChange={e=>setForm(c=>({...c,inspection_contest_days:Number(e.target.value)}))}/></label>
        <label className="field"><span>Garantia</span><select value={form.guarantee_type} onChange={e=>setForm(c=>({...c,guarantee_type:e.target.value as GuaranteeType}))}>{Object.entries(guaranteeLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
        <label className="field field-span-3"><span>Observações</span><textarea rows={3} value={form.notes} onChange={e=>setForm(c=>({...c,notes:e.target.value}))}/></label>
        {editing&&<label className="field field-span-3"><span>Resumo desta nova versão</span><input required minLength={3} value={changeSummary} onChange={e=>setChangeSummary(e.target.value)}/></label>}
      </div>
      <div className="lease-tenants"><div><span className="eyebrow">Locatários</span><h3>Quem assina como locatário</h3></div><div className="lease-tenant-grid">{tenantCandidates.map(person=><label className={form.tenant_ids.includes(person.id)?'selected':''} key={person.id}><input type="checkbox" checked={form.tenant_ids.includes(person.id)} onChange={()=>toggleTenant(person.id)}/><Users size={15}/><span><strong>{person.name}</strong><small>{person.document_number||person.email||'Cadastro sem documento'}</small></span></label>)}</div></div>
      <div className="contract-snapshot-note"><ShieldCheck size={16}/><span>O índice {form.adjustment_index}, a data-base e todas as regras acima serão congelados nesta versão do contrato.</span></div>
      <div className="form-actions"><button className="button secondary" type="button" onClick={()=>{setShowForm(false);setEditing(null)}}>Cancelar</button><button className="button primary" disabled={saving} type="submit">{saving?'Salvando...':editing?'Salvar nova versão':'Criar rascunho'}</button></div>
    </form>}

    {loading?<article className="panel settings-loading">Carregando locações...</article>:<div className="portfolio-card-list lease-list">{items.map(item=><article className="panel lease-card" key={item.id}><div className="lease-card-main"><div><span className="eyebrow">{item.code} · v{item.current_version}</span><strong>Imóvel #{item.property_code}</strong><small>{addressLine(item.property_address)}</small></div><div><span>Aluguel</span><strong>{money(Number(item.rent_amount))}</strong><small>vence dia {item.due_day}</small></div><div><span>Reajuste</span><strong>{item.adjustment_index} · {item.adjustment_period_months} meses</strong><small>próximo em {new Date(`${item.next_adjustment_date}T12:00:00`).toLocaleDateString('pt-BR')}</small></div><div><i className={`status-badge ${item.status==='approved'||item.status==='signed'?'success':item.status==='cancelled'?'danger':item.status==='review'?'warning':'neutral'}`}>{statusLabels[item.status]}</i></div></div>
      <div className="lease-card-detail"><span><Users size={14}/>{item.tenants.map(t=>t.name).join(' / ')}</span><span><ShieldCheck size={14}/>{guaranteeLabels[item.guarantee_type]}</span><span><CalendarClock size={14}/>{item.term_months} meses · multa {Number(item.termination_fine_months).toLocaleString('pt-BR')} aluguéis</span></div>
      <div className="contract-actions"><span className="lease-version-note">{item.versions.length} versão(ões)</span><div>{(item.status==='draft'||item.status==='review')&&canEdit&&<button className="button secondary" type="button" onClick={()=>openEdit(item)}>Nova versão</button>}{item.status==='draft'&&canEdit&&<button className="button primary" disabled={saving} type="button" onClick={()=>void workflow(item,'submit_review')}><Send size={14}/> Revisão</button>}{item.status==='review'&&canApprove&&<button className="button primary" disabled={saving} type="button" onClick={()=>void workflow(item,'approve')}><CheckCircle2 size={14}/> Aprovar</button>}{(item.status==='review'||item.status==='approved')&&canEdit&&<button className="button secondary" type="button" onClick={()=>void workflow(item,'return_draft')}><RotateCcw size={14}/> Rascunho</button>}{!['signed','cancelled'].includes(item.status)&&canEdit&&<button className="button ghost-danger" type="button" onClick={()=>void workflow(item,'cancel')}>Cancelar</button>}</div></div>
    </article>)}{items.length===0&&<article className="panel portfolio-empty"><FileText size={26}/><strong>Nenhum contrato de locação ainda.</strong><span>Crie a primeira minuta usando as regras-padrão da imobiliária.</span></article>}</div>}
  </section>
}
