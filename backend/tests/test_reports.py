from __future__ import annotations

from app.domains.foundation.access import UserContext, get_current_user_context
from app.main import app
from tests.helpers import assert_response, build_signed_rental, midday


def _paid_rent_scenario(client):
    scenario = build_signed_rental(client, publish=False)
    competence = scenario["start"]
    generated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": competence.isoformat(), "lease_contract_id": scenario["lease"]["id"]},
        )
    ).json()
    charge = generated["charges"][0]
    paid_at = midday(competence.replace(day=10))
    assert_response(
        client.post(
            f"/api/finance/charges/{charge['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": paid_at.isoformat(),
                "payment_method": "pix",
                "payment_reference": "REPORTS-TEST",
                "notes": "Pagamento fictício para validar relatórios.",
            },
        )
    )
    return scenario, charge, paid_at


def _grant_reports(identity, *, export: bool) -> None:
    base_context = identity["context"]
    permissions = set(base_context.permission_keys) | {"reports.view"}
    if export:
        permissions.add("reports.export")
    else:
        permissions.discard("reports.export")
    context = UserContext(user=base_context.user, permission_keys=frozenset(permissions))
    app.dependency_overrides[get_current_user_context] = lambda: context


def test_reports_annual_income_csv_and_dimob_readiness(client, identity):
    scenario, charge, paid_at = _paid_rent_scenario(client)
    _grant_reports(identity, export=True)
    year = paid_at.year

    annual = assert_response(
        client.get(
            "/api/reports/annual-income",
            params={"year": year, "party_type": "tenant", "person_id": scenario["tenant"]["id"]},
        )
    ).json()
    assert annual["person_id"] == scenario["tenant"]["id"]
    assert annual["total_paid"] == 2000.0
    assert len(annual["lines"]) == 1
    assert annual["lines"][0]["charge_code"] == charge["code"]

    csv_response = assert_response(
        client.get(
            "/api/reports/annual-income.csv",
            params={"year": year, "party_type": "tenant", "person_id": scenario["tenant"]["id"]},
        )
    )
    csv_text = csv_response.content.decode("utf-8-sig")
    assert "Competência;Data do pagamento;Imóvel;Cobrança" in csv_text
    assert charge["code"] in csv_text

    dimob = assert_response(client.get("/api/reports/dimob/validation", params={"year": year})).json()
    assert dimob["status"] == "ready_for_review"
    assert dimob["operation_count"] == 1
    assert dimob["lease_count"] == 1
    assert dimob["owner_count"] == 1
    assert dimob["tenant_count"] == 1
    assert dimob["error_count"] == 0
    assert dimob["official_layout_export_available"] is False


def test_reports_export_requires_specific_permission(client, identity):
    scenario, _, paid_at = _paid_rent_scenario(client)
    _grant_reports(identity, export=False)

    assert_response(
        client.get(
            "/api/reports/annual-income",
            params={"year": paid_at.year, "party_type": "tenant", "person_id": scenario["tenant"]["id"]},
        )
    )
    assert_response(
        client.get(
            "/api/reports/annual-income.csv",
            params={"year": paid_at.year, "party_type": "tenant", "person_id": scenario["tenant"]["id"]},
        ),
        403,
    )
