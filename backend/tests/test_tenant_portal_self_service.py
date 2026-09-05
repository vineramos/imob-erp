from app.api.routes import tenant_portal_recovery
from tests.helpers import assert_response, build_signed_rental


def test_tenant_portal_self_service_first_access_and_reset(client, monkeypatch):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    sent = []
    first_password = "A" * 12
    second_password = "B" * 12

    monkeypatch.setattr(tenant_portal_recovery, "smtp_configured", lambda: True)
    monkeypatch.setattr(
        tenant_portal_recovery,
        "send_portal_verification_email",
        lambda **payload: sent.append(payload),
    )

    generic = assert_response(
        client.post(
            "/api/tenant-portal/auth/access/request",
            json={"email": "missing@example.invalid", "purpose": "first_access"},
        )
    ).json()
    assert generic["expires_in_seconds"] == 600
    assert sent == []

    assert_response(
        client.post(
            "/api/tenant-portal/auth/access/request",
            json={"email": tenant["email"], "purpose": "first_access"},
        )
    )
    assert len(sent) == 1
    code = sent[-1]["code"]
    assert len(code) == 6 and code.isdigit()
    wrong_code = "000000" if code != "000000" else "000001"

    assert client.post(
        "/api/tenant-portal/auth/access/confirm",
        json={"email": tenant["email"], "code": wrong_code, "password": first_password},
    ).status_code == 422

    assert_response(
        client.post(
            "/api/tenant-portal/auth/access/confirm",
            json={"email": tenant["email"], "code": code, "password": first_password},
        )
    )
    assert_response(
        client.post(
            "/api/tenant-portal/auth/login",
            json={"email": tenant["email"], "password": first_password},
        )
    )
    assert_response(client.get("/api/tenant-portal/me"))

    assert_response(
        client.post(
            "/api/tenant-portal/auth/access/request",
            json={"email": tenant["email"], "purpose": "forgot_password"},
        )
    )
    reset_code = sent[-1]["code"]
    assert_response(
        client.post(
            "/api/tenant-portal/auth/access/confirm",
            json={"email": tenant["email"], "code": reset_code, "password": second_password},
        )
    )
    assert client.get("/api/tenant-portal/me").status_code == 401
    assert client.post(
        "/api/tenant-portal/auth/login",
        json={"email": tenant["email"], "password": first_password},
    ).status_code == 401
    assert_response(
        client.post(
            "/api/tenant-portal/auth/login",
            json={"email": tenant["email"], "password": second_password},
        )
    )

    accounts = assert_response(client.get("/api/finance/advanced/portal/accounts")).json()
    account = next(item for item in accounts if item["person_id"] == tenant["id"])
    assert account["email"] == tenant["email"].lower()

    accesses = assert_response(client.get("/api/finance/advanced/portal/access")).json()
    access = next(item for item in accesses if item["id"] == account["access_id"])
    assert_response(client.post(f"/api/finance/advanced/portal/access/{access['id']}/revoke"))
    sent_count = len(sent)
    assert_response(
        client.post(
            "/api/tenant-portal/auth/access/request",
            json={"email": tenant["email"], "purpose": "forgot_password"},
        )
    )
    assert len(sent) == sent_count
    assert client.get("/api/tenant-portal/me").status_code == 403


def test_tenant_portal_self_service_requires_email_delivery(client, monkeypatch):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    monkeypatch.setattr(tenant_portal_recovery, "smtp_configured", lambda: False)

    response = client.post(
        "/api/tenant-portal/auth/access/request",
        json={"email": tenant["email"], "purpose": "first_access"},
    )
    assert response.status_code == 503
    assert "ainda não está configurado" in response.json()["detail"]
