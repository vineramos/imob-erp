import {
  AlertTriangle,
  Building2,
  CalendarCheck2,
  FileSignature,
  Landmark,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'

const cards = [
  {
    label: 'Imóveis administrados',
    value: '—',
    hint: 'Módulo de imóveis entra na próxima etapa',
    icon: Building2,
    tone: 'blue',
  },
  {
    label: 'Contratos ativos',
    value: '—',
    hint: 'Aguardando módulo de contratos',
    icon: FileSignature,
    tone: 'violet',
  },
  {
    label: 'Pendências críticas',
    value: '0',
    hint: 'Nenhuma ocorrência crítica',
    icon: AlertTriangle,
    tone: 'orange',
  },
  {
    label: 'Tarefas de hoje',
    value: '0',
    hint: 'Agenda integrada sem pendências',
    icon: CalendarCheck2,
    tone: 'green',
  },
]

const foundation = [
  'Autenticação e Administrador inicial',
  'Perfis, permissões e alçadas',
  'Auditoria das ações sensíveis',
  'Dados da empresa e identidade visual',
  'Design System e navegação modular',
]

export function DashboardPage() {
  return (
    <section className="workspace dashboard-workspace">
      <div className="page-heading dashboard-heading">
        <div>
          <span className="eyebrow">Visão geral</span>
          <h1>Dashboard</h1>
          <p>Uma visão rápida da operação. Os indicadores ganham dados reais conforme os módulos forem ativados.</p>
        </div>
        <div className="environment-pill">
          <span className="status-dot status-ready" />
          Ambiente operacional
        </div>
      </div>

      <div className="metric-grid">
        {cards.map(({ icon: Icon, tone, ...card }) => (
          <article className="metric-card" key={card.label}>
            <div className={`metric-icon metric-icon-${tone}`}>
              <Icon size={20} strokeWidth={1.8} />
            </div>
            <div className="metric-copy">
              <span>{card.label}</span>
              <strong>{card.value}</strong>
              <small>{card.hint}</small>
            </div>
          </article>
        ))}
      </div>

      <div className="dashboard-grid dashboard-main-grid">
        <article className="panel dashboard-foundation-panel">
          <div className="panel-heading panel-heading-row">
            <div>
              <span className="eyebrow">Fundação</span>
              <h2>Base do ERP pronta para evoluir</h2>
            </div>
            <div className="panel-heading-icon"><ShieldCheck size={20} /></div>
          </div>

          <div className="foundation-list foundation-checklist">
            {foundation.map((item) => (
              <div key={item}>
                <span className="foundation-check"><ShieldCheck size={14} /></span>
                <span>{item}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="panel next-step-panel">
          <div className="panel-heading panel-heading-row">
            <div>
              <span className="eyebrow">Próxima etapa</span>
              <h2>Operação imobiliária</h2>
            </div>
            <div className="panel-heading-icon"><Sparkles size={20} /></div>
          </div>

          <div className="next-step-list">
            <div>
              <span className="next-step-number">01</span>
              <div><strong>Pessoas e imóveis</strong><small>Cadastros canônicos e propriedade.</small></div>
            </div>
            <div>
              <span className="next-step-number">02</span>
              <div><strong>Captação e administração</strong><small>Do lead do proprietário ao imóvel disponível.</small></div>
            </div>
            <div>
              <span className="next-step-number">03</span>
              <div><strong>Contratos e financeiro</strong><small>Regras próprias, cobrança, repasse e conciliação.</small></div>
            </div>
          </div>
        </article>
      </div>

      <div className="dashboard-grid dashboard-secondary-grid">
        <article className="panel operating-principles">
          <div className="panel-heading panel-heading-row">
            <div>
              <span className="eyebrow">Governança</span>
              <h2>Princípios que já nascem no sistema</h2>
            </div>
            <Landmark size={19} />
          </div>
          <div className="principle-grid">
            <div><strong>Rastreabilidade</strong><span>Ações sensíveis deixam histórico de quem, quando e o que mudou.</span></div>
            <div><strong>Segregação</strong><span>Valores de terceiros ficam separados do caixa operacional da imobiliária.</span></div>
            <div><strong>Regra por contrato</strong><span>Configuração define o padrão; cada contrato preserva sua própria regra.</span></div>
          </div>
        </article>

        <article className="panel activity-preview">
          <div className="panel-heading">
            <span className="eyebrow">Atividades recentes</span>
            <h2>Histórico operacional</h2>
          </div>
          <div className="activity-empty">
            <span className="activity-empty-icon"><CalendarCheck2 size={20} /></span>
            <strong>Nenhuma atividade operacional ainda</strong>
            <small>Novos eventos aparecerão aqui conforme os módulos forem utilizados.</small>
          </div>
        </article>
      </div>
    </section>
  )
}
