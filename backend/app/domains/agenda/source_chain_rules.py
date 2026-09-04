from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.agenda.models import AgendaTask
from app.domains.agenda.timezone_rules import local_date, local_today, profile_timezone


def install_source_chain_rule() -> None:
    """Reconcilia a cadeia automática com o estado real e o dia civil da origem.

    A origem é a verdade: uma conclusão anterior ao agendamento encerra a
    ocorrência original; uma origem ainda pendente continua sendo reagendada
    diariamente até ser concluída/cancelada. O cálculo de ontem/hoje é feito no
    timezone do perfil responsável (America/Sao_Paulo por padrão), embora os
    timestamps permaneçam persistidos em UTC.
    """
    from app.domains.agenda import logic

    current = logic._ensure_source_chain
    if getattr(current, "_source_reconciliation_installed", False):
        return

    def ensure_source_chain(
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
        zone = profile_timezone(db, organization_id, assigned_user_id)
        today = local_today(zone)
        original_date = local_date(original_at, zone)
        completion_date = local_date(completion_at, zone) if completion_at else None

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

        # Se a origem já estava encerrada antes da data agendada, a ocorrência
        # original é o ponto terminal da cadeia e nunca gera R1.
        effective_completion_date = max(original_date, completion_date) if completion_date else None

        if original_date > today:
            last_date = original_date
        elif effective_completion_date and effective_completion_date <= today:
            last_date = effective_completion_date
        else:
            last_date = today

        sequence_count = max(0, (last_date - original_date).days)
        root = by_sequence.get(0)
        previous = None

        for sequence in range(sequence_count + 1):
            occurrence_date = original_date + timedelta(days=sequence)
            item = by_sequence.get(sequence)
            completed_here = bool(effective_completion_date and effective_completion_date == occurrence_date)

            if item is None:
                starts_at = original_at if sequence == 0 else logic.noon(occurrence_date)
                occurrence_all_day = all_day if sequence == 0 else True
                ends_at = None if occurrence_all_day else starts_at + timedelta(minutes=duration_minutes)
                next_description = description
                if sequence > 0:
                    suffix = (
                        f"Reagendamento automático nº {sequence}. "
                        f"Agendamento original: {original_at.astimezone(zone).strftime('%d/%m/%Y')}."
                    )
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
            elif completed_here:
                # Também corrige dados legados que foram marcados como missed
                # apesar de a origem já estar concluída antes do agendamento.
                item.status = "completed"
                item.completed_at = completion_at
                item.missed_justification = None
                item.missed_at = None
                item.immutable_history = True

            previous = item

        # Se a origem foi encerrada retroativamente, ocorrências abertas depois
        # da data terminal deixam de ser exigíveis, mas o histórico é preservado.
        if completion_at:
            for sequence, item in by_sequence.items():
                if sequence <= sequence_count:
                    continue
                if item.status != "cancelled":
                    item.status = "cancelled"
                    item.completed_at = completion_at
                    item.immutable_history = True

    setattr(ensure_source_chain, "_source_reconciliation_installed", True)
    logic._ensure_source_chain = ensure_source_chain
