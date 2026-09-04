from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from app.core.database import SessionLocal
from app.domains.maintenance.models import MaintenanceRequest
from tests.helpers import assert_response, create_person, create_property


def _maintenance(
    identity,
    *,
    property_id: str,
    scheduled_at: datetime,
    status: str = "scheduled",
    completed_at: datetime | None = None,
) -> str:
    assert SessionLocal is not None
    with SessionLocal() as db:
        item = MaintenanceRequest(
            organization_id=identity["organization_id"],
            property_id=UUID(property_id),
            title="Manutenção automática de teste",
            category="general",
            priority="normal",
            status=status,
            description="Validação do reagendamento automático da Agenda.",
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


def _property(client):
    owner = create_person(
        client,
        name="Proprietário Agenda Automática",
        document="33333333333",
        email="agenda.owner@example.com",
        role_keys=["owner"],
    )
    return create_property(client, owner["id"])


def _maintenance_events(client, *, start, end, maintenance_id: str):
    payload = assert_response(
        client.get(f"/api/agenda/events?start={start.isoformat()}&end={end.isoformat()}&mine=true")
    ).json()
    return sorted(
        [row for row in payload["events"] if row.get("source_id") == maintenance_id and row.get("event_type") == "maintenance"],
        key=lambda row: row["reschedule_sequence"],
    )


def test_pending_maintenance_is_rescheduled_daily_and_keeps_missed_history(client, identity):
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    scheduled_at = datetime.combine(yesterday, time(hour=11, minute=30), tzinfo=timezone.utc)
    property_item = _property(client)
    maintenance_id = _maintenance(identity, property_id=property_item["id"], scheduled_at=scheduled_at)

    rows = _maintenance_events(client, start=yesterday, end=today, maintenance_id=maintenance_id)
    assert [row["reschedule_sequence"] for row in rows] == [0, 1]
    assert rows[0]["status"] == "pending"
    assert rows[0]["needs_justification"] is True
    assert rows[1]["status"] == "pending"
    assert rows[1]["needs_justification"] is False
    assert rows[1]["all_day"] is True

    original_task_id = rows[0]["task_id"]
    assert original_task_id
    justified = assert_response(
        client.post(
            f"/api/agenda/tasks/{original_task_id}/justify-missed",
            json={"justification": "Não foi possível executar a manutenção na data prevista."},
        )
    ).json()
    assert justified["status"] == "missed"

    rows = _maintenance_events(client, start=yesterday, end=today, maintenance_id=maintenance_id)
    assert [row["reschedule_sequence"] for row in rows] == [0, 1]
    assert rows[0]["status"] == "missed"
    assert rows[0]["missed_justification"] == "Não foi possível executar a manutenção na data prevista."
    assert rows[1]["status"] == "pending"

    history = assert_response(client.get(f"/api/agenda/tasks/{rows[1]['task_id']}/history")).json()
    assert len(history["entries"]) == 2
    assert history["entries"][0]["status"] == "missed"
    assert history["entries"][0]["justification"] == "Não foi possível executar a manutenção na data prevista."
    assert history["entries"][1]["status"] == "pending"


def test_maintenance_completed_before_schedule_never_becomes_missed_or_rescheduled(client, identity):
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    scheduled_at = datetime.combine(yesterday, time(hour=11, minute=30), tzinfo=timezone.utc)
    completed_at = scheduled_at - timedelta(days=1)
    property_item = _property(client)
    maintenance_id = _maintenance(
        identity,
        property_id=property_item["id"],
        scheduled_at=scheduled_at,
        status="completed",
        completed_at=completed_at,
    )

    rows = _maintenance_events(client, start=yesterday, end=today, maintenance_id=maintenance_id)
    assert len(rows) == 1
    assert rows[0]["reschedule_sequence"] == 0
    assert rows[0]["status"] == "completed"
    assert rows[0]["needs_justification"] is False
    assert rows[0]["completed_at"] == completed_at.isoformat().replace("+00:00", "Z")
