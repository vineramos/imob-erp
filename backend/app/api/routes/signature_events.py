from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.contracts.models import AdministrationContract, SignatureWebhookEvent
from app.domains.contracts.schemas import SignatureEventResponse
from app.domains.foundation.access import UserContext, require_permission

router = APIRouter(tags=["contracts", "signature"])


@router.get(
    "/administration-contracts/{contract_id}/signature/events",
    response_model=list[SignatureEventResponse],
)
def administration_contract_signature_events(
    contract_id: UUID,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> list[SignatureEventResponse]:
    contract = db.scalar(
        select(AdministrationContract).where(
            AdministrationContract.id == contract_id,
            AdministrationContract.organization_id == context.user.organization_id,
        )
    )
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato de administração não encontrado.")

    events = db.scalars(
        select(SignatureWebhookEvent)
        .where(SignatureWebhookEvent.contract_id == contract.id)
        .order_by(SignatureWebhookEvent.received_at.desc())
        .limit(100)
    ).all()
    return [
        SignatureEventResponse(
            id=event.id,
            provider=event.provider,
            event_name=event.event_name,
            envelope_id=event.envelope_id,
            hmac_valid=event.hmac_valid,
            received_at=event.received_at,
        )
        for event in events
    ]
