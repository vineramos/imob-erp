import { FormEvent } from 'react'
import { X } from 'lucide-react'
import { Lease, Maintenance, MaintenanceForm, Person, Property, categories, priorities, address } from './types'

type Props={editing:Maintenance|null;form:MaintenanceForm;setForm:(updater:(current:MaintenanceForm)=>MaintenanceForm)=>void;properties:Property[];people:Person[];leases:Lease[];saving:boolean;onClose:()=>void;onSubmit:(event:FormEvent)=>void}

export function MaintenanceCallModal({editing,form,setForm,properties,people,leases,saving,onClose,onSubmit}:Props){
  const availableLeases=leases.filter(item=>!form.property_id||item.property_id===form.property_id)
  return <div className="portfolio-modal-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget&&!saving)onClose()}}><form className="panel portfolio-modal maintenance-modal" onSubmit={onSubmit} role="dialog" aria-modal="true">
    <div className="portfolio-modal-header"><div><span className="eyebrow">Chamado de manutenção</span><h2>{editing?`Editar ${editing.code}`:'Nova manutenção'}</h2><p>Registre somente o problema relatado. Serviços, parceiros e valores serão definidos pelo setor de manutenção depois.</p></div><button className="portfolio-modal-close" type="button" onClick={onClose} disabled={saving}><X size={18}/></button></div>
    <div className="portfolio-modal-body">
      <div className="maintenance-flow-hint"><span>1</span><div><strong>Cliente / atendimento abre o chamado</strong><small>Sem custo, fornecedor ou orçamento.</small></div><i>→</i><span>2</span><div><strong>Manutenção define o escopo</strong><small>Os parceiros cotam exatamente os mesmos serviços.</small></div></div>
      <div className="form-grid three-columns">
        <label className="field field-span-2"><span>Imóvel</span><select required value={form.property_id} onChange={e=>setForm(c=>({...c,property_id:e.target.value,lease_contract_id:''}))}><option value="">Selecione...</option>{properties.map(p=><option key={p.id} value={p.id}>{p.code} · {p.public_title||address(p.address)}</option>)}</select></label>
        <label className="field"><span>Contrato de locação</span><select value={form.lease_contract_id} onChange={e=>setForm(c=>({...c,lease_contract_id:e.target.value}))}><option value="">Sem vínculo específico</option>{availableLeases.map(l=><option key={l.id} value={l.id}>{l.code} · {l.tenants.map(t=>t.name).join(' / ')}</option>)}</select></label>
        <label className="field"><span>Solicitante</span><select value={form.requester_person_id} onChange={e=>setForm(c=>({...c,requester_person_id:e.target.value}))}><option value="">Não informado</option>{people.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label className="field field-span-2"><span>Título do chamado</span><input required minLength={3} value={form.title} onChange={e=>setForm(c=>({...c,title:e.target.value}))} placeholder="Ex.: Vazamento na cozinha"/></label>
        <label className="field"><span>Categoria</span><select value={form.category} onChange={e=>setForm(c=>({...c,category:e.target.value}))}>{Object.entries(categories).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field"><span>Prioridade</span><select value={form.priority} onChange={e=>setForm(c=>({...c,priority:e.target.value}))}>{Object.entries(priorities).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field field-span-3"><span>Descrição do problema</span><textarea required minLength={3} rows={5} value={form.description} onChange={e=>setForm(c=>({...c,description:e.target.value}))} placeholder="Descreva o que aconteceu, onde está o problema e outras informações visíveis."/></label>
        <label className="field field-span-3"><span>Observações internas</span><input value={form.notes} onChange={e=>setForm(c=>({...c,notes:e.target.value}))}/></label>
      </div>
    </div>
    <div className="form-actions portfolio-modal-actions"><button className="button secondary" type="button" onClick={onClose} disabled={saving}>Cancelar</button><button className="button primary" disabled={saving}>{saving?'Salvando...':editing?'Salvar alterações':'Abrir chamado'}</button></div>
  </form></div>
}
