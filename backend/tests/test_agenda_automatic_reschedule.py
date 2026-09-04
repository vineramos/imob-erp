from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.database import SessionLocal
from app.domains.maintenance.models import MaintenanceRequest
from tests.helpers import assert_response, create_person, create_property


SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _maintenance(
    identity,
    *,
    property_id: str,
    scheduled_at: datetime,
    status: str = "scheduled",
    completed_at: datetime | None = None,
    cancelled_at: datetime | None = None,
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
            cancelled_at=cancelled_at,
            cancellation_reason="Cancelada no teste de regressão." if cancelled_at else None,
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
    assert history["entries"][1]["needs_justification"] is False


def test_pending_maintenance_creates_r2_when_r1_also_expires(client, identity):
    today = datetime.now(timezone.utc).date()
    original_day = today - timedelta(days=2)
    scheduled_at = datetime.combine(original_day, time(hour=11, minute=30), tzinfo=timezone.utc)
    property_item = _property(client)
    maintenance_id = _maintenance(identity, property_id=property_item["id"], scheduled_at=scheduled_at)

    rows = _maintenance_events(client, start=original_day, end=today, maintenance_id=maintenance_id)
    assert [row["reschedule_sequence"] for row in rows] == [0, 1, 2]
    assert rows[0]["needs_justification"] is True
    assert rows[1]["needs_justification"] is True
    assert rows[2]["status"] == "pending"
    assert rows[2]["needs_justification"] is False


def test_completed_maintenance_stops_chain_without_creating_next_day(client, identity):
    today = datetime.now(timezone.utc).date()
    original_day = today - timedelta(days=2)
    terminal_day = today - timedelta(days=1)
    scheduled_at = datetime.combine(original_day, time(hour=11, minute=30), tzinfo=timezone.utc)
    completed_at = datetime.combine(terminal_day, time(hour=15), tzinfo=timezone.utc)
    property_item = _property(client)
    maintenance_id = _maintenance(
        identity,
        property_id=property_item["id"],
        scheduled_at=scheduled_at,
        status="completed",
        completed_at=completed_at,
    )

    rows = _maintenance_events(client, start=original_day, end=today, maintenance_id=maintenance_id)
    assert [row["reschedule_sequence"] for row in rows] == [0, 1]
    assert all(row["reschedule_sequence"] != 2 for row in rows)


def test_cancelled_maintenance_stops_chain_without_creating_next_day(client, identity):
    today = datetime.now(timezone.utc).date()
    original_day = today - timedelta(days=2)
    terminal_day = today - timedelta(days=1)
    scheduled_at = datetime.combine(original_day, time(hour=11, minute=30), tzinfo=timezone.utc)
    cancelled_at = datetime.combine(terminal_day, time(hour=15), tzinfo=timezone.utc)
    property_item = _property(client)
    maintenance_id = _maintenance(
        identity,
        property_id=property_item["id"],
        scheduled_at=scheduled_at,
        status="cancelled",
        cancelled_at=cancelled_at,
    )

    rows = _maintenance_events(client, start=original_day, end=today, maintenance_id=maintenance_id)
    assert [row["reschedule_sequence"] for row in rows] == [0, 1]
    assert all(row["reschedule_sequence"] != 2 for row in rows)


def test_sao_paulo_local_day_drives_daily_reschedule_not_utc_day(client, identity):
    today_local = datetime.now(timezone.utc).astimezone(SAO_PAULO).date()
    yesterday_local = today_local - timedelta(days=1)
    # 22:30 em São Paulo já é 01:30 UTC do dia seguinte. A cadeia deve seguir
    # o dia civil do perfil, e não a data UTC persistida no banco.
    scheduled_local = datetime.combine(yesterday_local, time(hour=22, minute=30), tzinfo=SAO_PAULO)
    scheduled_at = scheduled_local.astimezone(timezone.utc)
    property_item = _property(client)
    maintenance_id = _maintenance(identity, property_id=property_item["id"], scheduled_at=scheduled_at)

    rows = _maintenance_events(client, start=yesterday_local, end=today_local, maintenance_id=maintenance_id)
    assert [row["reschedule_sequence"] for row in rows] == [0, 1]
    assert rows[0]["status"] == "pending"
    assert rows[0]["needs_justification"] is True
    assert rows[1]["status"] == "pending"
    assert rows[1]["needs_justification"] is False

    yesterday_rows = _maintenance_events(client, start=yesterday_local, end=yesterday_local, maintenance_id=maintenance_id)
    assert [row["reschedule_sequence"] for row in yesterday_rows] == [0]
    assert yesterday_rows[0]["needs_justification"] is True

    today_rows = _maintenance_events(client, start=today_local, end=today_local, maintenance_id=maintenance_id)
    assert [row["reschedule_sequence"] for row in today_rows] == [1]
    assert today_rows[0]["needs_justification"] is False

    history = assert_response(client.get(f"/api/agenda/tasks/{today_rows[0]['task_id']}/history")).json()
    assert [entry["sequence"] for entry in history["entries"]] == [0, 1]
    assert history["entries"][0]["needs_justification"] is True
    assert history["entries"][1]["needs_justification"] is False


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

    history = assert_response(client.get(f"/api/agenda/tasks/{rows[0]['task_id']}/history")).json()
    assert len(history["entries"]) == 1
    assert history["entries"][0]["status"] == "completed"
    assert history["entries"][0]["needs_justification"] is False
    assert history["entries"][0]["completed_at"] is not None
