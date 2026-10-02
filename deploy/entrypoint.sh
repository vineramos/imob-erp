#!/bin/sh
set -eu

# Mantém o banco alinhado com a versão do container sem exigir Cloud Shell manual.
# Alembic é idempotente: instâncias posteriores apenas confirmam que o banco já está no head.
echo "==> Aplicando migrations do banco"
cd /app/backend
migration_ok=false
attempt=1
while [ "$attempt" -le 3 ]; do
  if alembic upgrade head; then
    migration_ok=true
    break
  fi
  echo "Aviso: tentativa ${attempt}/3 de migration falhou; tentando novamente em 5s."
  attempt=$((attempt + 1))
  sleep 5
done

if [ "$migration_ok" != "true" ]; then
  echo "Aviso: migrations não puderam ser confirmadas no startup; iniciando a aplicação e deixando o readiness validar o banco."
fi

if [ "${DOCUMENT_STORAGE_MIGRATE_ON_START:-false}" = "true" ]; then
  echo "==> Migrando documentos do PostgreSQL para o Cloud Storage"
  python -m app.integrations.document_storage_migration || echo "Aviso: migração adiada; arquivos originais foram preservados no banco."
fi
cd /app

python - <<'PY'
import json
import os
from pathlib import Path

frontend_dir = Path(os.environ.get("FRONTEND_DIST", "/app/frontend-dist"))
frontend_dir.mkdir(parents=True, exist_ok=True)
config = {
    "apiUrl": os.environ.get("IMOB_PUBLIC_API_URL", "/api"),
    "neonAuthUrl": os.environ.get("NEON_AUTH_URL", ""),
}
(frontend_dir / "runtime-config.js").write_text(
    "window.__IMOB_CONFIG__ = " + json.dumps(config, ensure_ascii=False) + ";\n",
    encoding="utf-8",
)
PY

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
