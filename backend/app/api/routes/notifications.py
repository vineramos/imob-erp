from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, load_only

from app.core.database import get_db
from app.domains.agenda.logic import access_map, ensure_agenda_structure
from app.domains.agenda.models import AgendaMeetingParticipant, AgendaMeetingRequest, AgendaTask
from app.domains.contracts.models import AdministrationContract
from app.domains.finance.models import OwnerRepasse, RentCharge
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.foundation.models import AuditLog
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest

router = APIRouter(tags=["notifications"])
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
BR_TZ = ZoneInfo("America/Sao_Paulo")


class NotificationReadPayload(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=100)


def _code(prefix: str, number: int | None) -> str:
    return f"{prefix}{int(number):06d}" if number is not None else prefix.rstrip("-")


def _money(value: Any) -> str:
    if value is None:
        return "—"
    formatted = f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _date_at(value: date) -> datetime:
    return datetime.combine(value, time(hour=12), tzinfo=timezone.utc)


def _expiry_bucket(days: int) -> str:
    if days < 0:
        return "expired"
    for threshold in (7, 30, 60, 90, 120):
        if days <= threshold:
            return str(threshold)
    return "future"


def _expiry_text(days: int) -> str:
    if days < 0:
        return f"Vencido há {abs(days)} dia(s)"
    if days == 0:
        return "Vence hoje"
    return f"Vence em {days} dia(s)"


def _item(
    key: str,
    severity: str,
    category: str,
    title: str,
    subtitle: str,
    module: str,
    route: str,
    event_at: datetime,
    action_label: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "severity": severity,
        "category": category,
        "title": title,
        "subtitle": subtitle,
        "module": module,
        "route": route,
        "event_at": event_at,
        "action_label": action_label,
    }


def _task_scope(db: Session, context: UserContext) -> tuple[list[Any], set[Any], dict[Any, dict]]:
    users, profiles, departments = ensure_agenda_structure(db, context.user.organization_id)
    current = profiles.get(context.user.id)
    grants = access_map(db, context.user.organization_id, context.user.id)
    if current is None:
        return [context.user.id], set(), grants
    if current.access_level in {"director", "admin"}:
        return [user.id for user in users], set(departments), grants
    if current.access_level == "manager" and current.department_id:
        return [user.id for user in users if profiles[user.id].department_id == current.department_id], {current.department_id}, grants
    return [context.user.id], {current.department_id} if current.department_id else set(), grants


def _task_details_allowed(context: UserContext, grants: dict[Any, dict], task: AgendaTask) -> bool:
    if task.assigned_user_id is None or task.assigned_user_id == context.user.id:
        return True
    grant = grants.get(task.assigned_user_id)
    if not grant:
        return False
    return bool(grant.get("private_details" if task.privacy == "private" else "details"))


def _agenda_notifications(db: Session, context: UserContext, now: datetime) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    items: list[dict[str, Any]] = []
    blocked_sources: set[tuple[str, str]] = set()
    user_ids, department_ids, grants = _task_scope(db, context)
    scope = []
    if user_ids:
        scope.append(AgendaTask.assigned_user_id.in_(user_ids))
    if department_ids:
        scope.append(and_(AgendaTask.assigned_user_id.is_(None), AgendaTask.department_id.in_(department_ids)))
    if scope:
        tasks = db.scalars(
            select(AgendaTask).options(load_only(
                AgendaTask.id, AgendaTask.internal_number, AgendaTask.title,
                AgendaTask.starts_at, AgendaTask.priority, AgendaTask.privacy,
                AgendaTask.assigned_user_id, AgendaTask.department_id,
                AgendaTask.source_module, AgendaTask.source_id,
                AgendaTask.automatic, AgendaTask.mandatory_action,
                AgendaTask.reschedule_sequence,
            )).where(
                AgendaTask.organization_id == context.user.organization_id,
                AgendaTask.status == "pending",
                AgendaTask.starts_at <= now,
                or_(*scope),
            ).order_by(AgendaTask.mandatory_action.desc(), AgendaTask.starts_at.asc()).limit(30)
        ).all()
        for task in tasks:
            allowed = _task_details_allowed(context, grants, task)
            if task.automatic and task.mandatory_action and task.source_module and task.source_id:
                blocked_sources.add((task.source_module, task.source_id))
            severity = "critical" if task.mandatory_action else "warning" if task.priority in {"urgent", "high"} else "info"
            title = task.title if allowed else "Tarefa pendente na equipe"
            if task.mandatory_action:
                title = f"Justificativa obrigatória · {title}" if allowed else "Justificativa obrigatória na equipe"
            subtitle = "Conteúdo protegido pela privacidade da agenda." if not allowed else (
                f"{_code('TAR-', task.internal_number)} · pendente desde {task.starts_at.astimezone(BR_TZ).strftime('%d/%m/%Y')}"
                + (f" · {task.reschedule_sequence}º reagendamento" if task.reschedule_sequence else "")
            )
            items.append(_item(
                f"agenda-overdue:{task.id}:{task.reschedule_sequence}", severity, "agenda", title, subtitle, "agenda",
                f"/app/agenda/task/{task.id}" if allowed else "/app/agenda", task.starts_at,
                "Justificar" if task.mandatory_action else "Abrir tarefa",
            ))

    participants = db.scalars(
        select(AgendaMeetingParticipant).where(
            AgendaMeetingParticipant.user_id == context.user.id,
            AgendaMeetingParticipant.status == "pending",
        )
    ).all()
    request_ids = [row.meeting_request_id for row in participants]
    if request_ids:
        requests = db.scalars(
            select(AgendaMeetingRequest).where(
                AgendaMeetingRequest.organization_id == context.user.organization_id,
                AgendaMeetingRequest.id.in_(request_ids),
                AgendaMeetingRequest.status == "pending",
            )
        ).all()
        for request in requests:
            items.append(_item(
                f"meeting-invite:{request.id}:pending", "info", "agenda", "Convite de reunião aguardando resposta",
                request.title, "agenda", "/app/agenda", request.created_at, "Responder",
            ))
    return items, blocked_sources


