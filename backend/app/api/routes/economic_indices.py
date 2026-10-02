from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.portfolio.economic_indices import HISTORY_FLOOR, INDEX_DEFINITIONS, sync_index
from app.domains.portfolio.models import EconomicIndexValue
from app.domains.portfolio.schemas import EconomicIndexValueResponse

router = APIRouter(prefix="/economic-indices", tags=["economic-indices"])


@router.get("/{index_code}/history")
def economic_index_history(
    index_code: str,
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> dict:
    del context
    code = index_code.upper()
    definition = INDEX_DEFINITIONS.get(code)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Índice econômico não suportado.")

    earliest = db.scalar(
        select(func.min(EconomicIndexValue.competence)).where(EconomicIndexValue.index_code == code)
    )
    sync_message = None
    if earliest is None or earliest > HISTORY_FLOOR:
        result = sync_index(db, code)
        sync_message = result.get("message")

    rows = db.scalars(
        select(EconomicIndexValue)
        .where(
            EconomicIndexValue.index_code == code,
            EconomicIndexValue.competence >= HISTORY_FLOOR,
        )
        .order_by(EconomicIndexValue.competence.asc())
    ).all()
    latest_twelve = rows[-12:]
    average = None
    if latest_twelve:
        average = sum((Decimal(str(item.monthly_rate)) for item in latest_twelve), Decimal("0")) / Decimal(len(latest_twelve))

    values = [
        EconomicIndexValueResponse(
            index_code=item.index_code,
            sgs_code=item.sgs_code,
            competence=item.competence,
            monthly_rate=item.monthly_rate,
            source=item.source,
            fetched_at=item.fetched_at,
        )
        for item in rows
    ]
    return {
        "index_code": code,
        "name": definition.name,
        "from_competence": HISTORY_FLOOR,
        "average_12m": float(average) if average is not None else None,
        "months_in_average": len(latest_twelve),
        "sync_message": sync_message,
        "values": values,
    }
