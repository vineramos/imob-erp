from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.agenda import logic
from app.domains.agenda.communication_rules import install_communication_agenda_rule
from app.domains.agenda.models import AgendaDepartment, AgendaTask
from app.domains.communications.models import CommunicationMessage


def _create_message(identity, *, origin: str, category: str, status: str = "pending"):
    assert SessionLocal is not None
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        item = CommunicationMessage(
            organization_id=identity["organization_id"],
            recipient_name="Cliente Agenda Comunicação",
            recipient_email="cliente-agenda@example.invalid",
            recipient_phone="41999990000",
            recipient_role="tenant",
            channel="email",
            category=category,
            origin=origin,
            subject="Comunicação operacional",
            body="Conteúdo de teste para revisão humana.",
            status=status,
            source_module="finance" if category == "rent_overdue" else "contracts",
            source_type="rent_charge" if category == "rent_overdue" else "lease_contract",
            source_id=f"source-{category}-{now.timestamp()}",
            dedupe_key=f"agenda-test:{origin}:{category}:{now.timestamp()}",
            attachment_manifest=[],
            suggested_at=now if origin == "suggestion" else None,
            queued_at=now if origin == "suggestion" else None,
            created_by_user_id=identity["user_id"],
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id


def test_suggested_communication_creates_mandatory_department_task_but_manual_does_not(identity):
    install_communication_agenda_rule()
    suggestion_id = _create_message(identity, origin="suggestion", category="rent_overdue")
    manual_id = _create_message(identity, origin="manual", category="manual", status="draft")

    assert SessionLocal is not None
    with SessionLocal() as db:
        logic.sync_system_tasks(db, identity["organization_id"])
        db.flush()

        tasks = db.scalars(
            select(AgendaTask).where(
                AgendaTask.organization_id == identity["organization_id"],
                AgendaTask.source_module == "communications",
                AgendaTask.source_type == "communication_review",
                AgendaTask.source_id == str(suggestion_id),
            )
        ).all()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.status == "pending"
        assert task.automatic is True
        assert task.mandatory_action is True
        assert task.priority == "high"
        assert task.assigned_user_id is None
        assert "Revisão humana obrigatória" in (task.description or "")

        department = db.get(AgendaDepartment, task.department_id)
        assert department is not None
        assert department.name == "Financeiro"

        manual_task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.organization_id == identity["organization_id"],
                AgendaTask.source_module == "communications",
                AgendaTask.source_id == str(manual_id),
            )
        )
        assert manual_task is None


def test_failed_suggestion_remains_actionable_until_sent(identity):
    install_communication_agenda_rule()
    suggestion_id = _create_message(identity, origin="suggestion", category="lease_signed")

    assert SessionLocal is not None
    with SessionLocal() as db:
        logic.sync_system_tasks(db, identity["organization_id"])
        db.flush()
        task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.organization_id == identity["organization_id"],
                AgendaTask.source_type == "communication_review",
                AgendaTask.source_id == str(suggestion_id),
                AgendaTask.reschedule_sequence == 0,
            )
        )
        assert task is not None
        assert task.status == "pending"
        department = db.get(AgendaDepartment, task.department_id)
        assert department is not None
        assert department.name == "Administrativo"

        message = db.get(CommunicationMessage, suggestion_id)
        assert message is not None
        message.status = "failed"
        message.failed_at = datetime.now(timezone.utc)
        db.commit()

        logic.sync_system_tasks(db, identity["organization_id"])
        db.flush()
        db.refresh(task)
        assert task.status == "pending"

        message.status = "sent"
        message.sent_at = datetime.now(timezone.utc)
        message.failed_at = None
        db.commit()

        logic.sync_system_tasks(db, identity["organization_id"])
        db.flush()
        db.refresh(task)
        assert task.status == "completed"
        assert task.completed_at is not None
        assert task.immutable_history is True
