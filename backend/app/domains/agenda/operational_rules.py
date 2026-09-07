from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domains.agenda.models import AgendaTask
from app.domains.contracts.models import AdministrationContract
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest


MAINTENANCE_SLA_HOURS = {
    "urgent": 2,
    "high": 4,
    "normal": 24,
    "low": 48,
}

MAINTENANCE_ACTION = {
    "requested": "Realizar a triagem e definir a responsabilidade inicial.",
    "triage": "Definir os serviços necessários e liberar a coleta de orçamentos.",
    "awaiting_quote": "Coletar e comparar os orçamentos dos parceiros.",
    "awaiting_approval": "Revisar o orçamento selecionado e registrar a decisão de aprovação.",
    "approved": "Agendar a execução ou iniciar o serviço aprovado.",
    "scheduled": "Acompanhar a execução na data agendada.",
    "in_progress": "Acompanhar a execução e registrar a conclusão.",
    "completed": "Fluxo operacional concluído.",
    "cancelled": "Chamado cancelado.",
}

LOCAL_ZONE = ZoneInfo("America/Sao_Paulo")


def _priority(value: str | None) -> str:
    normalized = (value or "normal").strip().lower()
    return normalized if normalized in {"low", "normal", "high", "urgent"} else "normal"


def _deadline_label(value: datetime) -> str:
    return value.astimezone(LOCAL_ZONE).strftime("%d/%m/%Y às %H:%M")


def _same_department_assignee(
    user_id: UUID | None,
    profiles,
    department_id: UUID,
) -> UUID | None:
    if user_id is None:
        return None
    profile = profiles.get(user_id)
    if profile is None or profile.department_id != department_id:
        return None
    return user_id


def _complete_stale_contract_tasks(
    db: Session,
    *,
    organization_id: UUID,
    source_type: str,
    source_prefix: str,
    keep_source_id: str | None,
    completion_at: datetime,
) -> None:
    rows = db.scalars(
        select(AgendaTask).where(
            AgendaTask.organization_id == organization_id,
            AgendaTask.automatic.is_(True),
            AgendaTask.source_module == "contracts",
            AgendaTask.source_type == source_type,
            AgendaTask.source_id.like(f"{source_prefix}%"),
            AgendaTask.status.in_(("pending", "confirmed")),
        )
    ).all()
    for task in rows:
        if keep_source_id is not None and task.source_id == keep_source_id:
            continue
        task.status = "completed"
        task.completed_at = completion_at
        task.immutable_history = True


def _sync_maintenance_followups(
    db: Session,
    *,
    organization_id: UUID,
    lookback_days: int,
) -> None:
    from app.domains.agenda import logic

    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=lookback_days)
    _, profiles, _ = logic.ensure_agenda_structure(db, organization_id)
    operations = logic.department_by_name(db, organization_id, "Operações")

    rows = db.scalars(
        select(MaintenanceRequest).where(
            MaintenanceRequest.organization_id == organization_id,
            or_(
                MaintenanceRequest.status.not_in(("completed", "cancelled")),
                MaintenanceRequest.updated_at >= start_dt,
            ),
        )
    ).all()

    for item in rows:
        priority = _priority(item.priority)
        due_at = item.reported_at + timedelta(hours=MAINTENANCE_SLA_HOURS[priority])
        completion_at = None
        if item.status == "scheduled":
            completion_at = item.scheduled_at or item.updated_at
        elif item.status == "in_progress":
            completion_at = item.started_at or item.updated_at
        elif item.status == "completed":
            completion_at = item.completed_at or item.updated_at
        elif item.status == "cancelled":
            completion_at = item.cancelled_at or item.updated_at

        source_owner = item.approved_by_user_id or item.created_by_user_id
        assigned = _same_department_assignee(source_owner, profiles, operations.id)
        action = MAINTENANCE_ACTION.get(item.status, "Revisar a próxima ação operacional do chamado.")
        description = (
            f"{item.category} · responsabilidade: {item.responsibility}. "
            f"Próxima ação: {action} SLA desta etapa: {_deadline_label(due_at)}."
        )

        logic._ensure_source_chain(
            db,
            organization_id=organization_id,
            source_module="maintenance",
            source_type="maintenance",
            source_id=f"{item.id}:followup",
            title=f"Tratar manutenção · MAN-{item.internal_number:06d}",
            description=description,
            original_at=item.reported_at,
            completion_at=completion_at,
            assigned_user_id=assigned,
            department_id=operations.id,
            kind="task",
            all_day=True,
            duration_minutes=30,
            priority=priority,
            due_at=due_at,
            daily_reschedule=False,
            mandatory_action=False,
        )


