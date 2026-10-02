# Arquitetura do Imob ERP

## Objetivo

Manter o ERP modular, profissional e evolutivo, evitando dependências cruzadas entre módulos e integrações externas.

## Camadas

### Frontend
Responsável apenas por experiência do usuário, navegação, formulários, visualização e composição dos módulos.

### API / Aplicação
Orquestra casos de uso e valida permissões. Não deve conter detalhes específicos de fornecedores externos espalhados pelo sistema.

### Domínio
Concentra regras de negócio do ERP imobiliário: contratos, cobranças, repasses, comissões, vistorias, manutenção, alertas, etc.

### Integrações
Implementações externas devem ficar atrás de contratos internos, por exemplo:

- `BankProvider` → `InterBankProvider`
- `SignatureProvider` → `ClicksignProvider`
- futuro `PublicationProvider` → OLX/ZAP/Viva Real

### Dados
PostgreSQL no Neon como fonte transacional. Arquivos físicos ficam em object storage e o banco guarda metadados, vínculos, versões e auditoria.

## Regras transversais

- auditoria imutável para ações relevantes;
- permissões por ação, não apenas por tela;
- alçadas configuráveis apenas por Administradores;
- documentos finais assinados são imutáveis;
- nenhum pagamento é considerado concluído sem confirmação bancária;
- alertas críticos exigem ação válida antes de desaparecer;
- cada obrigação financeira precisa de origem rastreável;
- a conta corrente do proprietário é alimentada por fatos operacionais, não por edição direta de saldo.

## Organização futura sugerida do backend

```text
app/
├── api/
├── core/
├── domains/
│   ├── people/
│   ├── properties/
│   ├── contracts/
│   ├── finance/
│   ├── maintenance/
│   ├── inspections/
│   ├── documents/
│   └── agenda/
├── integrations/
│   ├── banking/
│   ├── signatures/
│   └── storage/
└── infrastructure/
```

A estrutura será expandida apenas quando cada módulo entrar em desenvolvimento, evitando pastas vazias e abstrações sem uso.
