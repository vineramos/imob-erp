import { CheckCircle2, Download, FileText, Upload, X } from 'lucide-react'
import { useState } from 'react'
import './commission-flow-demo.css'

type DemoTab='broker'|'finance'|'report'

const rows=[
  {contract:'CT-2026-0148',property:'Apartamento 101 – Ed. Vista Parque',client:'Ana Paula Ribeiro',received:'10/09/2026',base:'R$ 65.000,00',percent:'3,00%',commission:'R$ 1.950,00'},
  {contract:'CT-2026-0167',property:'Casa 305 – Condomínio Villa Bella',client:'Ricardo Santos',received:'18/09/2026',base:'R$ 4.833,33',percent:'30,00%',commission:'R$ 1.450,00'},
  {contract:'CT-2026-0171',property:'Sala 708 – Ed. Corporate Tower',client:'Luciana Mota',received:'25/09/2026',base:'R$ 483.333,33',percent:'0,30%',commission:'R$ 1.450,00'},
]

export function CommissionFlowDemo({open,onClose}:{open:boolean;onClose:()=>void}){
  const [tab,setTab]=useState<DemoTab>('broker')
  if(!open)return null
  return <div className="commission-demo-backdrop" onMouseDown={e=>{if(e.currentTarget===e.target)onClose()}}>
    <section className="commission-demo-shell" role="dialog" aria-modal="true" aria-label="Prévia visual do fluxo de comissões">
      <header className="commission-demo-header">
        <div><span>PRÉVIA VISUAL · DADOS FICTÍCIOS</span><h2>Fluxo mensal de comissões</h2><p>Somente para validação visual. Nenhum dado é salvo no financeiro.</p></div>
        <button type="button" onClick={onClose} aria-label="Fechar"><X size={17}/></button>
      </header>
      <nav className="commission-demo-tabs">
        <button className={tab==='broker'?'active':''} onClick={()=>setTab('broker')}>Tela do corretor</button>
        <button className={tab==='finance'?'active':''} onClick={()=>setTab('finance')}>Tela do financeiro</button>
        <button className={tab==='report'?'active':''} onClick={()=>setTab('report')}>Relatório do corretor</button>
      </nav>
      <div className="commission-demo-body">
        {tab==='broker'&&<div className="commission-demo-workspace">
          <div className="commission-demo-titlebar"><div><span>Corretores › João Pedro Martins › Comissões</span><h3>Lote de comissões – 09/2026</h3><p>Comissões referentes aos contratos recebidos no período de setembro de 2026.</p></div><i className="status-badge success">Relatório liberado</i></div>
          <div className="commission-demo-summary">
            <div><span>Protocolo / Código</span><strong>COM-2026-000127</strong></div>
            <div><span>Competência</span><strong>09/2026</strong></div>
            <div><span>Valor total</span><strong className="demo-blue">R$ 4.850,00</strong></div>
          </div>
          <div className="commission-demo-info-grid">
            <div><span>Razão social do corretor</span><strong>João Martins Negócios Imobiliários Ltda.</strong></div>
            <div><span>CNPJ</span><strong>12.345.678/0001-90</strong></div>
            <div><span>Tomador</span><strong>Imob Prime Negócios Imobiliários Ltda.</strong></div>
            <div><span>CNPJ do tomador</span><strong>48.222.111/0001-44</strong></div>
          </div>
          <div className="commission-demo-callout"><div><FileText size={16}/><span>O relatório está liberado. Gere o PDF e emita a Nota Fiscal referente a este lote.</span></div><button className="button primary" type="button">Gerar relatório</button></div>
          <div className="commission-demo-note-data"><strong>Dados para a nota fiscal</strong><span>Serviços prestados no mês de setembro de 2026, conforme relatório de pagamentos nº COM-2026-000127.</span><small>Previsão de pagamento: <b>13/10/2026</b></small></div>
          <div className="commission-demo-table-wrap"><table><thead><tr><th>Contrato / Imóvel</th><th>Cliente</th><th>Recebimento</th><th>Comissão</th></tr></thead><tbody>{rows.map(r=><tr key={r.contract}><td><b>{r.contract}</b><small>{r.property}</small></td><td>{r.client}</td><td>{r.received}</td><td><b>{r.commission}</b></td></tr>)}</tbody></table></div>
          <div className="commission-demo-upload"><div><Upload size={17}/><span><b>Anexar Nota Fiscal</b><small>Após o envio, o status passa para “Aguardando aprovação do setor financeiro”.</small></span></div><button className="button primary" type="button">Anexar nota fiscal</button></div>
        </div>}

        {tab==='finance'&&<div className="commission-demo-workspace">
          <div className="commission-demo-titlebar"><div><span>Financeiro › Comissões › Lotes de comissões</span><h3>COM-2026-000127</h3><p>Conferência documental e programação de pagamento.</p></div><i className="status-badge warning">Aguardando aprovação financeira</i></div>
          <div className="commission-demo-finance-head">
            <div><span>Corretor</span><strong>João Pedro Martins</strong><small>João Martins Negócios Imobiliários Ltda.</small></div>
            <div><span>CNPJ</span><strong>12.345.678/0001-90</strong></div>
            <div><span>Competência</span><strong>09/2026</strong></div>
            <div><span>Total</span><strong className="demo-blue">R$ 4.850,00</strong></div>
          </div>
          <div className="commission-demo-finance-grid">
            <section><h4>Comissões do lote</h4><div className="commission-demo-table-wrap"><table><thead><tr><th>Contrato</th><th>Cliente</th><th>Pgto.</th><th>Comissão</th></tr></thead><tbody>{rows.map(r=><tr key={r.contract}><td><b>{r.contract}</b><small>{r.property}</small></td><td>{r.client}</td><td>{r.received}</td><td><b>{r.commission}</b></td></tr>)}</tbody></table></div><div className="commission-demo-total"><span>Total do lote</span><strong>R$ 4.850,00</strong></div></section>
            <section><h4>Nota fiscal anexada</h4><div className="commission-demo-nf"><div className="nf-top"><b>NF-e nº 2026/0918</b><span>02/10/2026</span></div><dl><div><dt>Prestador</dt><dd>João Martins Negócios Imobiliários Ltda.</dd></div><div><dt>CNPJ</dt><dd>12.345.678/0001-90</dd></div><div><dt>Tomador</dt><dd>Imob Prime Negócios Imobiliários Ltda.</dd></div><div><dt>Valor</dt><dd>R$ 4.850,00</dd></div></dl></div><div className="commission-demo-checks"><span><CheckCircle2 size={14}/> Razão social confere</span><span><CheckCircle2 size={14}/> CNPJ confere</span><span><CheckCircle2 size={14}/> Descrição confere</span><span><CheckCircle2 size={14}/> Valor confere</span></div></section>
          </div>
          <div className="commission-demo-actions"><button className="button secondary" type="button">Devolver para correção</button><button className="button primary" type="button"><CheckCircle2 size={14}/> Aprovar e programar pagamento</button></div>
        </div>}

        {tab==='report'&&<article className="commission-demo-report">
          <header><div className="demo-logo">IMOB <b>PRIME</b><small>NEGÓCIOS IMOBILIÁRIOS</small></div><div><h3>Relatório de Comissões Liberadas</h3><p>Comissões recebidas no período de setembro de 2026</p></div></header>
          <div className="demo-report-meta"><div><span>Protocolo</span><strong>COM-2026-000127</strong></div><div><span>Competência</span><strong>09/2026</strong></div><div><span>Data de geração</span><strong>02/10/2026</strong></div><div><span>Situação</span><strong className="demo-green">Liberado</strong></div></div>
          <div className="demo-report-parties"><section><h4>Dados do corretor</h4><p><span>Nome</span><b>João Pedro Martins</b></p><p><span>Razão social</span><b>João Martins Negócios Imobiliários Ltda.</b></p><p><span>CNPJ</span><b>12.345.678/0001-90</b></p><p><span>CRECI</span><b>123.456-F</b></p></section><section><h4>Dados do tomador / pagador</h4><p><span>Razão social</span><b>Imob Prime Negócios Imobiliários Ltda.</b></p><p><span>CNPJ</span><b>48.222.111/0001-44</b></p><p><span>Endereço</span><b>Av. Paulista, 1.000 – Bela Vista – São Paulo/SP</b></p></section></div>
          <div className="demo-report-description"><FileText size={20}/><div><strong>Descrição sugerida para a Nota Fiscal</strong><p>Serviços prestados no mês de setembro de 2026, conforme relatório de pagamentos nº COM-2026-000127.</p></div></div>
          <h4 className="demo-report-section-title">Detalhamento das comissões</h4>
          <div className="commission-demo-table-wrap"><table><thead><tr><th>Contrato</th><th>Imóvel</th><th>Cliente / Locatário</th><th>Recebimento</th><th>Base recebida</th><th>Percentual</th><th>Comissão</th></tr></thead><tbody>{rows.map(r=><tr key={r.contract}><td><b>{r.contract}</b></td><td>{r.property}</td><td>{r.client}</td><td>{r.received}</td><td>{r.base}</td><td>{r.percent}</td><td><b>{r.commission}</b></td></tr>)}</tbody></table></div>
          <div className="demo-report-totals"><div><span>Base total recebida</span><strong>R$ 1.138.166,66</strong></div><div><span>Comissão total do lote</span><strong>R$ 4.850,00</strong></div><div><span>Previsão de pagamento</span><strong>13/10/2026</strong></div></div>
          <footer><span>Imob Prime Negócios Imobiliários · CNPJ 48.222.111/0001-44</span><span>Relatório gerado em 02/10/2026 às 14:37 · Página 1 de 1</span></footer>
        </article>}
      </div>
    </section>
  </div>
}
