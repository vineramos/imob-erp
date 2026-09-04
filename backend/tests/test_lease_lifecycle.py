from datetime import timedelta

from tests.helpers import _run_signature_flow, add_months, assert_response, build_signed_rental, midday


def test_termination_runs_exit_inspection_keys_and_releases_property(client):
    journey = build_signed_rental(client, publish=False)
    lease = journey["lease"]
    effective = journey["start"] + timedelta(days=365)

    started = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/termination",
            json={
                "effective_date": effective.isoformat(),
                "initiated_by": "tenant",
                "reason": "Desocupação antecipada da jornada automatizada.",
            },
        )
    ).json()
    assert started["process_type"] == "termination"
    assert started["status"] == "termination_requested"
    assert started["fine_status"] == "pending"
    assert float(started["termination_fine_amount"]) > 0

    next_competence = add_months(effective.replace(day=1), 1)
    future_charge = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": next_competence.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()
    assert future_charge["generated"] == 0
    assert future_charge["skipped_ineligible"] == 1
    assert future_charge["charges"] == []

    fine = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/fine",
            json={"action": "waive", "beneficiary": None, "amount": None, "due_date": None, "notes": "Dispensa em teste."},
        )
    ).json()
    assert fine["fine_status"] == "waived"

    lifecycle = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/exit-inspection",
            json={"scheduled_at": midday(effective).isoformat(), "inspector_name": "Vistoriador Saída", "notes": "Comparar com entrada."},
        )
    ).json()
    inspection_id = lifecycle["exit_inspection_id"]
    assert inspection_id
    assert lifecycle["exit_inspection_status"] == "draft"

    completed = assert_response(
        client.post(f"/api/inspections/{inspection_id}/workflow", json={"action": "complete", "reason": None})
    ).json()
    assert completed["inspection_type"] == "final"
    assert completed["status"] == "ready"
    assert completed["report_hash"]

    keys = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/keys-return",
            json={
                "returned_at": midday(effective).isoformat(),
                "received_by": "Administrativo Teste",
                "received_document": None,
                "keys": [{"label": "Chaves do imóvel", "quantity": 2, "notes": None}],
                "meter_readings": {"energia": "12345"},
                "notes": "Sem ressalvas.",
            },
        )
    ).json()
    assert keys["keys_returned_at"]
    assert keys["exit_inspection_status"] == "finalized"
    assert keys["financial_clearance"]["blocking_count"] == 0
    assert keys["can_close"] is True

    closed = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/close",
            json={"property_disposition": "available", "notes": "Encerramento automatizado."},
        )
    ).json()
    assert closed["status"] == "closed"
    assert closed["property_disposition"] == "available"

    leases = assert_response(client.get("/api/lease-contracts")).json()
    old_lease = next(item for item in leases if item["id"] == lease["id"])
    assert old_lease["status"] == "closed"
    assert old_lease["operational_end_date"] == effective.isoformat()
    assert old_lease["closed_at"]

    properties = assert_response(client.get("/api/properties")).json()
    prop = next(item for item in properties if item["id"] == journey["property"]["id"])
    assert prop["status"] == "available"
    assert prop["publication_enabled"] is False


def test_renewal_creates_new_signed_lease_and_closes_previous_contract(client):
    journey = build_signed_rental(client, publish=False)
    old = journey["lease"]
    renewal_start = add_months(journey["start"], 30)

    proposed = assert_response(
        client.post(
            f"/api/lease-contracts/{old['id']}/lifecycle/renewal",
            json={
                "start_date": renewal_start.isoformat(),
                "term_months": 24,
                "rent_amount": "2300.00",
                "adjustment_index": "IPCA",
                "adjustment_period_months": 12,
                "notes": "Renovação automatizada.",
            },
        )
    ).json()
    assert proposed["status"] == "renewal_proposed"

    prepared = assert_response(
        client.post(f"/api/lease-contracts/{old['id']}/lifecycle/renewal/prepare")
    ).json()
    renewed_id = prepared["renewed_lease_contract_id"]
    assert renewed_id
    assert prepared["renewed_lease_status"] == "draft"
    assert prepared["renewed_lease_code"]

    renewed = _run_signature_flow(client, kind="lease", contract_id=renewed_id)
    assert renewed["status"] == "signed"
    assert float(renewed["rent_amount"]) == 2300.0

    completed = assert_response(
        client.post(f"/api/lease-contracts/{old['id']}/lifecycle/renewal/complete")
    ).json()
    assert completed["status"] == "renewed"
    assert completed["renewed_lease_status"] == "signed"
    assert completed["closed_at"]

    leases = assert_response(client.get("/api/lease-contracts")).json()
    previous = next(item for item in leases if item["id"] == old["id"])
    current = next(item for item in leases if item["id"] == renewed_id)
    assert previous["status"] == "closed"
    assert current["status"] == "signed"

    properties = assert_response(client.get("/api/properties")).json()
    prop = next(item for item in properties if item["id"] == journey["property"]["id"])
    assert prop["status"] == "leased"
    assert prop["publication_enabled"] is False
