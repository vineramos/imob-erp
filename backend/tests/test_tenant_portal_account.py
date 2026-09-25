from tests.helpers import assert_response, build_signed_rental


def _login_with_personal_password(client, tenant_id: str, document_number: str, password: str):
    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": tenant_id, "label": "Portal do inquilino"},
        ),
        201,
    ).json()
    issued = assert_response(
        client.post(f"/api/finance/advanced/portal/access/{access['id']}/temporary-password")
    ).json()
    temporary_login = assert_response(
        client.post(
            "/api/tenant-portal/auth/document-login",
            json={"identifier": document_number, "password": issued["temporary_password"]},
        )
    ).json()
    assert_response(
        client.post(
            "/api/tenant-portal/auth/temporary-change",
            json={
                "identifier": document_number,
                "change_token": temporary_login["change_token"],
                "password": password,
            },
        )
    )
    return access


def test_tenant_can_change_personal_password_and_keep_current_session(client):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    old_password = "SenhaPessoal#2026"
    new_password = "NovaSenhaPessoal#2027"
    _login_with_personal_password(client, tenant["id"], tenant["document_number"], old_password)

    wrong = client.post(
        "/api/tenant-portal/account/password",
        json={"current_password": "SenhaIncorreta#2026", "new_password": new_password},
    )
    assert wrong.status_code == 422

    same = client.post(
        "/api/tenant-portal/account/password",
        json={"current_password": old_password, "new_password": old_password},
    )
    assert same.status_code == 422

    assert_response(
        client.post(
            "/api/tenant-portal/account/password",
            json={"current_password": old_password, "new_password": new_password},
        ),
        204,
    )
    assert_response(client.get("/api/tenant-portal/me"))

    assert_response(client.post("/api/tenant-portal/auth/logout"), 204)
    assert client.post(
        "/api/tenant-portal/auth/document-login",
        json={"identifier": tenant["document_number"], "password": old_password},
    ).status_code == 401
    assert_response(
        client.post(
            "/api/tenant-portal/auth/document-login",
            json={"identifier": tenant["document_number"], "password": new_password},
        )
    )
