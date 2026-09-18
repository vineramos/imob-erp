from tests.helpers import assert_response


def test_health_readiness_checks_database(client):
    payload = assert_response(client.get("/api/health/ready")).json()
    assert payload["status"] == "ready"
    assert payload["service"] == "imob-erp-api"
    assert payload["database"] == "ok"
    assert payload["release"]


def test_integration_readiness_exposes_configuration_without_secrets(client):
    payload = assert_response(client.get("/api/integrations/readiness")).json()

    assert isinstance(payload["ready"], bool)
    assert payload["pending_count"] >= 1

    by_key = {item["key"]: item for item in payload["items"]}
    assert {"auth", "document_storage", "bank", "signature", "email"} <= set(by_key)
    assert by_key["document_storage"]["configured"] is True
    assert by_key["signature"]["selected"] is True
    assert by_key["signature"]["configured"] is False

    serialized = str(payload).lower()
    for forbidden in ("access_token", "client_secret", "smtp_password", "webhook_secret"):
        assert forbidden not in serialized
