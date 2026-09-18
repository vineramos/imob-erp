from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.database import engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "imob-erp-api"}


@router.get("/ready")
def readiness_check() -> dict[str, str]:
    """Readiness técnica usada pelo deploy e pelo balanceador.

    Não testa providers externos: readiness deve responder apenas se o processo
    consegue atender requisições e acessar sua dependência crítica, o banco.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Banco de dados não configurado.")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível.") from exc
    return {"status": "ready", "service": "imob-erp-api", "database": "ok"}
