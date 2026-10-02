# Sprint 1 — Fundação

## Entrega esperada

Ao final desta sprint o ERP deverá possuir uma base segura e reutilizável para todos os módulos seguintes.

## Escopo

### Aplicação
- shell visual do ERP;
- sidebar modular;
- busca global preparada;
- topo com alertas e usuário;
- layout responsivo para PC e notebook.

### Identidade visual
- tokens de Design System;
- nome, logo e identidade institucional parametrizáveis;
- tema do ERP independente do futuro tema do site;
- futura tela administrativa para edição e pré-visualização.

### Segurança
- login por e-mail e senha;
- Neon Auth;
- sem cadastro público;
- usuários criados/administrados internamente;
- bloqueio de usuário;
- perfis-base e permissões granulares.

### Governança
- somente Administradores alteram permissões e alçadas;
- auditoria de alterações sensíveis;
- histórico com usuário, data/hora, antes/depois e justificativa quando aplicável.

### Infraestrutura
- frontend React/TypeScript;
- backend FastAPI;
- PostgreSQL Neon;
- containers prontos para Cloud Run;
- nenhuma dependência de Vercel;
- nenhuma dependência de Codex para implementação.

## Fora desta sprint

Imóveis, captação, contratos, financeiro e CRM começam apenas depois que a fundação estiver validada.
