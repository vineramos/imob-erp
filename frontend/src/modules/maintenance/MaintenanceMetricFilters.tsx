import { useEffect } from 'react'
import './maintenance-metric-filters.css'

type MetricKey = 'open' | 'approval' | 'execution' | 'urgent' | 'completed'

const metricKeys: MetricKey[] = ['open', 'approval', 'execution', 'urgent', 'completed']
const metricTitles: Record<MetricKey, string> = {
  open: 'Filtrar chamados em aberto',
  approval: 'Filtrar chamados aguardando aprovação',
  execution: 'Filtrar chamados agendados ou em execução',
  urgent: 'Filtrar chamados urgentes',
  completed: 'Filtrar manutenções concluídas',
}

export function MaintenanceMetricFilters() {
  useEffect(() => {
    let customMode: 'execution' | 'urgent' | null = null
    let internalChange = false

    const workspace = () => document.querySelector<HTMLElement>('.maintenance-workspace')
    const select = () => workspace()?.querySelector<HTMLSelectElement>('.maintenance-toolbar select') ?? null
    const cards = () => Array.from(workspace()?.querySelectorAll<HTMLElement>('.maintenance-metrics .metric-card') ?? [])
    const maintenanceCards = () => Array.from(workspace()?.querySelectorAll<HTMLElement>('.maintenance-list > .maintenance-card') ?? [])

    function allOption() {
      return select()?.querySelector<HTMLOptionElement>('option[value="all"]') ?? null
    }

    function restoreAllLabel() {
      const option = allOption()
      if (option) option.textContent = 'Todos'
    }

    function currentMetric(): MetricKey | null {
      if (customMode) return customMode
      const value = select()?.value
      if (value === 'open') return 'open'
      if (value === 'awaiting_approval') return 'approval'
      if (value === 'scheduled' || value === 'in_progress') return 'execution'
      if (value === 'completed') return 'completed'
      return null
    }

    function decorate() {
      cards().forEach((card, index) => {
        const key = metricKeys[index]
        if (!key) return
        card.classList.add('maintenance-metric-filter')
        card.dataset.metricFilter = key
        card.setAttribute('role', 'button')
        card.tabIndex = 0
        card.title = metricTitles[key]
      })
    }

    function apply() {
      decorate()
      const active = currentMetric()
      cards().forEach((card) => {
        const isActive = card.dataset.metricFilter === active
        card.classList.toggle('maintenance-metric-filter-active', isActive)
        card.setAttribute('aria-pressed', String(isActive))
      })

      maintenanceCards().forEach((card) => {
        let show = true
        if (customMode === 'urgent') {
          show = card.classList.contains('priority-urgent')
        } else if (customMode === 'execution') {
          const status = card.querySelector<HTMLElement>('.maintenance-meta .status-badge')?.textContent?.trim() ?? ''
          show = status === 'Agendado' || status === 'Em execução'
        }
        card.classList.toggle('maintenance-card--metric-hidden', !show)
      })
    }

    function dispatchFilter(value: string, mode: 'execution' | 'urgent' | null) {
      const control = select()
      if (!control) return
      customMode = mode
      const option = allOption()
      if (option) option.textContent = mode === 'execution' ? 'Agendadas / execução' : mode === 'urgent' ? 'Urgentes' : 'Todos'
      internalChange = true
      control.value = value
      control.dispatchEvent(new Event('change', { bubbles: true }))
      internalChange = false
      window.setTimeout(apply, 0)
    }

    function activate(key: MetricKey) {
      const active = currentMetric()
      if (active === key) {
        customMode = null
        restoreAllLabel()
        dispatchFilter('all', null)
        return
      }
      if (key === 'open') dispatchFilter('open', null)
      else if (key === 'approval') dispatchFilter('awaiting_approval', null)
      else if (key === 'completed') dispatchFilter('completed', null)
      else dispatchFilter('all', key)
    }

    function metricFromTarget(target: EventTarget | null) {
      if (!(target instanceof Element)) return null
      const card = target.closest<HTMLElement>('.maintenance-metrics .metric-card[data-metric-filter]')
      if (!card) return null
      return card.dataset.metricFilter as MetricKey | undefined
    }

    const onClick = (event: MouseEvent) => {
      const key = metricFromTarget(event.target)
      if (key) activate(key)
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Enter' && event.key !== ' ') return
      const key = metricFromTarget(event.target)
      if (!key) return
      event.preventDefault()
      activate(key)
    }

    const onChange = (event: Event) => {
      const target = event.target
      if (!(target instanceof HTMLSelectElement) || !target.closest('.maintenance-toolbar') || internalChange) return
      customMode = null
      restoreAllLabel()
      window.setTimeout(apply, 0)
    }

    const observer = new MutationObserver(() => apply())
    const root = document.getElementById('root')
    if (root) observer.observe(root, { childList: true, subtree: true })
    document.addEventListener('click', onClick)
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('change', onChange)
    apply()

    return () => {
      observer.disconnect()
      document.removeEventListener('click', onClick)
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('change', onChange)
      maintenanceCards().forEach((card) => card.classList.remove('maintenance-card--metric-hidden'))
      restoreAllLabel()
    }
  }, [])

  return null
}
