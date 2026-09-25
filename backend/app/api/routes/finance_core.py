from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.core_schemas import (
    FinanceCoreItem,
    FinanceCoreOverview,
    ManualFinancialCancellationRequest,
    ManualFinancialSettlementRequest,
    ManualFinancialTitleCreate,
)
from app.domains.finance.models import MaintenanceFinancialEntry, OwnerRepasse, RentCharge
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit

router = APIRouter(prefix="/finance/core", tags=["finance-core"])
CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def month_start(value: date) -> date:
    return value.replace(day=1)


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    after: dict | None = None,
    reason: str | None = None,
) -> None:
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


def _is_closed(status: str) -> bool:
    return status in {"paid", "settled", "settled_zero", "cancelled"}


def _remaining(amount: Decimal, settled: Decimal, status: str) -> Decimal:
    if status in {"cancelled", "settled_zero"}:
        return Decimal("0.00")
    return money(max(Decimal("0.00"), money(amount) - money(settled)))


def _normalized_status(status: str, due_date: date | None, settled: Decimal, amount: Decimal) -> str:
    if status == "cancelled":
        return "cancelled"
    if money(settled) >= money(amount) and money(amount) > 0:
        return "settled"
    if money(settled) > 0:
        return "partial"
    if due_date and due_date < date.today():
        return "overdue"
    if status in {"generated", "sent"}:
        return "pending"
    return status


def _rent_item(item: RentCharge) -> FinanceCoreItem:
    tenants = " / ".join(str(entry.get("name") or "").strip() for entry in list(item.tenant_snapshot or []) if entry.get("name"))
    settled = money(item.paid_amount) if item.status == "paid" else Decimal("0.00")
    status = _normalized_status(item.status, item.due_date, settled, money(item.gross_amount))
    return FinanceCoreItem(
        id=item.id,
        code=f"COB-{item.internal_number:06d}",
        source_type="rent",
        source_id=item.id,
        direction="receivable",
        fund_scope="third_party",
        category="Locação",
        description="Cobrança mensal de locação",
        counterparty_name=tenants or "Locatário",
        property_id=item.property_id,
        lease_contract_id=item.lease_contract_id,
        competence=item.competence,
        due_date=item.due_date,
        amount=money(item.gross_amount),
        settled_amount=settled,
        remaining_amount=_remaining(money(item.gross_amount), settled, item.status),
        margin_amount=Decimal("0.00"),
        status=status,
        overdue=status == "overdue",
        settled_at=item.paid_at,
        payment_method=item.payment_method,
        payment_reference=item.payment_reference,
        manual=False,
    )


def _repasse_item(item: OwnerRepasse, charge: RentCharge) -> FinanceCoreItem:
    settled = money(item.amount) if item.status == "paid" else Decimal("0.00")
    status = _normalized_status(item.status, item.due_date, settled, money(item.amount))
    return FinanceCoreItem(
        id=item.id,
        code=f"REP-{str(item.id)[:8].upper()}",
        source_type="owner_repasse",
        source_id=item.id,
        direction="payable",
        fund_scope="third_party",
        category="Repasse ao proprietário",
        description=f"Repasse da cobrança COB-{charge.internal_number:06d}",
        counterparty_name=item.owner_name,
        property_id=item.property_id,
        lease_contract_id=item.lease_contract_id,
        competence=charge.competence,
        due_date=item.due_date,
        amount=money(item.amount),
        settled_amount=settled,
        remaining_amount=_remaining(money(item.amount), settled, item.status),
        margin_amount=Decimal("0.00"),
        status=status,
        overdue=status == "overdue",
        settled_at=item.paid_at,
        payment_method="transfer" if item.paid_at else None,
        payment_reference=item.payment_reference,
        manual=False,
    )


def _maintenance_item(item: MaintenanceFinancialEntry) -> FinanceCoreItem:
    base_date = item.due_date or item.created_at.date()
    competence = month_start(base_date)
    settled = money(item.settled_amount)
    status = _normalized_status(item.status, item.due_date, settled, money(item.amount))
    snapshot = dict(item.source_snapshot or {})
    maintenance_code = str(snapshot.get("maintenance_code") or f"MAN-{str(item.maintenance_request_id)[:8]}")
    category = "Manutenção · parceiro" if item.direction == "payable" else "Manutenção · cliente"
    scope = "third_party" if item.direction == "receivable" and item.collection_method == "owner_repasse_deduction" else "operating"
    return FinanceCoreItem(
        id=item.id,
        code=f"MFIN-{item.internal_number:06d}",
        source_type="maintenance",
        source_id=item.maintenance_request_id,
        direction=item.direction,
        fund_scope=scope,
        category=category,
        description=f"{maintenance_code} · {snapshot.get('title') or 'Manutenção'}",
        counterparty_name=item.counterparty_name,
        property_id=item.property_id,
        lease_contract_id=item.lease_contract_id,
        competence=competence,
        due_date=item.due_date,
        amount=money(item.amount),
        settled_amount=settled,
        remaining_amount=_remaining(money(item.amount), settled, item.status),
        margin_amount=money(item.margin_amount),
        status=status,
        overdue=status == "overdue",
        settled_at=item.settled_at,
        payment_method=None,
        payment_reference=item.payment_reference,
        manual=False,
    )


