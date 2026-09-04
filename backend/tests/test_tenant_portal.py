from app.api.routes import tenant_portal as tenant_portal_routes
from tests.helpers import assert_response, build_signed_rental


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
