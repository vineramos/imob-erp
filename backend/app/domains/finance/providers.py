from __future__ import annotations

import ssl
import time
from dataclasses import dataclass
from datetime import date
from threading import Lock
from typing import Any

import httpx

from app.core.config import Settings, get_settings


class BankProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderStatus:
    configured: bool
    environment: str
    client_id_configured: bool
    certificate_configured: bool
    account_header_configured: bool
    billing_api: str
    banking_api: str


class BankProvider:
    key = "base"

    def status(self) -> ProviderStatus:
        raise NotImplementedError


class InterBankProvider(BankProvider):
    """Integração Banco Inter Empresas com OAuth2 + mTLS.

    A implementação usa exclusivamente segredos do ambiente. Nenhum Client
    Secret, certificado ou chave privada é persistido no banco do ERP.
    """

    key = "inter"
    _token_cache: dict[str, tuple[str, float]] = {}
    _token_lock = Lock()

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.inter_base_url.rstrip("/")

    @property
    def billing_base(self) -> str:
        return f"{self.base_url}/cobranca/v3"

    @property
    def banking_base(self) -> str:
        return f"{self.base_url}/banking/v2"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            configured=self.settings.inter_configured,
            environment=self.settings.inter_environment.strip().lower() or "sandbox",
            client_id_configured=bool(self.settings.inter_client_id and self.settings.inter_client_secret),
            certificate_configured=bool(self.settings.inter_cert_path and self.settings.inter_key_path),
            account_header_configured=bool(self.settings.inter_account_number),
            billing_api=self.billing_base,
            banking_api=self.banking_base,
        )

    def _ssl_context(self) -> ssl.SSLContext:
        if not self.settings.inter_cert_path or not self.settings.inter_key_path:
            raise BankProviderError("Certificado mTLS do Banco Inter não configurado.")
        context = ssl.create_default_context()
        try:
            context.load_cert_chain(
                certfile=self.settings.inter_cert_path,
                keyfile=self.settings.inter_key_path,
            )
        except (OSError, ssl.SSLError) as exc:
            raise BankProviderError("Não foi possível carregar o certificado mTLS do Banco Inter.") from exc
        return context

    def _headers(self, token: str) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if self.settings.inter_account_number:
            # A referência atual do Inter usa x-conta-corrente para Cobrança
            # e documenta x-conta-corrente/x-inter-conta-corrente em Banking.
            headers["x-conta-corrente"] = self.settings.inter_account_number
            headers["x-inter-conta-corrente"] = self.settings.inter_account_number
        return headers

    def _token(self, scopes: tuple[str, ...]) -> str:
        if not self.settings.inter_configured:
            raise BankProviderError("Integração Banco Inter ainda não possui credenciais/certificado configurados.")
        scope = " ".join(sorted(set(scopes)))
        cache_key = f"{self.base_url}:{self.settings.inter_client_id}:{scope}"
        now = time.time()
        with self._token_lock:
            cached = self._token_cache.get(cache_key)
            if cached and cached[1] > now + 60:
                return cached[0]

        payload = {
            "client_id": self.settings.inter_client_id,
            "client_secret": self.settings.inter_client_secret,
            "grant_type": "client_credentials",
            "scope": scope,
        }
        try:
            with httpx.Client(verify=self._ssl_context(), timeout=30.0) as client:
                response = client.post(f"{self.base_url}/oauth/v2/token", data=payload, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise BankProviderError("Falha de comunicação ao autenticar no Banco Inter.") from exc
        if response.status_code >= 400:
            raise BankProviderError(self._error_message(response, "Banco Inter recusou a autenticação OAuth2."))
        data = response.json()
        token = str(data.get("access_token") or "")
        if not token:
            raise BankProviderError("Banco Inter não retornou access_token.")
        expires_in = max(120, int(data.get("expires_in") or 3600))
        with self._token_lock:
            self._token_cache[cache_key] = (token, now + expires_in)
        return token

    @staticmethod
    def _error_message(response: httpx.Response, fallback: str) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                detail = data.get("detail") or data.get("message") or data.get("title") or data.get("error_description")
                if detail:
                    return f"{fallback} {detail}"
        except ValueError:
            pass
        text = response.text.strip()
        return f"{fallback} {text[:300]}" if text else fallback

    def _request(
        self,
        method: str,
        url: str,
        *,
        scopes: tuple[str, ...],
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        token = self._token(scopes)
        try:
            with httpx.Client(verify=self._ssl_context(), timeout=45.0) as client:
                response = client.request(method, url, headers=self._headers(token), params=params, json=json)
        except httpx.HTTPError as exc:
            raise BankProviderError("Falha de comunicação com o Banco Inter.") from exc
        if response.status_code not in expected:
            raise BankProviderError(self._error_message(response, f"Banco Inter retornou HTTP {response.status_code}."))
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise BankProviderError("Banco Inter retornou uma resposta inválida.") from exc

    def balance(self, *, balance_date: date | None = None) -> dict[str, Any]:
        params = {"dataSaldo": balance_date.isoformat()} if balance_date else None
        return self._request(
            "GET",
            f"{self.banking_base}/saldo",
            scopes=("extrato.read",),
            params=params,
        )

    def statement(self, *, start_date: date, end_date: date, enriched: bool = True) -> dict[str, Any]:
        if (end_date - start_date).days > 90:
            raise BankProviderError("O Banco Inter limita a consulta de extrato a 90 dias por chamada.")
        endpoint = "extrato/completo" if enriched else "extrato"
        params: dict[str, Any] = {"dataInicio": start_date.isoformat(), "dataFim": end_date.isoformat()}
        if enriched:
            params.update({"pagina": 0, "tamanhoPagina": 10000})
        return self._request(
            "GET",
            f"{self.banking_base}/{endpoint}",
            scopes=("extrato.read",),
            params=params,
        )

    def issue_charge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.billing_base}/cobrancas",
            scopes=("boleto-cobranca.write",),
            json=payload,
        )

    def charge(self, provider_charge_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"{self.billing_base}/cobrancas/{provider_charge_id}",
            scopes=("boleto-cobranca.read",),
        )

    def charge_pdf(self, provider_charge_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"{self.billing_base}/cobrancas/{provider_charge_id}/pdf",
            scopes=("boleto-cobranca.read",),
        )

    def cancel_charge(self, provider_charge_id: str) -> None:
        self._request(
            "DELETE",
            f"{self.billing_base}/cobrancas/{provider_charge_id}",
            scopes=("boleto-cobranca.write",),
            expected=(204,),
        )

    def set_billing_webhook(self, webhook_url: str) -> None:
        self._request(
            "PUT",
            f"{self.billing_base}/cobrancas/webhook",
            scopes=("boleto-cobranca.write",),
            json={"webhookUrl": webhook_url},
            expected=(204,),
        )


def bank_provider(key: str) -> BankProvider:
    normalized = key.strip().lower()
    if normalized == "inter":
        return InterBankProvider()
    raise BankProviderError(f"Provedor bancário não suportado: {key}.")