def _manual_item(item: FinancialTitle) -> FinanceCoreItem:
    settled = money(item.settled_amount)
    status = _normalized_status(item.status, item.due_date, settled, money(item.amount))
    is_manual = item.source_type == "manual"
    return FinanceCoreItem(
        id=item.id,
        code=f"FIN-{item.internal_number:06d}",
        source_type=item.source_type,
        source_id=item.id if is_manual else (item.source_id or item.id),
        direction=item.direction,
        fund_scope=item.fund_scope,
        category=item.category,
        description=item.description,
        counterparty_name=item.counterparty_name,
        property_id=item.property_id,
        lease_contract_id=item.lease_contract_id,
        competence=item.competence,
        due_date=item.due_date,
        amount=money(item.amount),
        settled_amount=settled,
        remaining_amount=_remaining(money(item.amount), settled, item.status),
        margin_amount=Decimal("0.00"),
        status=status,
        overdue=status == "overdue",
        settled_at=item.settled_at,
        payment_method=item.payment_method,
        payment_reference=item.payment_reference,
        manual=is_manual,
    )


def _collect_items(db: Session, organization_id: UUID, competence: date) -> list[FinanceCoreItem]:
    competence = month_start(competence)
    items: list[FinanceCoreItem] = []

    charges = db.scalars(
        select(RentCharge)
        .where(RentCharge.organization_id == organization_id, RentCharge.competence == competence)
        .order_by(RentCharge.due_date.asc(), RentCharge.internal_number.asc())
    ).all()
    items.extend(_rent_item(item) for item in charges)

    if charges:
        charge_map = {item.id: item for item in charges}
        repasses = db.scalars(
            select(OwnerRepasse)
            .where(
                OwnerRepasse.organization_id == organization_id,
                OwnerRepasse.charge_id.in_(list(charge_map.keys())),
            )
            .order_by(OwnerRepasse.due_date.asc())
        ).all()
        items.extend(_repasse_item(item, charge_map[item.charge_id]) for item in repasses if item.charge_id in charge_map)

    maintenance_entries = db.scalars(
        select(MaintenanceFinancialEntry)
        .where(MaintenanceFinancialEntry.organization_id == organization_id)
        .order_by(MaintenanceFinancialEntry.created_at.desc())
        .limit(1500)
    ).all()
    items.extend(
        _maintenance_item(item)
        for item in maintenance_entries
        if month_start(item.due_date or item.created_at.date()) == competence
    )

    manual_titles = db.scalars(
        select(FinancialTitle)
        .where(FinancialTitle.organization_id == organization_id, FinancialTitle.competence == competence)
        .order_by(FinancialTitle.due_date.asc(), FinancialTitle.internal_number.asc())
    ).all()
    items.extend(_manual_item(item) for item in manual_titles)

    return sorted(items, key=lambda entry: (entry.due_date or entry.competence, entry.code))


