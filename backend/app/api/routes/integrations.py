import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domains.finance.providers import BankProviderError, bank_provider
from app.core.database import get_db
from app.domains.contracts.models import AdministrationContract, SignatureWebhookEvent
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.models import OrganizationSettings
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Property
from app.integrations.document_storage import DocumentStorageError, DocumentStorageStatus, get_document_storage
from app.integrations.signature import SignatureProviderError, SignatureProviderStatus, get_signature_provider

router = APIRouter(tags=["integrations"])


class SignatureIntegrationStatusResponse(BaseModel):
    provider: str
    environment: str
    configured: bool
    reachable: bool | None
    message: str
    checked_at: datetime


class BankIntegrationStatusResponse(BaseModel):
    provider: str
    environment: str
    configured: bool
    reachable: bool | None
    message: str
    checked_at: datetime


class DocumentStorageStatusResponse(BaseModel):
    provider: str
    configured: bool
    reachable: bool | None
    bucket: str | None = None
    message: str
    checked_at: datetime


class IntegrationReadinessItem(BaseModel):
    key: str
    label: str
    status: Literal["ready", "attention", "disabled"]
    selected: bool
    configured: bool
    critical: bool
    message: str
    environment: str | None = None


class IntegrationReadinessResponse(BaseModel):
    ready: bool
    pending_count: int
    items: list[IntegrationReadinessItem]


def _response(value: SignatureProviderStatus) -> SignatureIntegrationStatusResponse:
    return SignatureIntegrationStatusResponse(
        provider=value.provider,
        environment=value.environment,
        configured=value.configured,
        reachable=value.reachable,
        message=value.message,
        checked_at=value.checked_at,
    )


def _storage_response(value: DocumentStorageStatus) -> DocumentStorageStatusResponse:
    return DocumentStorageStatusResponse(
        provider=value.provider,
        configured=value.configured,
        reachable=value.reachable,
        bucket=value.bucket,
        message=value.message,
        checked_at=value.checked_at,
    )


def _selected_signature_provider(db: Session, organization_id) -> str:
    settings = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    integrations = (settings.integrations if settings else {}) or {}
    return str(integrations.get("signature_provider") or "none")


def _selected_bank_provider(db: Session, organization_id) -> str:
    settings = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    integrations = (settings.integrations if settings else {}) or {}
    return str(integrations.get("bank_provider") or "none")


def _bank_status_response(provider_key: str, *, probe: bool = False) -> BankIntegrationStatusResponse:
    checked_at = datetime.now(timezone.utc)
    if provider_key == "none":
        return BankIntegrationStatusResponse(
            provider="none", environment="disabled", configured=False, reachable=None,
            message="Nenhum provedor bancário está selecionado.", checked_at=checked_at,
        )
    try:
        provider = bank_provider(provider_key)
        provider_status = provider.status()
    except BankProviderError as exc:
        return BankIntegrationStatusResponse(
            provider=provider_key, environment="unknown", configured=False,
            reachable=False if probe else None, message=str(exc), checked_at=checked_at,
        )
    if not provider_status.configured:
        return BankIntegrationStatusResponse(
            provider=provider_key, environment=provider_status.environment, configured=False, reachable=None,
            message="Provider selecionado, mas credenciais e certificado ainda não estão configurados.", checked_at=checked_at,
        )
    if not probe:
        return BankIntegrationStatusResponse(
            provider=provider_key, environment=provider_status.environment, configured=True, reachable=None,
            message="Credenciais presentes. Execute o teste para validar autenticação e acesso bancário.", checked_at=checked_at,
        )
    try:
        provider.balance()
    except BankProviderError as exc:
        return BankIntegrationStatusResponse(
            provider=provider_key, environment=provider_status.environment, configured=True, reachable=False,
            message=str(exc), checked_at=checked_at,
        )
    return BankIntegrationStatusResponse(
        provider=provider_key, environment=provider_status.environment, configured=True, reachable=True,
        message="Autenticação, certificado e consulta bancária validados com sucesso.", checked_at=checked_at,
    )


