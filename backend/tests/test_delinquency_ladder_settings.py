from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.agenda.models import AgendaTask
from app.domains.finance.models import RentCharge
from tests.helpers import assert_response, build_signed_rental


def _move_charge_to_days_overdue(charge_id: str, days: int) -> None:
    assert SessionLocal is not None
    with SessionLocal() as db:
        charge = db.get(RentCharge, UUID(charge_id))
        assert charge is not None
        charge.due_date = date.today() - timedelta(days=days)
        charge.status = "sent"
        charge.sent_at = datetime.now(timezone.utc) - timedelta(days=days + 1)
        db.commit()


def _task_types(case_id: str) -> set[str]:
    assert SessionLocal is not None
    with SessionLocal() as db:
        return {
            str(item.source_type)
            for item in db.scalars(
                select(AgendaTask).where(
                    AgendaTask.source_module == "finance",
                    AgendaTask.source_id == case_id,
                )
            ).all()
        }


def test_delinquency_ladder_is_configurable_and_order_is_validated(client):
    current = assert_response(client.get("/api/settings/operations")).json()
    assert current["delinquency_first_contact_day"] == 1
    assert current["delinquency_followup_day"] == 3
    assert current["delinquency_critical_day"] == 5

    invalid = {
        **current,
        "delinquency_first_contact_day": 5,
        "delinquency_followup_day": 2,
        "delinquency_critical_day": 4,
    }
    invalid_response = client.put("/api/settings/operations", json=invalid)
    assert invalid_response.status_code == 422

    configured = {
        **current,
        "delinquency_first_contact_day": 2,
        "delinquency_followup_day": 4,
        "delinquency_critical_day": 6,
    }
    saved = assert_response(client.put("/api/settings/operations", json=configured)).json()
    assert saved["delinquency_first_contact_day"] == 2
    assert saved["delinquency_followup_day"] == 4
    assert saved["delinquency_critical_day"] == 6

    journey = build_signed_rental(client, publish=False)
    competence = journey["start"].isoformat()
    assert_response(client.post("/api/finance/charges/generate", json={"competence": competence}))
    charges = assert_response(client.get(f"/api/finance/charges?competence={competence}")).json()
    assert len(charges) == 1
    charge = charges[0]

    # D+3: somente o primeiro contato (configurado para D+2) deve existir.
    _move_charge_to_days_overdue(charge["id"], 3)
    cases = assert_response(client.post("/api/finance/advanced/delinquency/refresh")).json()
    case = next(item for item in cases if item["charge_id"] == charge["id"])
    assert case["first_contact_after_days"] == 2
    assert case["followup_after_days"] == 4
    assert case["critical_after_days"] == 6
    assert case["critical"] is False
    assert _task_types(case["id"]) == {"delinquency_first_contact"}

    # D+5: entra o acompanhamento, mas ainda não o marco de garantia.
    _move_charge_to_days_overdue(charge["id"], 5)
    cases = assert_response(client.post("/api/finance/advanced/delinquency/refresh")).json()
    case = next(item for item in cases if item["charge_id"] == charge["id"])
    assert case["critical"] is False
    assert _task_types(case["id"]) == {"delinquency_first_contact", "delinquency_followup"}

    # D+7: somente agora o caso se torna crítico e a tarefa de garantia aparece.
    _move_charge_to_days_overdue(charge["id"], 7)
    cases = assert_response(client.post("/api/finance/advanced/delinquency/refresh")).json()
    case = next(item for item in cases if item["charge_id"] == charge["id"])
    assert case["critical"] is True
    assert _task_types(case["id"]) == {
        "delinquency_first_contact",
        "delinquency_followup",
        "delinquency_guarantee",
    }
