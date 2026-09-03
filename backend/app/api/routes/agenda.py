from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.agenda.models import AgendaTask
from app.domains.agenda.schemas import (
    AgendaEventResponse,
    AgendaEventsResponse,
    AgendaTaskCreate,
    AgendaTaskResponse,
    AgendaTaskStatus,
    AgendaTaskUpdate,
    AgendaUserResponse,
    DashboardEventResponse,
    DashboardOverviewResponse,
)
from app.domains.contracts.models import AdministrationContract
from app.domains.finance.models import OwnerRepasse, RentCharge
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import AppUser
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.portfolio.models import Property

router = APIRouter(tags=["agenda"])


def _noon(day: date) -> datetime:
    return datetime.combine(day, time(hour=12), tzinfo=timezone.utc)


def _task_code(item: AgendaTask) -> str:
    return f"TAR-{item.internal_number:06d}"


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, item: AgendaTask, action: str, *, before=None, after=None) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="agenda",
        entity_type="agenda_task",
        entity_id=str(item.id),
        before_data=before,
        after_data=after,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _assignee(db: Session, organization_id: UUID, user_id: UUID | None) -> AppUser | None:
    if user_id is None:
        return None
    item = db.scalar(select(AppUser).where(AppUser.id == user_id, AppUser.organization_id == organization_id, AppUser.is_active.is_(True)))
    if item is None:
        raise HTTPException(status_code=422, detail="Responsável da tarefa não foi encontrado ou está inativo.")
    return item


