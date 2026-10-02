from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.agenda.logic import ensure_agenda_structure
from app.domains.agenda.models import AgendaTask
from app.domains.agenda.timezone_rules import local_date, local_today, profile_timezone
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit


router = APIRouter(tags=["agenda"])


class AgendaOperationalItem(BaseModel):
    id: UUID
    code: str
    title: str
    description: str | None
    starts_at: datetime
    due_at: datetime | None
    priority: str
    status: str
    assigned_user_id: UUID | None
    assigned_user_name: str | None
    department_id: UUID | None
    department_name: str | None
    source_module: str | None
    source_type: str | None
    source_id: str | None
    mandatory_action: bool
    reschedule_sequence: int
    sla_state: str
    minutes_to_due: int | None
    claimable: bool
    assignable: bool


class AgendaOperationalOverview(BaseModel):
    total: int
    sla_breached: int
    due_today: int
    unassigned: int
    high_priority: int
    items: list[AgendaOperationalItem]


class AgendaOperationalAssign(BaseModel):
    user_id: UUID


def _task_code(item: AgendaTask) -> str:
    return f"TAR-{item.internal_number:06d}"


def _metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None), request.headers.get("user-agent")


def _visible(
    item: AgendaTask,
    *,
    context: UserContext,
    profiles,
) -> bool:
    current = profiles.get(context.user.id)
    if current is None:
        return False
    level = current.access_level
    if level in {"admin", "director"}:
        return True

    if item.assigned_user_id is not None:
        if item.assigned_user_id == context.user.id:
            return True
        target = profiles.get(item.assigned_user_id)
        return bool(
            level == "manager"
            and current.department_id
            and target
            and target.department_id == current.department_id
        )

    return bool(current.department_id and item.department_id == current.department_id)


