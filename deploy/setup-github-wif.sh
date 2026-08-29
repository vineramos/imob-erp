#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="imob-erp-vine-260829"
PROJECT_NUMBER="472913336861"
REGION="us-east1"
SERVICE="imob-erp"
ARTIFACT_REPOSITORY="cloud-run-source-deploy"
RUNTIME_SERVICE_ACCOUNT="imob-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOYER_NAME="imob-deployer"
DEPLOYER_SERVICE_ACCOUNT="${DEPLOYER_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
POOL_ID="github-actions"
PROVIDER_ID="github"
GITHUB_REPOSITORY="vineramos/imob-erp"
GITHUB_BRANCH="sprint-1-foundation"

retry_iam() {
  local attempt=1
  local max_attempts=12
  local delay_seconds=5

  while true; do
    if "$@"; then
      return 0
    fi

    if (( attempt >= max_attempts )); then
      echo "❌ O Google Cloud não concluiu a propagação do IAM após ${max_attempts} tentativas." >&2
      return 1
    fi

    echo "⏳ IAM ainda propagando (${attempt}/${max_attempts}). Tentando novamente em ${delay_seconds}s..."
    sleep "$delay_seconds"
    attempt=$((attempt + 1))
  done
}

printf '\n==> Configurando deploy automático do Imob ERP\n'
gcloud config set project "$PROJECT_ID" >/dev/null

gcloud services enable \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  artifactregistry.googleapis.com \
  run.googleapis.com >/dev/null

if ! gcloud artifacts repositories describe "$ARTIFACT_REPOSITORY" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$ARTIFACT_REPOSITORY" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Imob ERP deployment images" >/dev/null
fi

if ! gcloud iam service-accounts describe "$DEPLOYER_SERVICE_ACCOUNT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$DEPLOYER_NAME" \
    --display-name="Imob ERP GitHub deployer" >/dev/null
fi

# Service accounts are eventually consistent across Google IAM backends.
# Wait until the account is visible before attempting project policy bindings.
for attempt in {1..12}; do
  if gcloud iam service-accounts describe "$DEPLOYER_SERVICE_ACCOUNT" >/dev/null 2>&1; then
    break
  fi
  if (( attempt == 12 )); then
    echo "❌ A service account de deploy não ficou disponível a tempo." >&2
    exit 1
  fi
  echo "⏳ Aguardando propagação da service account (${attempt}/12)..."
  sleep 5
done

if ! gcloud iam workload-identity-pools describe "$POOL_ID" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL_ID" \
    --location=global \
    --display-name="GitHub Actions" >/dev/null
fi

if ! gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --workload-identity-pool="$POOL_ID" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --workload-identity-pool="$POOL_ID" \
    --location=global \
    --display-name="GitHub" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_REPOSITORY}'" >/dev/null
fi

for ROLE in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/serviceusage.serviceUsageConsumer; do
  retry_iam gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOYER_SERVICE_ACCOUNT}" \
    --role="$ROLE" \
    --condition=None >/dev/null
 done

retry_iam gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SERVICE_ACCOUNT" \
  --member="serviceAccount:${DEPLOYER_SERVICE_ACCOUNT}" \
  --role="roles/iam.serviceAccountUser" >/dev/null

PRINCIPAL_SET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPOSITORY}"
retry_iam gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SERVICE_ACCOUNT" \
  --member="$PRINCIPAL_SET" \
  --role="roles/iam.workloadIdentityUser" >/dev/null

PROVIDER_RESOURCE="$(gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --workload-identity-pool="$POOL_ID" \
  --location=global \
  --format='value(name)')"

command -v gh >/dev/null || { echo 'GitHub CLI (gh) não encontrado.' >&2; exit 1; }
gh auth status >/dev/null

gh variable set GCP_PROJECT_ID --body "$PROJECT_ID" --repo "$GITHUB_REPOSITORY"
gh variable set GCP_REGION --body "$REGION" --repo "$GITHUB_REPOSITORY"
gh variable set GCP_SERVICE --body "$SERVICE" --repo "$GITHUB_REPOSITORY"
gh variable set GCP_ARTIFACT_REPOSITORY --body "$ARTIFACT_REPOSITORY" --repo "$GITHUB_REPOSITORY"
gh variable set GCP_RUNTIME_SERVICE_ACCOUNT --body "$RUNTIME_SERVICE_ACCOUNT" --repo "$GITHUB_REPOSITORY"
gh variable set GCP_WIF_PROVIDER --body "$PROVIDER_RESOURCE" --repo "$GITHUB_REPOSITORY"
gh variable set GCP_WIF_SERVICE_ACCOUNT --body "$DEPLOYER_SERVICE_ACCOUNT" --repo "$GITHUB_REPOSITORY"
gh variable set GCP_WIF_READY --body "true" --repo "$GITHUB_REPOSITORY"

printf '\n✅ Federação GitHub → Google Cloud configurada.\n'
printf 'A partir de agora, o deploy pode ser executado pelo GitHub Actions sem chave permanente.\n'
printf 'Disparando a primeira execução automática...\n\n'

gh workflow run ci.yml --ref "$GITHUB_BRANCH" --repo "$GITHUB_REPOSITORY"

echo '✅ Workflow solicitado. O GitHub fará build, validação e deploy.'
