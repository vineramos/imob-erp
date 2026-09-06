from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.api.routes import owner_portal as owner_portal_routes
from app.core.database import SessionLocal
from app.domains.maintenance.models import MaintenanceRequest
from tests.helpers import add_months, assert_response, build_signed_rental, decimal, midday


def _owner_login(client, owner: dict) -> dict:
    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": owner["id"], "label": "Portal do proprietário"},
        ),
        201,
    ).json()
    issued = assert_response(
        client.post(f"/api/finance/advanced/portal/access/{access['id']}/temporary-password")
    ).json()
    first = assert_response(
        client.post(
            "/api/tenant-portal/auth/document-login",
            json={"identifier": owner["document_number"], "password": issued["temporary_password"]},
        )
    ).json()
    assert first["must_change_password"] is True
    assert_response(
        client.post(
            "/api/tenant-portal/auth/temporary-change",
            json={
                "identifier": owner["document_number"],
                "change_token": first["change_token"],
                "password": "SenhaDoProprietario#2026",
            },
        )
    )
    assert client.cookies.get("imob_portal_session")
    return access


def test_owner_portal_login_finance_and_context(client):
    journey = build_signed_rental(client, publish=False)
    owner = journey["owner"]
    lease = journey["lease"]
    start = journey["start"]
    _owner_login(client, owner)

    context = assert_response(client.get("/api/portal-context")).json()
    assert context["person_id"] == owner["id"]
    assert context["roles"] == ["owner"]

    initial = assert_response(client.get("/api/owner-portal/overview")).json()
    assert initial["metrics"]["properties"] == 1
    assert initial["metrics"]["active_leases"] == 1
    assert initial["properties"][0]["ownership_percent"] == 100
    assert any(item["status"] == "signed" for item in initial["administration_contracts"])
    assert any(item["id"] == lease["id"] for item in initial["leases"])

    first = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": start.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()["charges"][0]
    assert_response(
        client.post(
            f"/api/finance/charges/{first['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": midday(start.replace(day=10)).isoformat(),
                "payment_method": "pix",
                "payment_reference": "OWNER-PORTAL-FIRST",
                "notes": "Primeiro aluguel do teste do portal do proprietário.",
            },
        )
    )

    second_competence = add_months(start, 1)
    second = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": second_competence.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()["charges"][0]
    second_paid = assert_response(
        client.post(
            f"/api/finance/charges/{second['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": midday(second_competence.replace(day=10)).isoformat(),
                "payment_method": "pix",
                "payment_reference": "OWNER-PORTAL-SECOND",
                "notes": "Segundo aluguel do teste do portal do proprietário.",
            },
        )
    ).json()
    repasse = second_paid["settlement"]["repasses"][0]
    assert decimal(repasse["amount"]) == decimal("1800.00")

    pending = assert_response(client.get("/api/owner-portal/overview")).json()
    row = next(item for item in pending["repasses"] if item["id"] == repasse["id"])
    assert decimal(row["owner_rent_share"]) == decimal("2000.00")
    assert decimal(row["admin_fee"]) == decimal("200.00")
    assert decimal(row["amount"]) == decimal("1800.00")
    assert decimal(pending["metrics"]["pending_repasse_amount"]) == decimal("1800.00")
    assert pending["metrics"]["next_repasse_date"] is not None

    assert_response(
        client.post(
            f"/api/finance/repasses/{repasse['id']}/payment",
            json={
                "paid_at": midday(second_competence.replace(day=12)).isoformat(),
                "payment_reference": "OWNER-PORTAL-REPASSE",
                "notes": "Repasse do teste do portal do proprietário.",
            },
        )
    )
    paid = assert_response(client.get("/api/owner-portal/overview")).json()
    paid_row = next(item for item in paid["repasses"] if item["id"] == repasse["id"])
    assert paid_row["status"] == "paid"
    assert paid_row["payment_reference"] == "OWNER-PORTAL-REPASSE"
    assert paid["annual_reports"]
    assert decimal(paid["annual_reports"][0]["received_amount"]) >= decimal("1800.00")


def test_owner_portal_hides_internal_maintenance_cost_and_documents(client, identity, monkeypatch):
    monkeypatch.setattr(
        owner_portal_routes,
        "get_document_storage",
        lambda: identity["integrations"]["storage"],
    )
    journey = build_signed_rental(client, publish=False)
    owner = journey["owner"]
    _owner_login(client, owner)

    assert SessionLocal is not None
    quote_id = str(uuid4())
    with SessionLocal() as db:
        item = MaintenanceRequest(
            organization_id=identity["organization_id"],
            property_id=UUID(journey["property"]["id"]),
            lease_contract_id=UUID(journey["lease"]["id"]),
            requester_person_id=UUID(journey["tenant"]["id"]),
            title="Reparo hidráulico",
            category="hydraulic",
            priority="normal",
            status="awaiting_approval",
            description="Troca de tubulação e acabamento.",
            responsibility="owner",
            approval_required=True,
            services=[{"id": str(uuid4()), "title": "Reparo", "quantity": "1", "unit": "serviço"}],
            selected_quote_id=quote_id,
            quotes=[{
                "id": quote_id,
                "quote_code": "MAN-TESTE-ORC-01",
                "status": "selected",
                "partner_cost_total": "800.00",
                "client_price_total": "1050.00",
                "margin_total": "250.00",
                "partner_snapshot": {"name": "Parceiro Interno", "pix_key": "segredo-interno"},
                "items": [{"title": "Reparo", "partner_cost": "800.00", "client_price": "1050.00", "margin": "250.00"}],
            }],
            history=[],
            reported_at=datetime.now(timezone.utc),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        maintenance_id = str(item.id)

    internal_document = assert_response(
        client.post(
            "/api/documents",
            data={
                "title": "Orçamento interno do parceiro",
                "category": "maintenance",
                "entity_type": "maintenance",
                "entity_id": maintenance_id,
                "notes": "Documento que jamais pode chegar ao proprietário.",
            },
            files={"file": ("custo-interno.txt", b"parceiro 800 margem 250", "text/plain")},
        ),
        201,
    ).json()

    overview = assert_response(client.get("/api/owner-portal/overview")).json()
    maintenance = next(item for item in overview["maintenance"] if item["id"] == maintenance_id)
    assert decimal(maintenance["owner_charge_amount"]) == decimal("1050.00")
    assert maintenance["owner_decision_pending"] is True
    assert "partner_cost_total" not in maintenance
    assert "margin_total" not in maintenance
    assert "partner_snapshot" not in maintenance
    assert all(item["key"] != f"managed:{internal_document['id']}" for item in overview["documents"])
    assert client.get(f"/api/owner-portal/documents/managed:{internal_document['id']}/content").status_code == 404

    approved = assert_response(
        client.post(f"/api/owner-portal/maintenance/{maintenance_id}/decision", json={"decision": "approve"})
    ).json()
    assert approved["status"] == "approved"
    assert approved["owner_decision_pending"] is False
    assert decimal(approved["owner_charge_amount"]) == decimal("1050.00")
