import calendar
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.agenda.logic import (
    access_map,
    department_by_name,
    ensure_agenda_structure,
    next_common_available,
    noon,
    require_calendar_access,
    require_schedule_access,
    sync_system_tasks,
    user_available,
)
from app.domains.agenda.models import (
    AgendaDailyBriefing,
    AgendaDelegation,
    AgendaDepartment,
    AgendaMeetingOption,
    AgendaMeetingParticipant,
    AgendaMeetingRequest,
    AgendaMeetingVote,
    AgendaTask,
    AgendaUserProfile,
)
from app.domains.agenda.schemas import (
    AgendaContextResponse,
    AgendaDelegationResponse,
    AgendaDelegationWrite,
    AgendaDepartmentCreate,
    AgendaDepartmentResponse,
    AgendaDirectoryUser,
    AgendaEventResponse,
    AgendaEventsResponse,
    AgendaMissJustification,
    AgendaMyAvailabilityUpdate,
    AgendaTaskCreate,
    AgendaTaskResponse,
    AgendaTaskStatus,
    AgendaTaskUpdate,
    AgendaUserProfileUpdate,
    AvailabilityRequest,
    AvailabilityResponse,
    AvailabilityUserResult,
    DashboardEventResponse,
    DashboardOverviewResponse,
    FindTimeOption,
    FindTimeRequest,
    MeetingDeclineRequest,
    MeetingOptionsAdd,
    MeetingRequestCreate,
    MeetingVoteRequest,
    ReminderResponse,
    TodaySummaryResponse,
)
from app.domains.contracts.models import AdministrationContract
from app.domains.finance.models import OwnerRepasse, RentCharge
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import AppUser
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.portfolio.models import Capture, Person, Property

router = APIRouter(tags=["agenda"])


def _task_code(item: AgendaTask) -> str:
    return f"TAR-{item.internal_number:06d}"


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, item: AgendaTask, action: str, *, before=None, after=None, reason=None) -> None:
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
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _department_name(departments: dict[UUID, AgendaDepartment], department_id: UUID | None) -> str | None:
    return departments.get(department_id).name if department_id and department_id in departments else None


def _task_response(db: Session, item: AgendaTask) -> AgendaTaskResponse:
    users, _, departments = ensure_agenda_structure(db, item.organization_id)
    names = {user.id: user.name for user in users}
    return AgendaTaskResponse(
        id=item.id,
        code=_task_code(item),
        title=item.title,
        description=item.description,
        kind=item.kind,
        starts_at=item.starts_at,
        ends_at=item.ends_at,
        due_at=item.due_at,
        all_day=item.all_day,
        priority=item.priority,
        status=item.status,
        privacy=item.privacy,
        location=item.location,
        assigned_user_id=item.assigned_user_id,
        assigned_user_name=names.get(item.assigned_user_id),
        department_id=item.department_id,
        department_name=_department_name(departments, item.department_id),
        source_module=item.source_module,
        source_type=item.source_type,
        source_id=item.source_id,
        automatic=item.automatic,
        mandatory_action=item.mandatory_action,
        original_scheduled_at=item.original_scheduled_at,
        reschedule_sequence=item.reschedule_sequence,
        missed_justification=item.missed_justification,
        immutable_history=item.immutable_history,
        recurrence_group_id=item.recurrence_group_id,
        recurrence_sequence=item.recurrence_sequence,
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
    owner_user_id: UUID | None = None,
    department_id: UUID | None = None,
    department_name: str | None = None,
    property_code: str | None = None,
    amount: Decimal | float | None = None,
    automatic: bool = True,
    mandatory_action: bool = False,
    task_id: UUID | None = None,
    privacy: str = "normal",
    masked: bool = False,
    needs_justification: bool = False,
    original_scheduled_at: datetime | None = None,
    reschedule_sequence: int = 0,
    missed_justification: str | None = None,
    location: str | None = None,
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
        owner_user_id=owner_user_id,
        department_id=department_id,
        department_name=department_name,
        property_code=property_code,
        amount=float(amount) if amount is not None else None,
        automatic=automatic,
        mandatory_action=mandatory_action,
        task_id=task_id,
        privacy=privacy,
        masked=masked,
        needs_justification=needs_justification,
        original_scheduled_at=original_scheduled_at,
        reschedule_sequence=reschedule_sequence,
        missed_justification=missed_justification,
        location=location,
    )


def _scope(
    db: Session,
    context: UserContext,
    *,
    mine: bool,
    user_id: UUID | None,
    department_id: UUID | None,
) -> tuple[list[UUID], set[UUID], dict[UUID, dict]]:
    users, profiles, departments = ensure_agenda_structure(db, context.user.organization_id)
    grants = access_map(db, context.user.organization_id, context.user.id)
    current = profiles[context.user.id]
    if mine:
        return [context.user.id], {current.department_id} if current.department_id else set(), grants
    if user_id:
        grant = require_calendar_access(grants, user_id)
        shared = set()
        if grant["reason"] in {"self", "hierarchy"} and grant["profile"].department_id:
            shared.add(grant["profile"].department_id)
        return [user_id], shared, grants
    if department_id:
        if department_id not in departments:
            raise HTTPException(status_code=404, detail="Setor não encontrado.")
        if current.access_level not in {"director", "admin"} and not (current.access_level == "manager" and current.department_id == department_id):
            raise HTTPException(status_code=403, detail="Você não possui autorização para consultar este setor.")
        selected = [user.id for user in users if profiles[user.id].department_id == department_id]
        return selected, {department_id}, grants
    if current.access_level in {"director", "admin"}:
        return [user.id for user in users], set(departments), grants
    if current.access_level == "manager" and current.department_id:
        return [user.id for user in users if profiles[user.id].department_id == current.department_id], {current.department_id}, grants
    selected = [user_id for user_id, grant in grants.items() if grant["view"]]
    return selected, {current.department_id} if current.department_id else set(), grants


def _can_show_details(context: UserContext, grants: dict[UUID, dict], owner_user_id: UUID | None, privacy: str) -> bool:
    if owner_user_id is None or owner_user_id == context.user.id:
        return True
    grant = grants.get(owner_user_id)
    if not grant:
        return False
    if privacy == "private":
        return bool(grant.get("private_details"))
    return bool(grant.get("details"))


