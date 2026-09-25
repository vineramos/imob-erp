from dataclasses import dataclass

from app.api.routes import integrations as integrations_routes
from app.domains.finance.providers import BankProviderError, ProviderStatus
from tests.helpers import assert_response


@dataclass
class FakeBankProvider:
    reachable: bool = True

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            configured=True,
            environment="sandbox",
            client_id_configured=True,
            certificate_configured=True,
            account_header_configured=True,
            billing_api="https://bank.invalid/billing",
            banking_api="https://bank.invalid/banking",
        )

    def balance(self) -> dict:
        if not self.reachable:
            raise BankProviderError("Falha controlada ao consultar o banco.")
        return {"disponivel": 1000}


def test_bank_status_does_not_probe_external_provider(client, monkeypatch):
    provider = FakeBankProvider()
    monkeypatch.setattr(integrations_routes, "_selected_bank_provider", lambda _db, _organization_id: "inter")
    monkeypatch.setattr(integrations_routes, "bank_provider", lambda _key: provider)

    response = assert_response(client.get("/api/integrations/bank/status")).json()

    assert response["provider"] == "inter"
    assert response["configured"] is True
    assert response["reachable"] is None
    assert "Execute o teste" in response["message"]


def test_bank_connection_probe_reports_success_without_exposing_secrets(client, monkeypatch):
    provider = FakeBankProvider()
    monkeypatch.setattr(integrations_routes, "_selected_bank_provider", lambda _db, _organization_id: "inter")
    monkeypatch.setattr(integrations_routes, "bank_provider", lambda _key: provider)

    response = assert_response(client.post("/api/integrations/bank/test")).json()

    assert response["reachable"] is True
    assert response["environment"] == "sandbox"
    assert set(response) == {"provider", "environment", "configured", "reachable", "message", "checked_at"}


def test_bank_connection_probe_returns_operational_failure(client, monkeypatch):
    provider = FakeBankProvider(reachable=False)
    monkeypatch.setattr(integrations_routes, "_selected_bank_provider", lambda _db, _organization_id: "inter")
    monkeypatch.setattr(integrations_routes, "bank_provider", lambda _key: provider)

    response = assert_response(client.post("/api/integrations/bank/test")).json()

    assert response["configured"] is True
    assert response["reachable"] is False
    assert response["message"] == "Falha controlada ao consultar o banco."
