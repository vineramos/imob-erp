from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.advanced_models import CommissionEntry, CommissionPaymentBatch, CommissionPaymentBatchItem, CommissionRule
from app.domains.finance.advanced_schemas import (
    CommissionEntryResponse,
    CommissionRuleCreate,
    CommissionRuleResponse,
    CommissionRuleUpdate,
)
from app.domains.finance.advanced_service import generate_commissions_for_charge, money, sync_commission_status
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import FinancialSettlement, RentCharge
from app.domains.foundation.access import UserContext, get_current_user_context, require_permission
from app.domains.foundation.models import Organization
from app.domains.foundation.audit import write_audit
from app.domains.portfolio.models import Person
from app.domains.leases.models import LeaseContract
from app.domains.finance.commission_batch_pdf import build_commission_batch_pdf
from app.integrations.document_storage import DocumentStorageError, get_document_storage
from app.integrations.email import EmailDeliveryError, send_email_message, smtp_config_for_organization

router = APIRouter(prefix="/commissions")


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    action: str,
    entity_type: str,
    entity_id: str | None,
    after: dict | None = None,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type=entity_type,
        entity_id=entity_id,
        after_data=after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )


def _rule_response(item: CommissionRule) -> CommissionRuleResponse:
    return CommissionRuleResponse(
        id=item.id,
        code=f"COMR-{item.internal_number:04d}",
        name=item.name,
        event_type=item.event_type,
        basis=item.basis,
        calculation_type=item.calculation_type,
        value=float(item.value),
        beneficiary_type=item.beneficiary_type,
        beneficiary_person_id=item.beneficiary_person_id,
        beneficiary_name=item.beneficiary_name,
        property_id=item.property_id,
        lease_contract_id=item.lease_contract_id,
        due_days=item.due_days,
        priority=item.priority,
        is_active=item.is_active,
        notes=item.notes,
        created_at=item.created_at,
    )


def _entry_response(db: Session, item: CommissionEntry) -> CommissionEntryResponse:
    sync_commission_status(db, item)
    return CommissionEntryResponse(
        id=item.id,
        code=f"COM-{item.internal_number:06d}",
        rule_id=item.rule_id,
        source_type=item.source_type,
        source_id=item.source_id,
        source_code=item.source_code,
        beneficiary_type=item.beneficiary_type,
        beneficiary_person_id=item.beneficiary_person_id,
        beneficiary_name=item.beneficiary_name,
        competence=item.competence,
        basis_amount=float(money(item.basis_amount)),
        amount=float(money(item.amount)),
        due_date=item.due_date,
        status=item.status,
        financial_title_id=item.financial_title_id,
        paid_at=item.paid_at,
        payment_reference=item.payment_reference,
        created_at=item.created_at,
    )


def _person(db: Session, organization_id: UUID, person_id: UUID) -> Person:
    item = db.scalar(
        select(Person).where(
            Person.id == person_id,
            Person.organization_id == organization_id,
            Person.is_active.is_(True),
        )
    )
    if item is None:
        raise HTTPException(status_code=422, detail="Beneficiário da comissão não encontrado.")
    return item


def _treasury_category(item: CommissionEntry) -> str:
    if item.beneficiary_type == "broker":
        return "Comissões · corretores"
    if item.beneficiary_type == "referrer":
        return "Angariações"
    if item.beneficiary_type == "supplier":
        return "Comissões · fornecedores"
    return "Comissões"






def _broker_for_user(db: Session, context: UserContext) -> Person | None:
    email = (context.user.email or "").strip().lower()
    if not email:
        return None
    candidates = db.scalars(select(Person).where(
        Person.organization_id == context.user.organization_id,
        Person.is_active.is_(True),
    )).all()
    return next((person for person in candidates if (person.email or "").strip().lower() == email and any(role.role_key == "broker" and role.is_active for role in person.roles)), None)


def _authorize_batch_access(db: Session, context: UserContext, batch: CommissionPaymentBatch) -> None:
    if context.has("finance.view"):
        return
    broker = _broker_for_user(db, context)
    if broker is None or broker.id != batch.beneficiary_person_id:
        raise HTTPException(403, "Este lote não pertence ao corretor autenticado.")


