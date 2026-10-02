export type ContextTab = { key: string; label: string; count?: number }

type ContextTabsProps = { tabs: readonly ContextTab[]; activeKey: string; ariaLabel?: string; onChange: (key: string) => void }

export function ContextTabs({ tabs, activeKey, ariaLabel = 'Seções', onChange }: ContextTabsProps) {
  return <div className="ui-context-tabs" role="tablist" aria-label={ariaLabel}>
    {tabs.map(tab => <button
      key={tab.key}
      type="button"
      role="tab"
      aria-selected={activeKey === tab.key}
      className={activeKey === tab.key ? 'active' : undefined}
      onClick={() => onChange(tab.key)}
    >{tab.label}{tab.count !== undefined && <span>{tab.count}</span>}</button>)}
  </div>
}
