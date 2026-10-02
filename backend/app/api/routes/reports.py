import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.advanced_pdf import build_annual_income_pdf
from app.domains.finance.advanced_schemas import AnnualIncomeReport
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.models import Organization
from app.domains.reports.schemas import DimobValidationResponse
from app.domains.reports.service import annual_income_csv, annual_income_report, dimob_validation

router = APIRouter(prefix="/reports", tags=["reports"])


def _annual(db: Session, context: UserContext, *, year: int, party_type: str, person_id: UUID) -> AnnualIncomeReport:
    try:
        return annual_income_report(
            db,
            organization_id=context.user.organization_id,
            year=year,
            party_type=party_type,
            person_id=person_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    return normalized.strip("-") or "relatorio"


@router.get("/annual-income", response_model=AnnualIncomeReport)
def annual_income(
    year: int = Query(..., ge=2000, le=2200),
    party_type: str = Query(default="tenant", pattern="^(tenant|owner)$"),
    person_id: UUID = Query(...),
    context: UserContext = Depends(require_permission("reports.view")),
    db: Session = Depends(get_db),
) -> AnnualIncomeReport:
    return _annual(db, context, year=year, party_type=party_type, person_id=person_id)


@router.get("/annual-income.pdf")
def annual_income_pdf(
    year: int = Query(..., ge=2000, le=2200),
    party_type: str = Query(default="tenant", pattern="^(tenant|owner)$"),
    person_id: UUID = Query(...),
    context: UserContext = Depends(require_permission("reports.export")),
    db: Session = Depends(get_db),
) -> Response:
    report = _annual(db, context, year=year, party_type=party_type, person_id=person_id)
    organization = db.get(Organization, context.user.organization_id)
    payload = build_annual_income_pdf(report, organization.display_name if organization else "Imobiliária")
    filename = f"informe-{party_type}-{_safe_filename(report.person_name)}-{year}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/annual-income.csv")
def annual_income_csv_export(
    year: int = Query(..., ge=2000, le=2200),
    party_type: str = Query(default="tenant", pattern="^(tenant|owner)$"),
    person_id: UUID = Query(...),
    context: UserContext = Depends(require_permission("reports.export")),
    db: Session = Depends(get_db),
) -> Response:
    report = _annual(db, context, year=year, party_type=party_type, person_id=person_id)
    filename = f"informe-{party_type}-{_safe_filename(report.person_name)}-{year}.csv"
    return Response(
        content=annual_income_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/dimob/validation", response_model=DimobValidationResponse)
def validate_dimob(
    year: int = Query(..., ge=2000, le=2200),
    context: UserContext = Depends(require_permission("reports.view")),
    db: Session = Depends(get_db),
) -> DimobValidationResponse:
    return dimob_validation(db, organization_id=context.user.organization_id, year=year)
