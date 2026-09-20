from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.monthly_cycle import build_monthly_closing_readiness, build_monthly_cycle, month_start
from app.domains.finance.monthly_closing_models import FinanceMonthlyClosure, FinanceMonthlyClosureEvent
from app.domains.finance.monthly_cycle_schemas import (
    MonthlyClosingReadiness,
    MonthlyClosureEventResponse,
    MonthlyClosureRequest,
    MonthlyClosureResponse,
    MonthlyCycleResponse,
    MonthlyReopenRequest,
)
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit


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



def _closure_response(db: Session, *, organization_id, competence: date) -> MonthlyClosureResponse:
    competence = month_start(competence)
    readiness = build_monthly_closing_readiness(db, organization_id=organization_id, competence=competence)
    closure = db.scalar(
        select(FinanceMonthlyClosure).where(
            FinanceMonthlyClosure.organization_id == organization_id,
            FinanceMonthlyClosure.competence == competence,
        )
    )
    events: list[MonthlyClosureEventResponse] = []
    if closure is not None:
        event_rows = db.scalars(
            select(FinanceMonthlyClosureEvent)
            .where(FinanceMonthlyClosureEvent.closure_id == closure.id)
            .order_by(FinanceMonthlyClosureEvent.created_at.desc())
            .limit(50)
        ).all()
        events = [
            MonthlyClosureEventResponse(
                id=item.id,
                action=item.action,
                reason=item.reason,
                actor_user_id=item.actor_user_id,
                created_at=item.created_at,
            )
            for item in event_rows
        ]
    return MonthlyClosureResponse(
        id=closure.id if closure else None,
        competence=competence,
        status=closure.status if closure else "open",
        closed_at=closure.closed_at if closure else None,
        reopened_at=closure.reopened_at if closure else None,
        closing_note=closure.closing_note if closure else None,
        reopen_reason=closure.reopen_reason if closure else None,
        readiness=readiness,
        events=events,
    )


def _audit(request: Request, db: Session, context: UserContext, *, action: str, entity_id: str, after: dict) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type="finance_monthly_closure",
        entity_id=entity_id,
        after_data=after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )


@router.get("/closure", response_model=MonthlyClosureResponse)
def get_monthly_closure(
    competence: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> MonthlyClosureResponse:
    return _closure_response(
        db,
        organization_id=context.user.organization_id,
        competence=(competence or date.today()).replace(day=1),
    )


@router.post("/closure/close", response_model=MonthlyClosureResponse)
def close_monthly_competence(
    payload: MonthlyClosureRequest,
    request: Request,
    competence: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.period.close")),
    db: Session = Depends(get_db),
) -> MonthlyClosureResponse:
    target = (competence or date.today()).replace(day=1)
    readiness = build_monthly_closing_readiness(db, organization_id=context.user.organization_id, competence=target)
    if not readiness.can_close:
        raise HTTPException(
            status_code=409,
            detail="A competência possui bloqueadores e não pode ser fechada: " + " | ".join(readiness.blockers),
        )
    closure = db.scalar(
        select(FinanceMonthlyClosure)
        .where(
            FinanceMonthlyClosure.organization_id == context.user.organization_id,
            FinanceMonthlyClosure.competence == target,
        )
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    if closure is None:
        closure = FinanceMonthlyClosure(
            organization_id=context.user.organization_id,
            competence=target,
            status="closed",
            readiness_snapshot=readiness.model_dump(mode="json"),
            closing_note=(payload.note or "").strip() or None,
            closed_by_user_id=context.user.id,
            closed_at=now,
        )
        db.add(closure)
        db.flush()
    elif closure.status == "closed":
        raise HTTPException(status_code=409, detail="Esta competência já está fechada.")
    else:
        closure.status = "closed"
        closure.readiness_snapshot = readiness.model_dump(mode="json")
        closure.closing_note = (payload.note or "").strip() or None
        closure.closed_by_user_id = context.user.id
        closure.closed_at = now
        closure.reopen_reason = None

    db.add(
        FinanceMonthlyClosureEvent(
            organization_id=context.user.organization_id,
            closure_id=closure.id,
            competence=target,
            action="closed",
            reason=(payload.note or "").strip() or None,
            readiness_snapshot=readiness.model_dump(mode="json"),
            actor_user_id=context.user.id,
        )
    )
    _audit(
        request,
        db,
        context,
        action="finance.monthly_closure.closed",
        entity_id=str(closure.id),
        after={"competence": target.isoformat(), "blocker_count": readiness.blocker_count},
    )
    db.commit()
    return _closure_response(db, organization_id=context.user.organization_id, competence=target)


@router.post("/closure/reopen", response_model=MonthlyClosureResponse)
def reopen_monthly_competence(
    payload: MonthlyReopenRequest,
    request: Request,
    competence: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.period.reopen")),
    db: Session = Depends(get_db),
) -> MonthlyClosureResponse:
    target = (competence or date.today()).replace(day=1)
    reason = payload.reason.strip()
    if len(reason) < 5:
        raise HTTPException(status_code=422, detail="Informe um motivo de reabertura com pelo menos 5 caracteres.")
    closure = db.scalar(
        select(FinanceMonthlyClosure)
        .where(
            FinanceMonthlyClosure.organization_id == context.user.organization_id,
            FinanceMonthlyClosure.competence == target,
        )
        .with_for_update()
    )
    if closure is None or closure.status != "closed":
        raise HTTPException(status_code=409, detail="Esta competência não está fechada.")
    now = datetime.now(timezone.utc)
    closure.status = "open"
    closure.reopen_reason = reason
    closure.reopened_by_user_id = context.user.id
    closure.reopened_at = now
    snapshot = build_monthly_closing_readiness(
        db, organization_id=context.user.organization_id, competence=target
    ).model_dump(mode="json")
    db.add(
        FinanceMonthlyClosureEvent(
            organization_id=context.user.organization_id,
            closure_id=closure.id,
            competence=target,
            action="reopened",
            reason=reason,
            readiness_snapshot=snapshot,
            actor_user_id=context.user.id,
        )
    )
    _audit(
        request,
        db,
        context,
        action="finance.monthly_closure.reopened",
        entity_id=str(closure.id),
        after={"competence": target.isoformat(), "reason": reason},
    )
    db.commit()
    return _closure_response(db, organization_id=context.user.organization_id, competence=target)
