from tests.helpers import add_months, assert_response, build_signed_rental, decimal, midday


def load_cycle(client, competence):
    return assert_response(
        client.get("/api/finance/monthly-cycle", params={"competence": competence.isoformat()})
    ).json()


def test_monthly_finance_cycle_tracks_charge_receipt_settlement_and_repasse(client):
    scenario = build_signed_rental(client, publish=False)
    first_competence = scenario["start"]
    lease = scenario["lease"]

    initial = load_cycle(client, first_competence)
    assert initial["eligible_contracts"] == 1
    assert initial["charges_count"] == 0
    assert initial["missing_charges"] == 1
    assert initial["next_action"]["key"] == "charges"
    assert initial["next_action"]["target"] == "billing"

    first_generated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": first_competence.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()
    first_charge = first_generated["charges"][0]

    waiting_receipt = load_cycle(client, first_competence)
    assert waiting_receipt["charges_count"] == 1
    assert waiting_receipt["missing_charges"] == 0
    assert waiting_receipt["open_charges"] == 1
    assert decimal(waiting_receipt["gross_amount"]) == decimal("2000.00")
    assert waiting_receipt["next_action"]["key"] == "receipts"

    first_paid_at = midday(first_competence.replace(day=10))
    assert_response(
        client.post(
            f"/api/finance/charges/{first_charge['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": first_paid_at.isoformat(),
                "payment_method": "pix",
                "payment_reference": "E2E-CICLO-PRIMEIRO",
            },
        )
    )

    duplicate_first = client.post(
        f"/api/finance/charges/{first_charge['id']}/payment",
        json={
            "paid_amount": "2000.00",
            "paid_at": first_paid_at.isoformat(),
            "payment_method": "pix",
            "payment_reference": "E2E-CICLO-DUPLICADO",
        },
    )
    assert duplicate_first.status_code == 409

    first_closed = load_cycle(client, first_competence)
    assert first_closed["paid_charges"] == 1
    assert first_closed["settlements_count"] == 1
    assert decimal(first_closed["received_amount"]) == decimal("2000.00")
    assert decimal(first_closed["agency_revenue_amount"]) == decimal("2000.00")
    assert decimal(first_closed["owner_entitlement_amount"]) == decimal("0.00")
    assert first_closed["owner_repasse_pending_count"] == 0
    assert first_closed["statement_owner_count"] == 1
    assert first_closed["next_action"] is None

    second_competence = add_months(first_competence, 1)
    second_generated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": second_competence.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()
    second_charge = second_generated["charges"][0]
    second_paid_at = midday(second_competence.replace(day=10))
    second_paid = assert_response(
        client.post(
            f"/api/finance/charges/{second_charge['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": second_paid_at.isoformat(),
                "payment_method": "pix",
                "payment_reference": "E2E-CICLO-SEGUNDO",
            },
        )
    ).json()
    repasse = second_paid["settlement"]["repasses"][0]

    waiting_repasse = load_cycle(client, second_competence)
    assert waiting_repasse["paid_charges"] == 1
    assert waiting_repasse["settlements_count"] == 1
    assert decimal(waiting_repasse["agency_revenue_amount"]) == decimal("200.00")
    assert decimal(waiting_repasse["owner_entitlement_amount"]) == decimal("1800.00")
    assert waiting_repasse["owner_repasse_pending_count"] == 1
    assert decimal(waiting_repasse["owner_repasse_pending_amount"]) == decimal("1800.00")
    assert waiting_repasse["next_action"]["key"] == "owner_repasses"
    assert waiting_repasse["next_action"]["target"] == "rent"

    assert_response(
        client.post(
            f"/api/finance/repasses/{repasse['id']}/payment",
            json={
                "paid_at": second_paid_at.isoformat(),
                "payment_reference": "E2E-CICLO-REPASSE",
            },
        )
    )

    duplicate_repasse = client.post(
        f"/api/finance/repasses/{repasse['id']}/payment",
        json={
            "paid_at": second_paid_at.isoformat(),
            "payment_reference": "E2E-CICLO-REPASSE-DUPLICADO",
        },
    )
    assert duplicate_repasse.status_code == 409

    finished = load_cycle(client, second_competence)
    assert finished["owner_repasse_pending_count"] == 0
    assert finished["statement_owner_count"] == 1
    assert finished["next_action"] is None
    states = {step["key"]: step["state"] for step in finished["steps"]}
    assert states["contracts"] == "complete"
    assert states["charges"] == "complete"
    assert states["receipts"] == "complete"
    assert states["settlement"] == "complete"
    assert states["owner_repasses"] == "complete"


def test_finance_closing_control_reports_clean_period_without_bank_anomalies(client):
    scenario = build_signed_rental(client, publish=False)
    competence = scenario["start"]

    result = assert_response(
        client.get(
            "/api/reports/closing-control",
            params={
                "start_date": competence.isoformat(),
                "end_date": add_months(competence, 1).isoformat(),
            },
        )
    ).json()

    assert result["bank_transactions"] == 0
    assert result["bank_transactions_unreconciled"] == 0
    assert result["reconciliation_amount_mismatch"] == 0
    assert result["invalid_reconciliation_targets"] == 0
    assert result["dre_duplicate_commissions"] == 0
    assert result["dre_unclassified_commissions"] == 0
    assert result["ready_to_close"] is True
    assert result["issues"] == []
