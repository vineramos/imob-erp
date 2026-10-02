from uuid import UUID

from app.api.routes import tenant_portal as tenant_portal_routes
from app.core.database import SessionLocal
from app.domains.finance.advanced_models import BillingBatch, BillingItem
from app.domains.finance.models import RentCharge
from tests.helpers import add_months, assert_response, build_signed_rental, midday


def test_tenant_portal_login_overview_documents_and_maintenance(client, identity, monkeypatch):
    monkeypatch.setattr(
        tenant_portal_routes,
        "get_document_storage",
        lambda: identity["integrations"]["storage"],
    )
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    lease = journey["lease"]

    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": tenant["id"], "label": "Portal do inquilino"},
        ),
        201,
    ).json()

    credentials = assert_response(
        client.post(
            f"/api/finance/advanced/portal/access/{access['id']}/credentials",
            json={"password": "SenhaSegura#2026"},
        )
    ).json()
    assert credentials["email"] == tenant["email"].lower()
    assert credentials["login_path"] == "/portal"

    wrong = client.post(
        "/api/tenant-portal/auth/login",
        json={"email": tenant["email"], "password": "senha-incorreta"},
    )
    assert wrong.status_code == 401

    login = assert_response(
        client.post(
            "/api/tenant-portal/auth/login",
            json={"email": tenant["email"], "password": "SenhaSegura#2026"},
        )
    ).json()
    assert login["person_name"] == tenant["name"]
    assert client.cookies.get("imob_portal_session")

    me = assert_response(client.get("/api/tenant-portal/me")).json()
    assert me["person_id"] == tenant["id"]
    assert me["organization_name"] == "Imob Testes"

    overview = assert_response(client.get("/api/tenant-portal/overview")).json()
    assert overview["metrics"]["active_leases"] == 1
    assert any(item["id"] == lease["id"] and item["status"] == "signed" for item in overview["leases"])
    assert any(item["category"] == "contract" and "Locação" in item["title"] for item in overview["documents"])

    signed_document = next(
        item for item in overview["documents"]
        if item["key"].startswith(f"system:lease_contract:{lease['id']}:") and "Assinado" in item["title"]
    )
    downloaded = assert_response(client.get(f"/api{signed_document['download_path']}"))
    assert downloaded.headers["content-type"].startswith("application/pdf")
    assert downloaded.content.startswith(b"%PDF")

    created = assert_response(
        client.post(
            "/api/tenant-portal/maintenance",
            json={
                "lease_contract_id": lease["id"],
                "title": "Vazamento na cozinha",
                "category": "hydraulic",
                "priority": "high",
                "description": "Há vazamento contínuo abaixo da pia da cozinha.",
            },
        ),
        201,
    ).json()
    assert created["status"] == "requested"

    internal_document = assert_response(
        client.post(
            "/api/documents",
            data={
                "title": "Orçamento interno do parceiro",
                "category": "maintenance",
                "entity_type": "maintenance",
                "entity_id": created["id"],
                "notes": "Documento deliberadamente interno para validar privacidade do portal.",
            },
            files={"file": ("orcamento-interno.txt", b"custo interno do parceiro", "text/plain")},
        ),
        201,
    ).json()

    refreshed = assert_response(client.get("/api/tenant-portal/overview")).json()
    assert all(item["key"] != f"managed:{internal_document['id']}" for item in refreshed["documents"])
    assert client.get(f"/api/tenant-portal/documents/managed:{internal_document['id']}/content").status_code == 404
    request = next(item for item in refreshed["maintenance"] if item["id"] == created["id"])
    assert request["title"] == "Vazamento na cozinha"
    assert request["priority"] == "high"
    assert refreshed["metrics"]["maintenance_open"] >= 1

    assert_response(client.post("/api/tenant-portal/auth/logout"), 204)
    assert client.get("/api/tenant-portal/me").status_code == 401


