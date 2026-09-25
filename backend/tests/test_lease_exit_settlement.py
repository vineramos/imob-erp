from datetime import timedelta
from uuid import UUID

from app.core.database import SessionLocal
from app.domains.finance.core_models import FinancialTitle
from app.domains.lease_lifecycle.models import LeaseExitAdjustment
from tests.helpers import assert_response, build_signed_rental, midday


def _environment(condition: str, notes: str) -> list[dict]:
    return [
        {
            "key": "sala",
            "name": "Sala",
            "notes": None,
            "items": [
                {
                    "key": "parede-principal",
                    "label": "Parede principal",
                    "condition": condition,
                    "notes": notes,
                    "photos": [],
                }
            ],
        }
    ]


def test_exit_settlement_requires_human_adjustment_and_blocks_close_until_resolved(client):
    journey = build_signed_rental(client, publish=False)
    lease = journey["lease"]
    effective = journey["start"] + timedelta(days=365)

    initial = assert_response(
        client.post(
            "/api/inspections",
            json={
                "lease_contract_id": lease["id"],
                "scheduled_at": midday(journey["start"]).isoformat(),
                "inspector_name": "Vistoriador Entrada",
                "environments": _environment("good", "Pintura íntegra na entrada."),
                "notes": "Laudo inicial para comparação do acerto final.",
            },
        ),
        201,
    ).json()
    assert initial["inspection_type"] == "initial"
    initial_ready = assert_response(
        client.post(f"/api/inspections/{initial['id']}/workflow", json={"action": "complete", "reason": None})
    ).json()
    assert initial_ready["status"] == "ready"

    started = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/termination",
            json={
                "effective_date": effective.isoformat(),
                "initiated_by": "tenant",
                "reason": "Desocupação com acerto final automatizado.",
            },
        )
    ).json()
    assert started["fine_status"] == "pending"

    waived = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/fine",
            json={"action": "waive", "beneficiary": None, "amount": None, "due_date": None, "notes": "Dispensa controlada."},
        )
    ).json()
    assert waived["fine_status"] == "waived"

    lifecycle = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/exit-inspection",
            json={"scheduled_at": midday(effective).isoformat(), "inspector_name": "Vistoriador Saída", "notes": "Comparar com entrada."},
        )
    ).json()
    inspection_id = lifecycle["exit_inspection_id"]
    assert inspection_id

    too_early = client.post(
        f"/api/lease-contracts/{lease['id']}/lifecycle/exit-adjustments",
        json={
            "kind": "damage",
            "description": "Tentativa antes do laudo",
            "beneficiary": "owner",
            "amount": "100.00",
            "due_date": effective.isoformat(),
            "source_context": {},
            "notes": None,
        },
    )
    assert too_early.status_code == 409
    assert "Conclua o laudo" in too_early.json()["detail"]

    final_updated = assert_response(
        client.put(
            f"/api/inspections/{inspection_id}",
            json={
                "scheduled_at": midday(effective).isoformat(),
                "inspector_name": "Vistoriador Saída",
                "environments": _environment("damaged", "Pintura com dano e reparo necessário."),
                "notes": "Dano constatado na saída.",
                "change_summary": "Registrar condição final da parede",
            },
        )
    ).json()
    assert final_updated["environments"][0]["items"][0]["condition"] == "damaged"

    final_ready = assert_response(
        client.post(f"/api/inspections/{inspection_id}/workflow", json={"action": "complete", "reason": None})
    ).json()
    assert final_ready["status"] == "ready"

    workspace = assert_response(
        client.get(f"/api/lease-contracts/{lease['id']}/lifecycle/exit-workspace")
    ).json()
    assert workspace["inspection_ready_for_adjustments"] is True
    assert workspace["adjustments"] == []
    assert len(workspace["inspection_differences"]) == 1
    difference = workspace["inspection_differences"][0]
    assert difference["environment_key"] == "sala"
    assert difference["item_key"] == "parede-principal"
    assert difference["initial_condition"] == "good"
    assert difference["final_condition"] == "damaged"
    assert difference["severity_delta"] == 3
    # A diferença é apenas uma evidência: nenhuma cobrança nasce automaticamente.
    assert workspace["financial_blocking_count"] == 0

    owner_adjustment = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/exit-adjustments",
            json={
                "kind": "damage",
                "description": "Reparo e pintura da parede principal",
                "beneficiary": "owner",
                "amount": "450.00",
                "due_date": effective.isoformat(),
                "source_context": {
                    "source": "inspection_difference",
                    "environment_key": "sala",
                    "item_key": "parede-principal",
                    "initial_condition": "good",
                    "final_condition": "damaged",
                },
                "notes": "Valor aprovado após análise humana da vistoria.",
            },
        ),
        201,
    ).json()
    assert len(owner_adjustment["adjustments"]) == 1
    assert float(owner_adjustment["adjustment_open_amount"]) == 450.0
    assert owner_adjustment["financial_blocking_count"] == 1
    assert float(owner_adjustment["financial_blocking_amount"]) == 450.0

    agency_adjustment = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/exit-adjustments",
            json={
                "kind": "key_replacement",
                "description": "Reposição de controle de acesso",
                "beneficiary": "agency",
                "amount": "75.00",
                "due_date": effective.isoformat(),
                "source_context": {"source": "manual_exit_adjustment"},
                "notes": None,
            },
        ),
        201,
    ).json()
    assert len(agency_adjustment["adjustments"]) == 2
    assert float(agency_adjustment["adjustment_open_amount"]) == 525.0
    assert agency_adjustment["financial_blocking_count"] == 2
    assert float(agency_adjustment["financial_blocking_amount"]) == 525.0

    owner_row = next(item for item in agency_adjustment["adjustments"] if item["beneficiary"] == "owner")
    agency_row = next(item for item in agency_adjustment["adjustments"] if item["beneficiary"] == "agency")
    assert owner_row["financial_title_code"]
    assert agency_row["financial_title_code"]

    assert SessionLocal is not None
    with SessionLocal() as db:
        owner_item = db.get(LeaseExitAdjustment, UUID(owner_row["id"]))
        agency_item = db.get(LeaseExitAdjustment, UUID(agency_row["id"]))
        assert owner_item is not None and owner_item.financial_title_id is not None
        assert agency_item is not None and agency_item.financial_title_id is not None
        owner_title = db.get(FinancialTitle, owner_item.financial_title_id)
        agency_title = db.get(FinancialTitle, agency_item.financial_title_id)
        assert owner_title is not None and owner_title.fund_scope == "third_party"
        assert agency_title is not None and agency_title.fund_scope == "operating"
        assert owner_title.source_snapshot["origin"] == "lease_exit_adjustment"
        assert agency_title.source_snapshot["origin"] == "lease_exit_adjustment"

    keys = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/keys-return",
            json={
                "returned_at": midday(effective).isoformat(),
                "received_by": "Administrativo Teste",
                "received_document": None,
                "keys": [{"label": "Chaves do imóvel", "quantity": 2, "notes": None}],
                "meter_readings": {"energia": "12345", "agua": "6789"},
                "notes": "Leituras registradas na devolução.",
            },
        )
    ).json()
    assert keys["exit_inspection_status"] == "finalized"
    assert keys["can_close"] is False
    assert keys["financial_clearance"]["blocking_count"] == 2

    blocked_close = client.post(
        f"/api/lease-contracts/{lease['id']}/lifecycle/close",
        json={"property_disposition": "available", "notes": "Não deve fechar com ajustes em aberto."},
    )
    assert blocked_close.status_code == 409
    assert "pendência(s) financeira(s)" in blocked_close.json()["detail"]

    after_owner_cancel = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/exit-adjustments/{owner_row['id']}/cancel"
        )
    ).json()
    assert after_owner_cancel["financial_blocking_count"] == 1
    assert float(after_owner_cancel["financial_blocking_amount"]) == 75.0

    after_all_cancel = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/exit-adjustments/{agency_row['id']}/cancel"
        )
    ).json()
    assert after_all_cancel["financial_blocking_count"] == 0
    assert float(after_all_cancel["adjustment_open_amount"]) == 0.0
    assert after_all_cancel["can_close"] is True
    assert after_all_cancel["meter_readings"] == {"energia": "12345", "agua": "6789"}

    with SessionLocal() as db:
        owner_item = db.get(LeaseExitAdjustment, UUID(owner_row["id"]))
        agency_item = db.get(LeaseExitAdjustment, UUID(agency_row["id"]))
        assert owner_item is not None and owner_item.status == "cancelled"
        assert agency_item is not None and agency_item.status == "cancelled"
        owner_title = db.get(FinancialTitle, owner_item.financial_title_id)
        agency_title = db.get(FinancialTitle, agency_item.financial_title_id)
        assert owner_title is not None and owner_title.status == "cancelled"
        assert agency_title is not None and agency_title.status == "cancelled"

    closed = assert_response(
        client.post(
            f"/api/lease-contracts/{lease['id']}/lifecycle/close",
            json={"property_disposition": "available", "notes": "Acerto final concluído."},
        )
    ).json()
    assert closed["status"] == "closed"

    list_workspaces = assert_response(client.get("/api/lease-lifecycle/terminations")).json()
    final_workspace = next(item for item in list_workspaces if item["lease_contract_id"] == lease["id"])
    assert final_workspace["lifecycle_status"] == "closed"
    assert final_workspace["closed_at"]
    assert final_workspace["financial_blocking_count"] == 0
