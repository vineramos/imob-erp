#!/bin/sh
set -eu

# Mantém o banco alinhado com a versão do container sem exigir Cloud Shell manual.
# Alembic é idempotente: instâncias posteriores apenas confirmam que o banco já está no head.
echo "==> Aplicando migrations do banco"
cd /app/backend
alembic upgrade head
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
