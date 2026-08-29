import { Building2, KeyRound, Palette, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { AccessSettingsPage } from './AccessSettingsPage'
import { AppearanceSettingsPage } from './AppearanceSettingsPage'
import { AuditSettingsPage } from './AuditSettingsPage'

type SettingsTab = 'appearance' | 'access' | 'audit' | 'company'

const tabs = [
  { key: 'company' as const, label: 'Empresa', icon: Building2 },
  { key: 'appearance' as const, label: 'Aparência e Marca', icon: Palette },
  { key: 'access' as const, label: 'Usuários e Permissões', icon: KeyRound },
  { key: 'audit' as const, label: 'Auditoria', icon: ShieldCheck },
]

function CompanySettingsPage() {
  return (
    <section className="workspace settings-workspace">
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">Configurações · Institucional</span>
          <h1>Dados da empresa</h1>
          <p>Esses dados alimentam cabeçalhos, documentos, integrações e a identidade institucional do ERP.</p>
        </div>
        <button className="button primary" type="button">Salvar alterações</button>
      </div>

      <article className="panel form-panel">
        <div className="panel-heading"><span className="eyebrow">Cadastro institucional</span><h2>Imobiliária</h2></div>
        <div className="form-grid two-columns">
          <label className="field"><span>Razão social</span><input placeholder="Razão social" /></label>
          <label className="field"><span>Nome fantasia</span><input placeholder="Nome da imobiliária" /></label>
          <label className="field"><span>CNPJ</span><input placeholder="00.000.000/0000-00" /></label>
          <label className="field"><span>CRECI PJ</span><input placeholder="Registro da empresa" /></label>
          <label className="field"><span>E-mail institucional</span><input placeholder="contato@imobiliaria.com.br" /></label>
          <label className="field"><span>Telefone</span><input placeholder="(41) 0000-0000" /></label>
          <label className="field field-wide"><span>Endereço</span><input placeholder="Endereço completo" /></label>
        </div>
      </article>
    </section>
  )
}

export function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>('appearance')

  return (
    <div className="settings-shell">
      <div className="settings-tabs">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button className={tab === key ? 'active' : ''} type="button" key={key} onClick={() => setTab(key)}>
            <Icon size={16} /> {label}
          </button>
        ))}
      </div>
      {tab === 'company' && <CompanySettingsPage />}
      {tab === 'appearance' && <AppearanceSettingsPage />}
      {tab === 'access' && <AccessSettingsPage />}
      {tab === 'audit' && <AuditSettingsPage />}
    </div>
  )
}
