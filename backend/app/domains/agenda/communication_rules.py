from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.communications.models import CommunicationMessage


CATEGORY_LABELS = {
    "rent_overdue": "Cobrança em atraso",
    "lease_adjustment": "Reajuste de locação",
    "lease_expiry": "Contrato próximo do término",
    "lease_signed": "Contrato assinado",
    "owner_repasse_paid": "Repasse realizado ao proprietário",
    "owner_repasse_overdue": "Repasse pendente",
    "inspection_schedule": "Agendamento de vistoria",
    "maintenance_update": "Atualização de manutenção",
}

FINANCE_CATEGORIES = frozenset({"rent_overdue", "owner_repasse_paid", "owner_repasse_overdue"})
OPERATIONS_CATEGORIES = frozenset({"inspection_schedule", "maintenance_update"})
HIGH_PRIORITY_CATEGORIES = frozenset({"rent_overdue", "owner_repasse_overdue"})


def _completion_at(item: CommunicationMessage) -> datetime | None:
    if item.status == "sent":
        return item.sent_at or item.updated_at
    if item.status == "cancelled":
        return item.cancelled_at or item.updated_at
    return None


def install_communication_agenda_rule() -> None:
    """Faz sugestões de comunicação participarem da cadeia operacional da Agenda.

    A comunicação continua sendo a origem da verdade. Sugestões aguardando
    revisão ou com falha permanecem como ação obrigatória; envio ou cancelamento
    encerram a cadeia. Rascunhos manuais não geram tarefas automáticas.
    """
    from app.domains.agenda import logic

    current = logic.sync_system_tasks
    if getattr(current, "_communication_agenda_installed", False):
        return

    def sync_system_tasks(
        db: Session,
        organization_id,
        *,
        lookback_days: int = 120,
        horizon_days: int = 120,
    ) -> None:
        current(db, organization_id, lookback_days=lookback_days, horizon_days=horizon_days)

        now = datetime.now(timezone.utc)
        start_dt = now - timedelta(days=lookback_days)
        end_dt = now + timedelta(days=horizon_days)
        rows = db.scalars(
            select(CommunicationMessage).where(
                CommunicationMessage.organization_id == organization_id,
                CommunicationMessage.origin == "suggestion",
                CommunicationMessage.suggested_at.is_not(None),
                CommunicationMessage.suggested_at >= start_dt,
                CommunicationMessage.suggested_at <= end_dt,
            )
        ).all()
        if not rows:
            return

        finance = logic.department_by_name(db, organization_id, "Financeiro")
        administrative = logic.department_by_name(db, organization_id, "Administrativo")
        operations = logic.department_by_name(db, organization_id, "Operações")

        for item in rows:
            original_at = item.suggested_at
            if original_at is None:
                continue

            if item.category in FINANCE_CATEGORIES:
                department = finance
            elif item.category in OPERATIONS_CATEGORIES:
                department = operations
            else:
                department = administrative

            category_label = CATEGORY_LABELS.get(item.category, item.category.replace("_", " ").strip().title())
            priority = "high" if item.status == "failed" or item.category in HIGH_PRIORITY_CATEGORIES else "normal"
            code = f"COM-{item.internal_number:06d}"
            source = " / ".join(part for part in (item.source_module, item.source_type) if part) or "Central de Comunicações"
            description = (
                f"{category_label} · destinatário: {item.recipient_name} · canal: {item.channel}. "
                f"Origem: {source}. Revisão humana obrigatória antes do envio."
            )
            if item.status == "failed":
                description += " Há uma falha de envio pendente de tratamento."

            logic._ensure_source_chain(
                db,
                organization_id=organization_id,
                source_module="communications",
                source_type="communication_review",
                source_id=str(item.id),
                title=f"Tratar comunicação · {code}",
                description=description,
                original_at=original_at,
                completion_at=_completion_at(item),
                assigned_user_id=None,
                department_id=department.id,
                kind="task",
                all_day=True,
                duration_minutes=30,
                priority=priority,
            )

    setattr(sync_system_tasks, "_communication_agenda_installed", True)
    logic.sync_system_tasks = sync_system_tasks