def _sla(
    item: AgendaTask,
    *,
    now: datetime,
    zone,
) -> tuple[str, int | None]:
    if item.due_at is None:
        return "no_deadline", None
    minutes = int((item.due_at - now).total_seconds() // 60)
    if item.due_at < now:
        return "breached", minutes
    if local_date(item.due_at, zone) == local_today(zone):
        return "due_today", minutes
    return "on_track", minutes


def _latest_pending(rows: list[AgendaTask]) -> list[AgendaTask]:
    latest: dict[UUID, AgendaTask] = {}
    for item in rows:
        key = item.original_task_id or item.id
        current = latest.get(key)
        if current is None or item.reschedule_sequence > current.reschedule_sequence:
            latest[key] = item
    return list(latest.values())


def _serialize(
    item: AgendaTask,
    *,
    context: UserContext,
    profiles,
    departments,
    names: dict[UUID, str],
    now: datetime,
    zone,
) -> AgendaOperationalItem:
    current = profiles[context.user.id]
    level = current.access_level
    sla_state, minutes_to_due = _sla(item, now=now, zone=zone)
    claimable = bool(
        item.assigned_user_id is None
        and (
            level in {"admin", "director"}
            or (current.department_id is not None and item.department_id == current.department_id)
        )
    )
    return AgendaOperationalItem(
        id=item.id,
        code=_task_code(item),
        title=item.title,
        description=item.description,
        starts_at=item.starts_at,
        due_at=item.due_at,
        priority=item.priority,
        status=item.status,
        assigned_user_id=item.assigned_user_id,
        assigned_user_name=names.get(item.assigned_user_id),
        department_id=item.department_id,
        department_name=departments.get(item.department_id).name if item.department_id in departments else None,
        source_module=item.source_module,
        source_type=item.source_type,
        source_id=item.source_id,
        mandatory_action=item.mandatory_action,
        reschedule_sequence=item.reschedule_sequence,
        sla_state=sla_state,
        minutes_to_due=minutes_to_due,
        claimable=claimable,
        assignable=level in {"manager", "director", "admin"},
    )


@router.get("/agenda/operations", response_model=AgendaOperationalOverview)
def agenda_operations(
    horizon_days: int = Query(default=30, ge=0, le=180),
    limit: int = Query(default=40, ge=1, le=200),
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> AgendaOperationalOverview:
    organization_id = context.user.organization_id
    from app.domains.agenda import logic
    logic.sync_system_tasks(db, organization_id)

    users, profiles, departments = ensure_agenda_structure(db, organization_id)
    names = {item.id: item.name for item in users}
    zone = profile_timezone(db, organization_id, context.user.id)
    now = datetime.now(timezone.utc)
    horizon_at = now + timedelta(days=horizon_days)

    rows = db.scalars(
        select(AgendaTask).where(
            AgendaTask.organization_id == organization_id,
            AgendaTask.automatic.is_(True),
            AgendaTask.status.in_(("pending", "confirmed")),
        )
    ).all()
    rows = [item for item in rows if _visible(item, context=context, profiles=profiles)]
    rows = _latest_pending(rows)
    rows = [
        item for item in rows
        if item.starts_at <= horizon_at
        or (item.due_at is not None and item.due_at <= horizon_at)
    ]

    payload = [
        _serialize(
            item,
            context=context,
            profiles=profiles,
            departments=departments,
            names=names,
            now=now,
            zone=zone,
        )
        for item in rows
    ]
    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    sla_order = {"breached": 0, "due_today": 1, "on_track": 2, "no_deadline": 3}
    payload.sort(
        key=lambda item: (
            sla_order.get(item.sla_state, 3),
            priority_order.get(item.priority, 2),
            item.due_at or item.starts_at,
            item.title.casefold(),
        )
    )

    db.commit()
    return AgendaOperationalOverview(
        total=len(payload),
        sla_breached=sum(item.sla_state == "breached" for item in payload),
        due_today=sum(item.sla_state == "due_today" for item in payload),
        unassigned=sum(item.assigned_user_id is None for item in payload),
        high_priority=sum(item.priority in {"high", "urgent"} for item in payload),
        items=payload[:limit],
    )


def _load_operational_task(db: Session, context: UserContext, task_id: UUID) -> AgendaTask:
    item = db.scalar(
        select(AgendaTask).where(
            AgendaTask.id == task_id,
            AgendaTask.organization_id == context.user.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Pendência operacional não encontrada.")
    if not item.automatic or item.status not in {"pending", "confirmed"}:
        raise HTTPException(status_code=409, detail="Esta ocorrência não está disponível para atribuição.")
    return item


def _assign(
    db: Session,
    *,
    request: Request,
    context: UserContext,
    item: AgendaTask,
    target_user_id: UUID,
) -> AgendaTask:
    users, profiles, departments = ensure_agenda_structure(db, context.user.organization_id)
    user_map = {user.id: user for user in users}
    target = user_map.get(target_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Responsável não encontrado ou inativo.")

    current = profiles[context.user.id]
    target_profile = profiles[target_user_id]
    level = current.access_level

    if level not in {"admin", "director"}:
        if level == "manager":
            if (
                current.department_id is None
                or item.department_id != current.department_id
                or target_profile.department_id != current.department_id
            ):
                raise HTTPException(status_code=403, detail="Gerentes só podem atribuir pendências dentro do próprio setor.")
        else:
            if target_user_id != context.user.id:
                raise HTTPException(status_code=403, detail="Você só pode assumir uma pendência para si.")
            if item.assigned_user_id not in {None, context.user.id}:
                raise HTTPException(status_code=409, detail="A pendência já possui outro responsável.")
            if current.department_id is None or item.department_id != current.department_id:
                raise HTTPException(status_code=403, detail="A pendência pertence a outro setor.")

    before = str(item.assigned_user_id) if item.assigned_user_id else None
    root_id = item.original_task_id or item.id
    chain = db.scalars(
        select(AgendaTask).where(
            AgendaTask.organization_id == context.user.organization_id,
            AgendaTask.status.in_(("pending", "confirmed")),
            or_(AgendaTask.original_task_id == root_id, AgendaTask.id == root_id),
        )
    ).all()
    for occurrence in chain:
        occurrence.assigned_user_id = target_user_id

    ip_address, user_agent = _metadata(request)
    write_audit(
        db,
        context=context,
        action="agenda.operational.assigned",
        module="agenda",
        entity_type="agenda_task",
        entity_id=str(item.id),
        before_data={"assigned_user_id": before},
        after_data={
            "assigned_user_id": str(target_user_id),
            "assigned_user_name": target.name,
            "department": departments.get(item.department_id).name if item.department_id in departments else None,
        },
        reason="Atribuição operacional de pendência automática.",
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(item)
    return item


def _serialized_after_assignment(
    db: Session,
    *,
    context: UserContext,
    item: AgendaTask,
) -> AgendaOperationalItem:
    users, profiles, departments = ensure_agenda_structure(db, context.user.organization_id)
    names = {user.id: user.name for user in users}
    zone = profile_timezone(db, context.user.organization_id, context.user.id)
    return _serialize(
        item,
        context=context,
        profiles=profiles,
        departments=departments,
        names=names,
        now=datetime.now(timezone.utc),
        zone=zone,
    )


@router.post("/agenda/operations/{task_id}/claim", response_model=AgendaOperationalItem)
def claim_operational_task(
    task_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> AgendaOperationalItem:
    item = _load_operational_task(db, context, task_id)
    item = _assign(
        db,
        request=request,
        context=context,
        item=item,
        target_user_id=context.user.id,
    )
    return _serialized_after_assignment(db, context=context, item=item)


@router.post("/agenda/operations/{task_id}/assign", response_model=AgendaOperationalItem)
def assign_operational_task(
    task_id: UUID,
    payload: AgendaOperationalAssign,
    request: Request,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> AgendaOperationalItem:
    item = _load_operational_task(db, context, task_id)
    item = _assign(
        db,
        request=request,
        context=context,
        item=item,
        target_user_id=payload.user_id,
    )
    return _serialized_after_assignment(db, context=context, item=item)
