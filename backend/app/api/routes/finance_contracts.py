from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.service import (
    administration_terms,
    configured_monthly_charge_rules,
    money,
    suggested_monthly_charge_rules,
)
from app.domains.foundation.access import UserContext, require_permission
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Property

router = APIRouter(prefix="/finance", tags=["finance"])


@router.get("/lease-contracts/{lease_id}/monthly-charges")
def lease_monthly_charges(
    lease_id: UUID,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> dict:
    lease = db.scalar(
        select(LeaseContract).where(
            LeaseContract.id == lease_id,
            LeaseContract.organization_id == context.user.organization_id,
        )
    )
    if lease is None:
        raise HTTPException(status_code=404, detail="Contrato de locação não encontrado.")
    property_item = db.scalar(
        select(Property).where(
            Property.id == lease.property_id,
            Property.organization_id == context.user.organization_id,
        )
    )
    if property_item is None:
        raise HTTPException(status_code=404, detail="Imóvel da locação não encontrado.")

    configured = configured_monthly_charge_rules(lease)
    rules = configured or suggested_monthly_charge_rules(
        property_item,
        administration_terms(db, context.user.organization_id, property_item.id),
    )
    tenant_monthly_extras = sum(
        (
            money(rule.get("amount"))
            for rule in rules
            if bool(rule.get("active", True))
            and rule.get("payer", "tenant") == "tenant"
            and rule.get("include_in_invoice", True) is not False
            and str(rule.get("frequency") or "monthly") == "monthly"
        ),
        Decimal("0.00"),
    )
    scheduled_extras = [
        rule for rule in rules
        if bool(rule.get("active", True))
        and rule.get("payer", "tenant") == "tenant"
        and rule.get("include_in_invoice", True) is not False
        and str(rule.get("frequency") or "monthly") != "monthly"
    ]
    return {
        "lease_contract_id": str(lease.id),
        "lease_code": f"LOC-{lease.internal_number:06d}",
        "configured": bool(configured),
        "monthly_charges": rules,
        "tenant_monthly_total": str(money(lease.rent_amount) + tenant_monthly_extras),
        "scheduled_extras": scheduled_extras,
    }
