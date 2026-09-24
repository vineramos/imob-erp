from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.routes.tenant_portal import PortalIdentity, _tenant_leases, require_portal_identity
from app.core.database import get_db
from app.domains.finance.advanced_pdf import build_annual_income_pdf
from app.domains.foundation.models import Organization
from app.domains.reports.service import annual_income_report

router = APIRouter(prefix="/tenant-portal", tags=["tenant-portal"])


@router.get("/reports/{year}/payments.pdf")
def tenant_annual_payments_pdf(
    year: int,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> Response:
    if year < 2000 or year > 2200:
        raise HTTPException(status_code=422, detail="Ano inválido.")
    if not _tenant_leases(db, identity):
        raise HTTPException(status_code=404, detail="Nenhuma locação encontrada neste portal.")
    try:
        report = annual_income_report(
            db,
            organization_id=identity.account.organization_id,
            year=year,
            party_type="tenant",
            person_id=identity.person.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    organization = db.get(Organization, identity.account.organization_id)
    payload = build_annual_income_pdf(
        report,
        organization.display_name if organization else "Imobiliária",
    )
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="comprovante-anual-pagamentos-{year}.pdf"'},
    )