def _collect_events(
    db: Session,
    context: UserContext,
    start: date,
    end: date,
    *,
    mine: bool = True,
    user_id: UUID | None = None,
    department_id: UUID | None = None,
) -> list[AgendaEventResponse]:
    organization_id = context.user.organization_id
    sync_system_tasks(db, organization_id)
    users, profiles, departments = ensure_agenda_structure(db, organization_id)
    user_names = {item.id: item.name for item in users}
    selected_user_ids, shared_department_ids, grants = _scope(db, context, mine=mine, user_id=user_id, department_id=department_id)
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_exclusive = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    today = datetime.now(timezone.utc).date()
    events: list[AgendaEventResponse] = []

    task_scope = [AgendaTask.assigned_user_id.in_(selected_user_ids)] if selected_user_ids else []
    if shared_department_ids:
        task_scope.append(and_(AgendaTask.assigned_user_id.is_(None), AgendaTask.department_id.in_(shared_department_ids)))
    if task_scope:
        tasks = db.scalars(
            select(AgendaTask).where(
                AgendaTask.organization_id == organization_id,
                AgendaTask.status != "cancelled",
                AgendaTask.starts_at >= start_dt,
                AgendaTask.starts_at < end_exclusive,
                or_(*task_scope),
            )
        ).all()
    else:
        tasks = []
    for item in tasks:
        show = _can_show_details(context, grants, item.assigned_user_id, item.privacy)
        event_type = item.source_type if item.automatic and item.source_type else ("task" if item.kind == "task" else item.kind)
        title = item.title if show else "Ocupado"
        description = item.description if show else None
        events.append(_event(
            event_id=f"task:{item.id}",
            event_type=event_type,
            title=title,
            description=description,
            start_at=item.starts_at,
            end_at=item.ends_at or item.due_at,
            all_day=item.all_day,
            priority=item.priority,
            status_value=item.status,
            module=item.source_module or "agenda",
            source_id=item.source_id if show else None,
            source_code=_task_code(item) if show else None,
            responsible_name=user_names.get(item.assigned_user_id) if show else None,
            owner_user_id=item.assigned_user_id,
            department_id=item.department_id,
            department_name=_department_name(departments, item.department_id),
            automatic=item.automatic,
            mandatory_action=item.mandatory_action,
            task_id=item.id if show else None,
            privacy=item.privacy,
            masked=not show,
            needs_justification=item.automatic and item.mandatory_action and item.status == "pending" and item.starts_at.date() < today,
            original_scheduled_at=item.original_scheduled_at,
            reschedule_sequence=item.reschedule_sequence,
            missed_justification=item.missed_justification,
            location=item.location if show else None,
        ))

    participant_rows = db.scalars(
        select(AgendaMeetingParticipant).where(AgendaMeetingParticipant.user_id.in_(selected_user_ids or [UUID(int=0)]))
    ).all()
    participant_request_ids = {item.meeting_request_id for item in participant_rows}
    meeting_filter = [AgendaMeetingRequest.organizer_user_id.in_(selected_user_ids)] if selected_user_ids else []
    if participant_request_ids:
        meeting_filter.append(AgendaMeetingRequest.id.in_(participant_request_ids))
    if meeting_filter:
        requests = db.scalars(
            select(AgendaMeetingRequest).where(
                AgendaMeetingRequest.organization_id == organization_id,
                AgendaMeetingRequest.status == "confirmed",
                AgendaMeetingRequest.selected_option_id.is_not(None),
                or_(*meeting_filter),
            )
        ).all()
    else:
        requests = []
    for item in requests:
        option = db.scalar(select(AgendaMeetingOption).where(AgendaMeetingOption.id == item.selected_option_id))
        if option is None or option.starts_at >= end_exclusive or option.ends_at <= start_dt:
            continue
        participants = db.scalars(select(AgendaMeetingParticipant).where(AgendaMeetingParticipant.meeting_request_id == item.id)).all()
        participant_ids = {row.user_id for row in participants} | {item.organizer_user_id}
        viewer_is_participant = context.user.id in participant_ids
        show = viewer_is_participant or _can_show_details(context, grants, item.organizer_user_id, item.privacy)
        names = [user_names.get(user_id, "Usuário") for user_id in participant_ids]
        events.append(_event(
            event_id=f"meeting:{item.id}",
            event_type="meeting",
            title=item.title if show else "Ocupado",
            description=(item.description or f"Participantes: {', '.join(sorted(names))}") if show else None,
            start_at=option.starts_at,
            end_at=option.ends_at,
            all_day=False,
            priority="normal",
            status_value="confirmed",
            module="agenda",
            source_id=str(item.id) if show else None,
            source_code=f"REU-{item.internal_number:06d}" if show else None,
            responsible_name=user_names.get(item.organizer_user_id) if show else None,
            owner_user_id=item.organizer_user_id,
            department_id=profiles[item.organizer_user_id].department_id,
            department_name=_department_name(departments, profiles[item.organizer_user_id].department_id),
            automatic=False,
            privacy=item.privacy,
            masked=not show,
        ))

    property_codes = {item.id: f"{item.internal_number:06d}" for item in db.scalars(select(Property).where(Property.organization_id == organization_id)).all()}
    admin_department = department_by_name(db, organization_id, "Administrativo")
    if admin_department.id in shared_department_ids or (not mine and profiles[context.user.id].access_level in {"director", "admin"} and not user_id):
        window_end = end + timedelta(days=120)
        leases = db.scalars(
            select(LeaseContract).where(
                LeaseContract.organization_id == organization_id,
                LeaseContract.status.not_in(("draft", "review", "cancelled")),
                or_(LeaseContract.end_date.between(start, window_end), LeaseContract.next_adjustment_date.between(start, end)),
            )
        ).all()
        for item in leases:
            code = f"LOC-{item.internal_number:06d}"
            for days in (120, 90, 60, 30, 0):
                alert_day = item.end_date - timedelta(days=days)
                if start <= alert_day <= end:
                    events.append(_event(
                        event_id=f"lease:{item.id}:end-{days}",
                        event_type="contract_expiry",
                        title=f"Contrato encerra hoje · {code}" if days == 0 else f"Contrato vence em {days} dias · {code}",
                        description=f"Imóvel {property_codes.get(item.property_id) or '—'} · término em {item.end_date.strftime('%d/%m/%Y')}",
                        start_at=noon(alert_day),
                        all_day=True,
                        module="contracts",
                        source_id=str(item.id),
                        source_code=code,
                        department_id=admin_department.id,
                        department_name=admin_department.name,
                        property_code=property_codes.get(item.property_id),
                        priority="urgent" if days == 0 else "high" if days <= 30 else "normal" if days <= 60 else "low",
                        status_value=item.status,
                        automatic=True,
                        mandatory_action=False,
                    ))
            if start <= item.next_adjustment_date <= end:
                events.append(_event(
                    event_id=f"lease:{item.id}:adjustment",
                    event_type="adjustment",
                    title=f"Reajuste contratual · {code}",
                    description=f"Índice {item.adjustment_index} · imóvel {property_codes.get(item.property_id) or '—'}",
                    start_at=noon(item.next_adjustment_date),
                    all_day=True,
                    module="contracts",
                    source_id=str(item.id),
                    source_code=code,
                    department_id=admin_department.id,
                    department_name=admin_department.name,
                    property_code=property_codes.get(item.property_id),
                    automatic=True,
                ))

        admin_contracts = db.scalars(
            select(AdministrationContract).where(
                AdministrationContract.organization_id == organization_id,
                AdministrationContract.end_date.is_not(None),
                AdministrationContract.end_date.between(start, window_end),
                AdministrationContract.status.not_in(("draft", "review", "cancelled")),
            )
        ).all()
        for item in admin_contracts:
            if item.end_date is None:
                continue
            code = f"ADM-{item.internal_number:06d}"
            for days in (120, 90, 60, 30, 0):
                alert_day = item.end_date - timedelta(days=days)
                if start <= alert_day <= end:
                    events.append(_event(
                        event_id=f"admin:{item.id}:end-{days}",
                        event_type="contract_expiry",
                        title=f"Administração encerra hoje · {code}" if days == 0 else f"Administração vence em {days} dias · {code}",
                        description=f"Imóvel {property_codes.get(item.property_id) or '—'} · término em {item.end_date.strftime('%d/%m/%Y')}",
                        start_at=noon(alert_day),
                        all_day=True,
                        module="contracts",
                        source_id=str(item.id),
                        source_code=code,
                        department_id=admin_department.id,
                        department_name=admin_department.name,
                        property_code=property_codes.get(item.property_id),
                        priority="urgent" if days == 0 else "high" if days <= 30 else "normal",
                        status_value=item.status,
                        automatic=True,
                    ))

    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    events.sort(key=lambda item: (item.start_at, priority_order.get(item.priority, 2), item.title.lower()))
    return events


