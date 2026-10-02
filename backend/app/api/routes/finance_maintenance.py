from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.maintenance_schemas import (
    MaintenanceEntryResponse,
    MaintenanceEntrySettlementRequest,
    MaintenanceFinanceCase,
    MaintenanceFinanceDashboard,
)
from app.domains.finance.models import MaintenanceFinancialEntry, OwnerRepasse
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.portfolio.models import Property, PropertyOwner

router = APIRouter(prefix="/finance/maintenance", tags=["finance-maintenance"])
CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, *, action: str, entry: MaintenanceFinancialEntry, after: dict | None = None) -> None:
    ip, agent = _metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type="maintenance_financial_entry",
        entity_id=str(entry.id),
        after_data=after,
        ip_address=ip,
        user_agent=agent,
    )


def _load_entry(db: Session, organization_id: UUID, entry_id: UUID, direction: str) -> MaintenanceFinancialEntry:
    item = db.scalar(
        select(MaintenanceFinancialEntry).where(
            MaintenanceFinancialEntry.id == entry_id,
            MaintenanceFinancialEntry.organization_id == organization_id,
            MaintenanceFinancialEntry.direction == direction,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Lançamento financeiro da manutenção não encontrado.")
    return item


def _entry_response(item: MaintenanceFinancialEntry) -> MaintenanceEntryResponse:
    return MaintenanceEntryResponse(
        id=item.id,
        direction=item.direction,
        status=item.status,
        counterparty_type=item.counterparty_type,
        counterparty_name=item.counterparty_name,
        responsibility=item.responsibility,
        collection_method=item.collection_method,
        amount=item.amount,
        settled_amount=item.settled_amount,
        remaining_amount=money(item.amount - item.settled_amount),
        margin_amount=item.margin_amount,
        due_date=item.due_date,
        settled_at=item.settled_at,
        payment_reference=item.payment_reference,
    )


def _selected_quote(item: MaintenanceRequest) -> dict | None:
    if not item.selected_quote_id:
        return None
    return next((dict(q) for q in list(item.quotes or []) if q.get("id") == item.selected_quote_id), None)


def _case(db: Session, item: MaintenanceRequest, entries: list[MaintenanceFinancialEntry]) -> MaintenanceFinanceCase:
    prop = db.get(Property, item.property_id)
    quote = _selected_quote(item) or {}
    payable = next((entry for entry in entries if entry.direction == "payable"), None)
    receivable = next((entry for entry in entries if entry.direction == "receivable"), None)
    partner_cost = money(quote.get("partner_cost_total") or quote.get("amount") or (payable.amount if payable else 0))
    client_charge = money(quote.get("client_price_total") if quote.get("client_price_total") is not None else (receivable.amount if receivable else partner_cost))
    margin = money(client_charge - partner_cost) if item.responsibility != "agency" else money(-partner_cost)
    return MaintenanceFinanceCase(
        maintenance_id=item.id,
        maintenance_code=f"MAN-{item.internal_number:06d}",
        property_id=item.property_id,
        property_code=f"{prop.internal_number:06d}" if prop else "—",
        property_title=(prop.public_title or f"Imóvel {prop.internal_number:06d}") if prop else "Imóvel",
        title=item.title,
        responsibility=item.responsibility,
        quote_code=quote.get("quote_code"),
        partner_name=quote.get("supplier_name"),
        partner_cost=partner_cost,
        client_charge=client_charge if item.responsibility != "agency" else Decimal("0.00"),
        margin=margin,
        completed_at=item.completed_at,
        payable=_entry_response(payable) if payable else None,
        receivable=_entry_response(receivable) if receivable else None,
    )


@router.get("", response_model=MaintenanceFinanceDashboard)
def maintenance_finance_dashboard(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> MaintenanceFinanceDashboard:
    entries = db.scalars(
        select(MaintenanceFinancialEntry)
        .where(MaintenanceFinancialEntry.organization_id == context.user.organization_id)
        .order_by(MaintenanceFinancialEntry.created_at.desc())
    ).all()
    by_maintenance: dict[UUID, list[MaintenanceFinancialEntry]] = {}
    for entry in entries:
        by_maintenance.setdefault(entry.maintenance_request_id, []).append(entry)
    maintenances = db.scalars(
        select(MaintenanceRequest)
        .where(
            MaintenanceRequest.organization_id == context.user.organization_id,
            MaintenanceRequest.id.in_(list(by_maintenance.keys())) if by_maintenance else False,
        )
        .order_by(MaintenanceRequest.internal_number.desc())
    ).all() if by_maintenance else []
    cases = [_case(db, item, by_maintenance.get(item.id, [])) for item in maintenances]
    payable_pending = sum((money(entry.amount - entry.settled_amount) for entry in entries if entry.direction == "payable" and entry.status in {"pending", "partial"}), Decimal("0.00"))
    receivable_pending = sum((money(entry.amount - entry.settled_amount) for entry in entries if entry.direction == "receivable" and entry.status in {"pending", "partial"}), Decimal("0.00"))
    settled_payables = sum((money(entry.settled_amount) for entry in entries if entry.direction == "payable"), Decimal("0.00"))
    settled_receivables = sum((money(entry.settled_amount) for entry in entries if entry.direction == "receivable"), Decimal("0.00"))
    expected_margin = sum((money(case.margin) for case in cases), Decimal("0.00"))
    return MaintenanceFinanceDashboard(
        payable_pending=money(payable_pending),
        receivable_pending=money(receivable_pending),
        expected_margin=money(expected_margin),
        settled_payables=money(settled_payables),
        settled_receivables=money(settled_receivables),
        cases=cases,
    )


@router.post("/payables/{entry_id}/payment", response_model=MaintenanceEntryResponse)
def pay_maintenance_partner(
    entry_id: UUID,
    payload: MaintenanceEntrySettlementRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> MaintenanceEntryResponse:
    entry = _load_entry(db, context.user.organization_id, entry_id, "payable")
    if entry.status == "settled":
        raise HTTPException(status_code=409, detail="Este pagamento já foi liquidado.")
    entry.settled_amount = money(entry.amount)
    entry.status = "settled"
    entry.settled_at = payload.settled_at or datetime.now(timezone.utc)
    entry.payment_reference = (payload.payment_reference or "").strip() or None
    entry.notes = (payload.notes or "").strip() or entry.notes
    _audit(db, request, context, action="finance.maintenance_partner_paid", entry=entry, after={"amount": str(entry.amount), "reference": entry.payment_reference})
    db.commit()
    db.refresh(entry)
    return _entry_response(entry)


@router.post("/receivables/{entry_id}/receipt", response_model=MaintenanceEntryResponse)
def receive_maintenance_reimbursement(
    entry_id: UUID,
    payload: MaintenanceEntrySettlementRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> MaintenanceEntryResponse:
    entry = _load_entry(db, context.user.organization_id, entry_id, "receivable")
    if entry.status == "settled":
        raise HTTPException(status_code=409, detail="Esta cobrança já foi liquidada.")
    entry.settled_amount = money(entry.amount)
    entry.status = "settled"
    entry.settled_at = payload.settled_at or datetime.now(timezone.utc)
    entry.payment_reference = (payload.payment_reference or "").strip() or None
    entry.notes = (payload.notes or "").strip() or entry.notes
    _audit(db, request, context, action="finance.maintenance_reimbursement_received", entry=entry, after={"amount": str(entry.amount), "reference": entry.payment_reference})
    db.commit()
    db.refresh(entry)
    return _entry_response(entry)


@router.post("/receivables/{entry_id}/apply-owner-repasse", response_model=MaintenanceEntryResponse)
def apply_owner_repasse_deduction(
    entry_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.repasse.execute")),
    db: Session = Depends(get_db),
) -> MaintenanceEntryResponse:
    entry = _load_entry(db, context.user.organization_id, entry_id, "receivable")
    if entry.responsibility != "owner" or entry.collection_method != "owner_repasse_deduction":
        raise HTTPException(status_code=409, detail="Este lançamento não está configurado para desconto em repasse de proprietário.")
    if entry.status == "settled":
        raise HTTPException(status_code=409, detail="Esta cobrança já foi liquidada.")

    ownerships = db.scalars(
        select(PropertyOwner)
        .join(Property, Property.id == PropertyOwner.property_id)
        .where(
            PropertyOwner.property_id == entry.property_id,
            Property.organization_id == context.user.organization_id,
        )
        .order_by(PropertyOwner.created_at.asc(), PropertyOwner.person_id.asc())
    ).all()
    if not ownerships:
        raise HTTPException(status_code=409, detail="O imóvel não possui proprietários cadastrados para ratear a manutenção.")
    ownership_total = sum((Decimal(str(owner.ownership_percent)) for owner in ownerships), Decimal("0.00"))
    if ownership_total != Decimal("100"):
        raise HTTPException(status_code=409, detail="A participação dos proprietários precisa totalizar 100% antes do abatimento.")

    snapshot = dict(entry.source_snapshot or {})
    raw_deductions = dict(snapshot.get("owner_repasse_deductions") or {})
    deductions = {str(key): money(value) for key, value in raw_deductions.items()}
    if money(entry.settled_amount) > 0 and not deductions:
        raise HTTPException(
            status_code=409,
            detail="Este lançamento já possui liquidação anterior sem rateio por proprietário. Revise a origem antes de aplicar novo abatimento.",
        )
    tracked_total = money(sum(deductions.values(), Decimal("0.00")))
    if deductions and tracked_total != money(entry.settled_amount):
        raise HTTPException(status_code=409, detail="O histórico de abatimentos da manutenção está inconsistente e precisa de revisão.")

    repasses = db.scalars(
        select(OwnerRepasse)
        .where(
            OwnerRepasse.organization_id == context.user.organization_id,
            OwnerRepasse.property_id == entry.property_id,
            OwnerRepasse.status == "pending",
            OwnerRepasse.amount > 0,
        )
        .order_by(OwnerRepasse.due_date.asc(), OwnerRepasse.created_at.asc())
    ).all()
    if not repasses:
        raise HTTPException(status_code=409, detail="Ainda não há repasse pendente deste imóvel para aplicar a dedução.")

    by_owner: dict[UUID, list[OwnerRepasse]] = {}
    for repasse in repasses:
        by_owner.setdefault(repasse.owner_person_id, []).append(repasse)

    applied = Decimal("0.00")
    applied_by_owner: dict[str, Decimal] = {}
    current_refs: list[str] = []
    target_accumulated = Decimal("0.00")
    code = str(snapshot.get("maintenance_code") or "Manutenção")

    for index, ownership in enumerate(ownerships):
        owner_key = str(ownership.person_id)
        if index == len(ownerships) - 1:
            owner_target = money(entry.amount - target_accumulated)
        else:
            owner_target = money(entry.amount * Decimal(str(ownership.ownership_percent)) / Decimal("100"))
            target_accumulated = money(target_accumulated + owner_target)
        already = money(deductions.get(owner_key, Decimal("0.00")))
        owner_remaining = money(max(Decimal("0.00"), owner_target - already))
        if owner_remaining <= 0:
            continue

        owner_applied = Decimal("0.00")
        for repasse in by_owner.get(ownership.person_id, []):
            if owner_remaining <= 0:
                break
            take = money(min(money(repasse.amount), owner_remaining))
            if take <= 0:
                continue
            repasse.amount = money(repasse.amount - take)
            note = f"Dedução proporcional {code}: R$ {take:.2f}"
            repasse.notes = f"{repasse.notes}\n{note}".strip() if repasse.notes else note
            if repasse.amount <= 0:
                repasse.amount = Decimal("0.00")
                repasse.status = "settled_zero"
            owner_applied = money(owner_applied + take)
            owner_remaining = money(owner_remaining - take)
            current_refs.append(str(repasse.id))

        if owner_applied > 0:
            deductions[owner_key] = money(already + owner_applied)
            applied_by_owner[owner_key] = owner_applied
            applied = money(applied + owner_applied)

    if applied <= 0:
        raise HTTPException(status_code=409, detail="Não havia saldo disponível nos repasses dos proprietários para o rateio devido.")

    all_refs = [str(value) for value in list(snapshot.get("owner_repasse_refs") or [])]
    for value in current_refs:
        if value not in all_refs:
            all_refs.append(value)
    snapshot["owner_repasse_deductions"] = {key: str(value) for key, value in deductions.items()}
    snapshot["owner_repasse_refs"] = all_refs
    entry.source_snapshot = snapshot
    entry.settled_amount = money(sum(deductions.values(), Decimal("0.00")))
    entry.status = "settled" if entry.settled_amount >= entry.amount else "partial"
    entry.settled_at = datetime.now(timezone.utc) if entry.status == "settled" else None
    entry.payment_reference = f"repasse:{','.join(all_refs[-4:])}"
    entry.notes = (
        f"R$ {applied:.2f} abatidos proporcionalmente dos repasses dos proprietários. "
        f"Total abatido: R$ {entry.settled_amount:.2f}."
    )
    _audit(
        db,
        request,
        context,
        action="finance.maintenance_owner_repasse_offset",
        entry=entry,
        after={
            "applied": str(applied),
            "settled_amount": str(entry.settled_amount),
            "status": entry.status,
            "applied_by_owner": {key: str(value) for key, value in applied_by_owner.items()},
        },
    )
    db.commit()
    db.refresh(entry)
    return _entry_response(entry)