def _month_end(competence: date) -> date:
    next_month = (competence.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def _next_month_start(value: date) -> date:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def _payment_date(competence: date, approved_on: date | None = None) -> date:
    target_month = _next_month_start(competence)
    cutoff = target_month.replace(day=8)
    if approved_on and approved_on > cutoff:
        target_month = _next_month_start(target_month)
    result = target_month.replace(day=10)
    while result.weekday() >= 5:
        result += timedelta(days=1)
    return result


def _batch_code(batch: CommissionPaymentBatch) -> str:
    return f"COM-{batch.competence:%Y}-{batch.internal_number:06d}"


def _batch_items_payload(db: Session, batch: CommissionPaymentBatch) -> list[dict]:
    rows = db.scalars(
        select(CommissionPaymentBatchItem)
        .where(CommissionPaymentBatchItem.batch_id == batch.id)
        .order_by(CommissionPaymentBatchItem.created_at.asc())
    ).all()
    return [{"id": row.id, "commission_entry_id": row.commission_entry_id, "amount": float(row.amount), "snapshot": dict(row.snapshot or {})} for row in rows]


def _sync_batch_status(db: Session, batch: CommissionPaymentBatch) -> None:
    if batch.status in {"cancelled", "returned", "report_released", "report_issued", "awaiting_finance_approval"}:
        return
    rows = db.scalars(select(CommissionPaymentBatchItem).where(CommissionPaymentBatchItem.batch_id == batch.id)).all()
    if not rows:
        return
    entries = [db.get(CommissionEntry, row.commission_entry_id) for row in rows]
    for entry in entries:
        if entry:
            sync_commission_status(db, entry)
    valid = [entry for entry in entries if entry is not None]
    if valid and all(entry.status == "paid" for entry in valid):
        batch.status = "paid"
        batch.paid_at = max((entry.paid_at for entry in valid if entry.paid_at), default=datetime.now(timezone.utc))
        batch.payment_reference = ", ".join(sorted({entry.payment_reference for entry in valid if entry.payment_reference})) or None


def _batch_response(db: Session, batch: CommissionPaymentBatch) -> dict:
    _sync_batch_status(db, batch)
    return {
        "id": batch.id,
        "code": _batch_code(batch),
        "beneficiary_person_id": batch.beneficiary_person_id,
        "beneficiary_name": batch.beneficiary_name,
        "competence": batch.competence,
        "status": batch.status,
        "total_amount": float(batch.total_amount),
        "broker_legal_name": batch.broker_legal_name,
        "broker_document_number": batch.broker_document_number,
        "organization_legal_name": batch.organization_legal_name,
        "organization_document_number": batch.organization_document_number,
        "service_description": batch.service_description,
        "report_issued_at": batch.report_issued_at,
        "invoice_filename": batch.invoice_filename,
        "invoice_uploaded_at": batch.invoice_uploaded_at,
        "finance_review_notes": batch.finance_review_notes,
        "approved_at": batch.approved_at,
        "payment_due_date": batch.payment_due_date,
        "paid_at": batch.paid_at,
        "payment_reference": batch.payment_reference,
        "reminder_sent_at": batch.reminder_sent_at,
        "reminder_error": batch.reminder_error,
        "items": _batch_items_payload(db, batch),
    }


def _paid_charge_window(competence: date) -> tuple[datetime, datetime]:
    start = competence.replace(day=1)
    next_month = _next_month_start(start)
    return (
        datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        datetime(next_month.year, next_month.month, next_month.day, tzinfo=timezone.utc),
    )


def _eligible_batch_entries(db: Session, organization_id: UUID, competence: date) -> list[tuple[CommissionEntry, RentCharge]]:
    start_at, end_at = _paid_charge_window(competence)
    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.status == "paid",
            RentCharge.paid_at.is_not(None),
            RentCharge.paid_at >= start_at,
            RentCharge.paid_at < end_at,
        )
    ).all()
    paid = {charge.id: charge for charge in charges}
    if not paid:
        return []
    entries = db.scalars(
        select(CommissionEntry).where(
            CommissionEntry.organization_id == organization_id,
            CommissionEntry.beneficiary_type == "broker",
            CommissionEntry.charge_id.in_(list(paid)),
            CommissionEntry.status.not_in(("paid", "cancelled")),
        )
    ).all()
    if not entries:
        return []
    already = set(db.scalars(select(CommissionPaymentBatchItem.commission_entry_id).where(
        CommissionPaymentBatchItem.organization_id == organization_id,
        CommissionPaymentBatchItem.commission_entry_id.in_([entry.id for entry in entries]),
    )).all())
    return [(entry, paid[entry.charge_id]) for entry in entries if entry.id not in already and entry.charge_id in paid]


