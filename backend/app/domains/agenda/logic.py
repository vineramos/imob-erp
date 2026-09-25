from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.domains.agenda.models import (
    AgendaDelegation,
    AgendaDepartment,
    AgendaMeetingOption,
    AgendaMeetingParticipant,
    AgendaMeetingRequest,
    AgendaTask,
    AgendaUserProfile,
)
from app.domains.finance.models import OwnerRepasse, RentCharge
from app.domains.foundation.models import AppUser
from app.domains.inspections.models import Inspection
from app.domains.maintenance.models import MaintenanceRequest

DEFAULT_DEPARTMENTS = ("Administração", "Administrativo", "Financeiro", "Comercial", "Operações", "Geral")
LEVEL_ORDER = {"collaborator": 0, "manager": 1, "director": 2, "admin": 3}


def noon(day: date) -> datetime:
    return datetime.combine(day, time(hour=12), tzinfo=timezone.utc)


def role_keys(user: AppUser) -> set[str]:
    return {str(role.key).lower() for role in user.roles if role.is_active}


def infer_level(user: AppUser) -> str:
    keys = role_keys(user)
    names = {str(role.name).lower() for role in user.roles if role.is_active}
    joined = " ".join(keys | names)
    if "admin" in keys or "administrador" in joined:
        return "admin"
    if "director" in joined or "diretor" in joined:
        return "director"
    if "manager" in joined or "gerente" in joined:
        return "manager"
    return "collaborator"


def infer_department_name(user: AppUser) -> str:
    keys = role_keys(user)
    if "admin" in keys:
        return "Administração"
    if "finance" in keys:
        return "Financeiro"
    if "broker" in keys:
        return "Comercial"
    if "maintenance_inspection" in keys:
        return "Operações"
    if "administrative" in keys:
        return "Administrativo"
    return "Geral"


def ensure_agenda_structure(db: Session, organization_id: UUID) -> tuple[list[AppUser], dict[UUID, AgendaUserProfile], dict[UUID, AgendaDepartment]]:
    departments = db.scalars(
        select(AgendaDepartment).where(AgendaDepartment.organization_id == organization_id, AgendaDepartment.is_active.is_(True))
    ).all()
    by_name = {item.name.casefold(): item for item in departments}
    for name in DEFAULT_DEPARTMENTS:
        if name.casefold() not in by_name:
            item = AgendaDepartment(organization_id=organization_id, name=name, is_active=True)
            db.add(item)
            db.flush()
            departments.append(item)
            by_name[name.casefold()] = item

    users = db.scalars(
        select(AppUser)
        .options(selectinload(AppUser.roles))
        .where(AppUser.organization_id == organization_id, AppUser.is_active.is_(True))
        .order_by(AppUser.name)
    ).unique().all()
    profiles = db.scalars(select(AgendaUserProfile).where(AgendaUserProfile.organization_id == organization_id)).all()
    profile_map = {item.user_id: item for item in profiles}
    for user in users:
        profile = profile_map.get(user.id)
        if profile is None:
            department = by_name[infer_department_name(user).casefold()]
            profile = AgendaUserProfile(
                organization_id=organization_id,
                user_id=user.id,
                department_id=department.id,
                access_level=infer_level(user),
                work_start="08:30",
                work_end="18:00",
                lunch_start="12:00",
                lunch_end="13:00",
                work_days=[0, 1, 2, 3, 4],
                buffer_minutes=15,
                default_duration_minutes=60,
                timezone="America/Sao_Paulo",
            )
            db.add(profile)
            db.flush()
            profile_map[user.id] = profile
        elif "admin" in role_keys(user) and profile.access_level != "admin":
            profile.access_level = "admin"
    return users, profile_map, {item.id: item for item in departments}


def department_by_name(db: Session, organization_id: UUID, name: str) -> AgendaDepartment:
    item = db.scalar(
        select(AgendaDepartment).where(AgendaDepartment.organization_id == organization_id, func.lower(AgendaDepartment.name) == name.lower())
    )
    if item is None:
        item = AgendaDepartment(organization_id=organization_id, name=name, is_active=True)
        db.add(item)
        db.flush()
    return item


