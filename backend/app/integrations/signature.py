from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class SignatureProviderStatus:
    provider: str
    environment: str
    configured: bool
    reachable: bool | None
    message: str
    checked_at: datetime


class SignatureProviderError(RuntimeError):
    pass


class ClicksignProvider:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.clicksign_base_url.rstrip("/")
        self.token = self.settings.clicksign_access_token.strip()
        self.environment = self.settings.clicksign_environment.strip().lower() or "sandbox"

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise SignatureProviderError("Access Token da Clicksign ainda não foi configurado no Secret Manager.")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }

    def status(self) -> SignatureProviderStatus:
        if not self.configured:
            return SignatureProviderStatus(
                provider="clicksign",
                environment=self.environment,
                configured=False,
                reachable=None,
                message="Clicksign selecionada, mas o Access Token ainda não está configurado.",
                checked_at=datetime.now(timezone.utc),
            )
        return SignatureProviderStatus(
            provider="clicksign",
            environment=self.environment,
            configured=True,
            reachable=None,
            message="Credencial presente. Execute o teste de conexão para validar o ambiente.",
            checked_at=datetime.now(timezone.utc),
        )

    def test_connection(self) -> SignatureProviderStatus:
        if not self.configured:
            return self.status()
        try:
            with httpx.Client(timeout=12.0) as client:
                response = client.get(
                    f"{self.base_url}/envelopes",
                    params={"page[size]": 1},
                    headers=self._headers(),
                )
            if response.status_code == 200:
                return SignatureProviderStatus(
                    provider="clicksign",
                    environment=self.environment,
                    configured=True,
                    reachable=True,
                    message="Conexão autenticada com a Clicksign com sucesso.",
                    checked_at=datetime.now(timezone.utc),
                )
            detail = _safe_response_detail(response)
            return SignatureProviderStatus(
                provider="clicksign",
                environment=self.environment,
                configured=True,
                reachable=False,
                message=f"Clicksign respondeu HTTP {response.status_code}: {detail}",
                checked_at=datetime.now(timezone.utc),
            )
        except httpx.HTTPError as exc:
            return SignatureProviderStatus(
                provider="clicksign",
                environment=self.environment,
                configured=True,
                reachable=False,
                message=f"Não foi possível alcançar a Clicksign: {exc.__class__.__name__}.",
                checked_at=datetime.now(timezone.utc),
            )

    def create_empty_envelope(self, name: str) -> str:
        """Cria apenas o envelope. Documentos/signatários são adicionados em etapas posteriores."""
        payload = {
            "data": {
                "type": "envelopes",
                "attributes": {"name": name},
            }
        }
        with httpx.Client(timeout=15.0) as client:
            response = client.post(f"{self.base_url}/envelopes", headers=self._headers(), json=payload)
        if response.status_code not in {200, 201}:
            raise SignatureProviderError(
                f"Falha ao criar envelope Clicksign (HTTP {response.status_code}): {_safe_response_detail(response)}"
            )
        data = response.json()
        envelope_id = _extract_resource_id(data)
        if not envelope_id:
            raise SignatureProviderError("A Clicksign criou o envelope, mas não retornou um identificador reconhecível.")
        return envelope_id


def get_signature_provider(provider_key: str):
    if provider_key == "clicksign":
        return ClicksignProvider()
    return None


def _extract_resource_id(payload: dict) -> str | None:
    data = payload.get("data")
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    envelope = payload.get("envelope")
    if isinstance(envelope, dict) and envelope.get("id"):
        return str(envelope["id"])
    return None


def _safe_response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            if payload.get("message"):
                return str(payload["message"])[:300]
            errors = payload.get("errors")
            if isinstance(errors, list) and errors:
                return str(errors[0])[:300]
        return str(payload)[:300]
    except ValueError:
        return (response.text or "resposta sem detalhes").strip()[:300]