def _load_manual(db: Session, organization_id: UUID, title_id: UUID) -> FinancialTitle:
    item = db.scalar(
        select(FinancialTitle).where(
            FinancialTitle.id == title_id,
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.source_type == "manual",
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Título financeiro manual não encontrado.")
    return item


@router.get("/overview", response_model=FinanceCoreOverview)
def core_overview(
    competence: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> FinanceCoreOverview:
    competence = month_start(competence or date.today())
    items = _collect_items(db, context.user.organization_id, competence)
    open_items = [item for item in items if not _is_closed(item.status) and item.remaining_amount > 0]
    receivables = [item for item in open_items if item.direction == "receivable"]
    payables = [item for item in open_items if item.direction == "payable"]
    overdue = [item for item in open_items if item.overdue]
    return FinanceCoreOverview(
        competence=competence,
        receivable_open_amount=sum((money(item.remaining_amount) for item in receivables), Decimal("0.00")),
        payable_open_amount=sum((money(item.remaining_amount) for item in payables), Decimal("0.00")),
        overdue_receivable_amount=sum((money(item.remaining_amount) for item in overdue if item.direction == "receivable"), Decimal("0.00")),
        overdue_payable_amount=sum((money(item.remaining_amount) for item in overdue if item.direction == "payable"), Decimal("0.00")),
        received_amount=sum((money(item.settled_amount) for item in items if item.direction == "receivable"), Decimal("0.00")),
        paid_amount=sum((money(item.settled_amount) for item in items if item.direction == "payable"), Decimal("0.00")),
        operating_open_amount=sum((money(item.remaining_amount) for item in open_items if item.fund_scope == "operating"), Decimal("0.00")),
        third_party_open_amount=sum((money(item.remaining_amount) for item in open_items if item.fund_scope == "third_party"), Decimal("0.00")),
        receivable_open_count=len(receivables),
        payable_open_count=len(payables),
        overdue_count=len(overdue),
        items=items,
    )


@router.get("/items", response_model=list[FinanceCoreItem])
def core_items(
    competence: date | None = Query(default=None),
    direction: str | None = Query(default=None),
    item_status: str | None = Query(default=None, alias="status"),
    fund_scope: str | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[FinanceCoreItem]:
    items = _collect_items(db, context.user.organization_id, month_start(competence or date.today()))
    if direction:
        items = [item for item in items if item.direction == direction]
    if item_status:
        items = [item for item in items if item.status == item_status]
    if fund_scope:
        items = [item for item in items if item.fund_scope == fund_scope]
    return items


@router.post("/manual", response_model=FinanceCoreItem)
def create_manual_title(
    payload: ManualFinancialTitleCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> FinanceCoreItem:
    required = "finance.charge.create" if payload.direction == "receivable" else "finance.payment.prepare"
    if not context.has(required):
        raise HTTPException(status_code=403, detail=f"Permissão necessária: {required}")
    item = FinancialTitle(
        organization_id=context.user.organization_id,
        direction=payload.direction,
        fund_scope=payload.fund_scope,
        source_type="manual",
        property_id=payload.property_id,
        lease_contract_id=payload.lease_contract_id,
        category=payload.category.strip(),
        description=payload.description.strip(),
        counterparty_name=payload.counterparty_name.strip(),
        competence=month_start(payload.competence),
        due_date=payload.due_date,
        amount=money(payload.amount),
        settled_amount=Decimal("0.00"),
        status="pending",
        notes=(payload.notes or "").strip() or None,
        source_snapshot={},
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        context,
        action="finance.manual_title.created",
        entity_type="financial_title",
        entity_id=str(item.id),
        after={
            "direction": item.direction,
            "fund_scope": item.fund_scope,
            "amount": str(item.amount),
            "due_date": item.due_date.isoformat(),
        },
    )
    db.commit()
    db.refresh(item)
    return _manual_item(item)


@router.post("/manual/{title_id}/settle", response_model=FinanceCoreItem)
def settle_manual_title(
    title_id: UUID,
    payload: ManualFinancialSettlementRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> FinanceCoreItem:
    item = _load_manual(db, context.user.organization_id, title_id)
    required = "finance.reconcile" if item.direction == "receivable" else "finance.payment.approve"
    if not context.has(required):
        raise HTTPException(status_code=403, detail=f"Permissão necessária: {required}")
    if item.status == "cancelled":
        raise HTTPException(status_code=409, detail="Título cancelado não pode ser liquidado.")
    remaining = money(item.amount - item.settled_amount)
    if remaining <= 0:
        raise HTTPException(status_code=409, detail="Este título já está liquidado.")
    amount = money(payload.amount if payload.amount is not None else remaining)
    if amount <= 0 or amount > remaining:
        raise HTTPException(status_code=409, detail="Valor de liquidação inválido.")
    item.settled_amount = money(item.settled_amount + amount)
    item.status = "settled" if item.settled_amount >= item.amount else "partial"
    item.settled_at = payload.settled_at or datetime.now(timezone.utc)
    item.payment_method = payload.payment_method
    item.payment_reference = (payload.payment_reference or "").strip() or None
    if payload.notes:
        item.notes = payload.notes.strip()
    _audit(
        db,
        request,
        context,
        action="finance.manual_title.settled",
        entity_type="financial_title",
        entity_id=str(item.id),
        after={"settled_amount": str(item.settled_amount), "status": item.status},
    )
    db.commit()
    db.refresh(item)
    return _manual_item(item)


@router.post("/manual/{title_id}/cancel", response_model=FinanceCoreItem)
def cancel_manual_title(
    title_id: UUID,
    payload: ManualFinancialCancellationRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> FinanceCoreItem:
    item = _load_manual(db, context.user.organization_id, title_id)
    if item.settled_amount > 0:
        raise HTTPException(status_code=409, detail="Título com liquidação não pode ser cancelado.")
    item.status = "cancelled"
    item.notes = f"{item.notes}\nCancelamento: {payload.reason.strip()}".strip() if item.notes else f"Cancelamento: {payload.reason.strip()}"
    _audit(
        db,
        request,
        context,
        action="finance.manual_title.cancelled",
        entity_type="financial_title",
        entity_id=str(item.id),
        reason=payload.reason.strip(),
    )
    db.commit()
    db.refresh(item)
    return _manual_item(item)
