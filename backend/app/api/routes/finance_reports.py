from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.advanced_models import CommissionEntry
from app.domains.finance.advanced_pdf import build_annual_income_pdf, build_dre_pdf
from app.domains.finance.advanced_schemas import AnnualIncomeLine, AnnualIncomeReport, DreLine, DreReport, FinanceClosingControlResponse, FinanceReportOverview
from app.domains.finance.advanced_service import annual_income_values, dre_values, finance_closing_control, money, sync_commission_status
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import FinancialSettlement, MaintenanceFinancialEntry, OwnerRepasse, RentCharge
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.models import Organization

router = APIRouter(prefix="/reports")
legacy_router = APIRouter(prefix="/reports")
ZERO = Decimal("0.00")


def _commission_reclassification(
    db: Session,
    organization_id: UUID,
    start_date: date,
    end_date: date,
    regime: str,
) -> Decimal:
    """Reclassifica títulos de comissão que entram no motor de Tesouraria.

    Depois da aprovação, o título passa a usar source_type=`manual` apenas para
    reutilizar o fluxo consolidado de lotes/conciliação. A origem continua
    identificada pelo CommissionEntry e pelo source_snapshot. Aqui garantimos
    que a DRE continue reconhecendo o pagamento na linha Comissões, e não em
    Outras despesas operacionais.
    """
    entries = db.scalars(
        select(CommissionEntry).where(CommissionEntry.organization_id == organization_id)
    ).all()
    total = ZERO
    for entry in entries:
        sync_commission_status(db, entry)
        if not entry.financial_title_id:
            continue
        title = db.get(FinancialTitle, entry.financial_title_id)
        if title is None or title.status != "settled" or title.source_type == "commission":
            continue
        reference = entry.competence if regime == "competence" else (title.settled_at.date() if title.settled_at else None)
        if reference is None or reference < start_date or reference > end_date:
            continue
        total += money(title.settled_amount)
    return money(total)


def _dre(db: Session, organization_id: UUID, start_date: date, end_date: date, regime: str) -> DreReport:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="Período inválido.")
    values = dre_values(db, organization_id=organization_id, start_date=start_date, end_date=end_date, regime=regime)
    moved_commissions = _commission_reclassification(db, organization_id, start_date, end_date, regime)
    if moved_commissions > 0:
        values["commissions"] = money(values["commissions"] + moved_commissions)
        values["other_expense"] = money(max(ZERO, values["other_expense"] - moved_commissions))

    lines = [
        DreLine(key="administration", label="Taxas de administração", kind="revenue", amount=float(values["administration"])),
        DreLine(key="intermediation", label="Intermediação", kind="revenue", amount=float(values["intermediation"])),
        DreLine(key="maintenance_revenue", label="Receitas de manutenção", kind="revenue", amount=float(values["maintenance_revenue"])),
        DreLine(key="other_revenue", label="Outras receitas operacionais", kind="revenue", amount=float(values["other_revenue"])),
        DreLine(key="maintenance_cost", label="Custos de parceiros de manutenção", kind="expense", amount=float(values["maintenance_cost"])),
        DreLine(key="commissions", label="Comissões", kind="expense", amount=float(values["commissions"])),
        DreLine(key="other_expense", label="Outras despesas operacionais", kind="expense", amount=float(values["other_expense"])),
    ]
    revenue = money(sum((Decimal(str(line.amount)) for line in lines if line.kind == "revenue"), ZERO))
    expenses = money(sum((Decimal(str(line.amount)) for line in lines if line.kind == "expense"), ZERO))
    result = money(revenue - expenses)
    margin = float((result / revenue * Decimal("100")) if revenue else ZERO)
    return DreReport(
        start_date=start_date,
        end_date=end_date,
        regime=regime,
        total_revenue=float(revenue),
        total_expenses=float(expenses),
        result=float(result),
        margin_percent=round(margin, 2),
        lines=lines,
    )


def _annual(db: Session, organization_id: UUID, year: int, party_type: str, person_id: UUID) -> AnnualIncomeReport:
    try:
        person, raw_lines, allocation_method = annual_income_values(
            db,
            organization_id=organization_id,
            year=year,
            party_type=party_type,
            person_id=person_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    converted = []
    for raw in raw_lines:
        data = {key: float(value) if isinstance(value, Decimal) else value for key, value in raw.items()}
        converted.append(AnnualIncomeLine(**data))
    return AnnualIncomeReport(
        year=year,
        party_type=party_type,
        person_id=person.id,
        person_name=person.name,
        allocation_method=allocation_method,
        total_rent=float(money(sum((money(item["rent_amount"]) for item in raw_lines), ZERO))),
        total_additional_charges=float(money(sum((money(item["additional_charges"]) for item in raw_lines), ZERO))),
        total_paid=float(money(sum((money(item["total_amount"]) for item in raw_lines), ZERO))),
        total_administration_fee=float(money(sum((money(item["administration_fee"]) for item in raw_lines), ZERO))),
        total_owner_net=float(money(sum((money(item["owner_net_amount"]) for item in raw_lines), ZERO))),
        lines=converted,
    )


@router.get("/dre", response_model=DreReport)
def dre(
    start_date: date = Query(...),
    end_date: date = Query(...),
    regime: str = Query(default="cash", pattern="^(cash|competence)$"),
    context: UserContext = Depends(require_permission("reports.view")),
    db: Session = Depends(get_db),
) -> DreReport:
    return _dre(db, context.user.organization_id, start_date, end_date, regime)


@router.get("/dre.pdf")
def dre_pdf(
    start_date: date = Query(...),
    end_date: date = Query(...),
    regime: str = Query(default="cash", pattern="^(cash|competence)$"),
    context: UserContext = Depends(require_permission("reports.export")),
    db: Session = Depends(get_db),
) -> Response:
    report = _dre(db, context.user.organization_id, start_date, end_date, regime)
    organization = db.get(Organization, context.user.organization_id)
    payload = build_dre_pdf(report, organization.display_name if organization else "Imobiliária")
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="dre-{start_date:%Y-%m-%d}-{end_date:%Y-%m-%d}.pdf"'},
    )


