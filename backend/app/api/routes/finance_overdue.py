from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.routes.finance_core import _maintenance_item, _manual_item, _rent_item, _repasse_item
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.core_schemas import FinanceCoreItem
from app.domains.finance.models import MaintenanceFinancialEntry, OwnerRepasse, RentCharge
from app.domains.foundation.access import UserContext, require_permission

router = APIRouter(prefix="/finance/core", tags=["finance-core"])


@router.get("/overdue", response_model=list[FinanceCoreItem])
def overdue_items(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[FinanceCoreItem]:
    """Retorna todos os títulos vencidos da organização, sem corte por competência."""
    organization_id: UUID = context.user.organization_id
    today = date.today()
    items: list[FinanceCoreItem] = []

    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.status.not_in(("paid", "cancelled")),
            RentCharge.due_date < today,
        )
    ).all()
    items.extend(_rent_item(item) for item in charges)

    repasses = db.scalars(
        select(OwnerRepasse).where(
            OwnerRepasse.organization_id == organization_id,
            OwnerRepasse.status == "pending",
            OwnerRepasse.amount > 0,
            OwnerRepasse.due_date < today,
        )
    ).all()
    if repasses:
        charge_map = {
            item.id: item
            for item in db.scalars(
                select(RentCharge).where(RentCharge.id.in_([repasse.charge_id for repasse in repasses]))
            ).all()
        }
        items.extend(
            _repasse_item(item, charge_map[item.charge_id])
            for item in repasses
            if item.charge_id in charge_map
        )

    maintenance = db.scalars(
        select(MaintenanceFinancialEntry).where(
            MaintenanceFinancialEntry.organization_id == organization_id,
            MaintenanceFinancialEntry.status.in_(("pending", "partial")),
        )
    ).all()
    items.extend(
        _maintenance_item(item)
        for item in maintenance
        if (item.due_date or item.created_at.date()) < today
    )

    manual = db.scalars(
        select(FinancialTitle).where(
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.status.in_(("pending", "partial")),
            FinancialTitle.due_date < today,
        )
    ).all()
    items.extend(_manual_item(item) for item in manual)

    return sorted(
        [item for item in items if item.overdue and item.remaining_amount > 0],
        key=lambda entry: (entry.due_date or entry.competence, entry.code),
    )
