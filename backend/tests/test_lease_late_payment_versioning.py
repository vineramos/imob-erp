from __future__ import annotations

from datetime import date
from uuid import UUID

from app.core.database import SessionLocal
from app.domains.leases.models import LeaseContract
from tests.helpers import add_months, assert_response, create_person, create_property, first_month


def _lease_payload(property_id: str, tenant_id: str, start: date) -> dict:
    return {
        "property_id": property_id,
        "tenant_ids": [tenant_id],
        "rent_amount": "2000.00",
        "due_day": 10,
        "adjustment_index": "IPCA",
        "adjustment_period_months": 12,
        "adjustment_base_date": start.isoformat(),
        "next_adjustment_date": add_months(start, 12).isoformat(),
        "term_months": 30,
        "start_date": start.isoformat(),
        "end_date": add_months(start, 30).isoformat(),
        "termination_fine_months": "3.00",
        "inspection_contest_days": 5,
        "guarantee_type": "insurance",
        "guarantee_details": {"test_mode": True},
        "late_payment": {
            "fee_percent": "4.00",
            "interest_percent_monthly": "2.25",
            "interest_type": "compound",
            "compounding": "monthly",
        },
        "monthly_charges": [],
        "notes": "Contrato com mora definida manualmente.",
        "signers": [],
    }


def test_lease_accepts_and_versions_explicit_late_payment_terms(client):
    start = first_month()
    owner = create_person(
        client,
        name="Proprietário Mora Manual",
        document="73111111111",
        email="owner.mora.manual@example.com",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    tenant = create_person(
        client,
        name="Locatário Mora Manual",
        document="73222222222",
        email="tenant.mora.manual@example.com",
        role_keys=["tenant"],
    )

    payload = _lease_payload(property_item["id"], tenant["id"], start)
    created = assert_response(client.post("/api/lease-contracts", json=payload), 201).json()

    assert SessionLocal is not None
    with SessionLocal() as db:
        contract = db.get(LeaseContract, UUID(created["id"]))
        assert contract is not None
        frozen = dict(contract.rules_snapshot["late_payment"])
        assert frozen["fee_percent"] == "4.00"
        assert frozen["interest_percent_monthly"] == "2.25"
        assert frozen["interest_type"] == "compound"
        assert frozen["compounding"] == "monthly"
        assert dict(contract.versions[0].snapshot["rules"]["late_payment"]) == frozen

    finance_config = assert_response(
        client.get(f"/api/finance/lease-contracts/{created['id']}/monthly-charges")
    ).json()
    assert finance_config["late_payment"] == {
        "fee_percent": "4.00",
        "interest_percent_monthly": "2.25",
        "interest_type": "compound",
        "compounding": "monthly",
    }

    update_payload = {**payload}
    update_payload.pop("property_id")
    update_payload["change_summary"] = "Ajustar multa e juros desta versão"
    update_payload["late_payment"] = {
        "fee_percent": "1.50",
        "interest_percent_monthly": "0.75",
        "interest_type": "simple",
        "compounding": "daily",
    }
    updated = assert_response(
        client.put(f"/api/lease-contracts/{created['id']}", json=update_payload)
    ).json()
    assert updated["current_version"] == 2

    with SessionLocal() as db:
        contract = db.get(LeaseContract, UUID(created["id"]))
        assert contract is not None
        frozen = dict(contract.rules_snapshot["late_payment"])
        assert frozen["fee_percent"] == "1.50"
        assert frozen["interest_percent_monthly"] == "0.75"
        assert frozen["interest_type"] == "simple"
        assert frozen["compounding"] == "daily"
        versions = sorted(contract.versions, key=lambda item: item.version_number)
        assert dict(versions[-1].snapshot["rules"]["late_payment"]) == frozen

    finance_config = assert_response(
        client.get(f"/api/finance/lease-contracts/{created['id']}/monthly-charges")
    ).json()
    assert finance_config["late_payment"] == {
        "fee_percent": "1.50",
        "interest_percent_monthly": "0.75",
        "interest_type": "simple",
        "compounding": "daily",
    }