def _advance(value: datetime, frequency: str) -> datetime:
    if frequency == "daily":
        return value + timedelta(days=1)
    if frequency == "weekly":
        return value + timedelta(days=7)
    year, month = value.year, value.month + 1
    if month == 13:
        year, month = year + 1, 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _normalized_times(db: Session, organization_id: UUID, user_id: UUID, payload: AgendaTaskCreate | AgendaTaskUpdate) -> tuple[datetime, datetime | None]:
    if payload.all_day:
        return payload.starts_at, None
    if payload.ends_at:
        return payload.starts_at, payload.ends_at
    _, profiles, _ = ensure_agenda_structure(db, organization_id)
    defaults = {"task": 30, "appointment": 60, "meeting": 60, "visit": 45}
    duration = defaults.get(payload.kind, profiles[user_id].default_duration_minutes)
    return payload.starts_at, payload.starts_at + timedelta(minutes=duration)


def _conflict_or_next(db: Session, context: UserContext, user_id: UUID, starts_at: datetime, ends_at: datetime | None, *, allow_conflict: bool, exclude_task_id: UUID | None = None) -> None:
    if ends_at is None:
        return
    available, reason = user_available(db, context.user.organization_id, user_id, starts_at, ends_at, exclude_task_id=exclude_task_id)
    if available:
        return
    if user_id == context.user.id and allow_conflict:
        return
    next_at = next_common_available(db, context.user.organization_id, [user_id], ends_at, int((ends_at - starts_at).total_seconds() // 60), exclude_task_id=exclude_task_id)
    user = db.scalar(select(AppUser).where(AppUser.id == user_id))
    raise HTTPException(
        status_code=409,
        detail={
            "code": "agenda_conflict",
            "self_conflict": user_id == context.user.id,
            "user_id": str(user_id),
            "user_name": user.name if user else "Usuário",
            "reason": reason or "Horário indisponível.",
            "next_available_at": next_at.isoformat() if next_at else None,
        },
    )


@router.get("/agenda/context", response_model=AgendaContextResponse)
def agenda_context(
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> AgendaContextResponse:
    users, profiles, departments = ensure_agenda_structure(db, context.user.organization_id)
    grants = access_map(db, context.user.organization_id, context.user.id)
    profile = profiles[context.user.id]
    directory = []
    for user in users:
        grant = grants[user.id]
        directory.append(AgendaDirectoryUser(
            id=user.id,
            name=user.name,
            email=user.email,
            department_id=profiles[user.id].department_id,
            department_name=_department_name(departments, profiles[user.id].department_id),
            access_level=profiles[user.id].access_level,
            can_view_calendar=grant["view"],
            can_view_details=grant["details"],
            can_create=grant["create"],
            can_reschedule=grant["reschedule"],
            access_reason=grant["reason"],
        ))
    db.commit()
    return AgendaContextResponse(
        current_user_id=context.user.id,
        current_user_name=context.user.name,
        access_level=profile.access_level,
        department_id=profile.department_id,
        department_name=_department_name(departments, profile.department_id),
        work_start=profile.work_start,
        work_end=profile.work_end,
        lunch_start=profile.lunch_start,
        lunch_end=profile.lunch_end,
        work_days=list(profile.work_days or []),
        buffer_minutes=profile.buffer_minutes,
        default_duration_minutes=profile.default_duration_minutes,
        timezone=profile.timezone,
        departments=[AgendaDepartmentResponse(id=item.id, name=item.name) for item in sorted(departments.values(), key=lambda x: x.name.casefold())],
        directory=directory,
    )


@router.put("/agenda/profile/me", response_model=AgendaContextResponse)
def update_my_availability(
    payload: AgendaMyAvailabilityUpdate,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> AgendaContextResponse:
    _, profiles, _ = ensure_agenda_structure(db, context.user.organization_id)
    profile = profiles[context.user.id]
    profile.work_start = payload.work_start
    profile.work_end = payload.work_end
    profile.lunch_start = payload.lunch_start
    profile.lunch_end = payload.lunch_end
    profile.work_days = sorted(set(payload.work_days))
    profile.buffer_minutes = payload.buffer_minutes
    profile.default_duration_minutes = payload.default_duration_minutes
    profile.timezone = payload.timezone
    db.commit()
    return agenda_context(context=context, db=db)


@router.post("/agenda/departments", response_model=AgendaDepartmentResponse, status_code=status.HTTP_201_CREATED)
def create_department(
    payload: AgendaDepartmentCreate,
    context: UserContext = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> AgendaDepartmentResponse:
    ensure_agenda_structure(db, context.user.organization_id)
    existing = db.scalar(select(AgendaDepartment).where(AgendaDepartment.organization_id == context.user.organization_id, AgendaDepartment.name.ilike(payload.name.strip())))
    if existing:
        return AgendaDepartmentResponse(id=existing.id, name=existing.name)
    item = AgendaDepartment(organization_id=context.user.organization_id, name=payload.name.strip(), is_active=True)
    db.add(item); db.commit(); db.refresh(item)
    return AgendaDepartmentResponse(id=item.id, name=item.name)


@router.put("/agenda/profiles/{user_id}", response_model=AgendaContextResponse)
def update_user_agenda_profile(
    user_id: UUID,
    payload: AgendaUserProfileUpdate,
    context: UserContext = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> AgendaContextResponse:
    users, profiles, departments = ensure_agenda_structure(db, context.user.organization_id)
    current = profiles[context.user.id]
    if current.access_level != "admin":
        raise HTTPException(status_code=403, detail="Somente administradores podem alterar hierarquia da agenda.")
    if user_id not in profiles:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if payload.department_id and payload.department_id not in departments:
        raise HTTPException(status_code=422, detail="Setor inválido.")
    profile = profiles[user_id]
    profile.department_id = payload.department_id
    profile.access_level = payload.access_level
    db.commit()
    return agenda_context(context=context, db=db)


@router.get("/agenda/delegations", response_model=list[AgendaDelegationResponse])
def list_delegations(
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> list[AgendaDelegationResponse]:
    users = db.scalars(select(AppUser).where(AppUser.organization_id == context.user.organization_id)).all()
    names = {item.id: item.name for item in users}
    items = db.scalars(select(AgendaDelegation).where(AgendaDelegation.organization_id == context.user.organization_id, or_(AgendaDelegation.owner_user_id == context.user.id, AgendaDelegation.delegate_user_id == context.user.id))).all()
    return [AgendaDelegationResponse(
        id=item.id,
        owner_user_id=item.owner_user_id,
        owner_name=names.get(item.owner_user_id, "Usuário"),
        delegate_user_id=item.delegate_user_id,
        delegate_name=names.get(item.delegate_user_id, "Usuário"),
        can_view_availability=item.can_view_availability,
        can_view_details=item.can_view_details,
        can_create=item.can_create,
        can_reschedule=item.can_reschedule,
    ) for item in items]


@router.post("/agenda/delegations", response_model=AgendaDelegationResponse)
def save_delegation(
    payload: AgendaDelegationWrite,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> AgendaDelegationResponse:
    if payload.delegate_user_id == context.user.id:
        raise HTTPException(status_code=422, detail="Não é necessário delegar a própria agenda para você.")
    delegate = db.scalar(select(AppUser).where(AppUser.id == payload.delegate_user_id, AppUser.organization_id == context.user.organization_id, AppUser.is_active.is_(True)))
    if delegate is None:
        raise HTTPException(status_code=404, detail="Usuário delegado não encontrado.")
    item = db.scalar(select(AgendaDelegation).where(AgendaDelegation.owner_user_id == context.user.id, AgendaDelegation.delegate_user_id == payload.delegate_user_id))
    if item is None:
        item = AgendaDelegation(organization_id=context.user.organization_id, owner_user_id=context.user.id, delegate_user_id=payload.delegate_user_id, created_by_user_id=context.user.id)
        db.add(item)
    item.can_view_availability = payload.can_view_availability
    item.can_view_details = payload.can_view_details
    item.can_create = payload.can_create
    item.can_reschedule = payload.can_reschedule
    db.commit(); db.refresh(item)
    return AgendaDelegationResponse(id=item.id, owner_user_id=item.owner_user_id, owner_name=context.user.name, delegate_user_id=item.delegate_user_id, delegate_name=delegate.name, can_view_availability=item.can_view_availability, can_view_details=item.can_view_details, can_create=item.can_create, can_reschedule=item.can_reschedule)


@router.delete("/agenda/delegations/{delegation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_delegation(
    delegation_id: UUID,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> Response:
    item = db.scalar(select(AgendaDelegation).where(AgendaDelegation.id == delegation_id, AgendaDelegation.owner_user_id == context.user.id, AgendaDelegation.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Delegação não encontrada.")
    db.delete(item); db.commit()
    return Response(status_code=204)


@router.get("/agenda/events", response_model=AgendaEventsResponse)
def agenda_events(
    start: date = Query(...),
    end: date = Query(...),
    mine: bool = Query(default=True),
    user_id: UUID | None = Query(default=None),
    department_id: UUID | None = Query(default=None),
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> AgendaEventsResponse:
    if end < start:
        raise HTTPException(status_code=422, detail="O fim do período deve ser igual ou posterior ao início.")
    if (end - start).days > 370:
        raise HTTPException(status_code=422, detail="Consulte no máximo 370 dias por vez.")
    events = _collect_events(db, context, start, end, mine=mine, user_id=user_id, department_id=department_id)
    db.commit()
    return AgendaEventsResponse(start_date=start.isoformat(), end_date=end.isoformat(), events=events)


@router.post("/agenda/availability", response_model=AvailabilityResponse)
def check_availability(
    payload: AvailabilityRequest,
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> AvailabilityResponse:
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=422, detail="O término deve ser posterior ao início.")
    users, _, _ = ensure_agenda_structure(db, context.user.organization_id)
    user_map = {item.id: item for item in users}
    results = []
    duration = int((payload.ends_at - payload.starts_at).total_seconds() // 60)
    for user_id in dict.fromkeys(payload.user_ids):
        if user_id not in user_map:
            raise HTTPException(status_code=422, detail="Um dos participantes não pertence à empresa.")
        available, reason = user_available(db, context.user.organization_id, user_id, payload.starts_at, payload.ends_at, exclude_task_id=payload.exclude_task_id)
        next_at = None if available else next_common_available(db, context.user.organization_id, [user_id], payload.ends_at, duration, exclude_task_id=payload.exclude_task_id)
        results.append(AvailabilityUserResult(user_id=user_id, user_name=user_map[user_id].name, available=available, reason=reason, next_available_at=next_at))
    return AvailabilityResponse(all_available=all(item.available for item in results), users=results)


@router.post("/agenda/find-time", response_model=list[FindTimeOption])
def find_time(
    payload: FindTimeRequest,
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> list[FindTimeOption]:
    if payload.end_date < payload.start_date or (payload.end_date - payload.start_date).days > 60:
        raise HTTPException(status_code=422, detail="Informe uma janela de até 60 dias.")
    users, _, _ = ensure_agenda_structure(db, context.user.organization_id)
    valid_ids = {item.id for item in users}
    user_ids = list(dict.fromkeys(payload.user_ids))
    if any(item not in valid_ids for item in user_ids):
        raise HTTPException(status_code=422, detail="Um dos participantes não pertence à empresa.")
    candidate = datetime.combine(payload.start_date, time(hour=8), tzinfo=timezone.utc)
    end_limit = datetime.combine(payload.end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    results: list[FindTimeOption] = []
    while candidate < end_limit and len(results) < payload.limit:
        found = next_common_available(db, context.user.organization_id, user_ids, candidate, payload.duration_minutes, horizon_days=max(1, (payload.end_date - candidate.date()).days + 1))
        if found is None or found >= end_limit:
            break
        results.append(FindTimeOption(starts_at=found, ends_at=found + timedelta(minutes=payload.duration_minutes)))
        candidate = found + timedelta(minutes=15)
    return results


@router.post("/agenda/tasks", response_model=AgendaTaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: AgendaTaskCreate,
    request: Request,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> AgendaTaskResponse:
    users, profiles, _ = ensure_agenda_structure(db, context.user.organization_id)
    user_map = {item.id: item for item in users}
    assigned_user_id = payload.assigned_user_id or context.user.id
    if assigned_user_id not in user_map:
        raise HTTPException(status_code=422, detail="Responsável não encontrado.")
    grants = access_map(db, context.user.organization_id, context.user.id)
    require_schedule_access(grants, assigned_user_id)
    starts_at, ends_at = _normalized_times(db, context.user.organization_id, assigned_user_id, payload)

    occurrences: list[tuple[datetime, datetime | None, int]] = [(starts_at, ends_at, 0)]
    if payload.recurrence != "none":
        if payload.recurrence_until is None:
            raise HTTPException(status_code=422, detail="Informe até quando a recorrência deve ser criada.")
        cursor_start, cursor_end = starts_at, ends_at
        sequence = 0
        while cursor_start.date() < payload.recurrence_until:
            cursor_start = _advance(cursor_start, payload.recurrence)
            cursor_end = _advance(cursor_end, payload.recurrence) if cursor_end else None
            if cursor_start.date() > payload.recurrence_until:
                break
            sequence += 1
            if sequence > 366:
                raise HTTPException(status_code=422, detail="A recorrência ultrapassa o limite de 366 ocorrências.")
            occurrences.append((cursor_start, cursor_end, sequence))

    for occurrence_start, occurrence_end, _ in occurrences:
        if not payload.all_day:
            _conflict_or_next(db, context, assigned_user_id, occurrence_start, occurrence_end, allow_conflict=payload.allow_conflict)

    group_id = uuid.uuid4() if len(occurrences) > 1 else None
    first: AgendaTask | None = None
    for occurrence_start, occurrence_end, sequence in occurrences:
        item = AgendaTask(
            organization_id=context.user.organization_id,
            title=payload.title.strip(),
            description=(payload.description or "").strip() or None,
            kind=payload.kind,
            starts_at=occurrence_start,
            ends_at=occurrence_end,
            due_at=payload.due_at,
            all_day=payload.all_day,
            priority=payload.priority,
            status="pending",
            privacy=payload.privacy,
            location=(payload.location or "").strip() or None,
            assigned_user_id=assigned_user_id,
            department_id=profiles[assigned_user_id].department_id,
            automatic=False,
            mandatory_action=False,
            completion_source="agenda",
            recurrence_group_id=group_id,
            recurrence_sequence=sequence,
            recurrence_rule={"frequency": payload.recurrence, "until": payload.recurrence_until.isoformat() if payload.recurrence_until else None} if group_id else {},
            created_by_user_id=context.user.id,
        )
        db.add(item); db.flush()
        _audit(db, request, context, item, "agenda.task.created", after={"code": _task_code(item), "assigned_user_id": str(assigned_user_id), "starts_at": occurrence_start.isoformat(), "recurrence_sequence": sequence})
        if first is None:
            first = item
    db.commit(); db.refresh(first)
    return _task_response(db, first)


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
    if item.automatic or item.immutable_history:
        raise HTTPException(status_code=409, detail="Ocorrências automáticas e históricas não podem ser editadas.")
    if item.status == "cancelled":
        raise HTTPException(status_code=409, detail="Tarefa cancelada não pode ser editada.")
    users, profiles, _ = ensure_agenda_structure(db, context.user.organization_id)
    assigned_user_id = payload.assigned_user_id or context.user.id
    if assigned_user_id not in {user.id for user in users}:
        raise HTTPException(status_code=422, detail="Responsável não encontrado.")
    grants = access_map(db, context.user.organization_id, context.user.id)
    require_schedule_access(grants, assigned_user_id, reschedule=True)
    starts_at, ends_at = _normalized_times(db, context.user.organization_id, assigned_user_id, payload)
    if not payload.all_day:
        _conflict_or_next(db, context, assigned_user_id, starts_at, ends_at, allow_conflict=payload.allow_conflict, exclude_task_id=item.id)
    before = {"title": item.title, "starts_at": item.starts_at.isoformat(), "assigned_user_id": str(item.assigned_user_id) if item.assigned_user_id else None}
    item.title = payload.title.strip(); item.description = (payload.description or "").strip() or None
    item.kind = payload.kind; item.starts_at = starts_at; item.ends_at = ends_at; item.due_at = payload.due_at
    item.all_day = payload.all_day; item.priority = payload.priority; item.privacy = payload.privacy
    item.location = (payload.location or "").strip() or None; item.assigned_user_id = assigned_user_id; item.department_id = profiles[assigned_user_id].department_id
    _audit(db, request, context, item, "agenda.task.updated", before=before, after={"title": item.title, "starts_at": item.starts_at.isoformat(), "assigned_user_id": str(item.assigned_user_id)})
    db.commit(); db.refresh(item)
    return _task_response(db, item)


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
    if item.automatic:
        raise HTTPException(status_code=409, detail="A conclusão deste item automático é controlada pelo módulo de origem.")
    if item.immutable_history:
        raise HTTPException(status_code=409, detail="Este histórico é imutável.")
    if item.assigned_user_id:
        require_schedule_access(access_map(db, context.user.organization_id, context.user.id), item.assigned_user_id, reschedule=True)
    before = {"status": item.status}
    item.status = payload.status
    if payload.status == "completed":
        item.completed_at = datetime.now(timezone.utc); item.completed_by_user_id = context.user.id
    elif payload.status in {"pending", "confirmed"}:
        item.completed_at = None; item.completed_by_user_id = None
    _audit(db, request, context, item, "agenda.task.status_changed", before=before, after={"status": item.status})
    db.commit(); db.refresh(item)
    return _task_response(db, item)


@router.post("/agenda/tasks/{task_id}/justify-missed", response_model=AgendaTaskResponse)
def justify_missed_system_task(
    task_id: UUID,
    payload: AgendaMissJustification,
    request: Request,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> AgendaTaskResponse:
    item = db.scalar(select(AgendaTask).where(AgendaTask.id == task_id, AgendaTask.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada.")
    if not item.automatic or not item.mandatory_action or item.status != "pending" or item.starts_at.date() >= datetime.now(timezone.utc).date():
        raise HTTPException(status_code=409, detail="Esta ocorrência não exige justificativa de não cumprimento.")
    if item.assigned_user_id and item.assigned_user_id != context.user.id:
        require_schedule_access(access_map(db, context.user.organization_id, context.user.id), item.assigned_user_id, reschedule=True)
    item.status = "missed"; item.missed_justification = payload.justification.strip(); item.missed_at = datetime.now(timezone.utc); item.immutable_history = True
    _audit(db, request, context, item, "agenda.system.missed_justified", after={"status": "missed", "reschedule_sequence": item.reschedule_sequence}, reason=item.missed_justification)
    db.commit(); db.refresh(item)
    return _task_response(db, item)


def _meeting_payload(db: Session, context: UserContext, item: AgendaMeetingRequest) -> dict:
    users = db.scalars(select(AppUser).where(AppUser.organization_id == context.user.organization_id)).all()
    user_map = {user.id: user for user in users}
    participants = db.scalars(select(AgendaMeetingParticipant).where(AgendaMeetingParticipant.meeting_request_id == item.id)).all()
    participant_ids = [row.user_id for row in participants]
    all_user_ids = [item.organizer_user_id] + participant_ids
    options = db.scalars(select(AgendaMeetingOption).where(AgendaMeetingOption.meeting_request_id == item.id).order_by(AgendaMeetingOption.starts_at)).all()
    option_payload = []
    for option in options:
        votes = db.scalars(select(AgendaMeetingVote).where(AgendaMeetingVote.meeting_option_id == option.id)).all()
        vote_map = {vote.user_id: vote.decision for vote in votes}
        availability = []
        for user_id in all_user_ids:
            available, reason = user_available(db, context.user.organization_id, user_id, option.starts_at, option.ends_at)
            availability.append({"user_id": str(user_id), "user_name": user_map[user_id].name, "available": available, "reason": reason})
        option_payload.append({
            "id": str(option.id), "starts_at": option.starts_at, "ends_at": option.ends_at, "status": option.status,
            "proposed_by_user_id": str(option.proposed_by_user_id), "my_vote": vote_map.get(context.user.id),
            "votes": {str(key): value for key, value in vote_map.items()},
            "all_available": all(row["available"] for row in availability), "availability": availability,
        })
    return {
        "id": str(item.id), "code": f"REU-{item.internal_number:06d}", "title": item.title, "description": item.description,
        "duration_minutes": item.duration_minutes, "privacy": item.privacy, "status": item.status,
        "selected_option_id": str(item.selected_option_id) if item.selected_option_id else None,
        "organizer": {"id": str(item.organizer_user_id), "name": user_map[item.organizer_user_id].name},
        "participants": [{"id": str(row.user_id), "name": user_map[row.user_id].name, "status": row.status} for row in participants],
        "options": option_payload,
        "direction": "outgoing" if item.organizer_user_id == context.user.id else "incoming",
        "created_at": item.created_at,
    }


@router.get("/agenda/meeting-requests")
def list_meeting_requests(
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    participant_ids = db.scalars(select(AgendaMeetingParticipant.meeting_request_id).where(AgendaMeetingParticipant.user_id == context.user.id)).all()
    items = db.scalars(select(AgendaMeetingRequest).where(AgendaMeetingRequest.organization_id == context.user.organization_id, or_(AgendaMeetingRequest.organizer_user_id == context.user.id, AgendaMeetingRequest.id.in_(participant_ids or [UUID(int=0)]))).order_by(AgendaMeetingRequest.created_at.desc()).limit(100)).all()
    return [_meeting_payload(db, context, item) for item in items]


@router.post("/agenda/meeting-requests", status_code=status.HTTP_201_CREATED)
def create_meeting_request(
    payload: MeetingRequestCreate,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> dict:
    users = db.scalars(select(AppUser).where(AppUser.organization_id == context.user.organization_id, AppUser.is_active.is_(True))).all()
    valid_ids = {item.id for item in users}
    participant_ids = [item for item in dict.fromkeys(payload.participant_user_ids) if item != context.user.id]
    if not participant_ids or any(item not in valid_ids for item in participant_ids):
        raise HTTPException(status_code=422, detail="Selecione ao menos um participante válido.")
    item = AgendaMeetingRequest(organization_id=context.user.organization_id, organizer_user_id=context.user.id, title=payload.title.strip(), description=(payload.description or "").strip() or None, duration_minutes=payload.duration_minutes, privacy=payload.privacy, status="pending")
    db.add(item); db.flush()
    for user_id in participant_ids:
        db.add(AgendaMeetingParticipant(meeting_request_id=item.id, user_id=user_id, status="pending"))
    for option_input in payload.options:
        option = AgendaMeetingOption(meeting_request_id=item.id, starts_at=option_input.starts_at, ends_at=option_input.starts_at + timedelta(minutes=payload.duration_minutes), proposed_by_user_id=context.user.id, status="open")
        db.add(option); db.flush(); db.add(AgendaMeetingVote(meeting_option_id=option.id, user_id=context.user.id, decision="accepted"))
    db.commit(); db.refresh(item)
    return _meeting_payload(db, context, item)


def _meeting_for_user(db: Session, context: UserContext, request_id: UUID) -> AgendaMeetingRequest:
    item = db.scalar(select(AgendaMeetingRequest).where(AgendaMeetingRequest.id == request_id, AgendaMeetingRequest.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Solicitação de reunião não encontrada.")
    participant = db.scalar(select(AgendaMeetingParticipant).where(AgendaMeetingParticipant.meeting_request_id == item.id, AgendaMeetingParticipant.user_id == context.user.id))
    if item.organizer_user_id != context.user.id and participant is None:
        raise HTTPException(status_code=403, detail="Você não participa desta solicitação.")
    return item


@router.post("/agenda/meeting-requests/{request_id}/options")
def add_meeting_options(
    request_id: UUID,
    payload: MeetingOptionsAdd,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> dict:
    item = _meeting_for_user(db, context, request_id)
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="A reunião não aceita novas opções neste estado.")
    for option_input in payload.options:
        option = AgendaMeetingOption(meeting_request_id=item.id, starts_at=option_input.starts_at, ends_at=option_input.starts_at + timedelta(minutes=item.duration_minutes), proposed_by_user_id=context.user.id, status="open")
        db.add(option); db.flush(); db.add(AgendaMeetingVote(meeting_option_id=option.id, user_id=context.user.id, decision="accepted"))
    db.commit(); db.refresh(item)
    return _meeting_payload(db, context, item)


@router.post("/agenda/meeting-options/{option_id}/respond")
def respond_meeting_option(
    option_id: UUID,
    payload: MeetingVoteRequest,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> dict:
    option = db.scalar(select(AgendaMeetingOption).where(AgendaMeetingOption.id == option_id))
    if option is None:
        raise HTTPException(status_code=404, detail="Opção de horário não encontrada.")
    item = _meeting_for_user(db, context, option.meeting_request_id)
    if item.status != "pending" or option.status != "open":
        raise HTTPException(status_code=409, detail="Esta opção não está mais disponível para resposta.")
    if payload.decision == "accepted":
        available, reason = user_available(db, context.user.organization_id, context.user.id, option.starts_at, option.ends_at)
        if not available:
            next_at = next_common_available(db, context.user.organization_id, [context.user.id], option.ends_at, item.duration_minutes)
            raise HTTPException(status_code=409, detail={"code": "agenda_conflict", "self_conflict": True, "reason": reason, "next_available_at": next_at.isoformat() if next_at else None})
    vote = db.scalar(select(AgendaMeetingVote).where(AgendaMeetingVote.meeting_option_id == option.id, AgendaMeetingVote.user_id == context.user.id))
    if vote is None:
        vote = AgendaMeetingVote(meeting_option_id=option.id, user_id=context.user.id, decision=payload.decision); db.add(vote)
    else:
        vote.decision = payload.decision; vote.responded_at = datetime.now(timezone.utc)
    db.flush()
    participants = db.scalars(select(AgendaMeetingParticipant).where(AgendaMeetingParticipant.meeting_request_id == item.id)).all()
    required = {item.organizer_user_id} | {row.user_id for row in participants}
    accepted = set(db.scalars(select(AgendaMeetingVote.user_id).where(AgendaMeetingVote.meeting_option_id == option.id, AgendaMeetingVote.decision == "accepted")).all())
    if required.issubset(accepted):
        for user_id in required:
            available, _ = user_available(db, context.user.organization_id, user_id, option.starts_at, option.ends_at)
            if not available and user_id != context.user.id:
                raise HTTPException(status_code=409, detail="Um dos participantes ficou indisponível neste horário. Escolha ou proponha outro horário.")
        item.status = "confirmed"; item.selected_option_id = option.id; option.status = "selected"
        for other in db.scalars(select(AgendaMeetingOption).where(AgendaMeetingOption.meeting_request_id == item.id, AgendaMeetingOption.id != option.id)).all():
            other.status = "rejected"
        for participant in participants:
            participant.status = "accepted"; participant.responded_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(item)
    return _meeting_payload(db, context, item)


@router.post("/agenda/meeting-requests/{request_id}/decline")
def decline_meeting_request(
    request_id: UUID,
    payload: MeetingDeclineRequest,
    context: UserContext = Depends(require_permission("agenda.manage")),
    db: Session = Depends(get_db),
) -> dict:
    item = _meeting_for_user(db, context, request_id)
    participant = db.scalar(select(AgendaMeetingParticipant).where(AgendaMeetingParticipant.meeting_request_id == item.id, AgendaMeetingParticipant.user_id == context.user.id))
    if item.organizer_user_id == context.user.id:
        item.status = "cancelled"
    elif participant:
        participant.status = "declined"; participant.responded_at = datetime.now(timezone.utc)
        remaining = db.scalars(select(AgendaMeetingParticipant).where(AgendaMeetingParticipant.meeting_request_id == item.id, AgendaMeetingParticipant.status != "declined")).all()
        if not remaining:
            item.status = "declined"
    db.commit(); db.refresh(item)
    return _meeting_payload(db, context, item)


@router.get("/agenda/today-summary", response_model=TodaySummaryResponse)
def today_summary(
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> TodaySummaryResponse:
    today = datetime.now(timezone.utc).date()
    sync_system_tasks(db, context.user.organization_id)
    events = _collect_events(db, context, today, today, mine=True)
    _, profiles, _ = ensure_agenda_structure(db, context.user.organization_id)
    profile = profiles[context.user.id]
    pending_scope = [AgendaTask.assigned_user_id == context.user.id]
    if profile.department_id:
        pending_scope.append(and_(AgendaTask.assigned_user_id.is_(None), AgendaTask.department_id == profile.department_id))
    pending = db.scalars(select(AgendaTask).where(AgendaTask.organization_id == context.user.organization_id, AgendaTask.automatic.is_(True), AgendaTask.mandatory_action.is_(True), AgendaTask.status == "pending", AgendaTask.starts_at < datetime.combine(today, time.min, tzinfo=timezone.utc), or_(*pending_scope)).order_by(AgendaTask.starts_at)).all()
    participant_request_ids = db.scalars(select(AgendaMeetingParticipant.meeting_request_id).where(AgendaMeetingParticipant.user_id == context.user.id, AgendaMeetingParticipant.status == "pending")).all()
    pending_invites = len(db.scalars(select(AgendaMeetingRequest.id).where(AgendaMeetingRequest.id.in_(participant_request_ids or [UUID(int=0)]), AgendaMeetingRequest.status == "pending")).all())
    seen = db.scalar(select(AgendaDailyBriefing).where(AgendaDailyBriefing.user_id == context.user.id, AgendaDailyBriefing.briefing_date == today))
    db.commit()
    return TodaySummaryResponse(date=today.isoformat(), show_popup=seen is None or bool(pending), events=events, pending_justifications=[_task_response(db, item) for item in pending], pending_invites=pending_invites)


@router.post("/agenda/today-summary/seen", status_code=status.HTTP_204_NO_CONTENT)
def mark_today_summary_seen(
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> Response:
    today = datetime.now(timezone.utc).date()
    item = db.scalar(select(AgendaDailyBriefing).where(AgendaDailyBriefing.user_id == context.user.id, AgendaDailyBriefing.briefing_date == today))
    if item is None:
        db.add(AgendaDailyBriefing(organization_id=context.user.organization_id, user_id=context.user.id, briefing_date=today))
        db.commit()
    return Response(status_code=204)


@router.get("/agenda/reminders", response_model=list[ReminderResponse])
def agenda_reminders(
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> list[ReminderResponse]:
    now = datetime.now(timezone.utc)
    events = _collect_events(db, context, now.date(), now.date(), mine=True)
    reminders = []
    for item in events:
        if item.all_day or item.status in {"completed", "cancelled", "missed"}:
            continue
        minutes = int((item.start_at - now).total_seconds() // 60)
        if 4 <= minutes <= 15:
            reminders.append(ReminderResponse(event=item, minutes_until=minutes))
    db.commit()
    return reminders


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
def dashboard_overview(
    context: UserContext = Depends(require_permission("dashboard.view")),
    db: Session = Depends(get_db),
) -> DashboardOverviewResponse:
    org = context.user.organization_id
    today = datetime.now(timezone.utc).date(); limit = today + timedelta(days=120)
    administered_properties = db.scalar(select(func.count(func.distinct(AdministrationContract.property_id))).where(AdministrationContract.organization_id == org, AdministrationContract.status == "signed")) or 0
    available_properties = db.scalar(select(func.count(Property.id)).where(Property.organization_id == org, Property.status == "available")) or 0
    active_leases = db.scalar(select(func.count(LeaseContract.id)).where(LeaseContract.organization_id == org, LeaseContract.status == "signed")) or 0
    expiring_leases = db.scalar(select(func.count(LeaseContract.id)).where(LeaseContract.organization_id == org, LeaseContract.status == "signed", LeaseContract.end_date.between(today, limit))) or 0
    expiring_admin = db.scalar(select(func.count(AdministrationContract.id)).where(AdministrationContract.organization_id == org, AdministrationContract.status == "signed", AdministrationContract.end_date.is_not(None), AdministrationContract.end_date.between(today, limit))) or 0
    contracts_expiring_120 = int(expiring_leases) + int(expiring_admin)
    open_maintenance = db.scalar(select(func.count(MaintenanceRequest.id)).where(MaintenanceRequest.organization_id == org, MaintenanceRequest.status.not_in(("completed", "cancelled")))) or 0
    overdue_amount = db.scalar(select(func.coalesce(func.sum(RentCharge.gross_amount), Decimal("0"))).where(RentCharge.organization_id == org, RentCharge.due_date < today, RentCharge.status.not_in(("paid", "cancelled")))) or Decimal("0")
    pending_repasses_amount = db.scalar(select(func.coalesce(func.sum(OwnerRepasse.amount), Decimal("0"))).where(OwnerRepasse.organization_id == org, OwnerRepasse.status == "pending")) or Decimal("0")
    open_captures = db.scalar(select(func.count(Capture.id)).where(Capture.organization_id == org, Capture.status.not_in(("lost", "available")))) or 0
    approved_captures = db.scalar(select(func.count(Capture.id)).where(Capture.organization_id == org, Capture.status == "approved")) or 0
    properties_with_administration = db.scalar(select(func.count(func.distinct(AdministrationContract.property_id))).where(AdministrationContract.organization_id == org, AdministrationContract.status != "cancelled")) or 0
    total_properties = db.scalar(select(func.count(Property.id)).where(Property.organization_id == org)) or 0
    managed_properties = db.scalar(select(func.count(func.distinct(AdministrationContract.property_id))).where(AdministrationContract.organization_id == org, AdministrationContract.status == "signed")) or 0
    contracts_awaiting_signature = db.scalar(select(func.count(AdministrationContract.id)).where(AdministrationContract.organization_id == org, AdministrationContract.status == "pending_signature")) or 0
    contracts_in_review = db.scalar(select(func.count(AdministrationContract.id)).where(AdministrationContract.organization_id == org, AdministrationContract.status == "review")) or 0
    recent_capture_rows = db.execute(
        select(Capture.id, Capture.status, Capture.property_address, Capture.estimated_rent, Capture.created_at, Person.name)
        .outerjoin(Person, Person.id == Capture.contact_person_id)
        .where(Capture.organization_id == org, Capture.status != "lost")
        .order_by(Capture.created_at.desc())
        .limit(5)
    ).all()
    events = _collect_events(db, context, today, today, mine=True)
    overdue_tasks = len([item for item in events if item.needs_justification])
    tasks_today = len([item for item in events if item.status not in {"completed", "cancelled", "missed"}])
    db.commit()
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
        events_today=[DashboardEventResponse(id=item.id, title=item.title, start_at=item.start_at, event_type=item.event_type, module=item.module, priority=item.priority) for item in events[:8]],
        open_captures=int(open_captures),
        approved_captures=int(approved_captures),
        properties_without_administration=max(0, int(total_properties) - int(properties_with_administration)),
        properties_with_administration=int(properties_with_administration),
        managed_properties=int(managed_properties),
        contracts_awaiting_signature=int(contracts_awaiting_signature),
        contracts_in_review=int(contracts_in_review),
        recent_captures=[{
            "id": str(row.id), "status": row.status, "property_address": row.property_address,
            "estimated_rent": float(row.estimated_rent) if row.estimated_rent is not None else None,
            "created_at": row.created_at, "contact_person_name": row.name,
        } for row in recent_capture_rows],
    )
