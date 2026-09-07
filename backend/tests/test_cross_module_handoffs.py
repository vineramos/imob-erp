from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.agenda import logic
from app.domains.agenda.models import AgendaTask
from tests.helpers import assert_response, build_signed_rental, create_person


def _capture_payload(owner_id: str, *, suffix: str = "") -> dict:
    return {
        "status": "new",
        "source": "direct",
        "contact_person_id": owner_id,
        "responsible_user_id": None,
        "property_type": "apartment",
        "property_address": {
            "street": f"Rua da Captação {suffix}".strip(),
            "number": "88",
            "complement": "",
            "neighborhood": "Água Verde",
            "city": "Curitiba",
            "state": "PR",
            "postal_code": "80240-100",
        },
        "estimated_rent": "2800.00",
        "notes": "Oportunidade criada para validar a passagem até o imóvel definitivo.",
    }


def test_capture_advances_assigns_and_converts_into_available_property(client, identity):
    owner = create_person(
        client,
        name="Proprietária da Captação",
        document="67676767676",
        email="proprietaria.capture@example.com",
        role_keys=["owner"],
    )
    capture = assert_response(client.post("/api/captures", json=_capture_payload(owner["id"])), 201).json()

    responsibles = assert_response(client.get("/api/captures/responsibles")).json()
    assert {row["id"] for row in responsibles} >= {str(identity["user_id"])}
    capture = assert_response(
        client.post(
            f"/api/captures/{capture['id']}/workflow",
            json={"action": "assign", "responsible_user_id": str(identity["user_id"]), "reason": "Assumir negociação"},
        )
    ).json()
    assert capture["responsible_user_id"] == str(identity["user_id"])

    expected = ["negotiation", "documents", "inspection", "approved"]
    for stage in expected:
        capture = assert_response(
            client.post(f"/api/captures/{capture['id']}/workflow", json={"action": "advance"})
        ).json()
        assert capture["status"] == stage

    converted = assert_response(client.post(f"/api/captures/{capture['id']}/convert")).json()
    assert converted["capture"]["status"] == "available"
    assert converted["capture"]["converted_property_id"] == converted["property"]["id"]
    assert converted["property"]["status"] == "available"
    assert converted["property"]["purpose"] == "rent"
    assert converted["property"]["publication_enabled"] is False
    assert float(converted["property"]["rent_amount"]) == 2800
    assert converted["property"]["owners"] == [
        {
            "person_id": owner["id"],
            "name": owner["name"],
            "ownership_percent": 100.0,
        }
    ]

    duplicate = client.post(f"/api/captures/{capture['id']}/convert")
    assert duplicate.status_code == 409


def test_capture_loss_requires_reason_and_can_be_reopened(client):
    owner = create_person(
        client,
        name="Proprietário Segunda Captação",
        document="68686868686",
        email="proprietario.capture2@example.com",
        role_keys=["owner"],
    )
    capture = assert_response(client.post("/api/captures", json=_capture_payload(owner["id"], suffix="Dois")), 201).json()
    capture = assert_response(client.post(f"/api/captures/{capture['id']}/workflow", json={"action": "advance"})).json()
    assert capture["status"] == "negotiation"

    missing_reason = client.post(f"/api/captures/{capture['id']}/workflow", json={"action": "lose"})
    assert missing_reason.status_code == 422

    capture = assert_response(
        client.post(
            f"/api/captures/{capture['id']}/workflow",
            json={"action": "lose", "lost_reason": "Proprietário decidiu não administrar o imóvel neste momento."},
        )
    ).json()
    assert capture["status"] == "lost"
    assert "não administrar" in capture["lost_reason"]

    missing_reopen_reason = client.post(f"/api/captures/{capture['id']}/workflow", json={"action": "reopen"})
    assert missing_reopen_reason.status_code == 422

    capture = assert_response(
        client.post(
            f"/api/captures/{capture['id']}/workflow",
            json={"action": "reopen", "reason": "Proprietário retomou a negociação."},
        )
    ).json()
    assert capture["status"] == "negotiation"
    assert capture["lost_reason"] is None


def test_signed_lease_requires_initial_inspection_schedule_until_origin_is_created(client, identity):
    rental = build_signed_rental(client, publish=False)
    lease_id = rental["lease"]["id"]

    assert SessionLocal is not None
    with SessionLocal() as db:
        logic.sync_system_tasks(db, identity["organization_id"])
        db.commit()
        task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.organization_id == identity["organization_id"],
                AgendaTask.source_type == "initial_inspection_setup",
                AgendaTask.source_id == lease_id,
            )
        )
        assert task is not None
        assert task.status == "pending"
        assert task.automatic is True
        assert task.mandatory_action is True
        assert task.source_module == "inspections"
        assert task.due_at.date() == rental["start"]
        task_id = task.id

    scheduled_at = datetime.now(timezone.utc) + timedelta(days=2)
    created = assert_response(
        client.post(
            "/api/inspections",
            json={
                "lease_contract_id": lease_id,
                "scheduled_at": scheduled_at.isoformat(),
                "inspector_name": "Equipe de Vistorias",
                "environments": [
                    {
                        "key": "sala",
                        "name": "Sala",
                        "notes": None,
                        "items": [
                            {
                                "key": "paredes",
                                "label": "Paredes",
                                "condition": "good",
                                "notes": None,
                                "photos": [],
                            }
                        ],
                    }
                ],
                "notes": "Vistoria inicial agendada a partir da pendência operacional.",
            },
        ),
        201,
    ).json()
    assert created["scheduled_at"] is not None

    with SessionLocal() as db:
        logic.sync_system_tasks(db, identity["organization_id"])
        db.commit()
        task = db.get(AgendaTask, task_id)
        assert task is not None
        assert task.status == "completed"
        assert task.completion_source == "source"
        assert task.immutable_history is True
        assert task.completed_at is not None
