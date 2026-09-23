import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { apiRequest, ApiError } from '../../api/client'
import type { Property, PropertyAdditionalCharge as Charge } from '../../api/types'
import './property-additional-charges.css'

type Props={property:Property;canEdit:boolean;onUpdated:(updated:Property)=>void;hasSignedLease:boolean}
const kinds:Record<Charge['kind'],string>={fire_insurance:'Seguro incêndio',guarantee_insurance:'Seguro fiança',other:'Outro encargo'}
const empty=(kind:Charge['kind']):Charge=>({
 key:kind+'_'+Math.random().toString(36).slice(2,10),kind,label:kinds[kind],amount:0,
 active:true,payer:'tenant',beneficiary:'third_party',beneficiary_name:kind==='other'?'':'Seguradora',
 frequency:kind==='fire_insurance'?'annual':'monthly',include_in_invoice:true,
 agency_retention_type:'none',agency_retention_value:0,start_date:null,end_date:null,
})
const price=(value:number)=>Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
export function PropertyAdditionalChargesPanel({property,canEdit,onUpdated,hasSignedLease}:Props){
 const [rows,setRows]=useState<Charge[]>(property.additional_charges||[])
 const [editing,setEditing]=useState(false),[busy,setBusy]=useState(false)
 const [error,setError]=useState(''),[saved,setSaved]=useState('')
 useEffect(()=>{if(!editing)setRows(property.additional_charges||[])},[property.additional_charges,property.id,editing])
 const patch=(key:string,data:Partial<Charge>)=>setRows(old=>old.map(item=>item.key===key?{...item,...data}:item))
 async function save(){
   setError('');setSaved('')
   if(rows.some(row=>!row.label.trim())){setError('Informe a descrição de cada encargo.');return}
   if(rows.some(row=>!Number.isFinite(row.amount)||row.amount<0)){setError('Informe valores válidos para todos os encargos.');return}
   setBusy(true)
   try{
     const updated=await apiRequest<Property>(`/properties/${property.id}/additional-charges`,{method:'PUT',body:JSON.stringify({charges:rows.map(row=>({...row,label:row.label.trim(),beneficiary_name:row.beneficiary_name?.trim()||null}))})})
     // Use the canonical API response immediately; do not wait for a page refresh.
     // Synchronize the workspace source of truth before leaving edit mode so
     // the prop-sync effect cannot restore the previous empty list.
     onUpdated(updated)
     setRows(updated.additional_charges||[])
     setEditing(false)
     setSaved('Encargos adicionais salvos.')
   }catch(cause){setError(cause instanceof ApiError?cause.detail:'Não foi possível salvar os encargos.')}
   finally{setBusy(false)}
 }
 return <section className="property-charge-panel">
 <div className="property-charge-head"><div><span className="eyebrow">ENCARGOS DO IMÓVEL</span><h3>Seguros e outras cobranças</h3><p>Valores de referência aproveitados na composição de novas locações.</p></div>
 {canEdit&&!editing&&<button type="button" className="button secondary" onClick={()=>{setEditing(true);setSaved('')}}>Editar encargos</button>}</div>
 {hasSignedLease&&<p className="property-charge-notice">Contratos já assinados não são alterados automaticamente. Confira a composição da locação antes de gerar novas cobranças.</p>}
 {!rows.length&&!editing&&<p className="property-charge-notice">Nenhum encargo adicional cadastrado.</p>}
 <div className="property-charge-list">{rows.map(row=><article key={row.key} className="property-charge-item">
  <div className="property-charge-item-head"><strong>{row.label||kinds[row.kind]}</strong>{editing?<button type="button" className="button secondary" disabled={busy} onClick={()=>setRows(old=>old.filter(item=>item.key!==row.key))}><Trash2 size={14}/> Remover</button>:<strong>{price(row.amount)}</strong>}</div>
  {editing?<><div className="property-charge-fieldgrid">
   <label>Tipo<select value={row.kind} onChange={e=>{const kind=e.target.value as Charge['kind'];patch(row.key,{kind,label:row.label===kinds[row.kind]?kinds[kind]:row.label,frequency:kind==='fire_insurance'?'annual':row.frequency,agency_retention_type:'none',agency_retention_value:0})}}>{Object.entries(kinds).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
   <label>Descrição<input maxLength={120} value={row.label} onChange={e=>patch(row.key,{label:e.target.value})}/></label>
   <label>Valor (R$)<input type="number" min="0" step=".01" value={row.amount} onChange={e=>patch(row.key,{amount:Number(e.target.value)})}/></label>
   <label>Periodicidade<select value={row.frequency} onChange={e=>patch(row.key,{frequency:e.target.value as Charge['frequency']})}><option value="monthly">Mensal</option><option value="annual">Anual</option><option value="one_time">Única</option></select></label>
   <label>Quem paga<select value={row.payer} onChange={e=>patch(row.key,{payer:e.target.value as Charge['payer']})}><option value="tenant">Locatário</option><option value="owner">Proprietário</option><option value="agency">Imobiliária</option></select></label>
   <label>Destinatário<select value={row.beneficiary} onChange={e=>patch(row.key,{beneficiary:e.target.value as Charge['beneficiary'],agency_retention_type:'none',agency_retention_value:0})}><option value="third_party">Seguradora / terceiro</option><option value="owner">Proprietário</option><option value="agency">Imobiliária</option></select></label>
   <label>Nome do destinatário<input maxLength={180} value={row.beneficiary_name||''} onChange={e=>patch(row.key,{beneficiary_name:e.target.value})}/></label>
   <label>Retenção da imobiliária<select value={row.agency_retention_type} onChange={e=>patch(row.key,{agency_retention_type:e.target.value as Charge['agency_retention_type'],agency_retention_value:0})}><option value="none">Não há</option>{row.kind!=='other'&&row.beneficiary==='third_party'&&<><option value="percent">Percentual (%)</option><option value="fixed">Valor fixo (R$)</option></>}</select></label>
   {row.agency_retention_type!=='none'&&<label>Valor de retenção<input type="number" min="0" step=".01" value={row.agency_retention_value} onChange={e=>patch(row.key,{agency_retention_value:Number(e.target.value)})}/></label>}
  </div><div className="property-charge-choices"><label><input type="checkbox" checked={row.active} onChange={e=>patch(row.key,{active:e.target.checked})}/> Ativo</label><label><input type="checkbox" checked={row.include_in_invoice} onChange={e=>patch(row.key,{include_in_invoice:e.target.checked})}/> Incluir na cobrança</label></div></>:
  <div className="property-charge-choices"><span>{row.frequency==='monthly'?'Mensal':row.frequency==='annual'?'Anual':'Única'}</span><span>{row.active?'Ativo':'Inativo'}</span><span>{row.include_in_invoice?'Incluído na cobrança':'Fora da cobrança'}</span></div>}
 </article>)}</div>
 {editing&&<div className="property-charge-actions">
  {(['fire_insurance','guarantee_insurance','other'] as const).map(kind=><button key={kind} type="button" className="button secondary" disabled={busy||rows.length>=20} onClick={()=>setRows(old=>[...old,empty(kind)])}><Plus size={14}/>{kinds[kind]}</button>)}
  <button type="button" className="button secondary" disabled={busy} onClick={()=>{setEditing(false);setRows(property.additional_charges||[]);setError('')}}>Cancelar</button>
  <button type="button" className="button primary" disabled={busy} onClick={()=>void save()}>{busy?'Salvando...':'Salvar encargos'}</button>
 </div>}
 {error&&<p className="property-charge-error" role="alert">{error}</p>}{saved&&<p className="property-charge-notice" role="status">{saved}</p>}
 </section>
}
