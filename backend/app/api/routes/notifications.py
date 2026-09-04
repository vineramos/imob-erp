from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.agenda.logic import access_map, ensure_agenda_structure
from app.domains.agenda.models import AgendaMeetingParticipant, AgendaMeetingRequest, AgendaTask
from app.domains.contracts.models import AdministrationContract
from app.domains.finance.models import OwnerRepasse, RentCharge
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.foundation.notification_models import UserNotificationState
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest

router = APIRouter(tags=["notifications"])

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


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


def _notification(
    *,
    key: str,
    severity: str,
    category: str,
    title: str,
    subtitle: str,
    module: str,
    route: str,
    event_at: datetime,
    action_label: str = "Abrir",
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


def _task_details_allowed(context: UserContext, grants: dict[Any, dict], item: AgendaTask) -> bool:
    if item.assigned_user_id is None or item.assigned_user_id == context.user.id:
        return True
    grant = grants.get(item.assigned_user_id)
    if not grant:
        return False
    return bool(grant.get("private_details" if item.privacy == "private" else "details"))


def _collect_active_notifications(db: Session, context: UserContext) -> list[dict[str, Any]]:
    organization_id = context.user.organization_id
    now = datetime.now(timezone.utc)
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    items: list[dict[str, Any]] = []
    blocked_sources: set[tuple[str, str]] = set()

    if context.has("agenda.view"):
        user_ids, department_ids, grants = _task_scope(db, context)
        scope = []
        if user_ids:
            scope.append(AgendaTask.assigned_user_id.in_(user_ids))
        if department_ids:
            scope.append(and_(AgendaTask.assigned_user_id.is_(None), AgendaTask.department_id.in_(department_ids)))
        if scope:
            tasks = db.scalars(
                select(AgendaTask).where(
                    AgendaTask.organization_id == organization_id,
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
                    f"{_code('TAR-', task.internal_number)} · pendente desde {task.starts_at.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y')}"
                    + (f" · {task.reschedule_sequence}º reagendamento" if task.reschedule_sequence else "")
                )
                route = f"/app/agenda/task/{task.id}" if allowed else "/app/agenda"
                items.append(_notification(
                    key=f"agenda-overdue:{task.id}:{task.reschedule_sequence}",
                    severity=severity,
                    category="agenda",
                    title=title,
                    subtitle=subtitle,
                    module="agenda",
                    route=route,
                    event_at=task.starts_at,
                    action_label="Justificar" if task.mandatory_action else "Abrir tarefa",
                ))

        pending_participants = db.scalars(
            select(AgendaMeetingParticipant).where(
                AgendaMeetingParticipant.user_id == context.user.id,
                AgendaMeetingParticipant.status == "pending",
            )
        ).all()
        if pending_participants:
            request_ids = [row.meeting_request_id for row in pending_participants]
            requests = db.scalars(
                select(AgendaMeetingRequest).where(
                    AgendaMeetingRequest.organization_id == organization_id,
                    AgendaMeetingRequest.id.in_(request_ids),
                    AgendaMeetingRequest.status == "pending",
                )
            ).all()
            for request in requests:
                items.append(_notification(
                    key=f"meeting-invite:{request.id}:pending",
                    severity="info",
                    category="agenda",
                    title="Convite de reunião aguardando resposta",
                    subtitle=request.title,
                    module="agenda",
                    route="/app/agenda",
                    event_at=request.created_at,
                    action_label="Responder",
                ))

    if context.has("contracts.view"):
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
            bucket = _expiry_bucket(days)
            severity = "critical" if days <= 7 else "warning" if days <= 30 else "info"
            address = contract.property_snapshot.get("address", {}) if isinstance(contract.property_snapshot, dict) else {}
            neighborhood = address.get("neighborhood") or address.get("city") or "imóvel administrado"
            items.append(_notification(
                key=f"admin-contract-expiry:{contract.id}:{bucket}",
                severity=severity,
                category="contracts",
                title=f"Contrato de administração {_code('ADM-', contract.internal_number)}",
                subtitle=f"{_expiry_text(days)} · {neighborhood}",
                module="contracts",
                route=f"/app/contracts/administration/{contract.id}",
                event_at=_date_at(contract.end_date),
                action_label="Ver contrato",
            ))

        lease_contracts = db.scalars(
            select(LeaseContract).where(
                LeaseContract.organization_id == organization_id,
                LeaseContract.status == "signed",
                LeaseContract.end_date <= today + timedelta(days=120),
            )
        ).all()
        for contract in lease_contracts:
            days = (contract.end_date - today).days
            bucket = _expiry_bucket(days)
            severity = "critical" if days <= 7 else "warning" if days <= 30 else "info"
            tenants = " / ".join(str(row.get("name") or "") for row in (contract.tenant_snapshot or []) if row.get("name")) or "Locatário não informado"
            items.append(_notification(
                key=f"lease-contract-expiry:{contract.id}:{bucket}",
                severity=severity,
                category="contracts",
                title=f"Locação {_code('LOC-', contract.internal_number)} próxima do término",
                subtitle=f"{_expiry_text(days)} · {tenants}",
                module="contracts",
                route=f"/app/contracts/lease/{contract.id}",
                event_at=_date_at(contract.end_date),
                action_label="Ver contrato",
            ))
            adjustment_days = (contract.next_adjustment_date - today).days
            if 0 <= adjustment_days <= 30:
                items.append(_notification(
                    key=f"lease-adjustment:{contract.id}:{'7' if adjustment_days <= 7 else '30'}",
                    severity="warning" if adjustment_days <= 7 else "info",
                    category="contracts",
                    title=f"Reajuste de {_code('LOC-', contract.internal_number)}",
                    subtitle=f"{contract.adjustment_index} · {'hoje' if adjustment_days == 0 else f'em {adjustment_days} dia(s)'}",
                    module="contracts",
                    route=f"/app/contracts/lease/{contract.id}",
                    event_at=_date_at(contract.next_adjustment_date),
                    action_label="Conferir reajuste",
                ))

    if context.has("finance.view"):
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
            items.append(_notification(
                key=f"charge-overdue:{charge.id}",
                severity="critical" if overdue_days >= 5 else "warning",
                category="finance",
                title=f"Cobrança {_code('COB-', charge.internal_number)} vencida",
                subtitle=f"{tenants} · {overdue_days} dia(s) · {_money(charge.gross_amount)}",
                module="finance",
                route=f"/app/finance/charge/{charge.id}",
                event_at=_date_at(charge.due_date),
                action_label="Abrir cobrança",
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
            items.append(_notification(
                key=f"repasse-overdue:{repasse.id}",
                severity="critical" if overdue_days >= 3 else "warning",
                category="finance",
                title="Repasse ao proprietário em atraso",
                subtitle=f"{repasse.owner_name} · {overdue_days} dia(s) · {_money(repasse.amount)}",
                module="finance",
                route=f"/app/finance/charge/{repasse.charge_id}",
                event_at=_date_at(repasse.due_date),
                action_label="Abrir financeiro",
            ))

    if context.has("maintenance.view"):
        maintenances = db.scalars(
            select(MaintenanceRequest).where(
                MaintenanceRequest.organization_id == organization_id,
                MaintenanceRequest.status.in_(("awaiting_approval", "scheduled", "in_progress")),
            ).order_by(MaintenanceRequest.reported_at.asc()).limit(30)
        ).all()
        for maintenance in maintenances:
            if maintenance.status == "awaiting_approval":
                items.append(_notification(
                    key=f"maintenance-approval:{maintenance.id}:{maintenance.status}",
                    severity="critical" if maintenance.priority == "urgent" else "warning",
                    category="maintenance",
                    title=f"Manutenção {_code('MAN-', maintenance.internal_number)} aguarda aprovação",
                    subtitle=maintenance.title,
                    module="maintenance",
                    route=f"/app/maintenance/{maintenance.id}",
                    event_at=maintenance.updated_at,
                    action_label="Analisar orçamento",
                ))
            elif maintenance.scheduled_at and maintenance.scheduled_at < now and ("maintenance", str(maintenance.id)) not in blocked_sources:
                items.append(_notification(
                    key=f"maintenance-schedule:{maintenance.id}:{maintenance.scheduled_at.date().isoformat()}",
                    severity="critical" if maintenance.priority == "urgent" else "warning",
                    category="maintenance",
                    title=f"Manutenção {_code('MAN-', maintenance.internal_number)} requer acompanhamento",
                    subtitle=f"{maintenance.title} · agendada para {maintenance.scheduled_at.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m %H:%M')}",
                    module="maintenance",
                    route=f"/app/maintenance/{maintenance.id}",
                    event_at=maintenance.scheduled_at,
                    action_label="Abrir manutenção",
                ))

    if context.has("inspections.view"):
        inspections = db.scalars(
            select(Inspection).where(
                Inspection.organization_id == organization_id,
                Inspection.status.notin_(("finalized", "completed", "cancelled")),
            ).order_by(Inspection.scheduled_at.asc().nullslast()).limit(30)
        ).all()
        tomorrow = today + timedelta(days=1)
        for inspection in inspections:
            if inspection.scheduled_at:
                scheduled_local = inspection.scheduled_at.astimezone(ZoneInfo("America/Sao_Paulo"))
                if scheduled_local.date() <= today and ("inspections", str(inspection.id)) not in blocked_sources:
                    overdue = scheduled_local.date() < today
                    items.append(_notification(
                        key=f"inspection-schedule:{inspection.id}:{scheduled_local.date().isoformat()}",
                        severity="warning" if overdue else "info",
                        category="inspections",
                        title=f"Vistoria {_code('VIS-', inspection.internal_number)} {'atrasada' if overdue else 'hoje'}",
                        subtitle=f"{inspection.inspection_type} · {inspection.inspector_name or 'vistoriador a definir'}",
                        module="inspections",
                        route=f"/app/inspections/{inspection.id}",
                        event_at=inspection.scheduled_at,
                        action_label="Abrir vistoria",
                    ))
            if inspection.contest_deadline:
                contest_local = inspection.contest_deadline.astimezone(ZoneInfo("America/Sao_Paulo"))
                if today <= contest_local.date() <= tomorrow:
                    items.append(_notification(
                        key=f"inspection-contest:{inspection.id}:{contest_local.date().isoformat()}",
                        severity="warning",
                        category="inspections",
                        title=f"Prazo de contestação · {_code('VIS-', inspection.internal_number)}",
                        subtitle=f"Encerra em {contest_local.strftime('%d/%m/%Y %H:%M')}",
                        module="inspections",
                        route=f"/app/inspections/{inspection.id}",
                        event_at=inspection.contest_deadline,
                        action_label="Conferir vistoria",
                    ))

    items.sort(key=lambda row: (SEVERITY_ORDER.get(row["severity"], 9), row["event_at"]))
    return items


def _apply_read_state(db: Session, context: UserContext, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = [item["key"] for item in items]
    if not keys:
        return items
    states = db.scalars(
        select(UserNotificationState).where(
            UserNotificationState.organization_id == context.user.organization_id,
            UserNotificationState.user_id == context.user.id,
            UserNotificationState.notification_key.in_(keys),
            UserNotificationState.read_at.is_not(None),
        )
    ).all()
    read_keys = {state.notification_key for state in states}
    for item in items:
        item["read"] = item["key"] in read_keys
    return items


def _mark_read(db: Session, context: UserContext, keys: set[str]) -> int:
    if not keys:
        return 0
    states = db.scalars(
        select(UserNotificationState).where(
            UserNotificationState.organization_id == context.user.organization_id,
            UserNotificationState.user_id == context.user.id,
            UserNotificationState.notification_key.in_(keys),
        )
    ).all()
    by_key = {state.notification_key: state for state in states}
    read_at = datetime.now(timezone.utc)
    for key in keys:
        state = by_key.get(key)
        if state is None:
            db.add(UserNotificationState(
                organization_id=context.user.organization_id,
                user_id=context.user.id,
                notification_key=key,
                read_at=read_at,
            ))
        else:
            state.read_at = read_at
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
    requested = {key.strip() for key in payload.keys if key.strip() and len(key.strip()) <= 240}
    return {"updated": _mark_read(db, context, requested & active_keys)}


@router.post("/notifications/read-all")
def read_all_notifications(
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_current_user_context),
) -> dict[str, int]:
    keys = {item["key"] for item in _collect_active_notifications(db, context)}
    return {"updated": _mark_read(db, context, keys)}
