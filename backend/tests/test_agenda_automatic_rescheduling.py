from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.agenda.models import AgendaTask
from app.domains.maintenance.models import MaintenanceRequest
from tests.helpers import assert_response, create_person, create_property


def _maintenance_source(client, identity, *, status: str, scheduled_at: datetime, completed_at: datetime | None = None) -> str:
    owner = create_person(
        client,
        name=f"Proprietário Agenda {status}",
        document="66666666666" if status != "completed" else "77777777777",
        email=f"agenda.{status}@example.com",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])

    assert SessionLocal is not None
    with SessionLocal() as db:
        item = MaintenanceRequest(
            organization_id=identity["organization_id"],
            property_id=UUID(property_item["id"]),
            title=f"Manutenção agenda {status}",
            category="general",
            priority="normal",
            status=status,
            description="Fonte criada para validar a cadeia automática da Agenda.",
            responsibility="owner",
            approval_required=True,
            services=[],
            quotes=[],
            history=[],
            scheduled_at=scheduled_at,
            completed_at=completed_at,
            created_by_user_id=identity["user_id"],
            approved_by_user_id=identity["user_id"],
            completed_by_user_id=identity["user_id"] if completed_at else None,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return str(item.id)


def _source_events(client, source_id: str, start, end) -> list[dict]:
    payload = assert_response(
        client.get(
            "/api/agenda/events",
            params={"start": start.isoformat(), "end": end.isoformat(), "mine": "true"},
        )
    ).json()
    return [row for row in payload["events"] if row.get("source_id") == source_id and row["event_type"] == "maintenance"]


def test_pending_maintenance_is_automatically_rescheduled_next_day(client, identity):
    """Manutenção vencida e ainda aberta precisa ganhar R1 no dia seguinte."""
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    scheduled_at = datetime.combine(yesterday, time(hour=11, minute=30), tzinfo=timezone.utc)
    source_id = _maintenance_source(
        client,
        identity,
        status="scheduled",
        scheduled_at=scheduled_at,
    )

    rows = _source_events(client, source_id, yesterday, today)
    assert len(rows) == 2
    by_sequence = {row["reschedule_sequence"]: row for row in rows}

    original = by_sequence[0]
    rescheduled = by_sequence[1]
    assert original["status"] == "pending"
    assert original["needs_justification"] is True
    assert rescheduled["status"] == "pending"
    assert rescheduled["all_day"] is True
    assert rescheduled["start_at"][:10] == today.isoformat()
    assert "Reagendamento automático nº 1" in (rescheduled["description"] or "")

    # A justificativa preserva a ocorrência original, mas não remove o R1 atual.
    justified = assert_response(
        client.post(
            f"/api/agenda/tasks/{original['task_id']}/justify-missed",
            json={"justification": "Ocorrência não executada no dia previsto."},
        )
    ).json()
    assert justified["status"] == "missed"

    rows_after = _source_events(client, source_id, yesterday, today)
    after_by_sequence = {row["reschedule_sequence"]: row for row in rows_after}
    assert after_by_sequence[0]["status"] == "missed"
    assert after_by_sequence[1]["status"] == "pending"

    history = assert_response(
        client.get(f"/api/agenda/tasks/{after_by_sequence[1]['task_id']}/history")
    ).json()
    assert [entry["sequence"] for entry in history["entries"]] == [0, 1]
    assert [entry["status"] for entry in history["entries"]] == ["missed", "pending"]


def test_source_completed_before_schedule_closes_original_and_never_reschedules(client, identity):
    """Conclusão antecipada da origem não pode virar falsa pendência na Agenda."""
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    scheduled_at = datetime.combine(yesterday, time(hour=11, minute=30), tzinfo=timezone.utc)
    completed_at = scheduled_at - timedelta(days=1)
    source_id = _maintenance_source(
        client,
        identity,
        status="completed",
        scheduled_at=scheduled_at,
        completed_at=completed_at,
    )

    rows = _source_events(client, source_id, yesterday, today)
    assert len(rows) == 1
    original = rows[0]
    assert original["reschedule_sequence"] == 0
    assert original["status"] == "completed"
    assert original["needs_justification"] is False

    # Também corrige um estado legado incoerente já salvo como "missed".
    assert SessionLocal is not None
    with SessionLocal() as db:
        task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.id == UUID(original["task_id"]),
                AgendaTask.organization_id == identity["organization_id"],
            )
        )
        assert task is not None
        task.status = "missed"
        task.missed_justification = "Estado legado incoerente de teste."
        task.missed_at = datetime.now(timezone.utc)
        task.immutable_history = True
        db.commit()

    repaired = _source_events(client, source_id, yesterday, today)
    assert len(repaired) == 1
    assert repaired[0]["status"] == "completed"
    assert repaired[0]["needs_justification"] is False
