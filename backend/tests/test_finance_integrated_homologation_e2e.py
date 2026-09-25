"""Financial integration journey on the isolated PostgreSQL test database.

The conftest safety guard requires DATABASE_URL to name a test database.
No production records, banking transfers, or live signatures are used.
"""

from decimal import Decimal

from app.domains.foundation.access import UserContext, get_current_user_context
from app.main import app
from tests.helpers import (
    add_months,
    assert_response,
    build_signed_rental,
    create_person,
    decimal,
    midday,
)


def _charge(client, competence, lease_id):
    result = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": competence.isoformat(), "lease_contract_id": lease_id},
        )
    ).json()
    assert result["generated"] == 1
    return result["charges"][0]


def _dashboard(client, competence):
    return assert_response(
        client.get("/api/finance/dashboard", params={"competence": competence.isoformat()})
    ).json()


def test_rent_receipt_owner_repasse_commission_and_dashboard_stay_consistent(client, identity):
    scenario = build_signed_rental(client, publish=False)
    first_month = scenario["start"]
    second_month = add_months(first_month, 1)
    lease_id = scenario["lease"]["id"]
    owner_id = scenario["owner"]["id"]

    broker = create_person(
        client,
        name="Corretor Homologação Financeira",
        document="55555555555",
        email="broker.integrated@example.com",
        role_keys=["broker"],
    )
    rule = assert_response(
        client.post(
            "/api/finance/advanced/commissions/rules",
            json={
                "name": "Comissão recorrente integrada",
                "event_type": "recurring",
                "basis": "rent",
                "calculation_type": "percent",
                "value": 10,
                "beneficiary_type": "broker",
                "beneficiary_person_id": broker["id"],
                "property_id": scenario["property"]["id"],
                "lease_contract_id": lease_id,
                "due_days": 0,
                "priority": 10,
                "notes": "Homologação em banco isolado.",
            },
        ),
        201,
    ).json()
    assert rule["beneficiary_person_id"] == broker["id"]

    first = _charge(client, first_month, lease_id)
    second = _charge(client, second_month, lease_id)
    assert decimal(first["gross_amount"]) == Decimal("2000.00")
    assert decimal(second["gross_amount"]) == Decimal("2000.00")

    # A second generation attempt must not duplicate a charge.
    regenerated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": second_month.isoformat(), "lease_contract_id": lease_id},
        )
    ).json()
    assert regenerated["generated"] == 0
    assert regenerated["skipped_existing"] >= 1

    before = _dashboard(client, second_month)
    assert before["charges_open"] == 2
    assert decimal(before["open_amount"]) >= Decimal("4000.00")

    first_paid_at = midday(first_month.replace(day=10))
    first_paid = assert_response(
        client.post(
            f"/api/finance/charges/{first['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": first_paid_at.isoformat(),
                "payment_method": "pix",
                "payment_reference": "E2E-FIRST",
            },
        )
    ).json()
    assert first_paid["status"] == "paid"
    assert decimal(first_paid["settlement"]["agency_fee_withheld"]) == Decimal("2000.00")

    second_paid_at = midday(second_month.replace(day=10))
    second_paid = assert_response(
        client.post(
            f"/api/finance/charges/{second['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": second_paid_at.isoformat(),
                "payment_method": "pix",
                "payment_reference": "E2E-SECOND",
            },
        )
    ).json()
    assert second_paid["status"] == "paid"
    assert decimal(second_paid["settlement"]["agency_fee_withheld"]) == Decimal("200.00")
    assert decimal(second_paid["settlement"]["owner_entitlement_amount"]) == Decimal("1800.00")
    assert len(second_paid["settlement"]["repasses"]) == 1

    # Repeated receipt must not recreate settlements, repasses, or commissions.
    duplicate_payment = client.post(
        f"/api/finance/charges/{second['id']}/payment",
        json={
            "paid_amount": "2000.00",
            "paid_at": second_paid_at.isoformat(),
            "payment_method": "pix",
            "payment_reference": "E2E-DUPLICATE",
        },
    )
    assert duplicate_payment.status_code == 409

    second_charges = assert_response(
        client.get("/api/finance/charges", params={"competence": second_month.isoformat()})
    ).json()
    assert len(second_charges) == 1
    assert second_charges[0]["status"] == "paid"
    assert decimal(second_charges[0]["paid_amount"]) == Decimal("2000.00")

    repasses = assert_response(
        client.get("/api/finance/repasses", params={"competence": second_month.isoformat()})
    ).json()
    assert len(repasses) == 1
    repasse = repasses[0]
    assert repasse["owner_person_id"] == owner_id
    assert repasse["charge_id"] == second["id"]
    assert decimal(repasse["amount"]) == Decimal("1800.00")
    assert repasse["status"] == "pending"

    second_dashboard = _dashboard(client, second_month)
    assert second_dashboard["charges_open"] == 0
    assert decimal(second_dashboard["received_amount"]) == Decimal("2000.00")
    assert decimal(second_dashboard["agency_revenue_amount"]) == Decimal("200.00")
    assert decimal(second_dashboard["pending_repasse_amount"]) == Decimal("1800.00")
    assert second_dashboard["repasses_pending"] == 1

    # The commission module uses payment dates to select the same second month.
    generated_commissions = assert_response(
        client.post(
            "/api/finance/advanced/commissions/generate",
            params={"start_date": second_month.isoformat(), "end_date": second_month.replace(day=28).isoformat()},
        )
    ).json()
    commissions = assert_response(
        client.get("/api/finance/advanced/commissions", params={"competence": second_month.isoformat()})
    ).json()
    matching = [item for item in commissions if item["beneficiary_name"] == broker["name"]]
    assert len(matching) == 1
    commission = matching[0]
    assert decimal(commission["amount"]) == Decimal("200.00")
    assert commission["financial_title_id"]
    assert len([item for item in generated_commissions if item["id"] == commission["id"]]) <= 1

    approved = assert_response(
        client.post(f"/api/finance/advanced/commissions/{commission['id']}/approve")
    ).json()
    assert approved["status"] == "approved"
    assert approved["financial_title_id"] == commission["financial_title_id"]

    # A second generation pass must leave exactly one commission for this payment.
    assert_response(
        client.post(
            "/api/finance/advanced/commissions/generate",
            params={"start_date": second_month.isoformat(), "end_date": second_month.replace(day=28).isoformat()},
        )
    )
    again = assert_response(
        client.get("/api/finance/advanced/commissions", params={"competence": second_month.isoformat()})
    ).json()
    assert len([item for item in again if item["beneficiary_name"] == broker["name"]]) == 1

    paid_repasse = assert_response(
        client.post(
            f"/api/finance/repasses/{repasse['id']}/payment",
            json={"paid_at": second_paid_at.isoformat(), "payment_reference": "E2E-OWNER"},
        )
    ).json()
    assert paid_repasse["status"] == "paid"
    assert paid_repasse["payment_reference"] == "E2E-OWNER"

    duplicate_repasse = client.post(
        f"/api/finance/repasses/{repasse['id']}/payment",
        json={"paid_at": second_paid_at.isoformat(), "payment_reference": "E2E-OWNER-DUPLICATE"},
    )
    assert duplicate_repasse.status_code == 409

    after = _dashboard(client, second_month)
    assert after["repasses_pending"] == 0
    assert decimal(after["pending_repasse_amount"]) == Decimal("0.00")
    assert decimal(after["received_amount"]) == decimal(second_dashboard["received_amount"])
    assert decimal(after["agency_revenue_amount"]) == decimal(second_dashboard["agency_revenue_amount"])

    paid_rows = assert_response(
        client.get("/api/finance/repasses", params={"competence": second_month.isoformat(), "status": "paid"})
    ).json()
    assert [item["id"] for item in paid_rows] == [repasse["id"]]

    # A read-only user can inspect the same records but cannot mutate money flows.
    readonly = UserContext(user=identity["context"].user, permission_keys=frozenset({"finance.view"}))
    app.dependency_overrides[get_current_user_context] = lambda: readonly
    try:
        assert_response(client.get("/api/finance/dashboard", params={"competence": second_month.isoformat()}))
        assert_response(client.get("/api/finance/repasses", params={"competence": second_month.isoformat()}))
        denied_receipt = client.post(
            f"/api/finance/charges/{first['id']}/payment",
            json={"paid_amount": "2000.00", "payment_method": "pix"},
        )
        assert denied_receipt.status_code == 403
        denied_repasse = client.post(
            f"/api/finance/repasses/{repasse['id']}/payment",
            json={"payment_reference": "FORBIDDEN"},
        )
        assert denied_repasse.status_code == 403
        denied_commission = client.post(
            f"/api/finance/advanced/commissions/{commission['id']}/approve"
        )
        assert denied_commission.status_code == 403
    finally:
        app.dependency_overrides[get_current_user_context] = lambda: identity["context"]
