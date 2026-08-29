import { Building2, KeyRound, Palette, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { AccessSettingsPage } from './AccessSettingsPage'
import { AppearanceSettingsPage } from './AppearanceSettingsPage'
import { AuditSettingsPage } from './AuditSettingsPage'
import { CompanySettingsPage } from './CompanySettingsPage'

type SettingsTab = 'appearance' | 'access' | 'audit' | 'company'

type Props = {
  permissions: string[]
}

const tabs = [
  { key: 'company' as const, label: 'Empresa', icon: Building2, permission: 'settings.view' },
  { key: 'appearance' as const, label: 'Aparência e Marca', icon: Palette, permission: 'settings.view' },
  { key: 'access' as const, label: 'Usuários e Permissões', icon: KeyRound, permission: 'users.manage' },
  { key: 'audit' as const, label: 'Auditoria', icon: ShieldCheck, permission: 'audit.view' },
]

export function SettingsPage({ permissions }: Props) {
  const permissionSet = useMemo(() => new Set(permissions), [permissions])
  const visibleTabs = useMemo(() => tabs.filter((item) => permissionSet.has(item.permission)), [permissionSet])
  const [tab, setTab] = useState<SettingsTab>(visibleTabs[0]?.key ?? 'company')

  const activeTab = visibleTabs.some((item) => item.key === tab) ? tab : visibleTabs[0]?.key

  if (!activeTab) {
    return (
      <section className="workspace settings-workspace">
        <article className="panel empty-module">
          <strong>Sem configurações disponíveis.</strong>
          <span>Seu perfil não possui permissão para acessar esta área.</span>
        </article>
      </section>
    )
  }

  return (
    <div className="settings-shell">
      <div className="settings-tabs">
        {visibleTabs.map(({ key, label, icon: Icon }) => (
          <button className={activeTab === key ? 'active' : ''} type="button" key={key} onClick={() => setTab(key)}>
            <Icon size={16} /> {label}
          </button>
        ))}
      </div>
      {activeTab === 'company' && <CompanySettingsPage canEdit={permissionSet.has('settings.company.manage')} />}
      {activeTab === 'appearance' && <AppearanceSettingsPage canEdit={permissionSet.has('settings.appearance.manage')} />}
      {activeTab === 'access' && <AccessSettingsPage />}
      {activeTab === 'audit' && <AuditSettingsPage />}
    </div>
  )
}
