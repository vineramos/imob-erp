from uuid import UUID

from app.core.database import SessionLocal
from app.domains.portfolio.models import Person
from tests.helpers import assert_response, build_signed_rental


def _without_email(person_id: str) -> None:
    assert SessionLocal is not None
    with SessionLocal() as db:
        person = db.get(Person, UUID(person_id))
        assert person is not None
        person.email = None
        db.commit()


def test_tenant_portal_temporary_password_works_without_email_and_forces_personal_password(client):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    _without_email(tenant["id"])

    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": tenant["id"], "label": "Portal do inquilino"},
        ),
        201,
    ).json()

    issued = assert_response(
        client.post(f"/api/finance/advanced/portal/access/{access['id']}/temporary-password")
    ).json()
    assert issued["login_identifier"] == tenant["document_number"]
    assert issued["must_change_password"] is True
    assert issued["login_path"] == "/portal"
    temporary_password = issued["temporary_password"]
    assert len(temporary_password) == 14
    assert temporary_password.count("-") == 2

    pending = assert_response(client.get("/api/finance/advanced/portal/temporary-credentials")).json()
    pending_access = next(item for item in pending if item["access_id"] == access["id"])
    assert "temporary_password" not in pending_access

    wrong = client.post(
        "/api/tenant-portal/auth/document-login",
        json={"identifier": tenant["document_number"], "password": "SenhaErrada#2026"},
    )
    assert wrong.status_code == 401

    first_login = assert_response(
        client.post(
            "/api/tenant-portal/auth/document-login",
            json={"identifier": tenant["document_number"], "password": temporary_password},
        )
    ).json()
    assert first_login["must_change_password"] is True
    assert first_login["change_token"]
    assert client.cookies.get("imob_portal_session") is None
    assert client.get("/api/tenant-portal/me").status_code == 401

    bad_change = client.post(
        "/api/tenant-portal/auth/temporary-change",
        json={
            "identifier": tenant["document_number"],
            "change_token": "x" * 48,
            "password": "MinhaSenhaPessoal#2026",
        },
    )
    assert bad_change.status_code == 422

    changed = assert_response(
        client.post(
            "/api/tenant-portal/auth/temporary-change",
            json={
                "identifier": tenant["document_number"],
                "change_token": first_login["change_token"],
                "password": "MinhaSenhaPessoal#2026",
            },
        )
    ).json()
    assert changed["must_change_password"] is False
    assert client.cookies.get("imob_portal_session")

    me = assert_response(client.get("/api/tenant-portal/me")).json()
    assert me["person_id"] == tenant["id"]

    assert_response(client.post("/api/tenant-portal/auth/logout"), 204)
    assert client.post(
        "/api/tenant-portal/auth/document-login",
        json={"identifier": tenant["document_number"], "password": temporary_password},
    ).status_code == 401
    permanent = assert_response(
        client.post(
            "/api/tenant-portal/auth/document-login",
            json={"identifier": tenant["document_number"], "password": "MinhaSenhaPessoal#2026"},
        )
    ).json()
    assert permanent["must_change_password"] is False


def test_tenant_portal_new_temporary_password_invalidates_old_session_and_respects_revoke(client):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    access = assert_response(
        client.post("/api/finance/advanced/portal/access", json={"person_id": tenant["id"], "label": None}),
        201,
    ).json()

    first = assert_response(
        client.post(f"/api/finance/advanced/portal/access/{access['id']}/temporary-password")
    ).json()
    first_login = assert_response(
        client.post(
            "/api/tenant-portal/auth/document-login",
            json={"identifier": tenant["document_number"], "password": first["temporary_password"]},
        )
    ).json()
    assert_response(
        client.post(
            "/api/tenant-portal/auth/temporary-change",
            json={
                "identifier": tenant["document_number"],
                "change_token": first_login["change_token"],
                "password": "SenhaPessoalInicial#2026",
            },
        )
    )
    assert_response(client.get("/api/tenant-portal/me"))

    second = assert_response(
        client.post(f"/api/finance/advanced/portal/access/{access['id']}/temporary-password")
    ).json()
    assert second["temporary_password"] != first["temporary_password"]
    assert client.get("/api/tenant-portal/me").status_code == 401
    assert client.post(
        "/api/tenant-portal/auth/document-login",
        json={"identifier": tenant["document_number"], "password": "SenhaPessoalInicial#2026"},
    ).status_code == 401

    second_login = assert_response(
        client.post(
            "/api/tenant-portal/auth/document-login",
            json={"identifier": tenant["document_number"], "password": second["temporary_password"]},
        )
    ).json()
    assert second_login["must_change_password"] is True

    assert_response(client.post(f"/api/finance/advanced/portal/access/{access['id']}/revoke"))
    assert client.post(f"/api/finance/advanced/portal/access/{access['id']}/temporary-password").status_code == 409
    assert client.post(
        "/api/tenant-portal/auth/document-login",
        json={"identifier": tenant["document_number"], "password": second["temporary_password"]},
    ).status_code == 401
