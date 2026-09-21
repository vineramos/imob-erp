import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domains.finance.providers import BankProviderError, bank_provider
from app.core.database import get_db
from app.domains.contracts.models import AdministrationContract, SignatureWebhookEvent
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization, OrganizationIntegrationCredential, OrganizationSettings
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Property
from app.integrations.document_storage import DocumentStorageError, DocumentStorageStatus, get_document_storage
from app.integrations.signature import SignatureProviderError, SignatureProviderStatus, get_signature_provider
from app.integrations.credential_crypto import CredentialCryptoError, encrypt_secret
from app.integrations.email import EmailDeliveryError, SmtpConfig, send_email_message, smtp_config_for_organization

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


class SmtpConfigurationResponse(BaseModel):
    host: str = ""
    port: int = 587
    username: str = ""
    from_email: str = ""
    from_name: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    password_configured: bool = False
    source: Literal["erp", "environment", "none"] = "none"


class SmtpConfigurationUpdate(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(default="", max_length=255)
    password: str | None = Field(default=None, max_length=500)
    from_email: EmailStr
    from_name: str = Field(default="", max_length=160)
    use_tls: bool = True
    use_ssl: bool = False

    @model_validator(mode="after")
    def validate_security_mode(self):
        if self.use_tls and self.use_ssl:
            raise ValueError("Escolha TLS ou SSL, não os dois ao mesmo tempo.")
        return self


class SmtpTestRequest(BaseModel):
    recipient: EmailStr | None = None


class SmtpTestResponse(BaseModel):
    configured: bool
    reachable: bool
    message: str
    recipient: str
    checked_at: datetime


def _smtp_row(db: Session, organization_id) -> OrganizationIntegrationCredential | None:
    return db.scalar(select(OrganizationIntegrationCredential).where(
        OrganizationIntegrationCredential.organization_id == organization_id,
        OrganizationIntegrationCredential.provider == "smtp",
    ))


def _smtp_response(db: Session, organization_id) -> SmtpConfigurationResponse:
    row = _smtp_row(db, organization_id)
    if row is not None:
        value = dict(row.non_secret_config or {})
        return SmtpConfigurationResponse(
            host=str(value.get("host") or ""), port=int(value.get("port") or 587),
            username=str(value.get("username") or ""), from_email=str(value.get("from_email") or ""),
            from_name=str(value.get("from_name") or ""), use_tls=bool(value.get("use_tls", True)),
            use_ssl=bool(value.get("use_ssl", False)), password_configured=bool(row.encrypted_secret), source="erp",
        )
    environment = get_settings()
    if environment.email_smtp_configured:
        return SmtpConfigurationResponse(
            host=environment.email_smtp_host, port=environment.email_smtp_port,
            username=environment.email_smtp_username, from_email=environment.email_smtp_from_email,
            from_name=environment.email_smtp_from_name, use_tls=environment.email_smtp_use_tls,
            use_ssl=environment.email_smtp_use_ssl, password_configured=bool(environment.email_smtp_password),
            source="environment",
        )
    return SmtpConfigurationResponse()


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
        try:
            email_configured = smtp_config_for_organization(db, context.user.organization_id).configured
        except EmailDeliveryError:
            email_configured = False
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


@router.get("/integrations/email/config", response_model=SmtpConfigurationResponse)
def get_smtp_configuration(
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> SmtpConfigurationResponse:
    return _smtp_response(db, context.user.organization_id)


@router.put("/integrations/email/config", response_model=SmtpConfigurationResponse)
def update_smtp_configuration(
    payload: SmtpConfigurationUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> SmtpConfigurationResponse:
    row = _smtp_row(db, context.user.organization_id)
    before = _smtp_response(db, context.user.organization_id).model_dump(mode="json")
    if row is None:
        row = OrganizationIntegrationCredential(
            organization_id=context.user.organization_id,
            provider="smtp",
            non_secret_config={},
            updated_by_user_id=context.user.id,
        )
        db.add(row)
        db.flush()
    if payload.username.strip() and not ((payload.password or "").strip() or row.encrypted_secret):
        raise HTTPException(status_code=422, detail="Informe a senha SMTP para o usuário configurado.")
    if payload.password is not None and payload.password.strip():
        try:
            row.encrypted_secret = encrypt_secret(
                payload.password,
                scope=f"{context.user.organization_id}:smtp",
            )
        except CredentialCryptoError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    row.non_secret_config = {
        "host": payload.host.strip(), "port": payload.port, "username": payload.username.strip(),
        "from_email": str(payload.from_email).strip().lower(), "from_name": payload.from_name.strip(),
        "use_tls": payload.use_tls, "use_ssl": payload.use_ssl,
    }
    row.updated_by_user_id = context.user.id
    after = {**row.non_secret_config, "password_configured": bool(row.encrypted_secret)}
    safe_before = {**before, "password_configured": before["password_configured"]}
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db, context=context, action="settings.integrations.smtp.updated", module="settings",
        entity_type="organization_integration_credential", entity_id=str(row.id),
        before_data=safe_before, after_data=after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return _smtp_response(db, context.user.organization_id)


@router.post("/integrations/email/test", response_model=SmtpTestResponse)
def test_smtp_configuration(
    payload: SmtpTestRequest,
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> SmtpTestResponse:
    recipient = str(payload.recipient or context.user.email).strip().lower()
    organization = db.get(Organization, context.user.organization_id)
    organization_name = organization.display_name if organization else "Imob ERP"
    try:
        config = smtp_config_for_organization(db, context.user.organization_id)
        send_email_message(
            recipient=recipient,
            subject=f"{organization_name} · Teste de e-mail",
            text_body="Configuração SMTP validada com sucesso. O ERP já pode enviar comunicações operacionais.",
            organization_name=organization_name,
            config=config,
        )
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SmtpTestResponse(
        configured=True, reachable=True, message="E-mail de teste enviado com sucesso.",
        recipient=recipient, checked_at=datetime.now(timezone.utc),
    )


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