@router.get("/integrations/readiness", response_model=IntegrationReadinessResponse)
def integrations_readiness(
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> IntegrationReadinessResponse:
    settings = get_settings()
    organization_settings = db.scalar(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == context.user.organization_id)
    )
    selected = (organization_settings.integrations if organization_settings else {}) or {}

    bank_key = str(selected.get("bank_provider") or "none")
    signature_key = str(selected.get("signature_provider") or "none")
    email_key = str(selected.get("email_provider") or "none")

    items: list[IntegrationReadinessItem] = []

    auth_configured = bool(settings.neon_auth_url.strip())
    items.append(
        IntegrationReadinessItem(
            key="auth",
            label="Neon Auth",
            status="ready" if auth_configured else "attention",
            selected=True,
            configured=auth_configured,
            critical=True,
            message=(
                "Autenticação configurada para o ambiente."
                if auth_configured
                else "NEON_AUTH_URL ainda não está configurada."
            ),
        )
    )

    storage_status = get_document_storage().status()
    items.append(
        IntegrationReadinessItem(
            key="document_storage",
            label="Storage de documentos",
            status="ready" if storage_status.configured else "attention",
            selected=True,
            configured=storage_status.configured,
            critical=True,
            message=storage_status.message,
            environment=storage_status.provider,
        )
    )

    if bank_key == "none":
        items.append(
            IntegrationReadinessItem(
                key="bank",
                label="Banco / cobrança",
                status="disabled",
                selected=False,
                configured=True,
                critical=False,
                message="Integração bancária desativada; operação manual continua disponível.",
            )
        )
    else:
        try:
            bank_status = bank_provider(bank_key).status()
            bank_configured = bank_status.configured
            bank_message = (
                "Credenciais e certificado do provider bancário estão configurados."
                if bank_configured
                else "Provider bancário selecionado, mas credenciais/certificado estão pendentes."
            )
            bank_environment = bank_status.environment
        except BankProviderError as exc:
            bank_configured = False
            bank_message = str(exc)
            bank_environment = None
        items.append(
            IntegrationReadinessItem(
                key="bank",
                label="Banco / cobrança",
                status="ready" if bank_configured else "attention",
                selected=True,
                configured=bank_configured,
                critical=False,
                message=bank_message,
                environment=bank_environment,
            )
        )

    if signature_key == "none":
        items.append(
            IntegrationReadinessItem(
                key="signature",
                label="Assinatura eletrônica",
                status="disabled",
                selected=False,
                configured=True,
                critical=False,
                message="Assinatura eletrônica desativada.",
            )
        )
    else:
        provider = get_signature_provider(signature_key)
        signature_status = provider.status() if provider is not None else None
        signature_configured = bool(
            signature_status
            and signature_status.configured
            and settings.clicksign_webhook_secret.strip()
        )
        signature_message = (
            "Access Token e HMAC Secret do webhook estão configurados."
            if signature_configured
            else (
                "Provider de assinatura selecionado; configure o Access Token e o HMAC Secret do webhook."
                if provider is not None
                else "Provider de assinatura não suportado."
            )
        )
        items.append(
            IntegrationReadinessItem(
                key="signature",
                label="Assinatura eletrônica",
                status="ready" if signature_configured else "attention",
                selected=True,
                configured=signature_configured,
                critical=False,
                message=signature_message,
                environment=signature_status.environment if signature_status else None,
            )
        )

    if email_key == "none":
        items.append(
            IntegrationReadinessItem(
                key="email",
                label="E-mail transacional",
                status="disabled",
                selected=False,
                configured=True,
                critical=False,
                message="E-mail transacional desativado.",
            )
        )
    else:
        email_configured = settings.email_smtp_configured
        items.append(
            IntegrationReadinessItem(
                key="email",
                label="E-mail transacional",
                status="ready" if email_configured else "attention",
                selected=True,
                configured=email_configured,
                critical=False,
                message=(
                    "SMTP configurado para envio operacional."
                    if email_configured
                    else "SMTP selecionado, mas host/remetente/credenciais ainda estão pendentes."
                ),
                environment="smtp",
            )
        )

    pending = [item for item in items if item.selected and not item.configured]
    return IntegrationReadinessResponse(ready=not pending, pending_count=len(pending), items=items)