def access_map(db: Session, organization_id: UUID, current_user_id: UUID) -> dict[UUID, dict]:
    users, profiles, departments = ensure_agenda_structure(db, organization_id)
    current = profiles[current_user_id]
    delegations = db.scalars(
        select(AgendaDelegation).where(
            AgendaDelegation.organization_id == organization_id,
            AgendaDelegation.delegate_user_id == current_user_id,
        )
    ).all()
    delegation_map = {item.owner_user_id: item for item in delegations}
    result: dict[UUID, dict] = {}
    for user in users:
        profile = profiles[user.id]
        same_department = current.department_id is not None and current.department_id == profile.department_id
        delegation = delegation_map.get(user.id)
        if user.id == current_user_id:
            grants = dict(view=True, details=True, create=True, reschedule=True, reason="self", private_details=True)
        elif current.access_level in {"director", "admin"}:
            grants = dict(view=True, details=True, create=True, reschedule=True, reason="hierarchy", private_details=bool(delegation and delegation.can_view_details))
        elif current.access_level == "manager" and same_department:
            grants = dict(view=True, details=True, create=True, reschedule=True, reason="hierarchy", private_details=bool(delegation and delegation.can_view_details))
        elif delegation and delegation.can_view_availability:
            grants = dict(
                view=True,
                details=delegation.can_view_details,
                create=delegation.can_create,
                reschedule=delegation.can_reschedule,
                reason="delegation",
                private_details=delegation.can_view_details,
            )
        else:
            grants = dict(view=False, details=False, create=False, reschedule=False, reason=None, private_details=False)
        result[user.id] = {
            **grants,
            "user": user,
            "profile": profile,
            "department": departments.get(profile.department_id),
        }
    return result


def require_calendar_access(access: dict[UUID, dict], user_id: UUID) -> dict:
    grant = access.get(user_id)
    if grant is None or not grant["view"]:
        raise HTTPException(status_code=403, detail="Você não possui autorização para consultar a agenda desta pessoa.")
    return grant


def require_schedule_access(access: dict[UUID, dict], user_id: UUID, *, reschedule: bool = False) -> dict:
    grant = access.get(user_id)
    key = "reschedule" if reschedule else "create"
    if grant is None or not grant[key]:
        raise HTTPException(status_code=403, detail="Você não possui autorização para alterar a agenda desta pessoa.")
    return grant


