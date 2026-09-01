from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.finance.models import FinancialSettlement, OwnerRepasse, RentCharge
from app.domains.finance.pdf import build_owner_statement_pdf
from app.domains.finance.schemas import (
    ChargeCancellationRequest,
    ChargeItem,
    ChargePaymentRequest,
    ChargeResponse,
    FinanceDashboardResponse,
    GenerateChargesRequest,
    GenerateChargesResponse,
    OwnerStatementLine,
    OwnerStatementResponse,
    PropertyFinanceSummary,
    RepassePaymentRequest,
    RepasseResponse,
    SettlementResponse,
)
from app.domains.finance.service import generate_charges, money, record_payment, refresh_overdue
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person

router = APIRouter(prefix="/finance", tags=["finance"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, *, action: str, entity_type: str, entity_id: str | None, after: dict | None = None, reason: str | None = None) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type=entity_type,
        entity_id=entity_id,
        after_data=after,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _query_charges():
    return select(RentCharge).options(
        selectinload(RentCharge.settlement).selectinload(FinancialSettlement.repasses)
    )


def _load_charge(db: Session, organization_id: UUID, charge_id: UUID) -> RentCharge:
    item = db.scalar(_query_charges().where(RentCharge.id == charge_id, RentCharge.organization_id == organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Cobrança não encontrada.")
    return item


def _charge_code(item: RentCharge) -> str:
    return f"COB-{item.internal_number:06d}"


def _lease_code(db: Session, lease_id: UUID) -> str:
    lease = db.get(LeaseContract, lease_id)
    return f"LOC-{lease.internal_number:06d}" if lease else "LOC-—"


def _property_code(item: RentCharge) -> str:
    return str((item.property_snapshot or {}).get("code") or "—")


def _repasse_response(db: Session, item: OwnerRepasse, charge: RentCharge | None = None) -> RepasseResponse:
    charge = charge or db.get(RentCharge, item.charge_id)
    return RepasseResponse(
        id=item.id,
        charge_id=item.charge_id,
        charge_code=_charge_code(charge) if charge else "COB-—",
        lease_contract_id=item.lease_contract_id,
        lease_code=_lease_code(db, item.lease_contract_id),
        property_id=item.property_id,
        property_code=_property_code(charge) if charge else "—",
        competence=charge.competence if charge else item.due_date.replace(day=1),
        owner_person_id=item.owner_person_id,
        owner_name=item.owner_name,
        ownership_percent=item.ownership_percent,
        amount=item.amount,
        due_date=item.due_date,
        status=item.status,
        paid_at=item.paid_at,
        payment_reference=item.payment_reference,
    )


def _settlement_response(db: Session, item: FinancialSettlement, charge: RentCharge) -> SettlementResponse:
    return SettlementResponse(
        id=item.id,
        administration_contract_id=item.administration_contract_id,
        admin_fee_calculated=item.admin_fee_calculated,
        intermediation_fee_calculated=item.intermediation_fee_calculated,
        agency_fee_withheld=item.agency_fee_withheld,
        agency_reimbursement_amount=item.agency_reimbursement_amount,
        owner_entitlement_amount=item.owner_entitlement_amount,
        third_party_amount=item.third_party_amount,
        calculated_at=item.calculated_at,
        repasses=[_repasse_response(db, repasse, charge) for repasse in item.repasses],
    )


def _charge_response(db: Session, item: RentCharge, *, today: date | None = None) -> ChargeResponse:
    today = today or date.today()
    overdue_days = max(0, (today - item.due_date).days) if item.status not in {"paid", "cancelled"} else 0
    critical_after = int((item.admin_terms_snapshot or {}).get("delinquency_critical_day") or 5)
    return ChargeResponse(
        id=item.id,
        code=_charge_code(item),
        lease_contract_id=item.lease_contract_id,
        lease_code=_lease_code(db, item.lease_contract_id),
        property_id=item.property_id,
        property_code=_property_code(item),
        property_address=dict((item.property_snapshot or {}).get("address") or {}),
        tenants=list(item.tenant_snapshot or []),
        owners=list(item.owner_snapshot or []),
        competence=item.competence,
        due_date=item.due_date,
        status=item.status,
        days_overdue=overdue_days,
        critical_overdue=item.status == "overdue" and overdue_days >= critical_after,
        rent_amount=item.rent_amount,
        gross_amount=item.gross_amount,
        charge_items=[ChargeItem(**entry) for entry in list(item.charge_items or [])],
        sent_at=item.sent_at,
        paid_at=item.paid_at,
        paid_amount=item.paid_amount,
        payment_method=item.payment_method,
        payment_reference=item.payment_reference,
        settlement=_settlement_response(db, item.settlement, item) if item.settlement else None,
        created_at=item.created_at,
    )


@router.get("/dashboard", response_model=FinanceDashboardResponse)
def finance_dashboard(
    competence: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> FinanceDashboardResponse:
    competence = (competence or date.today()).replace(day=1)
    changed = refresh_overdue(db, context.user.organization_id)
    charges = db.scalars(_query_charges().where(RentCharge.organization_id == context.user.organization_id)).unique().all()
    if changed:
        db.commit()
    open_items = [item for item in charges if item.status in {"generated", "sent", "overdue"}]
    overdue = [item for item in open_items if item.status == "overdue"]
    critical = [item for item in overdue if _charge_response(db, item).critical_overdue]
    paid_competence = [item for item in charges if item.status == "paid" and item.competence == competence]
    settlements = [item.settlement for item in paid_competence if item.settlement]
    repasses = [repasse for settlement in settlements for repasse in settlement.repasses]
    all_pending_repasses = db.scalars(
        select(OwnerRepasse).where(OwnerRepasse.organization_id == context.user.organization_id, OwnerRepasse.status == "pending")
    ).all()
    return FinanceDashboardResponse(
        competence=competence,
        open_amount=sum((money(item.gross_amount) for item in open_items), Decimal("0.00")),
        overdue_amount=sum((money(item.gross_amount) for item in overdue), Decimal("0.00")),
        critical_overdue_amount=sum((money(item.gross_amount) for item in critical), Decimal("0.00")),
        received_amount=sum((money(item.paid_amount) for item in paid_competence), Decimal("0.00")),
        agency_revenue_amount=sum((money(s.agency_fee_withheld) for s in settlements), Decimal("0.00")),
        pending_repasse_amount=sum((money(item.amount) for item in all_pending_repasses), Decimal("0.00")),
        charges_open=len(open_items),
        charges_overdue=len(overdue),
        charges_critical=len(critical),
        repasses_pending=len(all_pending_repasses),
    )


@router.get("/charges", response_model=list[ChargeResponse])
def list_charges(
    competence: date | None = Query(default=None),
    charge_status: str | None = Query(default=None, alias="status"),
    property_id: UUID | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[ChargeResponse]:
    changed = refresh_overdue(db, context.user.organization_id)
    stmt = _query_charges().where(RentCharge.organization_id == context.user.organization_id)
    if competence:
        stmt = stmt.where(RentCharge.competence == competence.replace(day=1))
    if charge_status:
        stmt = stmt.where(RentCharge.status == charge_status)
    if property_id:
        stmt = stmt.where(RentCharge.property_id == property_id)
    items = db.scalars(stmt.order_by(RentCharge.due_date.desc(), RentCharge.internal_number.desc()).limit(500)).unique().all()
    if changed:
        db.commit()
    return [_charge_response(db, item) for item in items]


@router.post("/charges/generate", response_model=GenerateChargesResponse)
def generate_monthly_charges(
    payload: GenerateChargesRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.charge.create")),
    db: Session = Depends(get_db),
) -> GenerateChargesResponse:
    created, skipped_existing, skipped_ineligible = generate_charges(
        db,
        organization_id=context.user.organization_id,
        user_id=context.user.id,
        competence=payload.competence,
        lease_contract_id=payload.lease_contract_id,
    )
    _audit(
        db, request, context,
        action="finance.charges.generated",
        entity_type="charge_batch",
        entity_id=payload.competence.isoformat(),
        after={"generated": len(created), "skipped_existing": skipped_existing, "skipped_ineligible": skipped_ineligible},
    )
    db.commit()
    loaded = [
        _load_charge(db, context.user.organization_id, item.id)
        for item in created
    ]
    return GenerateChargesResponse(
        competence=payload.competence,
        generated=len(loaded),
        skipped_existing=skipped_existing,
        skipped_ineligible=skipped_ineligible,
        charges=[_charge_response(db, item) for item in loaded],
    )


@router.post("/charges/{charge_id}/mark-sent", response_model=ChargeResponse)
def mark_charge_sent(
    charge_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.charge.create")),
    db: Session = Depends(get_db),
) -> ChargeResponse:
    item = _load_charge(db, context.user.organization_id, charge_id)
    if item.status not in {"generated", "overdue", "sent"}:
        raise HTTPException(status_code=409, detail="Esta cobrança não pode ser marcada como enviada.")
    item.sent_at = item.sent_at or datetime.now(timezone.utc)
    if item.due_date >= date.today():
        item.status = "sent"
    _audit(db, request, context, action="finance.charge.sent", entity_type="rent_charge", entity_id=str(item.id), after={"code": _charge_code(item)})
    db.commit()
    return _charge_response(db, _load_charge(db, context.user.organization_id, item.id))


@router.post("/charges/{charge_id}/payment", response_model=ChargeResponse)
def receive_charge(
    charge_id: UUID,
    payload: ChargePaymentRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> ChargeResponse:
    item = _load_charge(db, context.user.organization_id, charge_id)
    try:
        settlement = record_payment(
            db,
            charge=item,
            paid_amount=payload.paid_amount,
            paid_at=payload.paid_at,
            payment_method=payload.payment_method,
            payment_reference=payload.payment_reference,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db, request, context,
        action="finance.charge.received",
        entity_type="rent_charge",
        entity_id=str(item.id),
        after={
            "code": _charge_code(item),
            "paid_amount": str(item.paid_amount),
            "agency_fee_withheld": str(settlement.agency_fee_withheld),
            "owner_entitlement": str(settlement.owner_entitlement_amount),
        },
    )
    db.commit()
    return _charge_response(db, _load_charge(db, context.user.organization_id, item.id))


@router.post("/charges/{charge_id}/cancel", response_model=ChargeResponse)
def cancel_charge(
    charge_id: UUID,
    payload: ChargeCancellationRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> ChargeResponse:
    item = _load_charge(db, context.user.organization_id, charge_id)
    if item.status == "paid":
        raise HTTPException(status_code=409, detail="Uma cobrança já recebida não pode ser cancelada.")
    item.status = "cancelled"
    item.cancelled_at = datetime.now(timezone.utc)
    item.cancellation_reason = payload.reason.strip()
    _audit(db, request, context, action="finance.charge.cancelled", entity_type="rent_charge", entity_id=str(item.id), reason=payload.reason.strip())
    db.commit()
    return _charge_response(db, _load_charge(db, context.user.organization_id, item.id))


@router.get("/repasses", response_model=list[RepasseResponse])
def list_repasses(
    competence: date | None = Query(default=None),
    repasse_status: str | None = Query(default=None, alias="status"),
    owner_person_id: UUID | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[RepasseResponse]:
    stmt = select(OwnerRepasse).where(OwnerRepasse.organization_id == context.user.organization_id)
    if repasse_status:
        stmt = stmt.where(OwnerRepasse.status == repasse_status)
    if owner_person_id:
        stmt = stmt.where(OwnerRepasse.owner_person_id == owner_person_id)
    items = db.scalars(stmt.order_by(OwnerRepasse.due_date.desc()).limit(500)).all()
    charges = {item.id: item for item in db.scalars(select(RentCharge).where(RentCharge.id.in_([repasse.charge_id for repasse in items]))).all()} if items else {}
    if competence:
        competence = competence.replace(day=1)
        items = [item for item in items if charges.get(item.charge_id) and charges[item.charge_id].competence == competence]
    return [_repasse_response(db, item, charges.get(item.charge_id)) for item in items]


@router.post("/repasses/{repasse_id}/payment", response_model=RepasseResponse)
def pay_repasse(
    repasse_id: UUID,
    payload: RepassePaymentRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.repasse.execute")),
    db: Session = Depends(get_db),
) -> RepasseResponse:
    item = db.scalar(select(OwnerRepasse).where(OwnerRepasse.id == repasse_id, OwnerRepasse.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Repasse não encontrado.")
    if item.status == "paid":
        raise HTTPException(status_code=409, detail="Este repasse já foi pago.")
    if item.status == "settled_zero":
        raise HTTPException(status_code=409, detail="Este repasse possui valor zero.")
    item.status = "paid"
    item.paid_at = payload.paid_at or datetime.now(timezone.utc)
    item.payment_reference = (payload.payment_reference or "").strip() or None
    item.notes = (payload.notes or "").strip() or None
    _audit(
        db, request, context,
        action="finance.repasse.paid",
        entity_type="owner_repasse",
        entity_id=str(item.id),
        after={"owner": item.owner_name, "amount": str(item.amount), "reference": item.payment_reference},
    )
    db.commit()
    charge = db.get(RentCharge, item.charge_id)
    return _repasse_response(db, item, charge)


def _owner_statement(db: Session, organization_id: UUID, owner_id: UUID, competence: date, property_id: UUID | None = None) -> OwnerStatementResponse:
    competence = competence.replace(day=1)
    stmt = (
        select(OwnerRepasse, RentCharge, FinancialSettlement)
        .join(RentCharge, RentCharge.id == OwnerRepasse.charge_id)
        .join(FinancialSettlement, FinancialSettlement.id == OwnerRepasse.settlement_id)
        .where(
            OwnerRepasse.organization_id == organization_id,
            OwnerRepasse.owner_person_id == owner_id,
            RentCharge.competence == competence,
            RentCharge.status == "paid",
        )
        .order_by(RentCharge.paid_at.asc())
    )
    if property_id:
        stmt = stmt.where(OwnerRepasse.property_id == property_id)
    rows = db.execute(stmt).all()
    owner = db.scalar(
        select(Person).where(
            Person.id == owner_id,
            Person.organization_id == organization_id,
            Person.is_active.is_(True),
        )
    )
    owner_name = rows[0][0].owner_name if rows else (owner.name if owner else "Proprietário não identificado")
    lines: list[OwnerStatementLine] = []
    for repasse, charge, settlement in rows:
        lines.append(OwnerStatementLine(
            repasse_id=repasse.id,
            charge_code=_charge_code(charge),
            lease_code=_lease_code(db, charge.lease_contract_id),
            property_code=_property_code(charge),
            property_address=dict((charge.property_snapshot or {}).get("address") or {}),
            competence=charge.competence,
            paid_at=charge.paid_at,
            gross_charge=charge.gross_amount,
            rent_amount=charge.rent_amount,
            admin_fee=settlement.admin_fee_calculated,
            intermediation_fee=settlement.intermediation_fee_calculated,
            owner_total_before_share=settlement.owner_entitlement_amount,
            ownership_percent=repasse.ownership_percent,
            repasse_amount=repasse.amount,
            repasse_due_date=repasse.due_date,
            repasse_status=repasse.status,
            repasse_paid_at=repasse.paid_at,
        ))
    return OwnerStatementResponse(
        owner_person_id=owner_id,
        owner_name=owner_name,
        competence=competence,
        property_id=property_id,
        total_received_from_tenants=sum((money(charge.gross_amount) for _, charge, _ in rows), Decimal("0.00")),
        total_agency_fees=sum((money(settlement.agency_fee_withheld) for _, _, settlement in rows), Decimal("0.00")),
        total_owner_entitlement=sum((money(settlement.owner_entitlement_amount) for _, _, settlement in rows), Decimal("0.00")),
        total_repasse=sum((money(repasse.amount) for repasse, _, _ in rows), Decimal("0.00")),
        total_repasse_paid=sum((money(repasse.amount) for repasse, _, _ in rows if repasse.status == "paid"), Decimal("0.00")),
        lines=lines,
    )


@router.get("/statements/{owner_id}", response_model=OwnerStatementResponse)
def owner_statement(
    owner_id: UUID,
    competence: date = Query(...),
    property_id: UUID | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> OwnerStatementResponse:
    return _owner_statement(db, context.user.organization_id, owner_id, competence, property_id)


@router.get("/statements/{owner_id}/pdf")
def owner_statement_pdf(
    owner_id: UUID,
    competence: date = Query(...),
    property_id: UUID | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> Response:
    statement = _owner_statement(db, context.user.organization_id, owner_id, competence, property_id)
    organization = db.get(Organization, context.user.organization_id)
    pdf = build_owner_statement_pdf(statement=statement, organization_name=organization.display_name if organization else "Imobiliária")
    filename = f"prestacao-contas-{statement.owner_name.lower().replace(' ', '-')}-{statement.competence:%Y-%m}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})


@router.get("/properties/{property_id}/summary", response_model=PropertyFinanceSummary)
def property_finance_summary(
    property_id: UUID,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> PropertyFinanceSummary:
    refresh_overdue(db, context.user.organization_id)
    charges = db.scalars(
        _query_charges().where(RentCharge.organization_id == context.user.organization_id, RentCharge.property_id == property_id)
    ).unique().all()
    db.commit()
    open_items = [item for item in charges if item.status in {"generated", "sent", "overdue"}]
    overdue = [item for item in open_items if item.status == "overdue"]
    paid = [item for item in charges if item.status == "paid"]
    repasses = [repasse for charge in paid if charge.settlement for repasse in charge.settlement.repasses if repasse.status == "pending"]
    return PropertyFinanceSummary(
        property_id=property_id,
        open_amount=sum((money(item.gross_amount) for item in open_items), Decimal("0.00")),
        overdue_amount=sum((money(item.gross_amount) for item in overdue), Decimal("0.00")),
        received_amount=sum((money(item.paid_amount) for item in paid), Decimal("0.00")),
        pending_repasse_amount=sum((money(item.amount) for item in repasses), Decimal("0.00")),
        next_due_date=min((item.due_date for item in open_items), default=None),
        last_payment_at=max((item.paid_at for item in paid if item.paid_at), default=None),
        critical_overdue=any(_charge_response(db, item).critical_overdue for item in overdue),
    )
