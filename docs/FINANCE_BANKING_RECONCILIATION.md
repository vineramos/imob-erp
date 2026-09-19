# Conciliação bancária multibanco

A camada bancária do Imob mantém a regra de negócio independente do banco. Contas sem integração direta usam o provider `manual` com CSV, OFX e movimentos manuais. Providers com API devem implementar o mesmo contrato de capacidades sem duplicar regras de liquidação, repasse ou conciliação.

## Matching determinístico

A ordem de evidência é:

1. identificadores bancários/provider;
2. código interno do título (`COB-...`, `FIN-...`, `MFIN-...`, `REP-...`);
3. referência/txid/FITID;
4. valor, data e contraparte como sinais auxiliares.

Identificador determinístico recebe peso superior às heurísticas de valor/data.

## Diferenças de valor

Cada candidato informa:

- saldo restante do título;
- saldo restante do movimento bancário;
- valor sugerido para alocação;
- diferença entre banco e título;
- classificação da diferença;
- se a liquidação é compatível com as regras atuais do título.

Quando o crédito bancário é maior que o título, o Imob pode liquidar o título pelo valor devido e manter o residual do movimento bancário aberto para classificação separada. O residual nunca é absorvido silenciosamente.

Cobranças de aluguel e repasses ao proprietário continuam exigindo liquidação integral do saldo do título. A interface bloqueia a ação quando o saldo bancário é insuficiente.

## Fila de exceções

A fila agora é persistente em `bank_reconciliation_exceptions`.

Classificações rotineiras:

- `identifier_detected`: identificador determinístico encontrado;
- `strong_candidate`: candidato forte, mas sem identificador determinístico.

Classificações de exceção real:

- `ambiguous_identifier`: a referência aponta para mais de um título;
- `review_required`: existem candidatos, mas a evidência não é suficiente;
- `no_candidate`: não há título compatível.

Por padrão, `GET /api/finance/banking/exceptions` mostra apenas exceções reais. Pendências rotineiras continuam disponíveis na fila geral de conciliação e podem ser incluídas com `include_routine=true`.

Uma exceção pode ser ignorada operacionalmente e reaberta depois. Se a classificação mudar, uma exceção ignorada volta automaticamente para revisão para não esconder nova evidência. A conciliação integral resolve a exceção vinculada.

## Auditoria

Ignorar/reabrir uma exceção e concluir uma conciliação permanecem sujeitos às permissões financeiras e geram eventos de auditoria. Exceções ignoradas não apagam o movimento bancário nem o título; apenas retiram a pendência da fila de exceções.

## Segurança do repositório público

O workflow `public-safety` faz checkout com histórico completo e inspeciona blobs Git alcançáveis em busca de:

- arquivos de chave/certificado;
- arquivos de credenciais/service account;
- assinaturas comuns de private keys;
- padrões de tokens GitHub/Google/AWS/Stripe.

A verificação do histórico é deliberada: apagar um segredo em um commit posterior não o remove de um repositório público.
