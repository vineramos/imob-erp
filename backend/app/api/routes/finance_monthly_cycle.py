from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.monthly_cycle import build_monthly_closing_readiness, build_monthly_cycle
from app.domains.finance.monthly_cycle_schemas import MonthlyClosingReadiness, MonthlyCycleResponse
from app.domains.foundation.access import UserContext, require_permission


router = APIRouter(prefix="/finance/monthly-cycle", tags=["finance-monthly-cycle"])


@router.get("", response_model=MonthlyCycleResponse)
def monthly_cycle(
    competence: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> MonthlyCycleResponse:
    return build_monthly_cycle(
        db,
        organization_id=context.user.organization_id,
        competence=(competence or date.today()).replace(day=1),
    )



@router.get("/closing-readiness", response_model=MonthlyClosingReadiness)
def monthly_closing_readiness(
    competence: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> MonthlyClosingReadiness:
    return build_monthly_closing_readiness(
        db,
        organization_id=context.user.organization_id,
        competence=(competence or date.today()).replace(day=1),
    )
