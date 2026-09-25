from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.agenda.logic import access_map, ensure_agenda_structure, require_calendar_access
from app.domains.agenda.models import AgendaTask
from app.domains.agenda.timezone_rules import local_date, local_today, resolve_timezone
from app.domains.foundation.access import UserContext, require_permission

router = APIRouter(tags=["agenda"])


def _can_view_unassigned(db: Session, context: UserContext, item: AgendaTask) -> bool:
    _, profiles, _ = ensure_agenda_structure(db, context.user.organization_id)
    profile = profiles[context.user.id]
    if item.department_id is None:
        return True
    if profile.access_level in {"director", "admin"}:
        return True
    return profile.department_id == item.department_id


def _needs_justification(row: AgendaTask, profiles, viewer_id: UUID) -> bool:
    if not (row.automatic and row.mandatory_action and row.status == "pending"):
        return False
    profile = profiles.get(row.assigned_user_id) if row.assigned_user_id else profiles.get(viewer_id)
    zone = resolve_timezone(profile.timezone if profile else None)
    occurrence_day = row.starts_at.date() if row.all_day else local_date(row.starts_at, zone)
    return occurrence_day < local_today(zone)


@router.get("/agenda/tasks/{task_id}/history")
def agenda_task_history(
    task_id: UUID,
    context: UserContext = Depends(require_permission("agenda.view")),
    db: Session = Depends(get_db),
) -> dict:
    item = db.scalar(
        select(AgendaTask).where(
            AgendaTask.id == task_id,
            AgendaTask.organization_id == context.user.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada.")

    if item.assigned_user_id:
        require_calendar_access(access_map(db, context.user.organization_id, context.user.id), item.assigned_user_id)
    elif not _can_view_unassigned(db, context, item):
        raise HTTPException(status_code=403, detail="Você não possui autorização para consultar este histórico.")

    root_id = item.original_task_id or (item.id if item.reschedule_sequence == 0 else None)
    if root_id:
        chain = db.scalars(
            select(AgendaTask).where(
                AgendaTask.organization_id == context.user.organization_id,
                or_(AgendaTask.id == root_id, AgendaTask.original_task_id == root_id),
            ).order_by(AgendaTask.reschedule_sequence, AgendaTask.starts_at)
        ).all()
    elif item.automatic and item.source_type and item.source_id and item.original_scheduled_at:
        chain = db.scalars(
            select(AgendaTask).where(
                AgendaTask.organization_id == context.user.organization_id,
                AgendaTask.automatic.is_(True),
                AgendaTask.source_type == item.source_type,
                AgendaTask.source_id == item.source_id,
                AgendaTask.original_scheduled_at == item.original_scheduled_at,
            ).order_by(AgendaTask.reschedule_sequence, AgendaTask.starts_at)
        ).all()
    else:
        chain = [item]

    _, profiles, _ = ensure_agenda_structure(db, context.user.organization_id)
    return {
        "task_id": str(item.id),
        "root_task_id": str(root_id or item.id),
        "entries": [
            {
                "task_id": str(row.id),
                "sequence": row.reschedule_sequence,
                "starts_at": row.starts_at,
                "all_day": row.all_day,
                "status": row.status,
                "justification": row.missed_justification,
                "missed_at": row.missed_at,
                "completed_at": row.completed_at,
                "created_at": row.created_at,
                "previous_task_id": str(row.previous_task_id) if row.previous_task_id else None,
                "needs_justification": _needs_justification(row, profiles, context.user.id),
                "selected": row.id == item.id,
            }
            for row in chain
        ],
    }