def _ensure_batches(db: Session, context: UserContext, competence: date) -> list[CommissionPaymentBatch]:
    competence = competence.replace(day=1)
    if date.today() <= _month_end(competence):
        raise HTTPException(409, "O lote só é liberado após o encerramento do mês de recebimento.")
    # garante que todo recebimento conciliado no mês tenha sua comissão materializada
    start_at, end_at = _paid_charge_window(competence)
    charges = db.scalars(select(RentCharge).where(
        RentCharge.organization_id == context.user.organization_id,
        RentCharge.status == "paid",
        RentCharge.paid_at.is_not(None),
        RentCharge.paid_at >= start_at,
        RentCharge.paid_at < end_at,
    )).all()
    charge_ids = [charge.id for charge in charges]
    settlements = {
        row.charge_id: row
        for row in (
            db.scalars(select(FinancialSettlement).where(
                FinancialSettlement.organization_id == context.user.organization_id,
                FinancialSettlement.charge_id.in_(charge_ids),
            )).all()
            if charge_ids else []
        )
    }
    for charge in charges:
        settlement = settlements.get(charge.id)
        if settlement:
            generate_commissions_for_charge(db, charge=charge, settlement=settlement)
    db.flush()

    organization = db.get(Organization, context.user.organization_id)
    grouped: dict[UUID, list[tuple[CommissionEntry, RentCharge]]] = {}
    for entry, charge in _eligible_batch_entries(db, context.user.organization_id, competence):
        grouped.setdefault(entry.beneficiary_person_id, []).append((entry, charge))

    created: list[CommissionPaymentBatch] = []
    for person_id, rows in grouped.items():
        existing = db.scalar(select(CommissionPaymentBatch).where(
            CommissionPaymentBatch.organization_id == context.user.organization_id,
            CommissionPaymentBatch.beneficiary_person_id == person_id,
            CommissionPaymentBatch.competence == competence,
        ))
        if existing:
            continue
        broker = db.get(Person, person_id)
        total = sum((money(entry.amount) for entry, _ in rows), Decimal("0.00"))
        month_name = competence.strftime("%m/%Y")
        batch = CommissionPaymentBatch(
            organization_id=context.user.organization_id,
            beneficiary_person_id=person_id,
            beneficiary_name=broker.name if broker else rows[0][0].beneficiary_name,
            competence=competence,
            status="report_released",
            total_amount=total,
            broker_legal_name=(broker.billing_legal_name if broker else None) or (broker.name if broker else rows[0][0].beneficiary_name),
            broker_document_number=(broker.billing_document_number if broker else None) or (broker.document_number if broker else None),
            organization_legal_name=organization.legal_name if organization else "Imobiliária",
            organization_document_number=organization.document_number if organization else None,
            service_description=f"Serviços de intermediação imobiliária prestados na competência {month_name}, conforme Relatório de Comissões.",
            report_snapshot={},
            payment_due_date=_payment_date(competence),
        )
        db.add(batch); db.flush()
        for entry, charge in rows:
            lease = db.get(LeaseContract, entry.lease_contract_id) if entry.lease_contract_id else None
            property_snapshot = dict(charge.property_snapshot or {})
            tenants = list(charge.tenant_snapshot or [])
            snapshot = {
                "commission_code": f"COM-{entry.internal_number:06d}",
                "source_code": entry.source_code,
                "lease_code": f"LOC-{lease.internal_number:06d}" if lease else None,
                "property_code": str(property_snapshot.get("code") or property_snapshot.get("property_code") or ""),
                "property_address": property_snapshot.get("address") or {},
                "tenant_name": (tenants[0].get("name") if tenants else None),
                "paid_at": charge.paid_at.isoformat() if charge.paid_at else None,
                "rent_amount": str(charge.rent_amount),
                "basis_amount": str(entry.basis_amount),
                "commission_amount": str(entry.amount),
            }
            db.add(CommissionPaymentBatchItem(
                organization_id=context.user.organization_id,
                batch_id=batch.id,
                commission_entry_id=entry.id,
                amount=entry.amount,
                snapshot=snapshot,
            ))
        batch.service_description = f"Serviços de intermediação imobiliária prestados na competência {month_name}, conforme Relatório de Comissões nº {_batch_code(batch)}."
        batch.report_snapshot = {
            "protocol": _batch_code(batch),
            "beneficiary_name": batch.beneficiary_name,
            "broker_legal_name": batch.broker_legal_name,
            "broker_document_number": batch.broker_document_number,
            "organization_legal_name": batch.organization_legal_name,
            "organization_document_number": batch.organization_document_number,
            "service_description": batch.service_description,
            "total_amount": str(batch.total_amount),
        }
        db.flush()
        if broker and broker.email:
            try:
                send_email_message(
                    recipient=broker.email,
                    subject=f"{_batch_code(batch)} · relatório de comissões liberado",
                    text_body=(
                        f"Olá, {broker.name}.\n\nSeu relatório de comissões da competência {month_name} está liberado no ERP. "
                        f"Valor total: R$ {batch.total_amount:.2f}. Gere o relatório e emita a Nota Fiscal conforme os dados informados pelo sistema.\n\n"
                        f"Previsão de pagamento: {batch.payment_due_date:%d/%m/%Y}, condicionada à aprovação do Financeiro."
                    ),
                    organization_name=organization.display_name if organization else "Imobiliária",
                    config=smtp_config_for_organization(db, context.user.organization_id),
                )
                batch.reminder_sent_at = datetime.now(timezone.utc)
            except EmailDeliveryError as exc:
                batch.reminder_error = str(exc)
        created.append(batch)
    db.flush()
    return created


