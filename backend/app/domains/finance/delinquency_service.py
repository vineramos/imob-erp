from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.agenda.models import AgendaTask
from app.domains.finance.advanced_models import DelinquencyCase
from app.domains.finance.delinquency_models import DelinquencyWorkflow
from app.domains.finance.models import RentCharge
from app.domains.finance.service import money, operational_defaults, refresh_overdue
from app.domains.leases.models import LeaseContract


GUARANTEE_LABELS = {
    "insurance": "Seguro fiança",
    "deposit": "Caução",
    "capitalization": "Título de capitalização",
    "guarantor": "Fiador",
    "none": "Sem garantia",
}


def guarantee_label(value: str | None) -> str:
    key = (value or "none").strip().lower()
    return GUARANTEE_LABELS.get(key, key.replace("_", " ").title())


def _detail(details: dict, *keys: str) -> str | None:
    for key in keys:
        value = details.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def ensure_workflow(
    db: Session,
    case: DelinquencyCase,
    charge: RentCharge,
    lease: LeaseContract | None,
    *,
    actor_user_id: UUID | None = None,
) -> DelinquencyWorkflow:
    item = db.scalar(select(DelinquencyWorkflow).where(DelinquencyWorkflow.delinquency_case_id == case.id))
    guarantee_type = (lease.guarantee_type if lease else "none") or "none"
    details = dict(lease.guarantee_details or {}) if lease else {}
    provider = _detail(details, "provider_name", "insurer", "insurance_company", "seguradora", "provider")
    policy = _detail(details, "policy_number", "policy", "apolice", "policy_code")
    initial_status = "not_applicable" if guarantee_type == "none" else "available"
    if item is None:
        item = DelinquencyWorkflow(
            organization_id=case.organization_id,
            delinquency_case_id=case.id,
            guarantee_type=guarantee_type,
            guarantee_provider_name=provider,
            guarantee_policy_number=policy,
            guarantee_status=initial_status,
            metadata_snapshot={
                "source": "lease_contract",
                "lease_contract_id": str(charge.lease_contract_id),
                "charge_id": str(charge.id),
            },
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        db.add(item)
        db.flush()
        return item

    if item.guarantee_status in {"not_applicable", "available"}:
        item.guarantee_type = guarantee_type
        item.guarantee_status = initial_status
        if not item.guarantee_provider_name and provider:
            item.guarantee_provider_name = provider
        if not item.guarantee_policy_number and policy:
            item.guarantee_policy_number = policy
    if actor_user_id:
        item.updated_by_user_id = actor_user_id
    return item


def _milestone_at(due_date: date, after_days: int) -> datetime:
    return datetime.combine(due_date + timedelta(days=max(0, after_days)), time(hour=12), tzinfo=timezone.utc)


def ensure_agenda_task(
    db: Session,
    *,
    case: DelinquencyCase,
    source_type: str,
    title: str,
    description: str,
    scheduled_at: datetime,
    priority: str = "normal",
    mandatory: bool = False,
) -> AgendaTask:
    existing = db.scalar(
        select(AgendaTask).where(
            AgendaTask.organization_id == case.organization_id,
            AgendaTask.source_module == "finance",
            AgendaTask.source_type == source_type,
            AgendaTask.source_id == str(case.id),
        )
    )
    if existing is not None:
        if existing.status == "pending":
            existing.assigned_user_id = case.assigned_user_id
            existing.title = title
            existing.description = description
            existing.priority = priority
            existing.mandatory_action = mandatory
        return existing

    task = AgendaTask(
        organization_id=case.organization_id,
        title=title,
        description=description,
        kind="task",
        starts_at=scheduled_at,
        due_at=scheduled_at,
        all_day=True,
        priority=priority,
        status="pending",
        privacy="normal",
        assigned_user_id=case.assigned_user_id,
        source_module="finance",
        source_type=source_type,
        source_id=str(case.id),
        automatic=True,
        mandatory_action=mandatory,
        completion_source="source",
        original_scheduled_at=scheduled_at,
        immutable_history=True,
    )
    db.add(task)
    db.flush()
    return task


def complete_agenda_tasks(
    db: Session,
    case: DelinquencyCase,
    *,
    source_types: Iterable[str] | None = None,
    prefix: str | None = None,
) -> int:
    rows = db.scalars(
        select(AgendaTask).where(
            AgendaTask.organization_id == case.organization_id,
            AgendaTask.source_module == "finance",
            AgendaTask.source_id == str(case.id),
            AgendaTask.status.in_(("pending", "missed")),
        )
    ).all()
    exact = set(source_types or [])
    now = datetime.now(timezone.utc)
    changed = 0
    for task in rows:
        if exact and task.source_type not in exact:
            continue
        if prefix and not str(task.source_type or "").startswith(prefix):
            continue
        task.status = "completed"
        task.completed_at = now
        task.completion_source = "source"
        changed += 1
    return changed


def pending_agenda_tasks(db: Session, case: DelinquencyCase) -> int:
    return len(db.scalars(
        select(AgendaTask).where(
            AgendaTask.organization_id == case.organization_id,
            AgendaTask.source_module == "finance",
            AgendaTask.source_id == str(case.id),
            AgendaTask.status == "pending",
        )
    ).all())


def schedule_next_action(
    db: Session,
    *,
    case: DelinquencyCase,
    when: datetime,
    title: str = "Acompanhar inadimplência",
    description: str = "Revisar o caso e registrar o próximo passo da cobrança.",
    source_prefix: str = "delinquency_next_action",
    priority: str = "high",
) -> AgendaTask:
    key = when.date().strftime("%Y%m%d")
    return ensure_agenda_task(
        db,
        case=case,
        source_type=f"{source_prefix}_{key}",
        title=title,
        description=description,
        scheduled_at=when,
        priority=priority,
        mandatory=True,
    )


def _log_once(case: DelinquencyCase, action: str, detail: str, *, at: datetime) -> None:
    if any(isinstance(row, dict) and row.get("action") == action for row in list(case.action_log or [])):
        return
    case.action_log = [*list(case.action_log or []), {"at": at.isoformat(), "action": action, "detail": detail, "source": "automation"}]


def _stage_days(db: Session, charge: RentCharge, critical_days: int) -> tuple[int, int]:
    defaults = operational_defaults(db, charge.organization_id)
    first = int((charge.admin_terms_snapshot or {}).get("delinquency_first_contact_day") or defaults.get("delinquency_first_contact_day", 1))
    followup = int((charge.admin_terms_snapshot or {}).get("delinquency_followup_day") or defaults.get("delinquency_followup_day", 3))
    first = max(1, min(first, max(1, critical_days)))
    followup = max(first, min(followup, max(first, critical_days)))
    return first, followup


def stage_days(db: Session, charge: RentCharge, case: DelinquencyCase) -> tuple[int, int, int]:
    first, followup = _stage_days(db, charge, case.critical_after_days)
    return first, followup, case.critical_after_days


def _tenant_name(charge: RentCharge) -> str:
    return next(
        (str(row.get("name")) for row in list(charge.tenant_snapshot or []) if isinstance(row, dict) and row.get("name")),
        "Locatário",
    )


def _charge_code(charge: RentCharge) -> str:
    return f"COB-{charge.internal_number:06d}"


def _task_description(charge: RentCharge, instruction: str) -> str:
    return (
        f"{_charge_code(charge)} · {_tenant_name(charge)} · vencimento {charge.due_date.strftime('%d/%m/%Y')} · "
        f"valor {money(charge.gross_amount)}. {instruction}"
    )


def refresh_delinquency_cases(
    db: Session,
    *,
    organization_id: UUID,
    today: date | None = None,
) -> list[DelinquencyCase]:
    today = today or date.today()
    refresh_overdue(db, organization_id, today=today)
    # O lock da cobrança serializa dois refreshes concorrentes (ex.: dashboard +
    # lista abrindo ao mesmo tempo) e evita a criação duplicada do caso único.
    charges = db.scalars(
        select(RentCharge)
        .where(RentCharge.organization_id == organization_id)
        .order_by(RentCharge.internal_number)
        .with_for_update()
    ).all()
    charge_by_id = {item.id: item for item in charges}
    existing = {
        item.charge_id: item
        for item in db.scalars(select(DelinquencyCase).where(DelinquencyCase.organization_id == organization_id)).all()
    }
    now = datetime.now(timezone.utc)

    for charge in charges:
        case = existing.get(charge.id)
        if charge.status == "overdue":
            defaults = operational_defaults(db, organization_id)
            critical_days = max(1, int((charge.admin_terms_snapshot or {}).get("delinquency_critical_day") or defaults.get("delinquency_critical_day", 5)))
            days = max(0, (today - charge.due_date).days)
            if case is None:
                case = DelinquencyCase(
                    organization_id=organization_id,
                    charge_id=charge.id,
                    property_id=charge.property_id,
                    lease_contract_id=charge.lease_contract_id,
                    status="open",
                    critical_after_days=critical_days,
                    opened_at=now,
                    action_log=[{
                        "at": now.isoformat(),
                        "action": "opened",
                        "detail": "Caso aberto automaticamente após o vencimento da cobrança.",
                        "source": "automation",
                    }],
                )
                db.add(case)
                db.flush()
                existing[charge.id] = case
            else:
                case.critical_after_days = critical_days
                if case.status == "resolved":
                    case.status = "open"
                    case.resolved_at = None
                    _log_once(case, "reopened", "Caso reaberto porque a cobrança continua em atraso.", at=now)

            lease = db.get(LeaseContract, charge.lease_contract_id)
            workflow = ensure_workflow(db, case, charge, lease)
            first_days, followup_days = _stage_days(db, charge, critical_days)

            if days >= first_days:
                _log_once(case, "ladder_first_contact", f"Régua de cobrança atingiu D+{first_days}: primeiro contato devido.", at=now)
                ensure_agenda_task(
                    db,
                    case=case,
                    source_type="delinquency_first_contact",
                    title=f"1º contato de cobrança · {_charge_code(charge)}",
                    description=_task_description(charge, "Realizar o primeiro contato e registrar canal, retorno e próximo passo no Financeiro."),
                    scheduled_at=_milestone_at(charge.due_date, first_days),
                    priority="normal",
                )

            if days >= followup_days:
                _log_once(case, "ladder_followup", f"Régua de cobrança atingiu D+{followup_days}: acompanhamento devido.", at=now)
                ensure_agenda_task(
                    db,
                    case=case,
                    source_type="delinquency_followup",
                    title=f"Acompanhamento de cobrança · {_charge_code(charge)}",
                    description=_task_description(charge, "Realizar novo contato, avaliar negociação e registrar eventual promessa de pagamento."),
                    scheduled_at=_milestone_at(charge.due_date, followup_days),
                    priority="high",
                )

            if days >= critical_days:
                if case.critical_at is None:
                    case.critical_at = now
                _log_once(case, "critical", f"Atraso atingiu {days} dia(s); limite crítico configurado em D+{critical_days}.", at=now)
                guarantee_instruction = (
                    f"Revisar documentação e preparar o acionamento da garantia ({guarantee_label(workflow.guarantee_type)}). "
                    "O Imob não envia nada à seguradora automaticamente."
                    if workflow.guarantee_type != "none"
                    else "Não há garantia contratual cadastrada; encaminhar o caso para decisão interna."
                )
                ensure_agenda_task(
                    db,
                    case=case,
                    source_type="delinquency_guarantee",
                    title=f"Atraso crítico · {_charge_code(charge)}",
                    description=_task_description(charge, guarantee_instruction),
                    scheduled_at=_milestone_at(charge.due_date, critical_days),
                    priority="urgent",
                    mandatory=True,
                )

            if workflow.promise_status == "pending" and workflow.promise_due_date and workflow.promise_due_date < today:
                workflow.promise_status = "broken"
                workflow.promise_broken_at = workflow.promise_broken_at or now
                case.status = "open"
                _log_once(
                    case,
                    "promise_broken",
                    f"Promessa de pagamento de {workflow.promise_due_date.strftime('%d/%m/%Y')} não foi cumprida.",
                    at=now,
                )
                complete_agenda_tasks(db, case, prefix="delinquency_promise_")
                ensure_agenda_task(
                    db,
                    case=case,
                    source_type=f"delinquency_promise_broken_{workflow.promise_due_date.strftime('%Y%m%d')}",
                    title=f"Promessa não cumprida · {_charge_code(charge)}",
                    description=_task_description(charge, "Retomar a cobrança imediatamente e reavaliar o acionamento da garantia."),
                    scheduled_at=datetime.combine(today, time(hour=12), tzinfo=timezone.utc),
                    priority="urgent",
                    mandatory=True,
                )
        elif case is not None and case.status != "resolved":
            case.status = "resolved"
            case.resolved_at = now
            workflow = db.scalar(select(DelinquencyWorkflow).where(DelinquencyWorkflow.delinquency_case_id == case.id))
            if workflow and workflow.promise_status == "pending":
                workflow.promise_status = "kept" if charge.status == "paid" else "cancelled"
            case.action_log = [
                *list(case.action_log or []),
                {
                    "at": now.isoformat(),
                    "action": "resolved",
                    "detail": f"Caso encerrado automaticamente porque a cobrança está {charge.status}.",
                    "source": "automation",
                },
            ]
            complete_agenda_tasks(db, case)

    db.flush()
    result = list(existing.values())
    result.sort(key=lambda item: (charge_by_id.get(item.charge_id).due_date if charge_by_id.get(item.charge_id) else today, item.opened_at))
    return result


def suggested_action(case: DelinquencyCase, workflow: DelinquencyWorkflow, *, days_overdue: int, first_days: int, followup_days: int) -> str | None:
    if case.status == "resolved":
        return None
    if workflow.promise_status == "broken":
        return "Promessa não cumprida: retomar cobrança e reavaliar a garantia."
    if workflow.promise_status == "pending" and workflow.promise_due_date:
        return f"Acompanhar promessa para {workflow.promise_due_date.strftime('%d/%m/%Y')}."
    if workflow.guarantee_status in {"submitted", "under_review", "approved"}:
        return "Acompanhar o processo da garantia e registrar o próximo retorno."
    if workflow.guarantee_status == "received":
        return "Indenização registrada: revisar a baixa financeira e o tratamento do débito do locatário."
    if days_overdue >= case.critical_after_days:
        if workflow.guarantee_type == "insurance":
            return "Revisar documentação e acionar o seguro fiança."
        if workflow.guarantee_type == "deposit":
            return "Avaliar a caução conforme o contrato e a orientação jurídica."
        if workflow.guarantee_type == "capitalization":
            return "Avaliar o acionamento do título de capitalização."
        if workflow.guarantee_type == "guarantor":
            return "Avaliar o acionamento do fiador."
        return "Caso crítico sem garantia cadastrada: encaminhar para decisão interna."
    if days_overdue >= followup_days:
        return "Realizar acompanhamento da cobrança e avaliar negociação."
    if days_overdue >= first_days:
        return "Realizar o primeiro contato de cobrança."
    return "Aguardar o primeiro marco da régua de cobrança."