def _contract_notifications(db: Session, context: UserContext, today: date) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    organization_id = context.user.organization_id
    admin_contracts = db.scalars(
        select(AdministrationContract).where(
            AdministrationContract.organization_id == organization_id,
            AdministrationContract.status == "signed",
            AdministrationContract.end_date.is_not(None),
            AdministrationContract.end_date <= today + timedelta(days=120),
        )
    ).all()
    for contract in admin_contracts:
        if contract.end_date is None:
            continue
        days = (contract.end_date - today).days
        severity = "critical" if days <= 7 else "warning" if days <= 30 else "info"
        address = contract.property_snapshot.get("address", {}) if isinstance(contract.property_snapshot, dict) else {}
        location = address.get("neighborhood") or address.get("city") or "imóvel administrado"
        items.append(_item(
            f"admin-contract-expiry:{contract.id}:{_expiry_bucket(days)}", severity, "contracts",
            f"Contrato de administração {_code('ADM-', contract.internal_number)}", f"{_expiry_text(days)} · {location}",
            "contracts", f"/app/contracts/administration/{contract.id}", _date_at(contract.end_date), "Ver contrato",
        ))

    leases = db.scalars(
        select(LeaseContract).where(
            LeaseContract.organization_id == organization_id,
            LeaseContract.status == "signed",
            LeaseContract.end_date <= today + timedelta(days=120),
        )
    ).all()
    for contract in leases:
        days = (contract.end_date - today).days
        severity = "critical" if days <= 7 else "warning" if days <= 30 else "info"
        tenants = " / ".join(str(row.get("name") or "") for row in (contract.tenant_snapshot or []) if row.get("name")) or "Locatário não informado"
        items.append(_item(
            f"lease-contract-expiry:{contract.id}:{_expiry_bucket(days)}", severity, "contracts",
            f"Locação {_code('LOC-', contract.internal_number)} próxima do término", f"{_expiry_text(days)} · {tenants}",
            "contracts", f"/app/contracts/lease/{contract.id}", _date_at(contract.end_date), "Ver contrato",
        ))
        adjustment_days = (contract.next_adjustment_date - today).days
        if 0 <= adjustment_days <= 30:
            items.append(_item(
                f"lease-adjustment:{contract.id}:{'7' if adjustment_days <= 7 else '30'}",
                "warning" if adjustment_days <= 7 else "info", "contracts",
                f"Reajuste de {_code('LOC-', contract.internal_number)}",
                f"{contract.adjustment_index} · {'hoje' if adjustment_days == 0 else f'em {adjustment_days} dia(s)'}",
                "contracts", f"/app/contracts/lease/{contract.id}", _date_at(contract.next_adjustment_date), "Conferir reajuste",
            ))
    return items


