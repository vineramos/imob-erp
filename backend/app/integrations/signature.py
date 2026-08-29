from __future__ import annotations

import base64
import re
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
                response = client.get(f"{self.base_url}/envelopes", params={"page[size]": 1}, headers=self._headers())
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
        payload = {
            "data": {
                "type": "envelopes",
                "attributes": {
                    "name": name,
                    "locale": "pt-BR",
                    "auto_close": True,
                    "remind_interval": 3,
                    "block_after_refusal": True,
                },
            }
        }
        return self._post_resource("/envelopes", payload, expected={200, 201}, resource_name="envelope")

    def upload_pdf(self, envelope_id: str, *, filename: str, content: bytes, metadata: dict | None = None) -> str:
        encoded = base64.b64encode(content).decode("ascii")
        payload = {
            "data": {
                "type": "documents",
                "attributes": {
                    "filename": filename,
                    "content_base64": f"data:application/pdf;base64,{encoded}",
                    "metadata": metadata or {},
                },
            }
        }
        return self._post_resource(
            f"/envelopes/{envelope_id}/documents",
            payload,
            expected={200, 201},
            resource_name="documento",
        )

    def create_signer(self, envelope_id: str, signer: dict) -> str:
        communication = str(signer.get("communication") or "email")
        phone = _digits(str(signer.get("phone") or "")) or None
        document = _digits(str(signer.get("document_number") or "")) or None
        attributes: dict = {
            "name": str(signer.get("name") or "").strip(),
            "email": str(signer.get("email") or "").strip().lower(),
            "phone_number": phone,
            "has_documentation": bool(document),
            "refusable": False,
            "group": int(signer.get("sign_order") or 1),
            "communicate_events": {
                "document_signed": "email",
                "signature_request": communication,
                "signature_reminder": "email" if communication != "none" else "none",
            },
        }
        if document:
            attributes["documentation"] = document
        payload = {"data": {"type": "signers", "attributes": attributes}}
        return self._post_resource(
            f"/envelopes/{envelope_id}/signers",
            payload,
            expected={200, 201},
            resource_name="signatário",
        )

    def create_signature_requirements(self, envelope_id: str, *, document_id: str, signer_id: str, role: str) -> None:
        qualification_role = "witness" if role == "witness" else "sign"
        relationships = {
            "document": {"data": {"type": "documents", "id": document_id}},
            "signer": {"data": {"type": "signers", "id": signer_id}},
        }
        qualification = {
            "data": {
                "type": "requirements",
                "attributes": {"action": "agree", "role": qualification_role},
                "relationships": relationships,
            }
        }
        authentication = {
            "data": {
                "type": "requirements",
                "attributes": {"action": "provide_evidence", "auth": "email"},
                "relationships": relationships,
            }
        }
        self._post_no_id(f"/envelopes/{envelope_id}/requirements", qualification, expected={200, 201})
        self._post_no_id(f"/envelopes/{envelope_id}/requirements", authentication, expected={200, 201})

    def activate_envelope(self, envelope_id: str) -> None:
        with httpx.Client(timeout=18.0) as client:
            response = client.post(f"{self.base_url}/envelopes/{envelope_id}/activate", headers=self._headers())
        if response.status_code not in {200, 202, 204}:
            raise SignatureProviderError(
                f"Falha ao ativar envelope Clicksign (HTTP {response.status_code}): {_safe_response_detail(response)}"
            )

    def signed_document_bytes(self, envelope_id: str, document_id: str) -> bytes:
        with httpx.Client(timeout=18.0) as client:
            response = client.get(
                f"{self.base_url}/envelopes/{envelope_id}/documents/{document_id}",
                headers=self._headers(),
            )
        if response.status_code != 200:
            raise SignatureProviderError(
                f"Falha ao consultar documento final Clicksign (HTTP {response.status_code}): {_safe_response_detail(response)}"
            )
        try:
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            links = data.get("links") if isinstance(data, dict) else None
            files = links.get("files") if isinstance(links, dict) else None
            signed_url = files.get("signed") if isinstance(files, dict) else None
        except (TypeError, ValueError):
            signed_url = None
        if not signed_url:
            raise SignatureProviderError("Documento final assinado ainda não está disponível para download na Clicksign.")
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                file_response = client.get(str(signed_url))
            file_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SignatureProviderError(f"Falha ao baixar PDF final assinado: {exc.__class__.__name__}.") from exc
        if not file_response.content.startswith(b"%PDF"):
            raise SignatureProviderError("A Clicksign não retornou um PDF válido para arquivamento.")
        return file_response.content

    def _post_resource(self, path: str, payload: dict, *, expected: set[int], resource_name: str) -> str:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(f"{self.base_url}{path}", headers=self._headers(), json=payload)
        if response.status_code not in expected:
            raise SignatureProviderError(
                f"Falha ao criar {resource_name} Clicksign (HTTP {response.status_code}): {_safe_response_detail(response)}"
            )
        resource_id = _extract_resource_id(response.json())
        if not resource_id:
            raise SignatureProviderError(f"A Clicksign criou {resource_name}, mas não retornou um identificador reconhecível.")
        return resource_id

    def _post_no_id(self, path: str, payload: dict, *, expected: set[int]) -> None:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(f"{self.base_url}{path}", headers=self._headers(), json=payload)
        if response.status_code not in expected:
            raise SignatureProviderError(
                f"Falha ao configurar requisito Clicksign (HTTP {response.status_code}): {_safe_response_detail(response)}"
            )


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


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)