def _sync_inspection_contestations(
    db: Session,
    *,
    organization_id: UUID,
    lookback_days: int,
    horizon_days: int,
) -> None:
    from app.domains.agenda import logic

    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=lookback_days)
    end_dt = now + timedelta(days=horizon_days)
    users, profiles, _ = logic.ensure_agenda_structure(db, organization_id)
    user_by_name = {item.name.strip().casefold(): item for item in users}
    operations = logic.department_by_name(db, organization_id, "Operações")

    rows = db.scalars(
        select(Inspection).where(
            Inspection.organization_id == organization_id,
            Inspection.performed_at.is_not(None),
            Inspection.contest_deadline.is_not(None),
            Inspection.contest_deadline >= start_dt,
            Inspection.contest_deadline <= end_dt,
        )
    ).all()

    for item in rows:
        if item.performed_at is None or item.contest_deadline is None:
            continue
        user = user_by_name.get((item.inspector_name or "").strip().casefold())
        assigned = _same_department_assignee(user.id if user else item.created_by_user_id, profiles, operations.id)
        completion_at = item.finalized_at
        if item.status == "cancelled":
            completion_at = item.updated_at

        overdue = item.contest_deadline < now and completion_at is None
        description = (
            f"{item.inspection_type.capitalize()} · prazo de contestação até "
            f"{_deadline_label(item.contest_deadline)}. Revisar manifestações e finalizar o laudo após o prazo."
        )
        logic._ensure_source_chain(
            db,
            organization_id=organization_id,
            source_module="inspections",
            source_type="inspection",
            source_id=f"{item.id}:contest",
            title=f"Acompanhar contestação · VIS-{item.internal_number:06d}",
            description=description,
            original_at=item.performed_at,
            completion_at=completion_at,
            assigned_user_id=assigned,
            department_id=operations.id,
            kind="task",
            all_day=True,
            duration_minutes=30,
            priority="urgent" if overdue else "high",
            due_at=item.contest_deadline,
            daily_reschedule=False,
            mandatory_action=False,
        )


