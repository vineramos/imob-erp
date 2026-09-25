#!/bin/sh
set -eu

PROJECT_ID="${1:-}"
REGION="${REGION:-us-east1}"
SERVICE_NAME="${SERVICE_NAME:-imob-erp}"
SECRET_NAME="${SECRET_NAME:-imob-database-url}"
RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-imob-runtime}"

if [ -z "$PROJECT_ID" ]; then
  echo "Uso: ./deploy/cloudrun-deploy.sh <GOOGLE_CLOUD_PROJECT_ID>"
  exit 1
fi

if [ -z "${NEON_AUTH_URL:-}" ]; then
  echo "Defina NEON_AUTH_URL antes do deploy."
  exit 1
fi

if [ -z "${BOOTSTRAP_ADMIN_EMAIL:-}" ]; then
  echo "Defina BOOTSTRAP_ADMIN_EMAIL antes do deploy."
  exit 1
fi

gcloud config set project "$PROJECT_ID" >/dev/null

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com

if ! gcloud secrets describe "$SECRET_NAME" >/dev/null 2>&1; then
  echo "Secret '$SECRET_NAME' não existe. Crie-o com a DATABASE_URL antes do deploy."
  exit 1
fi

RUNTIME_SA="$RUNTIME_SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME_SA_NAME" \
    --display-name="Imob ERP runtime"
fi

gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/secretmanager.secretAccessor" >/dev/null

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --service-account "$RUNTIME_SA" \
  --allow-unauthenticated \
  --min 0 \
  --max 3 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 40 \
  --set-secrets="DATABASE_URL=$SECRET_NAME:latest" \
  --set-env-vars="APP_ENV=production,APP_NAME=Imob ERP Imobiliario,NEON_AUTH_URL=$NEON_AUTH_URL,BOOTSTRAP_ADMIN_EMAIL=$BOOTSTRAP_ADMIN_EMAIL,CORS_ORIGINS="

echo
echo "Deploy concluído."
echo "URL: $(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format='value(status.url)')"