@router.get("/overview", response_model=FinanceReportOverview)
def overview(
    start_date: date = Query(...),
    end_date: date = Query(...),
    context: UserContext = Depends(require_permission("reports.view")),
    db: Session = Depends(get_db),
) -> FinanceReportOverview:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="Período inválido.")
    paid_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    paid_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    charges = db.scalars(select(RentCharge).where(
        RentCharge.organization_id == context.user.organization_id,
        or_(
            and_(RentCharge.status == "paid", RentCharge.paid_at >= paid_start, RentCharge.paid_at < paid_end),
            and_(RentCharge.status.in_(("generated", "sent", "overdue")), RentCharge.due_date <= end_date),
        ),
    )).all()
    paid = [
        item for item in charges
        if item.status == "paid" and item.paid_at and start_date <= item.paid_at.date() <= end_date
    ]
    open_items = [
        item for item in charges
        if item.status in {"generated", "sent", "overdue"} and item.due_date <= end_date
    ]
    overdue = [item for item in open_items if item.status == "overdue"]
    settlements = {
        item.charge_id: item
        for item in db.scalars(
            select(FinancialSettlement).where(
                FinancialSettlement.organization_id == context.user.organization_id,
                FinancialSettlement.charge_id.in_([item.id for item in paid] or [UUID(int=0)]),
            )
        ).all()
    }
    repasses = db.scalars(
        select(OwnerRepasse).where(
            OwnerRepasse.organization_id == context.user.organization_id,
            OwnerRepasse.status == "paid",
            OwnerRepasse.paid_at >= paid_start,
            OwnerRepasse.paid_at < paid_end,
        )
    ).all()
    maintenance = db.scalars(
        select(MaintenanceFinancialEntry).where(
            MaintenanceFinancialEntry.organization_id == context.user.organization_id,
            MaintenanceFinancialEntry.settled_at >= paid_start,
            MaintenanceFinancialEntry.settled_at < paid_end,
        )
    ).all()
    commissions = db.scalars(
        select(CommissionEntry).where(CommissionEntry.organization_id == context.user.organization_id)
    ).all()
    for item in commissions:
        sync_commission_status(db, item)
    db.flush()
    return FinanceReportOverview(
        start_date=start_date,
        end_date=end_date,
        tenant_collections=float(money(sum((money(item.paid_amount) for item in paid), ZERO))),
        agency_revenue=float(money(sum((money(settlements[item.id].agency_fee_withheld) for item in paid if item.id in settlements), ZERO))),
        owner_repasses=float(money(sum((money(item.amount) for item in repasses if item.paid_at and start_date <= item.paid_at.date() <= end_date), ZERO))),
        maintenance_revenue=float(money(sum((money(item.settled_amount) for item in maintenance if item.direction == "receivable" and item.collection_method != "owner_repasse_deduction" and item.settled_at and start_date <= item.settled_at.date() <= end_date), ZERO))),
        maintenance_cost=float(money(sum((money(item.settled_amount) for item in maintenance if item.direction == "payable" and item.settled_at and start_date <= item.settled_at.date() <= end_date), ZERO))),
        commissions=float(money(sum((money(item.amount) for item in commissions if item.status == "paid" and item.paid_at and start_date <= item.paid_at.date() <= end_date), ZERO))),
        overdue_amount=float(money(sum((money(item.gross_amount) for item in overdue), ZERO))),
        overdue_count=len(overdue),
        paid_charges=len(paid),
        open_charges=len(open_items),
    )


@router.get("/closing-control", response_model=FinanceClosingControlResponse)
def closing_control(
    start_date: date = Query(...),
    end_date: date = Query(...),
    context: UserContext = Depends(require_permission("reports.view")),
    db: Session = Depends(get_db),
) -> FinanceClosingControlResponse:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="Período inválido.")
    result = finance_closing_control(
        db,
        organization_id=context.user.organization_id,
        start_date=start_date,
        end_date=end_date,
    )
    return FinanceClosingControlResponse(
        start_date=start_date,
        end_date=end_date,
        **result,
    )

@legacy_router.get("/annual-income", response_model=AnnualIncomeReport)
def legacy_annual_income(
    year: int = Query(..., ge=2000, le=2200),
    party_type: str = Query(default="tenant", pattern="^(tenant|owner)$"),
    person_id: UUID = Query(...),
    context: UserContext = Depends(require_permission("reports.view")),
    db: Session = Depends(get_db),
) -> AnnualIncomeReport:
    return _annual(db, context.user.organization_id, year, party_type, person_id)


@legacy_router.get("/annual-income.pdf")
def legacy_annual_income_pdf(
    year: int = Query(..., ge=2000, le=2200),
    party_type: str = Query(default="tenant", pattern="^(tenant|owner)$"),
    person_id: UUID = Query(...),
    context: UserContext = Depends(require_permission("reports.export")),
    db: Session = Depends(get_db),
) -> Response:
    report = _annual(db, context.user.organization_id, year, party_type, person_id)
    organization = db.get(Organization, context.user.organization_id)
    payload = build_annual_income_pdf(report, organization.display_name if organization else "Imobiliária")
    filename = f"informe-{party_type}-{report.person_name.lower().replace(' ', '-')}-{year}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