@router.get("/integrations/signature/status", response_model=SignatureIntegrationStatusResponse)
def signature_status(
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> SignatureIntegrationStatusResponse:
    provider_key = _selected_signature_provider(db, context.user.organization_id)
    if provider_key == "none":
        return SignatureIntegrationStatusResponse(
            provider="none",
            environment="disabled",
            configured=False,
            reachable=None,
            message="Nenhum provedor de assinatura está selecionado.",
            checked_at=datetime.now().astimezone(),
        )
    provider = get_signature_provider(provider_key)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Provider de assinatura não suportado.")
    return _response(provider.status())


@router.get("/integrations/bank/status", response_model=BankIntegrationStatusResponse)
def bank_status(
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> BankIntegrationStatusResponse:
    return _bank_status_response(_selected_bank_provider(db, context.user.organization_id))


@router.post("/integrations/bank/test", response_model=BankIntegrationStatusResponse)
def test_bank_connection(
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> BankIntegrationStatusResponse:
    provider_key = _selected_bank_provider(db, context.user.organization_id)
    if provider_key == "none":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Selecione um provedor bancário primeiro.")
    return _bank_status_response(provider_key, probe=True)


@router.post("/integrations/signature/test", response_model=SignatureIntegrationStatusResponse)
def test_signature_connection(
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> SignatureIntegrationStatusResponse:
    provider_key = _selected_signature_provider(db, context.user.organization_id)
    if provider_key == "none":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Selecione um provedor de assinatura primeiro.")
    provider = get_signature_provider(provider_key)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Provider de assinatura não suportado.")
    return _response(provider.test_connection())


@router.get("/integrations/document-storage/status", response_model=DocumentStorageStatusResponse)
def document_storage_status(
    context: UserContext = Depends(require_permission("settings.view")),
) -> DocumentStorageStatusResponse:
    return _storage_response(get_document_storage().status())


@router.post("/integrations/document-storage/test", response_model=DocumentStorageStatusResponse)
def test_document_storage(
    context: UserContext = Depends(require_permission("settings.company.manage")),
) -> DocumentStorageStatusResponse:
    return _storage_response(get_document_storage().status(probe=True))


def _extract_envelope_id(payload: dict[str, Any]) -> str | None:
    candidates = [
        payload.get("envelope_id"),
        payload.get("envelope", {}).get("id") if isinstance(payload.get("envelope"), dict) else None,
        payload.get("data", {}).get("id") if isinstance(payload.get("data"), dict) else None,
    ]
    data = payload.get("data")
    if isinstance(data, dict):
        attributes = data.get("attributes")
        if isinstance(attributes, dict):
            candidates.extend([attributes.get("envelope_id"), attributes.get("envelope")])
        relationships = data.get("relationships")
        if isinstance(relationships, dict):
            envelope = relationships.get("envelope")
            if isinstance(envelope, dict):
                envelope_data = envelope.get("data")
                if isinstance(envelope_data, dict):
                    candidates.append(envelope_data.get("id"))
    return next(
        (str(value) for value in candidates if isinstance(value, (str, int)) and str(value).strip()),
        None,
    )


def _provider_status_from_event(event_name: str, payload: dict[str, Any]) -> str:
    event = event_name.lower()
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    if "cancel" in event or '"canceled"' in serialized or '"cancelled"' in serialized:
        return "provider_cancelled"
    if "closed" in event or "close" in event or '"closed"' in serialized:
        return "provider_closed_pending_archive"
    if "sign" in event or '"signed"' in serialized:
        return "provider_signature_progress"
    return "provider_event_received"


def _received_signature(request: Request) -> str:
    return request.headers.get("x-clicksign-signature", "").strip() or request.headers.get("content-hmac", "").strip()


def _contract_code(contract: AdministrationContract | LeaseContract) -> str:
    prefix = "LOC" if isinstance(contract, LeaseContract) else "ADM"
    return f"{prefix}-{contract.internal_number:06d}"


def _activate_lease_property(db: Session, contract: LeaseContract) -> None:
    property_item = db.scalar(
        select(Property).where(
            Property.id == contract.property_id,
            Property.organization_id == contract.organization_id,
        )
    )
    if property_item is None:
        return
    property_item.status = "leased"
    property_item.publication_enabled = False


def _try_auto_archive(db: Session, contract: AdministrationContract | LeaseContract) -> None:
    """Best effort: falha de infraestrutura mantém pendência e nunca perde o webhook."""
    if not contract.signing_envelope_id or not contract.signing_document_id:
        contract.archive_status = "archive_failed"
        contract.signing_status = "archive_failed"
        return
    provider = get_signature_provider(contract.signing_provider)
    storage = get_document_storage()
    if provider is None or not provider.configured:
        contract.archive_status = "provider_not_configured"
        return
    if not storage.configured:
        contract.archive_status = "storage_not_configured"
        return

    code = _contract_code(contract)
    try:
        final_pdf = provider.signed_document_bytes(contract.signing_envelope_id, contract.signing_document_id)
        final_hash = hashlib.sha256(final_pdf).hexdigest()
        object_name = storage.object_name(
            organization_id=str(contract.organization_id),
            contract_code=code,
            filename=f"{code}-v{contract.current_version}-ASSINADO.pdf",
        )
        reference = storage.upload_bytes(object_name=object_name, content=final_pdf, content_type="application/pdf")
    except (SignatureProviderError, DocumentStorageError):
        contract.archive_status = "archive_failed"
        contract.signing_status = "archive_failed"
        return

    now = datetime.now(timezone.utc)
    contract.archived_document_reference = reference
    contract.final_document_hash = final_hash
    contract.archived_at = now
    contract.signed_at = now
    contract.archive_status = "archived"
    contract.signing_status = "signed_archived"
    contract.status = "signed"
    if isinstance(contract, LeaseContract):
        _activate_lease_property(db, contract)


@router.post("/webhooks/clicksign", status_code=status.HTTP_200_OK)
async def clicksign_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    settings = get_settings()
    secret = settings.clicksign_webhook_secret.strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook Clicksign ainda não possui HMAC Secret configurado.",
        )

    raw_body = await request.body()
    received_hmac = _received_signature(request)
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    received_digest = received_hmac.removeprefix("sha256=")
    if not (bool(received_digest) and hmac.compare_digest(received_digest.lower(), expected.lower())):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura HMAC do webhook inválida.")

    event_name = request.headers.get("event", "unknown")[:120]
    event_fingerprint = hashlib.sha256(event_name.encode("utf-8") + b"\0" + raw_body).hexdigest()
    if db.scalar(select(SignatureWebhookEvent.id).where(SignatureWebhookEvent.event_fingerprint == event_fingerprint)) is not None:
        return {"status": "accepted_duplicate"}

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Payload JSON inválido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload do webhook deve ser um objeto JSON.")

    envelope_id = _extract_envelope_id(payload)
    administration_contract: AdministrationContract | None = None
    lease_contract: LeaseContract | None = None

    if envelope_id:
        administration_contract = db.scalar(
            select(AdministrationContract).where(AdministrationContract.signing_envelope_id == envelope_id)
        )
        if administration_contract is None:
            lease_contract = db.scalar(
                select(LeaseContract).where(LeaseContract.signing_envelope_id == envelope_id)
            )

        contract = administration_contract or lease_contract
        if contract is not None:
            contract.signing_status = _provider_status_from_event(event_name, payload)
            if contract.signing_status == "provider_closed_pending_archive":
                contract.archive_status = "pending"
                _try_auto_archive(db, contract)

    db.add(
        SignatureWebhookEvent(
            provider="clicksign",
            event_name=event_name,
            event_fingerprint=event_fingerprint,
            envelope_id=envelope_id,
            contract_id=administration_contract.id if administration_contract else None,
            lease_contract_id=lease_contract.id if lease_contract else None,
            payload=payload,
            hmac_valid=True,
        )
    )
    db.commit()
    return {"status": "accepted"}
