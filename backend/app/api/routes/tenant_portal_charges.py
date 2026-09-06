from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.tenant_portal import PortalIdentity, _tenant_leases, require_portal_identity
from app.core.database import get_db
from app.domains.finance.models import RentCharge
from app.domains.finance.service import configured_monthly_charge_rules

router = APIRouter(prefix="/tenant-portal", tags=["tenant-portal"])


def _safe_rule(row: dict) -> dict:
    return {
        "key": str(row.get("key") or "other"),
        "kind": str(row.get("kind") or "other"),
        "label": str(row.get("label") or "Encargo"),
        "amount": float(row.get("amount") or 0),
        "active": bool(row.get("active", True)),
        "payer": str(row.get("payer") or "tenant"),
        "beneficiary": str(row.get("beneficiary") or "third_party"),
        "beneficiary_name": str(row.get("beneficiary_name") or "").strip() or None,
        "frequency": str(row.get("frequency") or "monthly"),
        "include_in_invoice": row.get("include_in_invoice", True) is not False,
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
    }


def _safe_item(row: dict) -> dict:
    return {
        "key": str(row.get("key") or "other"),
        "kind": str(row.get("kind") or "other"),
        "label": str(row.get("label") or "Encargo"),
        "amount": float(row.get("amount") or 0),
        "frequency": str(row.get("frequency") or "monthly"),
    }


@router.get("/charge-composition")
def charge_composition(
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> dict:
    leases = _tenant_leases(db, identity)
    lease_ids = [item.id for item in leases]
    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == identity.account.organization_id,
            RentCharge.lease_contract_id.in_(lease_ids),
        )
    ).all() if lease_ids else []
    return {
        "leases": {
            str(lease.id): [
                _safe_rule(row)
                for row in configured_monthly_charge_rules(lease)
                if row.get("payer", "tenant") == "tenant"
            ]
            for lease in leases
        },
        "charges": {
            str(charge.id): [_safe_item(row) for row in list(charge.charge_items or [])]
            for charge in charges
        },
    }