def _sync_lease_reviews(
    db: Session,
    *,
    organization_id: UUID,
    horizon_days: int,
) -> None:
    from app.domains.agenda import logic

    now = datetime.now(timezone.utc)
    today = now.date()
    horizon = today + timedelta(days=horizon_days)
    earliest = today - timedelta(days=365)
    _, profiles, _ = logic.ensure_agenda_structure(db, organization_id)
    administrative = logic.department_by_name(db, organization_id, "Administrativo")

    leases = db.scalars(
        select(LeaseContract).where(
            LeaseContract.organization_id == organization_id,
            LeaseContract.status.not_in(("draft", "review", "cancelled")),
        )
    ).all()

    for item in leases:
        source_owner = item.approved_by_user_id or item.created_by_user_id
        assigned = _same_department_assignee(source_owner, profiles, administrative.id)
        closed_at = item.closed_at

        if closed_at is not None:
            _complete_stale_contract_tasks(
                db,
                organization_id=organization_id,
                source_type="adjustment",
                source_prefix=f"{item.id}:adjustment:",
                keep_source_id=None,
                completion_at=closed_at,
            )
            _complete_stale_contract_tasks(
                db,
                organization_id=organization_id,
                source_type="contract_expiry",
                source_prefix=f"{item.id}:expiry:",
                keep_source_id=None,
                completion_at=closed_at,
            )
            continue

        if earliest <= item.next_adjustment_date <= horizon:
            adjustment_source_id = f"{item.id}:adjustment:{item.next_adjustment_date.isoformat()}"
            _complete_stale_contract_tasks(
                db,
                organization_id=organization_id,
                source_type="adjustment",
                source_prefix=f"{item.id}:adjustment:",
                keep_source_id=adjustment_source_id,
                completion_at=item.updated_at or now,
            )
            trigger_day = item.next_adjustment_date - timedelta(days=30)
            due_day = item.next_adjustment_date - timedelta(days=5)
            due_at = logic.noon(due_day)
            days = (item.next_adjustment_date - today).days
            priority = "urgent" if due_at < now else "high" if days <= 15 else "normal"
            logic._ensure_source_chain(
                db,
                organization_id=organization_id,
                source_module="contracts",
                source_type="adjustment",
                source_id=adjustment_source_id,
                title=f"Preparar reajuste · LOC-{item.internal_number:06d}",
                description=(
                    f"Reajuste por {item.adjustment_index} previsto para "
                    f"{item.next_adjustment_date.strftime('%d/%m/%Y')}. "
                    "Revisar índice, memória de cálculo e comunicação ao locatário. "
                    "O envio externo continua sujeito à revisão humana na Central de Comunicações."
                ),
                original_at=logic.noon(trigger_day),
                completion_at=None,
                assigned_user_id=assigned,
                department_id=administrative.id,
                kind="task",
                all_day=True,
                duration_minutes=30,
                priority=priority,
                due_at=due_at,
                daily_reschedule=False,
                mandatory_action=False,
            )

        if earliest <= item.end_date <= horizon:
            expiry_source_id = f"{item.id}:expiry:{item.end_date.isoformat()}"
            _complete_stale_contract_tasks(
                db,
                organization_id=organization_id,
                source_type="contract_expiry",
                source_prefix=f"{item.id}:expiry:",
                keep_source_id=expiry_source_id,
                completion_at=item.updated_at or now,
            )
            trigger_day = item.end_date - timedelta(days=120)
            due_day = item.end_date - timedelta(days=30)
            due_at = logic.noon(due_day)
            days = (item.end_date - today).days
            priority = "urgent" if days <= 0 else "high" if days <= 30 else "normal"
            logic._ensure_source_chain(
                db,
                organization_id=organization_id,
                source_module="contracts",
                source_type="contract_expiry",
                source_id=expiry_source_id,
                title=f"Definir renovação ou encerramento · LOC-{item.internal_number:06d}",
                description=(
                    f"Término contratual em {item.end_date.strftime('%d/%m/%Y')}. "
                    "Conferir intenção das partes, renovação, desocupação e próximos marcos. "
                    "Alertas 120/90/60/30 dias permanecem disponíveis na Agenda."
                ),
                original_at=logic.noon(trigger_day),
                completion_at=None,
                assigned_user_id=assigned,
                department_id=administrative.id,
                kind="task",
                all_day=True,
                duration_minutes=30,
                priority=priority,
                due_at=due_at,
                daily_reschedule=False,
                mandatory_action=False,
            )