def _finance_notifications(db: Session, context: UserContext, today: date, blocked_sources: set[tuple[str, str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    organization_id = context.user.organization_id
    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.due_date < today,
            RentCharge.paid_at.is_(None),
            RentCharge.cancelled_at.is_(None),
            RentCharge.status.notin_(("paid", "cancelled")),
        ).order_by(RentCharge.due_date.asc()).limit(25)
    ).all()
    for charge in charges:
        if ("finance", str(charge.id)) in blocked_sources:
            continue
        overdue_days = (today - charge.due_date).days
        tenants = " / ".join(str(row.get("name") or "") for row in (charge.tenant_snapshot or []) if row.get("name")) or "Locatário não informado"
        items.append(_item(
            f"charge-overdue:{charge.id}", "critical" if overdue_days >= 5 else "warning", "finance",
            f"Cobrança {_code('COB-', charge.internal_number)} vencida",
            f"{tenants} · {overdue_days} dia(s) · {_money(charge.gross_amount)}", "finance",
            f"/app/finance/charge/{charge.id}", _date_at(charge.due_date), "Abrir cobrança",
        ))

    repasses = db.scalars(
        select(OwnerRepasse).where(
            OwnerRepasse.organization_id == organization_id,
            OwnerRepasse.due_date < today,
            OwnerRepasse.status == "pending",
            OwnerRepasse.paid_at.is_(None),
        ).order_by(OwnerRepasse.due_date.asc()).limit(25)
    ).all()
    for repasse in repasses:
        if ("finance", str(repasse.id)) in blocked_sources:
            continue
        overdue_days = (today - repasse.due_date).days
        items.append(_item(
            f"repasse-overdue:{repasse.id}", "critical" if overdue_days >= 3 else "warning", "finance",
            "Repasse ao proprietário em atraso", f"{repasse.owner_name} · {overdue_days} dia(s) · {_money(repasse.amount)}",
            "finance", f"/app/finance/charge/{repasse.charge_id}", _date_at(repasse.due_date), "Abrir financeiro",
        ))
    return items


def _maintenance_notifications(db: Session, context: UserContext, now: datetime, blocked_sources: set[tuple[str, str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    rows = db.scalars(
        select(MaintenanceRequest).options(load_only(
            MaintenanceRequest.id, MaintenanceRequest.internal_number,
            MaintenanceRequest.title, MaintenanceRequest.priority,
            MaintenanceRequest.status, MaintenanceRequest.scheduled_at,
            MaintenanceRequest.reported_at, MaintenanceRequest.updated_at,
        )).where(
            MaintenanceRequest.organization_id == context.user.organization_id,
            MaintenanceRequest.status.in_(("awaiting_approval", "scheduled", "in_progress")),
        ).order_by(MaintenanceRequest.reported_at.asc()).limit(30)
    ).all()
    for maintenance in rows:
        if maintenance.status == "awaiting_approval":
            items.append(_item(
                f"maintenance-approval:{maintenance.id}:{maintenance.status}",
                "critical" if maintenance.priority == "urgent" else "warning", "maintenance",
                f"Manutenção {_code('MAN-', maintenance.internal_number)} aguarda aprovação", maintenance.title,
                "maintenance", f"/app/maintenance/{maintenance.id}", maintenance.updated_at, "Analisar orçamento",
            ))
        elif maintenance.scheduled_at and maintenance.scheduled_at < now and ("maintenance", str(maintenance.id)) not in blocked_sources:
            items.append(_item(
                f"maintenance-schedule:{maintenance.id}:{maintenance.scheduled_at.date().isoformat()}",
                "critical" if maintenance.priority == "urgent" else "warning", "maintenance",
                f"Manutenção {_code('MAN-', maintenance.internal_number)} requer acompanhamento",
                f"{maintenance.title} · agendada para {maintenance.scheduled_at.astimezone(BR_TZ).strftime('%d/%m %H:%M')}",
                "maintenance", f"/app/maintenance/{maintenance.id}", maintenance.scheduled_at, "Abrir manutenção",
            ))
    return items


def _inspection_notifications(db: Session, context: UserContext, today: date, blocked_sources: set[tuple[str, str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    rows = db.scalars(
        select(Inspection).where(
            Inspection.organization_id == context.user.organization_id,
            Inspection.status.notin_(("finalized", "completed", "cancelled")),
        ).order_by(Inspection.scheduled_at.asc().nullslast()).limit(30)
    ).all()
    tomorrow = today + timedelta(days=1)
    for inspection in rows:
        if inspection.scheduled_at:
            scheduled_local = inspection.scheduled_at.astimezone(BR_TZ)
            if scheduled_local.date() <= today and ("inspections", str(inspection.id)) not in blocked_sources:
                overdue = scheduled_local.date() < today
                items.append(_item(
                    f"inspection-schedule:{inspection.id}:{scheduled_local.date().isoformat()}", "warning" if overdue else "info", "inspections",
                    f"Vistoria {_code('VIS-', inspection.internal_number)} {'atrasada' if overdue else 'hoje'}",
                    f"{inspection.inspection_type} · {inspection.inspector_name or 'vistoriador a definir'}",
                    "inspections", f"/app/inspections/{inspection.id}", inspection.scheduled_at, "Abrir vistoria",
                ))
        if inspection.contest_deadline:
            contest_local = inspection.contest_deadline.astimezone(BR_TZ)
            if today <= contest_local.date() <= tomorrow:
                items.append(_item(
                    f"inspection-contest:{inspection.id}:{contest_local.date().isoformat()}", "warning", "inspections",
                    f"Prazo de contestação · {_code('VIS-', inspection.internal_number)}",
                    f"Encerra em {contest_local.strftime('%d/%m/%Y %H:%M')}", "inspections",
                    f"/app/inspections/{inspection.id}", inspection.contest_deadline, "Conferir vistoria",
                ))
    return items


def _collect_active_notifications(db: Session, context: UserContext) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    today = datetime.now(BR_TZ).date()
    items: list[dict[str, Any]] = []
    blocked_sources: set[tuple[str, str]] = set()

    if context.has("agenda.view"):
        agenda_items, blocked_sources = _agenda_notifications(db, context, now)
        items.extend(agenda_items)
    if context.has("contracts.view"):
        items.extend(_contract_notifications(db, context, today))
    if context.has("finance.view"):
        items.extend(_finance_notifications(db, context, today, blocked_sources))
    if context.has("maintenance.view"):
        items.extend(_maintenance_notifications(db, context, now, blocked_sources))
    if context.has("inspections.view"):
        items.extend(_inspection_notifications(db, context, today, blocked_sources))

    items.sort(key=lambda row: (SEVERITY_ORDER.get(row["severity"], 9), row["event_at"]))
    return items


def _read_keys(db: Session, context: UserContext, keys: list[str]) -> set[str]:
    if not keys:
        return set()
    values = db.scalars(
        select(AuditLog.entity_id).where(
            AuditLog.organization_id == context.user.organization_id,
            AuditLog.actor_user_id == context.user.id,
            AuditLog.action == "notification.read",
            AuditLog.module == "notifications",
            AuditLog.entity_type == "notification",
            AuditLog.entity_id.in_(keys),
        )
    ).all()
    return {str(value) for value in values if value}


def _apply_read_state(db: Session, context: UserContext, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    read = _read_keys(db, context, [item["key"] for item in items])
    for item in items:
        item["read"] = item["key"] in read
    return items


def _mark_read(db: Session, context: UserContext, keys: set[str]) -> int:
    if not keys:
        return 0
    existing = _read_keys(db, context, list(keys))
    pending = keys - existing
    read_at = datetime.now(timezone.utc)
    for key in pending:
        db.add(AuditLog(
            organization_id=context.user.organization_id,
            actor_user_id=context.user.id,
            action="notification.read",
            module="notifications",
            entity_type="notification",
            entity_id=key,
            before_data=None,
            after_data={"read_at": read_at.isoformat()},
            reason=None,
            ip_address=None,
            user_agent=None,
        ))
    if pending:
        db.commit()
    return len(keys)


@router.get("/notifications")
def notifications(
    limit: int = 60,
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    active = _apply_read_state(db, context, _collect_active_notifications(db, context))
    bounded = active[: max(1, min(limit, 100))]
    unread = sum(1 for item in active if not item.get("read"))
    critical = sum(1 for item in active if item["severity"] == "critical" and not item.get("read"))
    return {
        "items": bounded,
        "unread_count": unread,
        "critical_count": critical,
        "generated_at": datetime.now(timezone.utc),
    }


@router.post("/notifications/read")
def read_notifications(
    payload: NotificationReadPayload,
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_current_user_context),
) -> dict[str, int]:
    active_keys = {item["key"] for item in _collect_active_notifications(db, context)}
    requested = {key.strip() for key in payload.keys if key.strip() and len(key.strip()) <= 180}
    return {"updated": _mark_read(db, context, requested & active_keys)}


@router.post("/notifications/read-all")
def read_all_notifications(
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_current_user_context),
) -> dict[str, int]:
    keys = {item["key"] for item in _collect_active_notifications(db, context)}
    return {"updated": _mark_read(db, context, keys)}
