from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.agenda.models import AgendaTask
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract


_SOURCE_TYPE = "initial_inspection_setup"


def _sync_initial_inspection_followups(
    db: Session,
    *,
    organization_id: UUID,
    lookback_days: int,
    horizon_days: int,
) -> None:
    from app.domains.agenda import logic

    now = datetime.now(timezone.utc)
    today = now.date()
    start_limit = today - timedelta(days=max(30, lookback_days))
    end_limit = today + timedelta(days=max(30, horizon_days))
    operations = logic.department_by_name(db, organization_id, "Operações")

    leases = db.scalars(
        select(LeaseContract).where(
            LeaseContract.organization_id == organization_id,
            LeaseContract.status == "signed",
            LeaseContract.signed_at.is_not(None),
            LeaseContract.start_date <= end_limit,
            LeaseContract.end_date >= start_limit,
        ).order_by(LeaseContract.start_date.asc(), LeaseContract.internal_number.asc())
    ).all()
    lease_ids = [lease.id for lease in leases]

    inspections_by_lease: dict[UUID, Inspection] = {}
    if lease_ids:
        inspections = db.scalars(
            select(Inspection).where(
                Inspection.organization_id == organization_id,
                Inspection.lease_contract_id.in_(lease_ids),
                Inspection.inspection_type == "initial",
                Inspection.status != "cancelled",
            ).order_by(Inspection.updated_at.desc())
        ).all()
        for inspection in inspections:
            inspections_by_lease.setdefault(inspection.lease_contract_id, inspection)

    for lease in leases:
        inspection = inspections_by_lease.get(lease.id)
        inspection_ready = bool(
            inspection
            and (
                inspection.scheduled_at is not None
                or inspection.performed_at is not None
                or inspection.finalized_at is not None
            )
        )
        completion_at = (inspection.updated_at or inspection.created_at) if inspection_ready and inspection else None
        due_at = logic.noon(lease.start_date)
        days_to_start = (lease.start_date - today).days
        priority = "urgent" if due_at < now else "high" if days_to_start <= 7 else "normal"

        logic._ensure_source_chain(
            db,
            organization_id=organization_id,
            source_module="inspections",
            source_type=_SOURCE_TYPE,
            source_id=str(lease.id),
            title=f"Agendar vistoria inicial · LOC-{lease.internal_number:06d}",
            description=(
                f"Contrato assinado com início em {lease.start_date.strftime('%d/%m/%Y')}. "
                "Agendar a vistoria inicial obrigatória antes da entrega de chaves e do início operacional da locação. "
                "A Agenda não cria nem conclui a vistoria automaticamente."
            ),
            original_at=lease.signed_at,
            completion_at=completion_at,
            assigned_user_id=None,
            department_id=operations.id,
            kind="task",
            all_day=True,
            duration_minutes=30,
            priority=priority,
            due_at=due_at,
            daily_reschedule=False,
            mandatory_action=True,
        )

    # Se uma locação que originou a pendência deixar de estar assinada/ativa,
    # a tarefa não pode continuar solta na operação. O próprio contrato encerra
    # a cadeia; não há estado paralelo nem conclusão manual fictícia.
    open_tasks = db.scalars(
        select(AgendaTask).where(
            AgendaTask.organization_id == organization_id,
            AgendaTask.source_type == _SOURCE_TYPE,
            AgendaTask.status.in_(("pending", "confirmed")),
        )
    ).all()
    active_ids = {str(lease.id) for lease in leases}
    for task in open_tasks:
        if task.source_id in active_ids:
            continue
        try:
            lease_id = UUID(str(task.source_id))
        except (TypeError, ValueError):
            continue
        lease = db.get(LeaseContract, lease_id)
        if lease is None or lease.organization_id != organization_id or lease.status == "signed":
            continue
        task.status = "completed"
        task.completed_at = lease.closed_at or lease.updated_at or now
        task.completion_source = "source"
        task.immutable_history = True


def install_lease_handover_agenda_rule() -> None:
    """Garante a passagem Contrato assinado -> Vistoria inicial na Agenda.

    O contrato e a vistoria permanecem as fontes de verdade. Esta regra só
    produz a obrigação operacional de agendamento e nunca cria vistoria,
    entrega chaves ou envia comunicação por conta própria.
    """
    from app.domains.agenda import logic
    from app.domains.agenda.source_chain_rules import install_source_chain_rule

    install_source_chain_rule()
    current = logic.sync_system_tasks
    if getattr(current, "_lease_handover_agenda_installed", False):
        return

    def sync_system_tasks(
        db: Session,
        organization_id: UUID,
        *,
        lookback_days: int = 120,
        horizon_days: int = 120,
    ) -> None:
        current(db, organization_id, lookback_days=lookback_days, horizon_days=horizon_days)
        _sync_initial_inspection_followups(
            db,
            organization_id=organization_id,
            lookback_days=lookback_days,
            horizon_days=horizon_days,
        )

    setattr(sync_system_tasks, "_lease_handover_agenda_installed", True)
    logic.sync_system_tasks = sync_system_tasks

    from app.api.routes import agenda as agenda_routes
    agenda_routes.sync_system_tasks = sync_system_tasks
