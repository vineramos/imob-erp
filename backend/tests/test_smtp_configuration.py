from sqlalchemy import select

from app.api.routes import integrations as integration_routes
from app.core.database import SessionLocal
from app.domains.foundation.models import AuditLog, OrganizationIntegrationCredential


def test_smtp_credentials_are_encrypted_masked_and_testable(client, identity, monkeypatch):
    password = "senha-super-secreta-123"
    response = client.put(
        "/api/integrations/email/config",
        json={
            "host": "smtp.example.com",
            "port": 587,
            "username": "mailer@example.com",
            "password": password,
            "from_email": "mailer@example.com",
            "from_name": "Imob Testes",
            "use_tls": True,
            "use_ssl": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["password_configured"] is True
    assert "password" not in body

    assert SessionLocal is not None
    with SessionLocal() as db:
        row = db.scalar(select(OrganizationIntegrationCredential).where(
            OrganizationIntegrationCredential.organization_id == identity["organization_id"],
            OrganizationIntegrationCredential.provider == "smtp",
        ))
        assert row is not None
        assert row.encrypted_secret
        assert password not in row.encrypted_secret
        assert password not in str(row.non_secret_config)
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "settings.integrations.smtp.updated"))
        assert audit is not None
        assert password not in str(audit.after_data)
        assert password not in str(audit.before_data)

    sent = {}

    def fake_send(**kwargs):
        sent.update(kwargs)

    monkeypatch.setattr(integration_routes, "send_email_message", fake_send)
    tested = client.post("/api/integrations/email/test", json={"recipient": "admin@example.com"})
    assert tested.status_code == 200, tested.text
    assert tested.json()["reachable"] is True
    assert sent["config"].password == password
    assert sent["recipient"] == "admin@example.com"


def test_smtp_update_keeps_existing_password_when_blank(client):
    payload = {
        "host": "smtp.example.com", "port": 465, "username": "mailer@example.com",
        "password": "primeira-senha-segura", "from_email": "mailer@example.com",
        "from_name": "Imob", "use_tls": False, "use_ssl": True,
    }
    assert client.put("/api/integrations/email/config", json=payload).status_code == 200
    payload["password"] = None
    payload["from_name"] = "Imob Atualizado"
    response = client.put("/api/integrations/email/config", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["password_configured"] is True
