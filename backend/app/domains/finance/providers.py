from __future__ import annotations

import ssl
import time
import uuid
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


@dataclass(frozen=True)
class ProviderCapabilities:
    statement: bool = False
    balance: bool = False
    billing: bool = False
    pix_payment: bool = False


@dataclass(frozen=True)
class ProviderPaymentResult:
    reference: str
    status: str
    raw: dict[str, Any]


class BankProvider:
    """Contrato de integração bancária opcional.

    O ERP funciona sem provider. Um provider apenas adiciona automações (extrato,
    saldo, cobrança ou pagamento) à conta bancária cadastrada no núcleo.
    """

    key = "base"

    def status(self) -> ProviderStatus:
        raise NotImplementedError

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def balance(self, *, balance_date: date | None = None) -> dict[str, Any]:
        raise BankProviderError(f"O provider {self.key} não oferece consulta automática de saldo.")

    def statement(self, *, start_date: date, end_date: date, enriched: bool = True) -> dict[str, Any]:
        raise BankProviderError(f"O provider {self.key} não oferece consulta automática de extrato.")

    def pix_payment(
        self,
        *,
        amount: float,
        payment_date: date,
        description: str,
        pix_key: str,
        idempotency_key: str | None = None,
    ) -> ProviderPaymentResult:
        raise BankProviderError(f"O provider {self.key} não oferece pagamento Pix pela API.")

    def pix_payment_status(self, reference: str) -> ProviderPaymentResult:
        raise BankProviderError(f"O provider {self.key} não oferece consulta de pagamento Pix.")


class ManualBankProvider(BankProvider):
    """Provider neutro para qualquer banco sem integração direta."""

    key = "manual"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            configured=True,
            environment="manual",
            client_id_configured=False,
            certificate_configured=False,
            account_header_configured=False,
            billing_api="",
            banking_api="",
        )


class InterBankProvider(BankProvider):
    """Integração Banco Inter Empresas com OAuth2 + mTLS.

    É apenas uma implementação do contrato bancário. Nenhuma regra de negócio do
    ERP depende do Inter e nenhum segredo é persistido no banco do ERP.
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

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(statement=True, balance=True, billing=True, pix_payment=True)

    def _ssl_context(self) -> ssl.SSLContext:
        if not self.settings.inter_cert_path or not self.settings.inter_key_path:
            raise BankProviderError("Certificado mTLS do Banco Inter não configurado.")
        context = ssl.create_default_context()
        try:
            context.load_cert_chain(certfile=self.settings.inter_cert_path, keyfile=self.settings.inter_key_path)
        except (OSError, ssl.SSLError) as exc:
            raise BankProviderError("Não foi possível carregar o certificado mTLS do Banco Inter.") from exc
        return context

    def _headers(self, token: str) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if self.settings.inter_account_number:
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
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        token = self._token(scopes)
        headers = self._headers(token)
        headers.update(extra_headers or {})
        try:
            with httpx.Client(verify=self._ssl_context(), timeout=45.0) as client:
                response = client.request(method, url, headers=headers, params=params, json=json)
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
        return self._request("GET", f"{self.banking_base}/saldo", scopes=("extrato.read",), params=params)

    def statement(self, *, start_date: date, end_date: date, enriched: bool = True) -> dict[str, Any]:
        if (end_date - start_date).days > 90:
            raise BankProviderError("O Banco Inter limita a consulta de extrato a 90 dias por chamada.")
        endpoint = "extrato/completo" if enriched else "extrato"
        params: dict[str, Any] = {"dataInicio": start_date.isoformat(), "dataFim": end_date.isoformat()}
        if enriched:
            params.update({"pagina": 0, "tamanhoPagina": 10000})
        return self._request("GET", f"{self.banking_base}/{endpoint}", scopes=("extrato.read",), params=params)

    def issue_charge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"{self.billing_base}/cobrancas", scopes=("boleto-cobranca.write",), json=payload)

    def charge(self, provider_charge_id: str) -> dict[str, Any]:
        return self._request("GET", f"{self.billing_base}/cobrancas/{provider_charge_id}", scopes=("boleto-cobranca.read",))

    def charge_pdf(self, provider_charge_id: str) -> dict[str, Any]:
        return self._request("GET", f"{self.billing_base}/cobrancas/{provider_charge_id}/pdf", scopes=("boleto-cobranca.read",))

    def cancel_charge(self, provider_charge_id: str) -> None:
        self._request("DELETE", f"{self.billing_base}/cobrancas/{provider_charge_id}", scopes=("boleto-cobranca.write",), expected=(204,))

    def set_billing_webhook(self, webhook_url: str) -> None:
        self._request("PUT", f"{self.billing_base}/cobrancas/webhook", scopes=("boleto-cobranca.write",), json={"webhookUrl": webhook_url}, expected=(204,))

    def pix_payment(
        self,
        *,
        amount: float,
        payment_date: date,
        description: str,
        pix_key: str,
        idempotency_key: str | None = None,
    ) -> ProviderPaymentResult:
        idempotency = idempotency_key or str(uuid.uuid4())
        payload = {
            "valor": round(float(amount), 2),
            "dataPagamento": payment_date.isoformat(),
            "descricao": description[:140],
            "destinatario": {"tipo": "CHAVE", "chave": pix_key},
        }
        data = self._request(
            "POST",
            f"{self.banking_base}/pix",
            scopes=("pagamento-pix.write",),
            json=payload,
            extra_headers={"x-id-idempotente": idempotency},
        )
        reference = str((data or {}).get("codigoSolicitacao") or "").strip()
        if not reference:
            raise BankProviderError("Banco Inter não retornou o código da solicitação do Pix.")
        status = str((data or {}).get("tipoRetorno") or "SOLICITADO").upper()
        return ProviderPaymentResult(reference=reference, status=status, raw=dict(data or {}))

    def pix_payment_status(self, reference: str) -> ProviderPaymentResult:
        data = self._request("GET", f"{self.banking_base}/pix/{reference}", scopes=("pagamento-pix.read",))
        transaction = (data or {}).get("transacaoPix") if isinstance((data or {}).get("transacaoPix"), dict) else {}
        status = str(transaction.get("status") or (data or {}).get("status") or "DESCONHECIDO").upper()
        resolved_reference = str(transaction.get("codigoSolicitacao") or reference)
        return ProviderPaymentResult(reference=resolved_reference, status=status, raw=dict(data or {}))


def bank_provider(key: str) -> BankProvider:
    normalized = (key or "manual").strip().lower()
    if normalized in {"", "manual", "none"}:
        return ManualBankProvider()
    if normalized == "inter":
        return InterBankProvider()
    raise BankProviderError(f"Provedor bancário não suportado: {key}.")