def _task_response(item: AgendaTask, assignee_name: str | None = None) -> AgendaTaskResponse:
    return AgendaTaskResponse(
        id=item.id,
        code=_task_code(item),
        title=item.title,
        description=item.description,
        starts_at=item.starts_at,
        due_at=item.due_at,
        all_day=item.all_day,
        priority=item.priority,
        status=item.status,
        assigned_user_id=item.assigned_user_id,
        assigned_user_name=assignee_name,
        source_module=item.source_module,
        source_type=item.source_type,
        source_id=item.source_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _event(
    *,
    event_id: str,
    event_type: str,
    title: str,
    start_at: datetime,
    module: str,
    description: str | None = None,
    end_at: datetime | None = None,
    all_day: bool = False,
    priority: str = "normal",
    status_value: str = "pending",
    source_id: str | None = None,
    source_code: str | None = None,
    responsible_name: str | None = None,
    property_code: str | None = None,
    amount: Decimal | float | None = None,
    automatic: bool = True,
    task_id: UUID | None = None,
) -> AgendaEventResponse:
    return AgendaEventResponse(
        id=event_id,
        event_type=event_type,
        title=title,
        description=description,
        start_at=start_at,
        end_at=end_at,
        all_day=all_day,
        priority=priority,
        status=status_value,
        module=module,
        source_id=source_id,
        source_code=source_code,
        responsible_name=responsible_name,
        property_code=property_code,
        amount=float(amount) if amount is not None else None,
        automatic=automatic,
        task_id=task_id,
    )


def _collect_events(db: Session, organization_id: UUID, start: date, end: date) -> list[AgendaEventResponse]:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_exclusive = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    events: list[AgendaEventResponse] = []

    properties = db.scalars(select(Property).where(Property.organization_id == organization_id)).all()
    property_codes = {item.id: f"{item.internal_number:06d}" for item in properties}

    users = db.scalars(select(AppUser).where(AppUser.organization_id == organization_id, AppUser.is_active.is_(True))).all()
    user_names = {item.id: item.name for item in users}

    tasks = db.scalars(
        select(AgendaTask).where(
            AgendaTask.organization_id == organization_id,
            AgendaTask.status != "cancelled",
            AgendaTask.starts_at >= start_dt - timedelta(days=1),
            AgendaTask.starts_at < end_exclusive + timedelta(days=1),
        )
    ).all()
    for item in tasks:
        events.append(_event(
            event_id=f"task:{item.id}",
            event_type="task",
            title=item.title,
            description=item.description,
            start_at=item.starts_at,
            end_at=item.due_at,
            all_day=item.all_day,
            priority=item.priority,
            status_value=item.status,
            module=item.source_module or "agenda",
            source_id=item.source_id,
            source_code=_task_code(item),
            responsible_name=user_names.get(item.assigned_user_id),
            automatic=False,
            task_id=item.id,
        ))

    inspections = db.scalars(
        select(Inspection).where(
            Inspection.organization_id == organization_id,
            or_(
                Inspection.scheduled_at.between(start_dt, end_exclusive),
                Inspection.contest_deadline.between(start_dt, end_exclusive),
            ),
        )
    ).all()
    for item in inspections:
        code = f"VIS-{item.internal_number:06d}"
        property_code = property_codes.get(item.property_id)
        if item.scheduled_at and start_dt <= item.scheduled_at < end_exclusive:
            events.append(_event(
                event_id=f"inspection:{item.id}:scheduled",
                event_type="inspection",
                title=f"Vistoria agendada · Imóvel {property_code or '—'}",
                description=f"{item.inspection_type.capitalize()} · vistoriador: {item.inspector_name or 'a definir'}",
                start_at=item.scheduled_at,
                module="inspections",
                source_id=str(item.id),
                source_code=code,
                responsible_name=item.inspector_name,
                property_code=property_code,
                priority="high" if item.status not in {"finalized", "completed"} else "normal",
                status_value=item.status,
            ))
        if item.contest_deadline and start_dt <= item.contest_deadline < end_exclusive:
            events.append(_event(
                event_id=f"inspection:{item.id}:contest",
                event_type="inspection_deadline",
                title=f"Fim do prazo de contestação · {code}",
                description="Prazo final para contestação da vistoria.",
                start_at=item.contest_deadline,
                module="inspections",
                source_id=str(item.id),
                source_code=code,
                property_code=property_code,
                priority="high",
                status_value=item.status,
            ))

    maintenances = db.scalars(
        select(MaintenanceRequest).where(
            MaintenanceRequest.organization_id == organization_id,
            MaintenanceRequest.scheduled_at >= start_dt,
            MaintenanceRequest.scheduled_at < end_exclusive,
            MaintenanceRequest.status.not_in(("completed", "cancelled")),
        )
    ).all()
    for item in maintenances:
        events.append(_event(
            event_id=f"maintenance:{item.id}:scheduled",
            event_type="maintenance",
            title=f"Manutenção · {item.title}",
            description=f"{item.category} · responsabilidade: {item.responsibility}",
            start_at=item.scheduled_at,
            module="maintenance",
            source_id=str(item.id),
            source_code=f"MAN-{item.internal_number:06d}",
            property_code=property_codes.get(item.property_id),
            priority="urgent" if item.priority == "urgent" else "high" if item.priority == "high" else "normal",
            status_value=item.status,
        ))

    contract_window_end = end + timedelta(days=120)
    leases = db.scalars(
        select(LeaseContract).where(
            LeaseContract.organization_id == organization_id,
            LeaseContract.status.not_in(("draft", "review", "cancelled")),
            or_(
                LeaseContract.end_date.between(start, contract_window_end),
                LeaseContract.next_adjustment_date.between(start, end),
            ),
        )
    ).all()
    for item in leases:
        code = f"LOC-{item.internal_number:06d}"
        property_code = property_codes.get(item.property_id)
        for days in (120, 90, 60, 30, 0):
            alert_day = item.end_date - timedelta(days=days)
            if start <= alert_day <= end:
                title = f"Contrato encerra hoje · {code}" if days == 0 else f"Contrato vence em {days} dias · {code}"
                events.append(_event(
                    event_id=f"lease:{item.id}:end-{days}",
                    event_type="contract_expiry",
                    title=title,
                    description=f"Imóvel {property_code or '—'} · término em {item.end_date.strftime('%d/%m/%Y')}",
                    start_at=_noon(alert_day),
                    all_day=True,
                    module="contracts",
                    source_id=str(item.id),
                    source_code=code,
                    property_code=property_code,
                    priority="urgent" if days == 0 else "high" if days <= 30 else "normal" if days <= 60 else "low",
                    status_value=item.status,
                ))
        if start <= item.next_adjustment_date <= end:
            events.append(_event(
                event_id=f"lease:{item.id}:adjustment",
                event_type="adjustment",
                title=f"Reajuste contratual · {code}",
                description=f"Índice {item.adjustment_index} · imóvel {property_code or '—'}",
                start_at=_noon(item.next_adjustment_date),
                all_day=True,
                module="contracts",
                source_id=str(item.id),
                source_code=code,
                property_code=property_code,
                priority="normal",
                status_value=item.status,
            ))

    admin_contracts = db.scalars(
        select(AdministrationContract).where(
            AdministrationContract.organization_id == organization_id,
            AdministrationContract.end_date.is_not(None),
            AdministrationContract.end_date.between(start, contract_window_end),
            AdministrationContract.status.not_in(("draft", "review", "cancelled")),
        )
    ).all()
    for item in admin_contracts:
        if item.end_date is None:
            continue
        code = f"ADM-{item.internal_number:06d}"
        property_code = property_codes.get(item.property_id)
        for days in (120, 90, 60, 30, 0):
            alert_day = item.end_date - timedelta(days=days)
            if start <= alert_day <= end:
                events.append(_event(
                    event_id=f"admin:{item.id}:end-{days}",
                    event_type="contract_expiry",
                    title=(f"Administração encerra hoje · {code}" if days == 0 else f"Administração vence em {days} dias · {code}"),
                    description=f"Imóvel {property_code or '—'} · término em {item.end_date.strftime('%d/%m/%Y')}",
                    start_at=_noon(alert_day),
                    all_day=True,
                    module="contracts",
                    source_id=str(item.id),
                    source_code=code,
                    property_code=property_code,
                    priority="urgent" if days == 0 else "high" if days <= 30 else "normal" if days <= 60 else "low",
                    status_value=item.status,
                ))

    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.due_date.between(start, end),
            RentCharge.status.not_in(("paid", "cancelled")),
        )
    ).all()
    today = datetime.now(timezone.utc).date()
    for item in charges:
        overdue = item.due_date < today
        events.append(_event(
            event_id=f"charge:{item.id}:due",
            event_type="billing",
            title=f"Vencimento de cobrança · COB-{item.internal_number:06d}",
            description=f"Competência {item.competence.strftime('%m/%Y')} · imóvel {property_codes.get(item.property_id) or '—'}",
            start_at=_noon(item.due_date),
            all_day=True,
            module="finance",
            source_id=str(item.id),
            source_code=f"COB-{item.internal_number:06d}",
            property_code=property_codes.get(item.property_id),
            amount=item.gross_amount,
            priority="high" if overdue else "normal",
            status_value="overdue" if overdue else item.status,
        ))

    repasses = db.scalars(
        select(OwnerRepasse).where(
            OwnerRepasse.organization_id == organization_id,
            OwnerRepasse.due_date.between(start, end),
            OwnerRepasse.status == "pending",
        )
    ).all()
    for item in repasses:
        events.append(_event(
            event_id=f"repasse:{item.id}:due",
            event_type="repasse",
            title=f"Repasse previsto · {item.owner_name}",
            description=f"Imóvel {property_codes.get(item.property_id) or '—'}",
            start_at=_noon(item.due_date),
            all_day=True,
            module="finance",
            source_id=str(item.id),
            source_code=None,
            responsible_name=item.owner_name,
            property_code=property_codes.get(item.property_id),
            amount=item.amount,
            priority="normal",
            status_value=item.status,
        ))

    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    events.sort(key=lambda item: (item.start_at, priority_order.get(item.priority, 2), item.title.lower()))
    return events


