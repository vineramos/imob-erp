from datetime import date

from tests.helpers import (
    add_months,
    assert_response,
    create_person,
    create_property,
    create_signed_administration_contract,
    first_month,
)


def _admin_payload(property_id: str, start: date) -> dict:
    return {
        "property_id": property_id,
        "plan": "essential",
        "admin_fee_type": "percent",
        "admin_fee_percent": "10.00",
        "admin_fee_amount": None,
        "intermediation_percent": "100.00",
        "intermediation_installments": 1,
        "owner_repasse_business_days": 2,
        "condo_operational_payer": "tenant",
        "iptu_operational_payer": "tenant",
        "publication_requires_owner_approval": False,
        "maintenance_limit_amount": None,
        "emergency_limit_amount": None,
        "start_date": start.isoformat(),
        "end_date": add_months(start, 60).isoformat(),
        "end_of_term_action": "renew_indefinite",
        "notes": "Administração criada após encerramento da anterior.",
        "signers": [],
    }


def test_closed_administration_preserves_history_and_allows_replacement(client):
    start = first_month()
    owner = create_person(
        client,
        name="Proprietário Encerramento",
        document="39053344705",
        email="owner.closure@example.com",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    signed = create_signed_administration_contract(client, property_item["id"], start=start)

    closed = assert_response(
        client.post(
            f"/api/administration-contracts/{signed['id']}/workflow",
            json={
                "action": "close",
                "reason": "Encerramento solicitado pelo proprietário.",
                "effective_date": date.today().isoformat(),
            },
        )
    ).json()
    assert closed["status"] == "closed"
    assert closed["closed_at"]
    assert closed["closure_reason"] == "Encerramento solicitado pelo proprietário."
    assert closed["archive_status"] == "archived"
    assert closed["final_document_hash"] == signed["final_document_hash"]

    replacement = assert_response(
        client.post("/api/administration-contracts", json=_admin_payload(property_item["id"], date.today())),
        201,
    ).json()
    assert replacement["status"] == "draft"
    assert replacement["id"] != signed["id"]

    lifecycle = assert_response(client.get(f"/api/properties/{property_item['id']}/lifecycle")).json()
    assert lifecycle["administration"]["id"] == replacement["id"]
    assert lifecycle["administration"]["status"] == "draft"