def parse_clock(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def _working_hours_available(profile: AgendaUserProfile, starts_at: datetime, ends_at: datetime) -> tuple[bool, str | None]:
    try:
        zone = ZoneInfo(profile.timezone or "America/Sao_Paulo")
    except Exception:
        zone = ZoneInfo("America/Sao_Paulo")
    local_start = starts_at.astimezone(zone)
    local_end = ends_at.astimezone(zone)
    if local_start.date() != local_end.date():
        return False, "O compromisso atravessa mais de um dia."
    if local_start.weekday() not in set(profile.work_days or [0, 1, 2, 3, 4]):
        return False, "Fora dos dias de trabalho configurados."
    work_start, work_end = parse_clock(profile.work_start), parse_clock(profile.work_end)
    if local_start.time() < work_start or local_end.time() > work_end:
        return False, "Fora do horário de trabalho."
    if profile.lunch_start and profile.lunch_end:
        lunch_start, lunch_end = parse_clock(profile.lunch_start), parse_clock(profile.lunch_end)
        if local_start.time() < lunch_end and local_end.time() > lunch_start:
            return False, "Conflita com o intervalo configurado."
    return True, None


def busy_intervals(db: Session, organization_id: UUID, user_id: UUID, starts_at: datetime, ends_at: datetime, *, exclude_task_id: UUID | None = None) -> list[tuple[datetime, datetime]]:
    stmt = select(AgendaTask).where(
        AgendaTask.organization_id == organization_id,
        AgendaTask.assigned_user_id == user_id,
        AgendaTask.all_day.is_(False),
        AgendaTask.ends_at.is_not(None),
        AgendaTask.status.in_(("pending", "confirmed")),
        AgendaTask.starts_at < ends_at + timedelta(hours=4),
        AgendaTask.ends_at > starts_at - timedelta(hours=4),
    )
    if exclude_task_id:
        stmt = stmt.where(AgendaTask.id != exclude_task_id)
    tasks = db.scalars(stmt).all()
    result = [(item.starts_at, item.ends_at) for item in tasks if item.ends_at]

    participant_request_ids = db.scalars(
        select(AgendaMeetingParticipant.meeting_request_id).where(AgendaMeetingParticipant.user_id == user_id)
    ).all()
    requests = db.scalars(
        select(AgendaMeetingRequest).where(
            AgendaMeetingRequest.organization_id == organization_id,
            AgendaMeetingRequest.status == "confirmed",
            or_(AgendaMeetingRequest.organizer_user_id == user_id, AgendaMeetingRequest.id.in_(participant_request_ids or [UUID(int=0)])),
        )
    ).all()
    option_ids = [item.selected_option_id for item in requests if item.selected_option_id]
    if option_ids:
        for item in db.scalars(select(AgendaMeetingOption).where(AgendaMeetingOption.id.in_(option_ids))).all():
            if item.starts_at < ends_at + timedelta(hours=4) and item.ends_at > starts_at - timedelta(hours=4):
                result.append((item.starts_at, item.ends_at))
    return result


def user_available(db: Session, organization_id: UUID, user_id: UUID, starts_at: datetime, ends_at: datetime, *, exclude_task_id: UUID | None = None) -> tuple[bool, str | None]:
    users, profiles, _ = ensure_agenda_structure(db, organization_id)
    user_map = {item.id: item for item in users}
    if user_id not in user_map:
        return False, "Usuário indisponível."
    profile = profiles[user_id]
    valid, reason = _working_hours_available(profile, starts_at, ends_at)
    if not valid:
        return False, reason
    buffer_delta = timedelta(minutes=max(0, profile.buffer_minutes))
    requested_start = starts_at - buffer_delta
    requested_end = ends_at + buffer_delta
    for busy_start, busy_end in busy_intervals(db, organization_id, user_id, starts_at, ends_at, exclude_task_id=exclude_task_id):
        busy_start -= buffer_delta
        busy_end += buffer_delta
        if requested_start < busy_end and requested_end > busy_start:
            return False, "Já existe compromisso neste horário."
    return True, None


def next_common_available(
    db: Session,
    organization_id: UUID,
    user_ids: list[UUID],
    starts_at: datetime,
    duration_minutes: int,
    *,
    exclude_task_id: UUID | None = None,
    horizon_days: int = 21,
) -> datetime | None:
    candidate = starts_at.replace(second=0, microsecond=0)
    remainder = candidate.minute % 15
    if remainder:
        candidate += timedelta(minutes=15 - remainder)
    duration = timedelta(minutes=duration_minutes)
    deadline = candidate + timedelta(days=horizon_days)
    while candidate <= deadline:
        end = candidate + duration
        if all(user_available(db, organization_id, user_id, candidate, end, exclude_task_id=exclude_task_id)[0] for user_id in user_ids):
            return candidate
        candidate += timedelta(minutes=15)
    return None


def _ensure_source_chain(
    db: Session,
    *,
    organization_id: UUID,
    source_module: str,
    source_type: str,
    source_id: str,
    title: str,
    description: str | None,
    original_at: datetime,
    completion_at: datetime | None,
    assigned_user_id: UUID | None,
    department_id: UUID | None,
    kind: str,
    all_day: bool,
    duration_minutes: int,
    priority: str,
) -> None:
    today = datetime.now(timezone.utc).date()
    existing = db.scalars(
        select(AgendaTask).where(
            AgendaTask.organization_id == organization_id,
            AgendaTask.automatic.is_(True),
            AgendaTask.source_type == source_type,
            AgendaTask.source_id == source_id,
            AgendaTask.original_scheduled_at == original_at,
        ).order_by(AgendaTask.reschedule_sequence)
    ).all()
    by_sequence = {item.reschedule_sequence: item for item in existing}
    if original_at.date() > today:
        last_date = original_at.date()
    elif completion_at and completion_at.date() <= today:
        last_date = max(original_at.date(), completion_at.date())
    else:
        last_date = today
    sequence_count = max(0, (last_date - original_at.date()).days)
    root = by_sequence.get(0)
    previous = None
    for sequence in range(sequence_count + 1):
        occurrence_date = original_at.date() + timedelta(days=sequence)
        item = by_sequence.get(sequence)
        # Se a origem foi concluída antes do horário/data inicialmente agendado,
        # a ocorrência raiz é concluída antecipadamente. Ela nunca deve virar
        # "não cumprida" nem abrir um reagendamento automático no dia seguinte.
        completed_here = bool(
            completion_at
            and (
                completion_at.date() == occurrence_date
                or (sequence == 0 and completion_at.date() <= original_at.date())
            )
        )
        if item is None:
            starts_at = original_at if sequence == 0 else noon(occurrence_date)
            occurrence_all_day = all_day if sequence == 0 else True
            ends_at = None if occurrence_all_day else starts_at + timedelta(minutes=duration_minutes)
            next_description = description
            if sequence > 0:
                suffix = f"Reagendamento automático nº {sequence}. Agendamento original: {original_at.astimezone(timezone.utc).strftime('%d/%m/%Y')}."
                next_description = f"{description + ' ' if description else ''}{suffix}"
            item = AgendaTask(
                organization_id=organization_id,
                title=title,
                description=next_description,
                kind=kind,
                starts_at=starts_at,
                ends_at=ends_at,
                due_at=None,
                all_day=occurrence_all_day,
                priority=priority,
                status="completed" if completed_here else "pending",
                privacy="normal",
                assigned_user_id=assigned_user_id,
                department_id=department_id,
                source_module=source_module,
                source_type=source_type,
                source_id=source_id,
                automatic=True,
                mandatory_action=True,
                completion_source="source",
                original_scheduled_at=original_at,
                previous_task_id=previous.id if previous else None,
                reschedule_sequence=sequence,
                immutable_history=completed_here,
                completed_at=completion_at if completed_here else None,
            )
            db.add(item)
            db.flush()
            if root is None:
                root = item
                root.original_task_id = root.id
            else:
                item.original_task_id = root.id
            by_sequence[sequence] = item
        elif completed_here and item.status == "pending":
            item.status = "completed"
            item.completed_at = completion_at
            item.immutable_history = True
        previous = item


def sync_system_tasks(db: Session, organization_id: UUID, *, lookback_days: int = 120, horizon_days: int = 120) -> None:
    users, profiles, _ = ensure_agenda_structure(db, organization_id)
    user_by_name = {item.name.strip().casefold(): item for item in users}
    start_dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    end_dt = datetime.now(timezone.utc) + timedelta(days=horizon_days)
    operations = department_by_name(db, organization_id, "Operações")
    finance = department_by_name(db, organization_id, "Financeiro")

    inspections = db.scalars(
        select(Inspection).where(
            Inspection.organization_id == organization_id,
            Inspection.scheduled_at.is_not(None),
            Inspection.scheduled_at.between(start_dt, end_dt),
        )
    ).all()
    for item in inspections:
        user = user_by_name.get((item.inspector_name or "").strip().casefold())
        completion = item.finalized_at or item.performed_at if item.status in {"finalized", "completed"} else None
        if item.status == "cancelled":
            completion = item.updated_at
        _ensure_source_chain(
            db,
            organization_id=organization_id,
            source_module="inspections",
            source_type="inspection",
            source_id=str(item.id),
            title=f"Vistoria · VIS-{item.internal_number:06d}",
            description=f"{item.inspection_type.capitalize()} · vistoriador: {item.inspector_name or 'a definir'}",
            original_at=item.scheduled_at,
            completion_at=completion,
            assigned_user_id=user.id if user else None,
            department_id=profiles[user.id].department_id if user else operations.id,
            kind="appointment",
            all_day=False,
            duration_minutes=90,
            priority="high" if item.status not in {"finalized", "completed"} else "normal",
        )

    maintenances = db.scalars(
        select(MaintenanceRequest).where(
            MaintenanceRequest.organization_id == organization_id,
            MaintenanceRequest.scheduled_at.is_not(None),
            MaintenanceRequest.scheduled_at.between(start_dt, end_dt),
        )
    ).all()
    for item in maintenances:
        assigned = item.approved_by_user_id or item.created_by_user_id
        profile = profiles.get(assigned) if assigned else None
        completion = item.completed_at if item.status == "completed" else item.cancelled_at if item.status == "cancelled" else None
        _ensure_source_chain(
            db,
            organization_id=organization_id,
            source_module="maintenance",
            source_type="maintenance",
            source_id=str(item.id),
            title=f"Manutenção · {item.title}",
            description=f"{item.category} · responsabilidade: {item.responsibility}",
            original_at=item.scheduled_at,
            completion_at=completion,
            assigned_user_id=assigned,
            department_id=profile.department_id if profile else operations.id,
            kind="appointment",
            all_day=False,
            duration_minutes=60,
            priority="urgent" if item.priority == "urgent" else "high" if item.priority == "high" else "normal",
        )

    start_date, end_date = start_dt.date(), end_dt.date()
    charges = db.scalars(
        select(RentCharge).where(RentCharge.organization_id == organization_id, RentCharge.due_date.between(start_date, end_date))
    ).all()
    for item in charges:
        completion = item.paid_at or item.cancelled_at
        _ensure_source_chain(
            db,
            organization_id=organization_id,
            source_module="finance",
            source_type="billing",
            source_id=str(item.id),
            title=f"Cobrança · COB-{item.internal_number:06d}",
            description=f"Competência {item.competence.strftime('%m/%Y')} · valor R$ {item.gross_amount}",
            original_at=noon(item.due_date),
            completion_at=completion,
            assigned_user_id=None,
            department_id=finance.id,
            kind="task",
            all_day=True,
            duration_minutes=0,
            priority="high" if item.due_date < datetime.now(timezone.utc).date() and not completion else "normal",
        )

    repasses = db.scalars(
        select(OwnerRepasse).where(OwnerRepasse.organization_id == organization_id, OwnerRepasse.due_date.between(start_date, end_date))
    ).all()
    for item in repasses:
        completion = item.paid_at if item.status != "pending" else None
        _ensure_source_chain(
            db,
            organization_id=organization_id,
            source_module="finance",
            source_type="repasse",
            source_id=str(item.id),
            title=f"Repasse · {item.owner_name}",
            description=f"Repasse previsto ao proprietário · R$ {item.amount}",
            original_at=noon(item.due_date),
            completion_at=completion,
            assigned_user_id=None,
            department_id=finance.id,
            kind="task",
            all_day=True,
            duration_minutes=0,
            priority="normal",
        )
