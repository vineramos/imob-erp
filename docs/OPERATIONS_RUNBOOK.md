# Runbook operacional — Imob ERP

Este documento descreve como validar, publicar, diagnosticar e recuperar o Imob ERP no ambiente atual.

## Pipeline oficial

A branch `sprint-1-foundation` dispara o workflow `.github/workflows/ci.yml`.

A promoção só avança quando, nesta ordem:

1. o frontend passa por typecheck e build;
2. o backend instala dependências, executa `pip check`, compila aplicação e testes, valida mappers e Alembic e executa a suíte Pytest;
3. a imagem Docker completa é construída;
4. a imagem é enviada ao Artifact Registry;
5. o Cloud Run recebe a imagem pelo SHA exato do commit;
6. o serviço responde aos smoke tests;
7. o SHA exposto por `/api/health` e `/api/health/ready` precisa ser o mesmo SHA do workflow.

O deploy usa Workload Identity Federation. Não deve existir chave JSON estática do Google Cloud no repositório.

## Health e readiness

### Liveness

`GET /api/health`

Confirma que o processo HTTP está atendendo e informa o release efetivo:

```json
{
  "status": "ok",
  "service": "imob-erp-api",
  "release": "<git-sha>"
}
```

### Readiness técnica

`GET /api/health/ready`

Além do processo, executa `SELECT 1` no PostgreSQL/Neon. Responde HTTP 503 quando o banco está indisponível.

### Readiness operacional

`GET /api/integrations/readiness`

Requer `settings.view` e consolida a configuração mínima de:

- Neon Auth;
- storage persistente de documentos;
- provider bancário selecionado;
- assinatura eletrônica e HMAC do webhook;
- e-mail transacional.

O endpoint nunca retorna tokens, senhas, chaves privadas ou client secrets.

## Clicksign

Variáveis:

- `CLICKSIGN_ENVIRONMENT=sandbox|production`
- `CLICKSIGN_ACCESS_TOKEN`
- `CLICKSIGN_WEBHOOK_SECRET`

O Access Token e o HMAC Secret devem ficar no Secret Manager/ambiente seguro do Cloud Run.

O webhook do ERP é `POST /api/webhooks/clicksign`. Eventos sem HMAC válido retornam 401. Eventos repetidos são aceitos de forma idempotente sem duplicar processamento.

A assinatura somente é considerada finalizada depois que o PDF assinado é recuperado e arquivado no storage persistente.

## Banco Inter

Variáveis:

- `INTER_ENVIRONMENT=sandbox|production`
- `INTER_CLIENT_ID`
- `INTER_CLIENT_SECRET`
- `INTER_CERT_PATH`
- `INTER_KEY_PATH`
- `INTER_ACCOUNT_NUMBER`
- `INTER_WEBHOOK_SECRET`

O provider usa OAuth2 + mTLS. O ERP continua operacional com provider manual quando o Inter não estiver configurado.

Dinheiro de terceiros e caixa operacional permanecem separados por `fund_scope`.

## Storage de documentos

Quando `DOCUMENT_STORAGE_BUCKET` estiver preenchido, o ERP usa Google Cloud Storage com a service account do runtime.

Quando estiver vazio, o sistema usa o fallback persistente no PostgreSQL/Neon.

Nunca armazenar chave JSON de service account em variável de aplicação.

## Rollback

1. identificar o último SHA saudável no GitHub Actions;
2. localizar a imagem correspondente no Artifact Registry;
3. promover essa imagem ao serviço Cloud Run;
4. confirmar `/api/health`, `/api/health/ready` e o SHA do release;
5. registrar a causa da regressão antes de retomar novos deploys.

As migrations devem ser projetadas para compatibilidade progressiva. Rollback de imagem não implica rollback automático de schema.

## Diagnóstico rápido

Quando o deploy falhar, investigar na ordem:

1. frontend/typecheck;
2. compileall e `pip check`;
3. Alembic;
4. Pytest;
5. build Docker;
6. autenticação WIF;
7. push no Artifact Registry;
8. criação da revisão Cloud Run;
9. health/readiness;
10. Neon Auth;
11. integrações opcionais.

Se Clicksign ou Banco Inter estiverem desconfigurados, o sistema pode permanecer publicado; a tela Configurações → Integrações sinaliza a pendência operacional sem exibir segredos.
