from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.advanced_models import DelinquencyCase
from app.domains.finance.delinquency_models import DelinquencyWorkflow
from app.domains.finance.delinquency_schemas import (
    DelinquencyActionRequest,
    DelinquencyCaseResponse,
    DelinquencyGuaranteeRequest,
    DelinquencyOverviewResponse,
    DelinquencyPromiseRequest,
    DelinquencyWorkflowResponse,
)
from app.domains.finance.delinquency_service import (
    complete_agenda_tasks,
    ensure_workflow,
    guarantee_label,
    pending_agenda_tasks,
    refresh_delinquency_cases,
    schedule_next_action,
    stage_days,
    suggested_action,
)
from app.domains.finance.models import RentCharge
from app.domains.finance.service import money
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.leases.models import LeaseContract

router = APIRouter(prefix="/delinquency")


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    action: str,
    entity_id: str | None,
    after: dict | None = None,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type="delinquency_case",
        entity_id=entity_id,
        after_data=after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )


def _load_case(db: Session, organization_id: UUID, case_id: UUID) -> DelinquencyCase:
    item = db.scalar(
        select(DelinquencyCase).where(
            DelinquencyCase.id == case_id,
            DelinquencyCase.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Caso de inadimplência não encontrado.")
    return item


def _charge(db: Session, item: DelinquencyCase) -> RentCharge:
    charge = db.get(RentCharge, item.charge_id)
    if charge is None:
        raise HTTPException(status_code=409, detail="Cobrança da inadimplência não foi encontrada.")
    return charge


def _lease(db: Session, item: DelinquencyCase) -> LeaseContract | None:
    return db.get(LeaseContract, item.lease_contract_id)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _tenant_contacts(charge: RentCharge) -> list[dict]:
    result: list[dict] = []
    for row in list(charge.tenant_snapshot or []):
        if not isinstance(row, dict):
            continue
        result.append({
            "name": str(row.get("name") or "Locatário"),
            "email": str(row.get("email") or "").strip() or None,
            "phone": str(row.get("phone") or "").strip() or None,
        })
    return result or [{"name": "Locatário", "email": None, "phone": None}]


def _workflow_response(item: DelinquencyWorkflow) -> DelinquencyWorkflowResponse:
    return DelinquencyWorkflowResponse(
        guarantee_type=item.guarantee_type,
        guarantee_label=guarantee_label(item.guarantee_type),
        guarantee_provider_name=item.guarantee_provider_name,
        guarantee_policy_number=item.guarantee_policy_number,
        guarantee_status=item.guarantee_status,
        guarantee_protocol=item.guarantee_protocol,
        claimed_amount=float(item.claimed_amount) if item.claimed_amount is not None else None,
        approved_amount=float(item.approved_amount) if item.approved_amount is not None else None,
        received_amount=float(item.received_amount) if item.received_amount is not None else None,
        guarantee_submitted_at=item.guarantee_submitted_at,
        guarantee_approved_at=item.guarantee_approved_at,
        guarantee_received_at=item.guarantee_received_at,
        guarantee_rejected_at=item.guarantee_rejected_at,
        guarantee_payment_reference=item.guarantee_payment_reference,
        promise_amount=float(item.promise_amount) if item.promise_amount is not None else None,
        promise_due_date=item.promise_due_date,
        promise_status=item.promise_status,
        promise_recorded_at=item.promise_recorded_at,
        promise_broken_at=item.promise_broken_at,
        notes=item.notes,
        external_submission_performed=False,
    )


def _response(db: Session, item: DelinquencyCase) -> DelinquencyCaseResponse:
    charge = _charge(db, item)
    lease = _lease(db, item)
    workflow = ensure_workflow(db, item, charge, lease)
    days = max(0, (date.today() - charge.due_date).days) if charge.status == "overdue" else 0
    first_days, followup_days, critical_days = stage_days(db, charge, item)
    property_code = str((charge.property_snapshot or {}).get("code") or "—")
    contacts = _tenant_contacts(charge)
    return DelinquencyCaseResponse(
        id=item.id,
        code=f"INA-{item.internal_number:05d}",
        charge_id=charge.id,
        charge_code=f"COB-{charge.internal_number:06d}",
        lease_contract_id=item.lease_contract_id,
        lease_code=f"LOC-{lease.internal_number:06d}" if lease else "LOC-—",
        property_id=item.property_id,
        property_code=property_code,
        tenant_name=contacts[0]["name"],
        tenant_contacts=contacts,
        due_date=charge.due_date,
        amount=float(money(charge.gross_amount)),
        days_overdue=days,
        first_contact_after_days=first_days,
        followup_after_days=followup_days,
        critical_after_days=critical_days,
        critical=days >= critical_days and item.status != "resolved",
        status=item.status,
        suggested_action=suggested_action(
            item,
            workflow,
            days_overdue=days,
            first_days=first_days,
            followup_days=followup_days,
        ),
        insurer_protocol=item.insurer_protocol,
        assigned_user_id=item.assigned_user_id,
        pending_agenda_tasks=pending_agenda_tasks(db, item),
        opened_at=item.opened_at,
        critical_at=item.critical_at,
        last_contact_at=item.last_contact_at,
        next_action_at=item.next_action_at,
        insurer_triggered_at=item.insurer_triggered_at,
        resolved_at=item.resolved_at,
        notes=item.notes,
        action_log=list(item.action_log or []),
        workflow=_workflow_response(workflow),
    )


def _append_log(item: DelinquencyCase, *, action: str, actor_user_id: UUID, notes: str | None = None, **extra) -> None:
    now = datetime.now(timezone.utc)
    row = {
        "at": now.isoformat(),
        "action": action,
        "actor_user_id": str(actor_user_id),
        "notes": notes,
        "source": "internal_user",
    }
    row.update(extra)
    item.action_log = [*list(item.action_log or []), row]


def _refresh_and_commit(db: Session, organization_id: UUID) -> list[DelinquencyCase]:
    items = refresh_delinquency_cases(db, organization_id=organization_id)
    db.commit()
    return items


@router.get("/overview", response_model=DelinquencyOverviewResponse)
def overview(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> DelinquencyOverviewResponse:
    items = _refresh_and_commit(db, context.user.organization_id)
    active = [item for item in items if item.status != "resolved"]
    charges = {item.charge_id: db.get(RentCharge, item.charge_id) for item in active}
    workflows = {
        item.id: ensure_workflow(db, item, charges[item.charge_id], _lease(db, item))
        for item in active if charges.get(item.charge_id) is not None
    }
    today = date.today()
    overdue_amount = sum((money(charges[item.charge_id].gross_amount) for item in active if charges.get(item.charge_id)), Decimal("0.00"))
    critical = [
        item for item in active
        if charges.get(item.charge_id) and (today - charges[item.charge_id].due_date).days >= item.critical_after_days
    ]
    critical_amount = sum((money(charges[item.charge_id].gross_amount) for item in critical if charges.get(item.charge_id)), Decimal("0.00"))
    return DelinquencyOverviewResponse(
        open_cases=len(active),
        critical_cases=len(critical),
        overdue_amount=float(overdue_amount),
        critical_amount=float(critical_amount),
        promises_pending=sum(1 for flow in workflows.values() if flow.promise_status == "pending"),
        promises_broken=sum(1 for flow in workflows.values() if flow.promise_status == "broken"),
        guarantees_available=sum(1 for flow in workflows.values() if flow.guarantee_status in {"available", "prepared"}),
        guarantees_submitted=sum(1 for flow in workflows.values() if flow.guarantee_status in {"submitted", "under_review", "approved"}),
        guarantees_received=sum(1 for flow in workflows.values() if flow.guarantee_status == "received"),
        guarantees_received_amount=float(sum((money(flow.received_amount) for flow in workflows.values() if flow.guarantee_status == "received"), Decimal("0.00"))),
    )


@router.post("/refresh", response_model=list[DelinquencyCaseResponse])
def refresh_cases(
    request: Request,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[DelinquencyCaseResponse]:
    items = refresh_delinquency_cases(db, organization_id=context.user.organization_id)
    _audit(db, request, context, "finance.delinquency.refreshed", None, {"cases": len(items)})
    db.commit()
    return [_response(db, item) for item in items]


@router.get("", response_model=list[DelinquencyCaseResponse])
def list_cases(
    case_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[DelinquencyCaseResponse]:
    items = _refresh_and_commit(db, context.user.organization_id)
    if case_status:
        items = [item for item in items if item.status == case_status]
    charge_dates = {
        item.charge_id: (db.get(RentCharge, item.charge_id).due_date if db.get(RentCharge, item.charge_id) else date.max)
        for item in items
    }
    items.sort(key=lambda item: (item.status == "resolved", charge_dates[item.charge_id]))
    return [_response(db, item) for item in items]


@router.post("/{case_id}/action", response_model=DelinquencyCaseResponse)
def case_action(
    case_id: UUID,
    payload: DelinquencyActionRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> DelinquencyCaseResponse:
    item = _load_case(db, context.user.organization_id, case_id)
    charge = _charge(db, item)
    lease = _lease(db, item)
    workflow = ensure_workflow(db, item, charge, lease, actor_user_id=context.user.id)
    now = datetime.now(timezone.utc)
    previous = item.status

    if payload.status == "resolved" and charge.status == "overdue":
        raise HTTPException(status_code=409, detail="A cobrança continua em aberto. Registre o recebimento ou cancelamento antes de encerrar a inadimplência.")

    item.status = payload.status
    if payload.notes is not None:
        item.notes = payload.notes.strip() or None
    item.next_action_at = _utc(payload.next_action_at) if payload.next_action_at else None

    if payload.status in {"contacted", "negotiating"}:
        item.last_contact_at = now
        complete_agenda_tasks(db, item, source_types={"delinquency_first_contact"})
        if payload.status == "negotiating":
            complete_agenda_tasks(db, item, source_types={"delinquency_followup"})

    if payload.status == "insurer_triggered":
        days = max(0, (date.today() - charge.due_date).days)
        if days < item.critical_after_days:
            raise HTTPException(status_code=409, detail="O caso ainda não atingiu o marco crítico para acionamento da garantia.")
        if workflow.guarantee_type == "none":
            raise HTTPException(status_code=409, detail="Este contrato não possui garantia cadastrada.")
        item.insurer_triggered_at = item.insurer_triggered_at or now
        item.insurer_protocol = (payload.insurer_protocol or item.insurer_protocol or "").strip() or None
        workflow.guarantee_status = "submitted"
        workflow.guarantee_submitted_at = workflow.guarantee_submitted_at or now
        workflow.guarantee_protocol = item.insurer_protocol
        workflow.claimed_amount = workflow.claimed_amount or money(charge.gross_amount)
        complete_agenda_tasks(db, item, source_types={"delinquency_guarantee"})

    if payload.status == "resolved":
        item.resolved_at = now
        complete_agenda_tasks(db, item)
    elif previous == "resolved":
        item.resolved_at = None

    if item.next_action_at:
        schedule_next_action(
            db,
            case=item,
            when=item.next_action_at,
            title=f"Próximo passo · INA-{item.internal_number:05d}",
            description="Revisar o caso de inadimplência e registrar o andamento no Financeiro.",
        )

    _append_log(
        item,
        action=payload.status,
        actor_user_id=context.user.id,
        notes=payload.notes,
        channel=payload.channel,
        insurer_protocol=item.insurer_protocol,
    )
    _audit(db, request, context, "finance.delinquency.action", str(item.id), {"from": previous, "to": item.status, "channel": payload.channel, "protocol": item.insurer_protocol})
    db.commit()
    return _response(db, item)


@router.post("/{case_id}/promise", response_model=DelinquencyCaseResponse)
def record_promise(
    case_id: UUID,
    payload: DelinquencyPromiseRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> DelinquencyCaseResponse:
    item = _load_case(db, context.user.organization_id, case_id)
    charge = _charge(db, item)
    lease = _lease(db, item)
    workflow = ensure_workflow(db, item, charge, lease, actor_user_id=context.user.id)
    today = date.today()
    if charge.status != "overdue" or item.status == "resolved":
        raise HTTPException(status_code=409, detail="A cobrança não está em inadimplência ativa.")
    if payload.due_date < today:
        raise HTTPException(status_code=422, detail="A promessa de pagamento não pode ficar no passado.")
    if payload.due_date > today + timedelta(days=90):
        raise HTTPException(status_code=422, detail="A promessa de pagamento deve ficar dentro dos próximos 90 dias.")

    full_amount = money(charge.gross_amount)
    promised = money(payload.amount) if payload.amount is not None else full_amount
    if promised != full_amount:
        raise HTTPException(status_code=422, detail="O Imob não aceita promessa parcial para esta cobrança. Informe o valor integral em aberto.")

    now = datetime.now(timezone.utc)
    workflow.promise_amount = full_amount
    workflow.promise_due_date = payload.due_date
    workflow.promise_status = "pending"
    workflow.promise_recorded_at = now
    workflow.promise_broken_at = None
    if payload.notes is not None:
        workflow.notes = payload.notes.strip() or None
    item.status = "negotiating"
    item.last_contact_at = now
    item.next_action_at = datetime.combine(payload.due_date, time(hour=12), tzinfo=timezone.utc)
    complete_agenda_tasks(db, item, source_types={"delinquency_first_contact", "delinquency_followup"})
    schedule_next_action(
        db,
        case=item,
        when=item.next_action_at,
        title=f"Conferir promessa de pagamento · INA-{item.internal_number:05d}",
        description=f"Confirmar o pagamento integral prometido para {payload.due_date.strftime('%d/%m/%Y')}. Se não houver baixa, retomar a régua imediatamente.",
        source_prefix="delinquency_promise",
        priority="high",
    )
    _append_log(
        item,
        action="promise_recorded",
        actor_user_id=context.user.id,
        notes=payload.notes,
        promise_due_date=payload.due_date.isoformat(),
        promise_amount=str(full_amount),
    )
    _audit(db, request, context, "finance.delinquency.promise", str(item.id), {"due_date": payload.due_date.isoformat(), "amount": str(full_amount)})
    db.commit()
    return _response(db, item)


@router.post("/{case_id}/guarantee", response_model=DelinquencyCaseResponse)
def guarantee_action(
    case_id: UUID,
    payload: DelinquencyGuaranteeRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> DelinquencyCaseResponse:
    item = _load_case(db, context.user.organization_id, case_id)
    charge = _charge(db, item)
    lease = _lease(db, item)
    workflow = ensure_workflow(db, item, charge, lease, actor_user_id=context.user.id)
    if workflow.guarantee_type == "none":
        raise HTTPException(status_code=409, detail="Este contrato não possui garantia cadastrada.")

    days = max(0, (date.today() - charge.due_date).days) if charge.status == "overdue" else 0
    critical_states = {"submitted", "under_review", "approved", "rejected", "received"}
    if payload.status in critical_states and days < item.critical_after_days:
        raise HTTPException(status_code=409, detail="O caso ainda não atingiu o marco crítico para registrar o acionamento da garantia.")
    if payload.status in critical_states and charge.status != "overdue":
        raise HTTPException(status_code=409, detail="A cobrança não está mais em atraso.")
    if workflow.guarantee_type == "insurance" and payload.status in {"submitted", "under_review"} and not (payload.protocol or workflow.guarantee_protocol):
        raise HTTPException(status_code=422, detail="Informe o protocolo da seguradora para registrar o acionamento do seguro fiança.")

    gross = money(charge.gross_amount)
    claimed = money(payload.claimed_amount) if payload.claimed_amount is not None else (workflow.claimed_amount or gross)
    if claimed > gross:
        raise HTTPException(status_code=422, detail="O valor acionado da garantia não pode superar o valor em aberto da cobrança.")
    approved = money(payload.approved_amount) if payload.approved_amount is not None else workflow.approved_amount
    if approved is not None and approved > claimed:
        raise HTTPException(status_code=422, detail="O valor aprovado não pode ser maior que o valor acionado.")
    received = money(payload.received_amount) if payload.received_amount is not None else workflow.received_amount
    receipt_limit = approved if approved is not None else claimed
    if received is not None and received > receipt_limit:
        raise HTTPException(status_code=422, detail="O valor recebido da garantia não pode superar o valor aprovado/acionado.")
    if payload.status == "received" and received is None:
        raise HTTPException(status_code=422, detail="Informe o valor efetivamente recebido da garantia.")

    now = datetime.now(timezone.utc)
    workflow.guarantee_status = payload.status
    workflow.guarantee_provider_name = (payload.provider_name or workflow.guarantee_provider_name or "").strip() or None
    workflow.guarantee_policy_number = (payload.policy_number or workflow.guarantee_policy_number or "").strip() or None
    workflow.guarantee_protocol = (payload.protocol or workflow.guarantee_protocol or "").strip() or None
    workflow.claimed_amount = claimed if payload.status not in {"available", "cancelled"} else workflow.claimed_amount
    workflow.approved_amount = approved
    workflow.received_amount = received
    workflow.guarantee_payment_reference = (payload.payment_reference or workflow.guarantee_payment_reference or "").strip() or None
    if payload.notes is not None:
        workflow.notes = payload.notes.strip() or None
    if payload.status == "submitted":
        workflow.guarantee_submitted_at = workflow.guarantee_submitted_at or now
        item.status = "insurer_triggered"
        item.insurer_triggered_at = item.insurer_triggered_at or now
        item.insurer_protocol = workflow.guarantee_protocol
        complete_agenda_tasks(db, item, source_types={"delinquency_guarantee"})
    elif payload.status == "under_review":
        workflow.guarantee_submitted_at = workflow.guarantee_submitted_at or now
        item.status = "insurer_triggered"
        item.insurer_triggered_at = item.insurer_triggered_at or now
        item.insurer_protocol = workflow.guarantee_protocol
    elif payload.status == "approved":
        workflow.guarantee_approved_at = now
        item.status = "insurer_triggered"
    elif payload.status == "rejected":
        workflow.guarantee_rejected_at = now
        item.status = "open"
    elif payload.status == "received":
        workflow.guarantee_received_at = now
        item.status = "insurer_triggered"

    if payload.next_action_at:
        item.next_action_at = _utc(payload.next_action_at)
        schedule_next_action(
            db,
            case=item,
            when=item.next_action_at,
            title=f"Acompanhar garantia · INA-{item.internal_number:05d}",
            description=f"Acompanhar {guarantee_label(workflow.guarantee_type).lower()} e registrar protocolo/retorno. Nenhum envio externo é feito automaticamente pelo Imob.",
            source_prefix="delinquency_guarantee_followup",
            priority="high",
        )

    _append_log(
        item,
        action=f"guarantee_{payload.status}",
        actor_user_id=context.user.id,
        notes=payload.notes,
        protocol=workflow.guarantee_protocol,
        claimed_amount=str(workflow.claimed_amount) if workflow.claimed_amount is not None else None,
        approved_amount=str(workflow.approved_amount) if workflow.approved_amount is not None else None,
        received_amount=str(workflow.received_amount) if workflow.received_amount is not None else None,
        external_submission_performed=False,
    )
    _audit(
        db,
        request,
        context,
        "finance.delinquency.guarantee",
        str(item.id),
        {
            "status": payload.status,
            "guarantee_type": workflow.guarantee_type,
            "protocol": workflow.guarantee_protocol,
            "external_submission_performed": False,
        },
    )
    db.commit()
    return _response(db, item)