def _sync_administration_contract_reviews(
    db: Session,
    *,
    organization_id: UUID,
    horizon_days: int,
) -> None:
    from app.domains.agenda import logic

    now = datetime.now(timezone.utc)
    today = now.date()
    horizon = today + timedelta(days=horizon_days)
    earliest = today - timedelta(days=365)
    _, profiles, _ = logic.ensure_agenda_structure(db, organization_id)
    administrative = logic.department_by_name(db, organization_id, "Administrativo")

    rows = db.scalars(
        select(AdministrationContract).where(
            AdministrationContract.organization_id == organization_id,
            AdministrationContract.end_date.is_not(None),
        )
    ).all()

    for item in rows:
        if item.end_date is None:
            continue
        source_prefix = f"admin:{item.id}:expiry:"
        terminal = item.status in {"cancelled", "terminated", "closed"}
        if terminal:
            _complete_stale_contract_tasks(
                db,
                organization_id=organization_id,
                source_type="contract_expiry",
                source_prefix=source_prefix,
                keep_source_id=None,
                completion_at=item.updated_at or now,
            )
            continue
        if item.status in {"draft", "review"} or not (earliest <= item.end_date <= horizon):
            continue

        source_id = f"{source_prefix}{item.end_date.isoformat()}"
        _complete_stale_contract_tasks(
            db,
            organization_id=organization_id,
            source_type="contract_expiry",
            source_prefix=source_prefix,
            keep_source_id=source_id,
            completion_at=item.updated_at or now,
        )
        trigger_day = item.end_date - timedelta(days=120)
        due_at = logic.noon(item.end_date - timedelta(days=30))
        days = (item.end_date - today).days
        priority = "urgent" if days <= 0 else "high" if days <= 30 else "normal"
        source_owner = item.approved_by_user_id or item.created_by_user_id
        assigned = _same_department_assignee(source_owner, profiles, administrative.id)

        logic._ensure_source_chain(
            db,
            organization_id=organization_id,
            source_module="contracts",
            source_type="contract_expiry",
            source_id=source_id,
            title=f"Revisar contrato de administração · ADM-{item.internal_number:06d}",
            description=(
                f"Contrato de administração com término em {item.end_date.strftime('%d/%m/%Y')}. "
                "Validar continuidade da administração, comunicação ao proprietário e situação do imóvel."
            ),
            original_at=logic.noon(trigger_day),
            completion_at=None,
            assigned_user_id=assigned,
            department_id=administrative.id,
            kind="task",
            all_day=True,
            duration_minutes=30,
            priority=priority,
            due_at=due_at,
            daily_reschedule=False,
            mandatory_action=False,
        )


def install_operational_agenda_rules() -> None:
    """Amplia a Agenda com pendências reais de operação e SLA.

    Não cria estado paralelo: cada tarefa é reconciliada diretamente com
    Manutenção, Vistoria ou Contratos. Nenhuma ação externa é executada daqui.
    """
    from app.domains.agenda import logic
    from app.domains.agenda.source_chain_rules import install_source_chain_rule

    install_source_chain_rule()
    current = logic.sync_system_tasks
    if getattr(current, "_operational_agenda_installed", False):
        return

    def sync_system_tasks(
        db: Session,
        organization_id: UUID,
        *,
        lookback_days: int = 120,
        horizon_days: int = 120,
    ) -> None:
        current(db, organization_id, lookback_days=lookback_days, horizon_days=horizon_days)
        _sync_maintenance_followups(
            db,
            organization_id=organization_id,
            lookback_days=lookback_days,
        )
        _sync_inspection_contestations(
            db,
            organization_id=organization_id,
            lookback_days=lookback_days,
            horizon_days=horizon_days,
        )
        _sync_lease_reviews(
            db,
            organization_id=organization_id,
            horizon_days=horizon_days,
        )
        _sync_administration_contract_reviews(
            db,
            organization_id=organization_id,
            horizon_days=horizon_days,
        )

    setattr(sync_system_tasks, "_operational_agenda_installed", True)
    logic.sync_system_tasks = sync_system_tasks

    # agenda.py importa a função durante o bootstrap. Reapontamos a referência
    # global do módulo para que events/today-summary/reminders usem a cadeia
    # completa de reconciliação instalada acima, e não uma cópia anterior.
    from app.api.routes import agenda as agenda_routes
    agenda_routes.sync_system_tasks = sync_system_tasks
