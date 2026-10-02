# Imob ERP Imobiliário

ERP imobiliário modular, auditável e preparado para crescer. O projeto nasce com foco total na operação de uma imobiliária e mantém separadas as responsabilidades de interface, regras de negócio, integrações e dados.

## Arquitetura inicial

- **Frontend:** React + TypeScript + Vite
- **Backend:** FastAPI + Python
- **Banco:** PostgreSQL no Neon
- **Autenticação:** Neon Auth (e-mail e senha, sem cadastro público)
- **Hospedagem:** Google Cloud Run com deploy automatizado via GitHub Actions + Workload Identity Federation
- **Assinaturas:** Clicksign via provider dedicado
- **Banco operacional:** Banco Inter via `BankProvider`
- **Arquivos:** object storage, nunca dentro do banco relacional

## Estrutura

```text
imob-erp/
├── frontend/       # interface do ERP
├── backend/        # API, regras e integrações
├── docs/           # arquitetura e decisões do projeto
└── .github/        # validações automatizadas
```

## Princípios

1. Um dado é cadastrado uma vez e reutilizado pelos módulos.
2. Configurações definem padrões; contratos e registros guardam suas regras efetivas.
3. Ações sensíveis são auditadas.
4. Pagamentos manuais são exceção.
5. Dinheiro de terceiros nunca é tratado como caixa disponível da imobiliária.
6. Integrações externas ficam encapsuladas em providers.
7. O sistema deve continuar modular mesmo quando crescer.

## Sprint atual

**Sprint 1 — Fundação + hardening operacional**

Além da fundação inicial, a branch atual já inclui:

- CRM, imóveis, contratos, locação, manutenção, agenda, documentos, portais e financeiro;
- ciclo de cobrança, baixa, liquidação, comissão, repasse, tesouraria e conciliação;
- separação entre recursos próprios e dinheiro de terceiros;
- fechamento financeiro com verificações de rastreabilidade;
- relatórios, DRE e informes anuais;
- readiness técnico em `/api/health/ready`;
- readiness consolidado de integrações na tela Configurações → Integrações;
- build de container e deploy automatizado no Cloud Run;
- smoke tests pós-deploy de aplicação e Neon Auth;
- identificação do SHA efetivamente publicado para evitar deploy stale;
- headers HTTP defensivos e container executado sem root.

O runbook de produção está em `docs/OPERATIONS_RUNBOOK.md`.

> Branch de desenvolvimento: `sprint-1-foundation`