@router.get("/agenda/users", response_model=list[AgendaUserResponse])
def agenda_users(
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> list[AgendaUserResponse]:
    users = db.scalars(select(AppUser).where(AppUser.organization_id == context.user.organization_id, AppUser.is_active.is_(True)).order_by(AppUser.name)).all()
    return [AgendaUserResponse(id=item.id, name=item.name, email=item.email) for item in users]


@router.get("/agenda/events", response_model=AgendaEventsResponse)
def agenda_events(
    start: date = Query(...),
    end: date = Query(...),
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> AgendaEventsResponse:
    if end < start:
        raise HTTPException(status_code=422, detail="O fim do período deve ser igual ou posterior ao início.")
    if (end - start).days > 370:
        raise HTTPException(status_code=422, detail="Consulte no máximo 370 dias por vez.")
    return AgendaEventsResponse(start_date=start.isoformat(), end_date=end.isoformat(), events=_collect_events(db, context.user.organization_id, start, end))


@router.post("/agenda/tasks", response_model=AgendaTaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: AgendaTaskCreate,
    request: Request,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> AgendaTaskResponse:
    assigned = _assignee(db, context.user.organization_id, payload.assigned_user_id)
    if payload.due_at and payload.due_at < payload.starts_at:
        raise HTTPException(status_code=422, detail="O prazo final não pode ser anterior ao início da tarefa.")
    item = AgendaTask(
        organization_id=context.user.organization_id,
        title=payload.title.strip(),
        description=(payload.description or "").strip() or None,
        starts_at=payload.starts_at,
        due_at=payload.due_at,
        all_day=payload.all_day,
        priority=payload.priority,
        status="pending",
        assigned_user_id=assigned.id if assigned else context.user.id,
        source_module=payload.source_module,
        source_type=payload.source_type,
        source_id=payload.source_id,
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    _audit(db, request, context, item, "agenda.task.created", after={"code": _task_code(item), "title": item.title, "starts_at": item.starts_at.isoformat(), "assigned_user_id": str(item.assigned_user_id)})
    db.commit()
    db.refresh(item)
    return _task_response(item, assigned.name if assigned else context.user.name)


@router.put("/agenda/tasks/{task_id}", response_model=AgendaTaskResponse)
def update_task(
    task_id: UUID,
    payload: AgendaTaskUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> AgendaTaskResponse:
    item = db.scalar(select(AgendaTask).where(AgendaTask.id == task_id, AgendaTask.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if item.status == "cancelled":
        raise HTTPException(status_code=409, detail="Tarefa cancelada não pode ser editada.")
    assigned = _assignee(db, context.user.organization_id, payload.assigned_user_id)
    if payload.due_at and payload.due_at < payload.starts_at:
        raise HTTPException(status_code=422, detail="O prazo final não pode ser anterior ao início da tarefa.")
    before = {"title": item.title, "starts_at": item.starts_at.isoformat(), "priority": item.priority, "assigned_user_id": str(item.assigned_user_id) if item.assigned_user_id else None}
    item.title = payload.title.strip()
    item.description = (payload.description or "").strip() or None
    item.starts_at = payload.starts_at
    item.due_at = payload.due_at
    item.all_day = payload.all_day
    item.priority = payload.priority
    item.assigned_user_id = assigned.id if assigned else context.user.id
    item.source_module = payload.source_module
    item.source_type = payload.source_type
    item.source_id = payload.source_id
    _audit(db, request, context, item, "agenda.task.updated", before=before, after={"title": item.title, "starts_at": item.starts_at.isoformat(), "priority": item.priority, "assigned_user_id": str(item.assigned_user_id)})
    db.commit()
    db.refresh(item)
    return _task_response(item, assigned.name if assigned else context.user.name)


@router.post("/agenda/tasks/{task_id}/status", response_model=AgendaTaskResponse)
def update_task_status(
    task_id: UUID,
    payload: AgendaTaskStatus,
    request: Request,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> AgendaTaskResponse:
    item = db.scalar(select(AgendaTask).where(AgendaTask.id == task_id, AgendaTask.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    before = {"status": item.status}
    item.status = payload.status
    if payload.status == "completed":
        item.completed_at = datetime.now(timezone.utc)
        item.completed_by_user_id = context.user.id
    else:
        item.completed_at = None
        item.completed_by_user_id = None
    _audit(db, request, context, item, "agenda.task.status_changed", before=before, after={"status": item.status})
    db.commit()
    db.refresh(item)
    assigned_name = db.scalar(select(AppUser.name).where(AppUser.id == item.assigned_user_id)) if item.assigned_user_id else None
    return _task_response(item, assigned_name)


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
def dashboard_overview(
    context: UserContext = Depends(require_permission("dashboard.view")),
    db: Session = Depends(get_db),
) -> DashboardOverviewResponse:
    org = context.user.organization_id
    today = datetime.now(timezone.utc).date()
    limit = today + timedelta(days=120)

    admin_contracts = db.scalars(select(AdministrationContract).where(AdministrationContract.organization_id == org, AdministrationContract.status == "signed")).all()
    administered_properties = len({item.property_id for item in admin_contracts})
    available_properties = len(db.scalars(select(Property.id).where(Property.organization_id == org, Property.status == "available")).all())
    active_leases = len(db.scalars(select(LeaseContract.id).where(LeaseContract.organization_id == org, LeaseContract.status == "signed")).all())

    expiring_leases = db.scalars(select(LeaseContract.id).where(LeaseContract.organization_id == org, LeaseContract.status == "signed", LeaseContract.end_date.between(today, limit))).all()
    expiring_admin = db.scalars(select(AdministrationContract.id).where(AdministrationContract.organization_id == org, AdministrationContract.status == "signed", AdministrationContract.end_date.is_not(None), AdministrationContract.end_date.between(today, limit))).all()
    contracts_expiring_120 = len(expiring_leases) + len(expiring_admin)

    open_maintenance = len(db.scalars(select(MaintenanceRequest.id).where(MaintenanceRequest.organization_id == org, MaintenanceRequest.status.not_in(("completed", "cancelled")))).all())
    overdue_charges = db.scalars(select(RentCharge).where(RentCharge.organization_id == org, RentCharge.due_date < today, RentCharge.status.not_in(("paid", "cancelled")))).all()
    overdue_amount = sum((item.gross_amount for item in overdue_charges), Decimal("0"))
    pending_repasses = db.scalars(select(OwnerRepasse).where(OwnerRepasse.organization_id == org, OwnerRepasse.status == "pending")).all()
    pending_repasses_amount = sum((item.amount for item in pending_repasses), Decimal("0"))

    now = datetime.now(timezone.utc)
    overdue_tasks = len(db.scalars(select(AgendaTask.id).where(AgendaTask.organization_id == org, AgendaTask.status == "pending", AgendaTask.due_at.is_not(None), AgendaTask.due_at < now)).all())
    todays_events = _collect_events(db, org, today, today)
    tasks_today = len([item for item in todays_events if item.event_type == "task" and item.status != "completed"])

    return DashboardOverviewResponse(
        administered_properties=administered_properties,
        available_properties=available_properties,
        active_leases=active_leases,
        contracts_expiring_120=contracts_expiring_120,
        open_maintenance=open_maintenance,
        overdue_amount=float(overdue_amount),
        pending_repasses_amount=float(pending_repasses_amount),
        tasks_today=tasks_today,
        overdue_tasks=overdue_tasks,
        events_today=[DashboardEventResponse(id=item.id, title=item.title, start_at=item.start_at, event_type=item.event_type, module=item.module, priority=item.priority) for item in todays_events[:8]],
    )
