from sqlalchemy import select

from app.api.routes import auth_proxy
from app.core.database import SessionLocal
from app.domains.foundation.models import AppUser, AuditLog, UserInvitation


def test_admin_creates_single_use_invitation(client):
    response = client.post(
        "/api/settings/users/invitations",
        json={
            "name": "Maria Financeiro",
            "email": "Maria.Financeiro@example.com",
            "role_keys": ["admin"],
            "reason": "Segunda administradora para contingência operacional.",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["user"]["email"] == "maria.financeiro@example.com"
    assert payload["user"]["access_status"] == "pending"
    assert payload["token"]

    details = client.get(f"/api/auth/invitations/{payload['token']}")
    assert details.status_code == 200
    assert details.json()["name"] == "Maria Financeiro"

    assert SessionLocal is not None
    with SessionLocal() as db:
        invitation = db.scalar(select(UserInvitation))
        invited_user = db.scalar(select(AppUser).where(AppUser.email == "maria.financeiro@example.com"))
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "security.user.invited"))
        assert invitation is not None
        assert invitation.token_digest != payload["token"]
        assert invited_user is not None and invited_user.auth_user_id.startswith("pending:")
        assert audit is not None and audit.entity_id == str(invited_user.id)


def test_admin_role_invitation_requires_reason(client):
    response = client.post(
        "/api/settings/users/invitations",
        json={"name": "Sem Motivo", "email": "sem-motivo@example.com", "role_keys": ["admin"]},
    )
    assert response.status_code == 422
    assert "justificativa" in response.json()["detail"].lower()


def test_public_signup_is_closed_after_bootstrap(client, monkeypatch):
    called = False

    async def unexpected_upstream(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Neon Auth não deve ser chamado")

    monkeypatch.setattr(auth_proxy, "_upstream_request", unexpected_upstream)
    response = client.post(
        "/api/auth/sign-up",
        json={"name": "Intruso", "email": "intruso@example.com", "password": "uma-senha-com-12"},
    )
    assert response.status_code == 403
    assert called is False
