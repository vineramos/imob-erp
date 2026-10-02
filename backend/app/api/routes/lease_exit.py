from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.lease_lifecycle.exit_schemas import LeaseExitAdjustmentCreate, LeaseExitWorkspaceResponse
from app.domains.lease_lifecycle.exit_service import (
    cancel_adjustment,
    create_adjustment,
    exit_workspace,
    list_exit_workspaces,
    require_active_termination,
)

router = APIRouter(tags=["lease-exit"])


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    *,
    action: str,
    entity_id: str | None,
    after: dict | None = None,
    reason: str | None = None,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action=action,
        module="contracts",
        entity_type="lease_exit_adjustment",
        entity_id=entity_id,
        after_data=after,
        reason=reason,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )


@router.get("/lease-lifecycle/terminations", response_model=list[LeaseExitWorkspaceResponse])
def termination_workspaces(
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> list[LeaseExitWorkspaceResponse]:
    return list_exit_workspaces(db, organization_id=context.user.organization_id)


@router.get(
    "/lease-contracts/{lease_contract_id}/lifecycle/exit-workspace",
    response_model=LeaseExitWorkspaceResponse,
)
def lease_exit_workspace(
    lease_contract_id: UUID,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> LeaseExitWorkspaceResponse:
    case, _ = require_active_termination(
        db,
        organization_id=context.user.organization_id,
        lease_contract_id=lease_contract_id,
    )
    return exit_workspace(db, case)


@router.post(
    "/lease-contracts/{lease_contract_id}/lifecycle/exit-adjustments",
    response_model=LeaseExitWorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_exit_adjustment(
    lease_contract_id: UUID,
    payload: LeaseExitAdjustmentCreate,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseExitWorkspaceResponse:
    item = create_adjustment(
        db,
        organization_id=context.user.organization_id,
        lease_contract_id=lease_contract_id,
        payload=payload,
        user_id=context.user.id,
    )
    _audit(
        db,
        request,
        context,
        action="contracts.lease.exit_adjustment_registered",
        entity_id=str(item.id),
        after={
            "lease_contract_id": str(lease_contract_id),
            "kind": item.kind,
            "beneficiary": item.beneficiary,
            "amount": str(item.amount),
            "due_date": item.due_date.isoformat(),
            "financial_title_id": str(item.financial_title_id) if item.financial_title_id else None,
            "source_context": dict(item.source_context or {}),
        },
        reason=item.notes,
    )
    db.commit()
    case, _ = require_active_termination(
        db,
        organization_id=context.user.organization_id,
        lease_contract_id=lease_contract_id,
    )
    return exit_workspace(db, case)


@router.post(
    "/lease-contracts/{lease_contract_id}/lifecycle/exit-adjustments/{adjustment_id}/cancel",
    response_model=LeaseExitWorkspaceResponse,
)
def cancel_exit_adjustment(
    lease_contract_id: UUID,
    adjustment_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseExitWorkspaceResponse:
    item = cancel_adjustment(
        db,
        organization_id=context.user.organization_id,
        lease_contract_id=lease_contract_id,
        adjustment_id=adjustment_id,
        user_id=context.user.id,
    )
    _audit(
        db,
        request,
        context,
        action="contracts.lease.exit_adjustment_cancelled",
        entity_id=str(item.id),
        after={
            "lease_contract_id": str(lease_contract_id),
            "status": item.status,
            "financial_title_id": str(item.financial_title_id) if item.financial_title_id else None,
        },
    )
    db.commit()
    case, _ = require_active_termination(
        db,
        organization_id=context.user.organization_id,
        lease_contract_id=lease_contract_id,
    )
    return exit_workspace(db, case)