@router.post("/batches/ensure")
def ensure_payment_batches(
    request: Request,
    competence: date = Query(...),
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
):
    created = _ensure_batches(db, context, competence)
    _audit(db, request, context, "finance.commission_batches.generated", "commission_payment_batch", competence.isoformat(), {"created": len(created)})
    db.commit()
    rows = db.scalars(select(CommissionPaymentBatch).where(
        CommissionPaymentBatch.organization_id == context.user.organization_id,
        CommissionPaymentBatch.competence == competence.replace(day=1),
    ).order_by(CommissionPaymentBatch.internal_number.desc())).all()
    return [_batch_response(db, row) for row in rows]




@router.get("/batches/mine")
def list_my_payment_batches(
    context: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    broker = _broker_for_user(db, context)
    if broker is None:
        raise HTTPException(404, "Usuário autenticado não está vinculado a um cadastro de corretor pelo mesmo e-mail.")
    today = date.today()
    previous_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    if today > _month_end(previous_month):
        _ensure_batches(db, context, previous_month)
    rows = db.scalars(select(CommissionPaymentBatch).where(
        CommissionPaymentBatch.organization_id == context.user.organization_id,
        CommissionPaymentBatch.beneficiary_person_id == broker.id,
    ).order_by(CommissionPaymentBatch.internal_number.desc()).limit(60)).all()
    payload = [_batch_response(db, row) for row in rows]
    db.commit()
    return payload


@router.get("/batches")
def list_payment_batches(
    competence: date | None = Query(default=None),
    beneficiary_person_id: UUID | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
):
    stmt = select(CommissionPaymentBatch).where(CommissionPaymentBatch.organization_id == context.user.organization_id)
    if competence:
        stmt = stmt.where(CommissionPaymentBatch.competence == competence.replace(day=1))
    if beneficiary_person_id:
        stmt = stmt.where(CommissionPaymentBatch.beneficiary_person_id == beneficiary_person_id)
    rows = db.scalars(stmt.order_by(CommissionPaymentBatch.internal_number.desc()).limit(300)).all()
    payload = [_batch_response(db, row) for row in rows]
    db.commit()
    return payload


@router.post("/batches/{batch_id}/report")
def issue_batch_report(
    batch_id: UUID,
    request: Request,
    context: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    batch = db.scalar(select(CommissionPaymentBatch).where(
        CommissionPaymentBatch.id == batch_id,
        CommissionPaymentBatch.organization_id == context.user.organization_id,
    ))
    if batch is None:
        raise HTTPException(404, "Lote de comissão não encontrado.")
    _authorize_batch_access(db, context, batch)
    if batch.status not in {"report_released", "report_issued", "returned"}:
        raise HTTPException(409, "O relatório deste lote não pode ser emitido neste status.")
    if batch.status != "returned":
        batch.status = "report_issued"
    batch.report_issued_at = batch.report_issued_at or datetime.now(timezone.utc)
    items = _batch_items_payload(db, batch)
    pdf = build_commission_batch_pdf(batch=batch, items=items)
    _audit(db, request, context, "finance.commission_batch.report_issued", "commission_payment_batch", str(batch.id), {"protocol": _batch_code(batch)})
    db.commit()
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{_batch_code(batch)}.pdf"'})


@router.post("/batches/{batch_id}/invoice")
async def upload_batch_invoice(
    batch_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    context: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    batch = db.scalar(select(CommissionPaymentBatch).where(
        CommissionPaymentBatch.id == batch_id,
        CommissionPaymentBatch.organization_id == context.user.organization_id,
    ))
    if batch is None:
        raise HTTPException(404, "Lote de comissão não encontrado.")
    _authorize_batch_access(db, context, batch)
    if batch.status not in {"report_issued", "returned"}:
        raise HTTPException(409, "Emita o relatório antes de anexar a Nota Fiscal.")
    filename = (file.filename or "nota-fiscal.pdf").replace("..", "-").replace("/", "-").replace("\\", "-")
    content = await file.read()
    if not content or len(content) > 12 * 1024 * 1024:
        raise HTTPException(422, "A Nota Fiscal deve possuir até 12 MB.")
    content_type = file.content_type or "application/pdf"
    if content_type not in {"application/pdf", "image/png", "image/jpeg"}:
        raise HTTPException(422, "Envie a Nota Fiscal em PDF, PNG ou JPG.")
    storage = get_document_storage()
    object_name = f"imob-erp/{context.user.organization_id}/commissions/{_batch_code(batch)}/{filename}"
    try:
        reference = storage.upload_bytes(object_name=object_name, content=content, content_type=content_type)
    except DocumentStorageError as exc:
        raise HTTPException(503, str(exc)) from exc
    batch.invoice_reference = reference
    batch.invoice_filename = filename
    batch.invoice_uploaded_at = datetime.now(timezone.utc)
    batch.finance_review_notes = None
    batch.status = "awaiting_finance_approval"
    _audit(db, request, context, "finance.commission_batch.invoice_uploaded", "commission_payment_batch", str(batch.id), {"filename": filename})
    db.commit()
    return _batch_response(db, batch)


@router.get("/batches/{batch_id}/invoice")
def download_batch_invoice(
    batch_id: UUID,
    context: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    batch = db.scalar(select(CommissionPaymentBatch).where(
        CommissionPaymentBatch.id == batch_id,
        CommissionPaymentBatch.organization_id == context.user.organization_id,
    ))
    if batch is None or not batch.invoice_reference:
        raise HTTPException(404, "Nota Fiscal não encontrada.")
    _authorize_batch_access(db, context, batch)
    try:
        content = get_document_storage().download_bytes(batch.invoice_reference)
    except DocumentStorageError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{batch.invoice_filename or "nota-fiscal.pdf"}"'})


@router.post("/batches/{batch_id}/approve")
def approve_batch(
    batch_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
):
    batch = db.scalar(select(CommissionPaymentBatch).where(
        CommissionPaymentBatch.id == batch_id,
        CommissionPaymentBatch.organization_id == context.user.organization_id,
    ))
    if batch is None:
        raise HTTPException(404, "Lote de comissão não encontrado.")
    if batch.status != "awaiting_finance_approval" or not batch.invoice_reference:
        raise HTTPException(409, "O lote precisa estar com Nota Fiscal anexada e aguardando aprovação.")
    broker = db.get(Person, batch.beneficiary_person_id)
    if not batch.broker_legal_name or not batch.broker_document_number:
        raise HTTPException(422, "Informe razão social e CNPJ do corretor antes da aprovação.")
    batch.status = "scheduled"
    batch.approved_by_user_id = context.user.id
    batch.approved_at = datetime.now(timezone.utc)
    batch.finance_review_notes = None
    batch.payment_due_date = _payment_date(batch.competence, date.today())
    for row in db.scalars(select(CommissionPaymentBatchItem).where(CommissionPaymentBatchItem.batch_id == batch.id)).all():
        entry = db.get(CommissionEntry, row.commission_entry_id)
        if not entry:
            continue
        entry.status = "approved"
        entry.approved_by_user_id = context.user.id
        entry.approved_at = batch.approved_at
        if entry.financial_title_id:
            title = db.get(FinancialTitle, entry.financial_title_id)
            if title and title.status != "cancelled":
                title.category = _treasury_category(entry)
                title.due_date = batch.payment_due_date
                title.status = "pending" if title.settled_amount < title.amount else "settled"
    _audit(db, request, context, "finance.commission_batch.approved", "commission_payment_batch", str(batch.id), {"payment_due_date": batch.payment_due_date.isoformat()})
    db.commit()
    return _batch_response(db, batch)


@router.post("/batches/{batch_id}/return")
def return_batch(
    batch_id: UUID,
    request: Request,
    reason: str = Query(..., min_length=3, max_length=1000),
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
):
    batch = db.scalar(select(CommissionPaymentBatch).where(
        CommissionPaymentBatch.id == batch_id,
        CommissionPaymentBatch.organization_id == context.user.organization_id,
    ))
    if batch is None:
        raise HTTPException(404, "Lote de comissão não encontrado.")
    if batch.status != "awaiting_finance_approval":
        raise HTTPException(409, "Somente lotes em análise podem ser devolvidos.")
    batch.status = "returned"
    batch.finance_review_notes = reason.strip()
    _audit(db, request, context, "finance.commission_batch.returned", "commission_payment_batch", str(batch.id), {"reason": reason.strip()})
    db.commit()
    return _batch_response(db, batch)


@router.get("/rules", response_model=list[CommissionRuleResponse])
def list_rules(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[CommissionRuleResponse]:
    items = db.scalars(
        select(CommissionRule)
        .where(CommissionRule.organization_id == context.user.organization_id)
        .order_by(CommissionRule.priority, CommissionRule.internal_number)
    ).all()
    return [_rule_response(item) for item in items]


@router.post("/rules", response_model=CommissionRuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: CommissionRuleCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> CommissionRuleResponse:
    person = _person(db, context.user.organization_id, payload.beneficiary_person_id)
    item = CommissionRule(
        organization_id=context.user.organization_id,
        name=payload.name.strip(),
        event_type=payload.event_type,
        basis=payload.basis,
        calculation_type=payload.calculation_type,
        value=Decimal(str(payload.value)),
        beneficiary_type=payload.beneficiary_type,
        beneficiary_person_id=person.id,
        beneficiary_name=person.name,
        property_id=payload.property_id,
        lease_contract_id=payload.lease_contract_id,
        due_days=payload.due_days,
        priority=payload.priority,
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        request,
        context,
        "finance.commission_rule.created",
        "commission_rule",
        str(item.id),
        {"name": item.name, "beneficiary": item.beneficiary_name},
    )
    db.commit()
    return _rule_response(item)


@router.put("/rules/{rule_id}", response_model=CommissionRuleResponse)
def update_rule(
    rule_id: UUID,
    payload: CommissionRuleUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> CommissionRuleResponse:
    item = db.scalar(
        select(CommissionRule).where(
            CommissionRule.id == rule_id,
            CommissionRule.organization_id == context.user.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Regra de comissão não encontrada.")
    person = _person(db, context.user.organization_id, payload.beneficiary_person_id)
    item.name = payload.name.strip()
    item.event_type = payload.event_type
    item.basis = payload.basis
    item.calculation_type = payload.calculation_type
    item.value = Decimal(str(payload.value))
    item.beneficiary_type = payload.beneficiary_type
    item.beneficiary_person_id = person.id
    item.beneficiary_name = person.name
    item.property_id = payload.property_id
    item.lease_contract_id = payload.lease_contract_id
    item.due_days = payload.due_days
    item.priority = payload.priority
    item.is_active = payload.is_active
    item.notes = (payload.notes or "").strip() or None
    _audit(
        db,
        request,
        context,
        "finance.commission_rule.updated",
        "commission_rule",
        str(item.id),
        {"active": item.is_active, "beneficiary": item.beneficiary_name},
    )
    db.commit()
    return _rule_response(item)


@router.post("/generate", response_model=list[CommissionEntryResponse])
def generate_entries(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> list[CommissionEntryResponse]:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="Período inválido.")
    start_at = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end_exclusive_date = end_date + timedelta(days=1)
    end_at = datetime(end_exclusive_date.year, end_exclusive_date.month, end_exclusive_date.day, tzinfo=timezone.utc)
    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == context.user.organization_id,
            RentCharge.status == "paid",
            RentCharge.paid_at.is_not(None),
            RentCharge.paid_at >= start_at,
            RentCharge.paid_at < end_at,
        )
    ).all()
    charge_ids = [charge.id for charge in charges]
    settlements = {
        item.charge_id: item
        for item in (
            db.scalars(
                select(FinancialSettlement).where(
                    FinancialSettlement.organization_id == context.user.organization_id,
                    FinancialSettlement.charge_id.in_(charge_ids),
                )
            ).all()
            if charge_ids else []
        )
    }
    created: list[CommissionEntry] = []
    for charge in charges:
        settlement = settlements.get(charge.id)
        if settlement:
            created.extend(generate_commissions_for_charge(db, charge=charge, settlement=settlement))
    _audit(
        db,
        request,
        context,
        "finance.commissions.generated",
        "commission_batch",
        f"{start_date}:{end_date}",
        {"created": len(created)},
    )
    db.commit()
    return [_entry_response(db, item) for item in created]


@router.get("", response_model=list[CommissionEntryResponse])
def list_entries(
    competence: date | None = Query(default=None),
    entry_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[CommissionEntryResponse]:
    stmt = select(CommissionEntry).where(
        CommissionEntry.organization_id == context.user.organization_id
    )
    if competence:
        stmt = stmt.where(CommissionEntry.competence == competence.replace(day=1))
    items = db.scalars(
        stmt.order_by(CommissionEntry.due_date.desc(), CommissionEntry.internal_number.desc()).limit(500)
    ).all()
    responses = [_entry_response(db, item) for item in items]
    db.commit()
    return [item for item in responses if not entry_status or item.status == entry_status]


@router.post("/{entry_id}/approve", response_model=CommissionEntryResponse)
def approve_entry(
    entry_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> CommissionEntryResponse:
    item = db.scalar(
        select(CommissionEntry).where(
            CommissionEntry.id == entry_id,
            CommissionEntry.organization_id == context.user.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    sync_commission_status(db, item)
    if item.status in {"paid", "cancelled"}:
        raise HTTPException(status_code=409, detail="Esta comissão não pode mais ser aprovada.")

    title = db.get(FinancialTitle, item.financial_title_id) if item.financial_title_id else None
    if title is None:
        raise HTTPException(status_code=409, detail="A obrigação financeira desta comissão não foi encontrada.")
    if title.status == "cancelled":
        raise HTTPException(status_code=409, detail="A obrigação financeira desta comissão está cancelada.")

    # O motor atual de Tesouraria reutiliza o fluxo genérico de FinancialTitle.
    # A CommissionEntry e o source_snapshot preservam a origem para relatórios/DRE;
    # a categoria identifica corretamente corretor, angariador ou outro beneficiário.
    title.category = _treasury_category(item)
    title.source_type = "manual"
    title.status = "pending" if title.settled_amount < title.amount else "settled"
    snapshot = dict(title.source_snapshot or {})
    snapshot["financial_origin"] = "commission"
    snapshot["commission_entry_id"] = str(item.id)
    snapshot["beneficiary_type"] = item.beneficiary_type
    title.source_snapshot = snapshot
    item.status = "approved"
    item.approved_by_user_id = context.user.id
    item.approved_at = datetime.now(timezone.utc)
    _audit(
        db,
        request,
        context,
        "finance.commission.approved",
        "commission_entry",
        str(item.id),
        {
            "amount": str(item.amount),
            "beneficiary": item.beneficiary_name,
            "category": title.category,
            "financial_title_id": str(title.id),
            "treasury_eligible": True,
        },
    )
    db.commit()
    return _entry_response(db, item)


@router.post("/{entry_id}/cancel", response_model=CommissionEntryResponse)
def cancel_entry(
    entry_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> CommissionEntryResponse:
    item = db.scalar(
        select(CommissionEntry).where(
            CommissionEntry.id == entry_id,
            CommissionEntry.organization_id == context.user.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    sync_commission_status(db, item)
    if item.status == "paid":
        raise HTTPException(status_code=409, detail="Comissão já paga não pode ser cancelada.")
    item.status = "cancelled"
    if item.financial_title_id:
        title = db.get(FinancialTitle, item.financial_title_id)
        if title and title.status != "settled":
            title.status = "cancelled"
    _audit(
        db,
        request,
        context,
        "finance.commission.cancelled",
        "commission_entry",
        str(item.id),
    )
    db.commit()
    return _entry_response(db, item)