def test_tenant_portal_password_reset_invalidates_session_and_revoke_blocks_access(client):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]

    access = assert_response(
        client.post("/api/finance/advanced/portal/access", json={"person_id": tenant["id"], "label": None}),
        201,
    ).json()
    assert_response(
        client.post(
            f"/api/finance/advanced/portal/access/{access['id']}/credentials",
            json={"password": "PrimeiraSenha#2026"},
        )
    )
    assert_response(
        client.post(
            "/api/tenant-portal/auth/login",
            json={"email": tenant["email"], "password": "PrimeiraSenha#2026"},
        )
    )
    assert_response(client.get("/api/tenant-portal/me"))

    assert_response(
        client.post(
            f"/api/finance/advanced/portal/access/{access['id']}/credentials",
            json={"password": "NovaSenha#2026"},
        )
    )
    assert client.get("/api/tenant-portal/me").status_code == 401

    assert client.post(
        "/api/tenant-portal/auth/login",
        json={"email": tenant["email"], "password": "PrimeiraSenha#2026"},
    ).status_code == 401
    assert_response(
        client.post(
            "/api/tenant-portal/auth/login",
            json={"email": tenant["email"], "password": "NovaSenha#2026"},
        )
    )

    assert_response(client.post(f"/api/finance/advanced/portal/access/{access['id']}/revoke"))
    assert client.get("/api/tenant-portal/me").status_code == 403


def test_tenant_portal_downloads_annual_payment_statement(client):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    competence = add_months(journey["start"], 1)
    charge = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": competence.isoformat(), "lease_contract_id": journey["lease"]["id"]},
        )
    ).json()["charges"][0]
    assert_response(
        client.post(
            f"/api/finance/charges/{charge['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": midday(competence.replace(day=10)).isoformat(),
                "payment_method": "pix",
                "payment_reference": "TENANT-ANNUAL-PDF",
            },
        )
    )
    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": tenant["id"], "label": "Portal anual do inquilino"},
        ),
        201,
    ).json()
    assert_response(
        client.post(
            f"/api/finance/advanced/portal/access/{access['id']}/credentials",
            json={"password": "SenhaAnual#2026"},
        )
    )
    assert_response(
        client.post(
            "/api/tenant-portal/auth/login",
            json={"email": tenant["email"], "password": "SenhaAnual#2026"},
        )
    )
    annual = client.get(f"/api/tenant-portal/reports/{competence.year}/payments.pdf")
    assert annual.status_code == 200
    assert annual.headers["content-type"].startswith("application/pdf")
    assert "comprovante-anual-pagamentos-" in annual.headers.get("content-disposition", "")
    assert annual.content.startswith(b"%PDF")


def test_tenant_portal_hides_cancelled_charge_payment_instruments(client, identity):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    competence = add_months(journey["start"], 1)
    charge = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": competence.isoformat(), "lease_contract_id": journey["lease"]["id"]},
        )
    ).json()["charges"][0]

    assert SessionLocal is not None
    with SessionLocal() as db:
        stored = db.get(RentCharge, UUID(charge["id"]))
        assert stored is not None
        batch = BillingBatch(
            organization_id=identity["organization_id"],
            competence=competence.replace(day=1),
            status="completed",
            provider="inter",
            generated_count=1,
            issued_count=1,
            sent_count=1,
            confirmed_count=0,
            error_count=0,
            created_by_user_id=identity["user_id"],
        )
        db.add(batch)
        db.flush()
        db.add(BillingItem(
            organization_id=identity["organization_id"],
            billing_batch_id=batch.id,
            charge_id=stored.id,
            provider="inter",
            provider_charge_id="INTER-CANCELLED-PORTAL",
            provider_status="CANCELADO",
            boleto_line="34191.79001 01043.510047 91020.150008 8 00000000200000",
            pix_copy_paste="pix-cancelado-nao-deve-ser-exibido",
            pdf_reference="storage://billing/cancelled.pdf",
            request_snapshot={},
            response_snapshot={},
        ))
        stored.status = "cancelled"
        db.commit()

    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": tenant["id"], "label": "Portal cobrança cancelada"},
        ),
        201,
    ).json()
    assert_response(
        client.post(
            f"/api/finance/advanced/portal/access/{access['id']}/credentials",
            json={"password": "SenhaCancelada#2026"},
        )
    )
    assert_response(
        client.post(
            "/api/tenant-portal/auth/login",
            json={"email": tenant["email"], "password": "SenhaCancelada#2026"},
        )
    )

    overview = assert_response(client.get("/api/tenant-portal/overview")).json()
    row = next(item for item in overview["charges"] if item["id"] == charge["id"])
    assert row["status"] == "cancelled"
    assert row["boleto_line"] is None
    assert row["pix_copy_paste"] is None
    assert row["billing_pdf_available"] is False
    assert overview["metrics"]["open_charges"] == 0
    assert client.get(f"/api/tenant-portal/charges/{charge['id']}/billing.pdf").status_code == 409
