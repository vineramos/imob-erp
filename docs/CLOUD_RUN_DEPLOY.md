# Deploy do Imob ERP no Google Cloud Run

O Imob é publicado como um único serviço Cloud Run. O projeto continua modular internamente (React + FastAPI), mas frontend e API usam o mesmo domínio em produção.

## Por que um único serviço

- reduz custo e quantidade de serviços;
- elimina CORS entre frontend e API;
- simplifica autenticação e observabilidade;
- mantém `min instances = 0`;
- permite separar os serviços futuramente sem alterar os domínios do negócio.

## Pré-requisitos

1. Projeto Google Cloud com faturamento habilitado.
2. `gcloud` autenticado.
3. Secret Manager com a `DATABASE_URL` da branch/ambiente correto.
4. Neon Auth ativo e sua Auth URL conhecida.
5. `BOOTSTRAP_ADMIN_EMAIL` definido somente no ambiente do Cloud Run.

## Segredos

A connection string do Neon nunca deve ser commitada no GitHub.

O deploy espera um secret chamado:

```text
imob-database-url
```

O runtime usa uma service account dedicada chamada `imob-runtime` com acesso somente a esse secret.

## Variáveis não secretas

Antes do deploy:

```bash
export NEON_AUTH_URL='https://.../neondb/auth'
export BOOTSTRAP_ADMIN_EMAIL='email-do-administrador'
```

## Deploy

Na raiz do repositório:

```bash
chmod +x deploy/cloudrun-deploy.sh
./deploy/cloudrun-deploy.sh <GOOGLE_CLOUD_PROJECT_ID>
```

O script habilita as APIs necessárias, prepara a service account dedicada, vincula o Secret Manager e publica o serviço `imob-erp` em `us-east1` por padrão.

## Configuração inicial do ERP

Enquanto `public.app_users` estiver vazio, a tela de login mostra `Configurar primeiro acesso`.

O primeiro cadastro somente se torna Administrador do ERP quando o e-mail autenticado coincidir com `BOOTSTRAP_ADMIN_EMAIL`. Depois que o primeiro `app_user` é criado, a opção de primeiro acesso desaparece automaticamente.

A criação de uma identidade no Neon Auth, isoladamente, não concede acesso ao ERP.

## Depois do primeiro deploy

1. Adicionar a URL do Cloud Run aos trusted domains do Neon Auth quando necessário.
2. Validar login e criação do primeiro Administrador.
3. Confirmar `/api/health`.
4. Validar leitura/escrita no Neon.
5. Conferir auditoria do bootstrap e das configurações.
6. Somente depois promover a Sprint 1 para `main`.
