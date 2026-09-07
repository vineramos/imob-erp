from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.routes.finance import _owner_statement
from app.api.routes.owner_portal import _require_owner
from app.api.routes.tenant_portal import PortalIdentity, require_portal_identity
from app.core.database import get_db
from app.domains.finance.advanced_pdf import build_annual_income_pdf
from app.domains.finance.advanced_schemas import AnnualIncomeLine, AnnualIncomeReport
from app.domains.finance.owner_portal_service import money, owner_annual_income_values
from app.domains.finance.pdf import build_owner_statement_pdf
from app.domains.foundation.models import Organization

router = APIRouter(prefix="/owner-portal", tags=["owner-portal"])
ZERO = Decimal("0.00")


def _owned_property_ids(db: Session, identity: PortalIdentity) -> set[UUID]:
    return {property_item.id for property_item, _ in _require_owner(db, identity)}


@router.get("/statements/{competence}/pdf")
def owner_statement_pdf(
    competence: date,
    property_id: UUID | None = Query(default=None),
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> Response:
    owned_property_ids = _owned_property_ids(db, identity)
    if property_id is not None and property_id not in owned_property_ids:
        raise HTTPException(status_code=404, detail="Imóvel não encontrado neste portal.")

    statement = _owner_statement(
        db,
        identity.account.organization_id,
        identity.person.id,
        competence,
        property_id,
    )
    organization = db.get(Organization, identity.account.organization_id)
    payload = build_owner_statement_pdf(
        statement=statement,
        organization_name=organization.display_name if organization else "Imobiliária",
    )
    filename = f"prestacao-contas-{statement.competence:%Y-%m}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/reports/{year}/income.pdf")
def owner_annual_income_pdf(
    year: int,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> Response:
    if year < 2000 or year > 2200:
        raise HTTPException(status_code=422, detail="Ano inválido.")
    _require_owner(db, identity)
    try:
        person, raw_lines, allocation = owner_annual_income_values(
            db,
            organization_id=identity.account.organization_id,
            year=year,
            person_id=identity.person.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    lines = [
        AnnualIncomeLine(**{
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in raw.items()
        })
        for raw in raw_lines
    ]
    report = AnnualIncomeReport(
        year=year,
        party_type="owner",
        person_id=person.id,
        person_name=person.name,
        allocation_method=allocation,
        total_rent=float(money(sum((money(entry["rent_amount"]) for entry in raw_lines), ZERO))),
        total_additional_charges=float(money(sum((money(entry["additional_charges"]) for entry in raw_lines), ZERO))),
        total_paid=float(money(sum((money(entry["total_amount"]) for entry in raw_lines), ZERO))),
        total_administration_fee=float(money(sum((money(entry["administration_fee"]) for entry in raw_lines), ZERO))),
        total_owner_net=float(money(sum((money(entry["owner_net_amount"]) for entry in raw_lines), ZERO))),
        lines=lines,
    )
    organization = db.get(Organization, identity.account.organization_id)
    payload = build_annual_income_pdf(
        report,
        organization.display_name if organization else "Imobiliária",
    )
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="informe-rendimentos-{year}.pdf"'},
    )
