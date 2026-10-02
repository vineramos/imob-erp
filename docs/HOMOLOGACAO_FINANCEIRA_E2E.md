# Homologação Financeira E2E

Este documento define o gate operacional do financeiro antes de considerar uma versão apta para uso diário.

A homologação não substitui os testes unitários. Ela valida jornadas completas atravessando módulos, persistência, conciliação, tesouraria e fechamento.

## Cenários homologados

| Cenário | Evidência automatizada | Resultado esperado |
| --- | --- | --- |
| Cobrança normal e pagamento em dia | `test_finance_monthly_cycle.py` | Cobrança paga, liquidação criada e composição financeira íntegra |
| Pagamento em atraso com juros/multa | `test_full_rental_lifecycle_e2e.py` | Valor nominal insuficiente é bloqueado; valor atualizado liquida cobrança e preserva juros/multa |
| Diferença residual bancária | `test_finance_closing_readiness.py` | Principal é liquidado e residual permanece separado até classificação |
| Duplicidade de extrato | `test_banking_operations.py` | Mesmo arquivo é rejeitado; movimentos repetidos não são duplicados |
| Exceção bancária e resolução manual | `test_bank_reconciliation_exceptions.py` e `test_finance_closing_readiness.py` | Exceção fica rastreável e pode ser vinculada ao título correto |
| Repasse ao proprietário | `test_finance_monthly_cycle.py` e `test_full_rental_lifecycle_e2e.py` | Direito líquido do proprietário é preservado e repasse termina pago |
| Obrigações de terceiros | `test_full_rental_lifecycle_e2e.py` | Obrigações permanecem segregadas do caixa operacional |
| Lote de pagamento | `test_finance_operational_homologation_e2e.py` | Draft → Ready → Approved → Executed, com título liquidado e movimento bancário criado |
| Conciliação do pagamento executado | `test_finance_operational_homologation_e2e.py` | Movimento criado pelo lote nasce reconciliado com a obrigação liquidada |
| Fechamento diário bancário | `test_finance_operational_homologation_e2e.py` | ERP e banco fecham sem diferença e sem movimentos pendentes |
| Fechamento mensal | `test_finance_operational_homologation_e2e.py` e `test_monthly_closure_lock.py` | Competência só fecha com checklist limpo |
| Trava retroativa | `test_finance_operational_homologation_e2e.py` e `test_monthly_closure_lock.py` | Alterações críticas são bloqueadas após fechamento até reabertura auditada |

## Jornada de tesouraria usada como prova operacional

A homologação cria uma conta operacional com saldo inicial controlado, cria uma obrigação manual, confirma que ela aparece entre os candidatos de pagamento, monta o lote, prepara, aprova e executa o lote.

A execução deve:

1. liquidar integralmente a obrigação;
2. gerar um movimento bancário de débito;
3. vincular esse movimento ao item do lote;
4. deixar a transação reconciliada;
5. reduzir o saldo da conta pelo valor exato;
6. permitir o fechamento diário somente quando o saldo bancário informado for igual ao saldo calculado pelo ERP.

O cenário de referência usa saldo inicial de R$ 5.000,00 e pagamento de R$ 750,00. O saldo final esperado é R$ 4.250,00.

## Jornada de fechamento mensal usada como prova operacional

A homologação usa uma competência anterior, fecha a conta bancária no último dia da competência com diferença zero e exige que o endpoint de prontidão retorne:

- zero contas sem fechamento;
- zero movimentos não conciliados;
- zero exceções bancárias abertas;
- zero repasses pendentes;
- zero lotes de pagamento em aberto;
- zero bloqueadores totais.

Somente nesse estado o fechamento mensal pode ser confirmado.

Depois do fechamento, o teste tenta inserir um movimento bancário retroativo na mesma competência. A operação deve ser rejeitada até que a competência seja formalmente reaberta.

## Critério de aprovação

Uma versão financeira está homologada somente quando:

- toda a suíte `pytest -q` passa;
- frontend typecheck/build passa;
- migration head é único e aplica em banco isolado;
- container Docker compila;
- `public-safety` passa;
- deploy completa;
- health/readiness confirma o SHA exato publicado.

Se qualquer item falhar, a versão fica como **PENDENTE DE HOMOLOGAÇÃO**.

## Limites desta homologação

Os testes usam PostgreSQL descartável e providers fake/manual. Eles provam regras e integração interna do ERP, mas não substituem homologação externa de credenciais reais de bancos, Clicksign ou outros fornecedores.

Banco Inter e demais providers específicos devem ter homologação própria quando suas credenciais de produção/sandbox forem ativadas.
