import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.domains.contracts.models import AdministrationContract, SignatureWebhookEvent
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.models import OrganizationSettings
from app.integrations.signature import SignatureProviderStatus, get_signature_provider

router = APIRouter(tags=["integrations"])


class SignatureIntegrationStatusResponse(BaseModel):
    provider: str
    environment: str
    configured: bool
    reachable: bool | None
    message: str
    checked_at: datetime


def _response(value: SignatureProviderStatus) -> SignatureIntegrationStatusResponse:
    return SignatureIntegrationStatusResponse(
        provider=value.provider,
        environment=value.environment,
        configured=value.configured,
        reachable=value.reachable,
        message=value.message,
        checked_at=value.checked_at,
    )


def _selected_signature_provider(db: Session, organization_id) -> str:
    settings = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    integrations = (settings.integrations if settings else {}) or {}
    return str(integrations.get("signature_provider") or "none")


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
    return next((str(value) for value in candidates if isinstance(value, (str, int)) and str(value).strip()), None)


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


@router.post("/webhooks/clicksign", status_code=status.HTTP_202_ACCEPTED)
async def clicksign_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    settings = get_settings()
    secret = settings.clicksign_webhook_secret.strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook Clicksign ainda não possui HMAC Secret configurado.",
        )

    raw_body = await request.body()
    received_hmac = request.headers.get("content-hmac", "").strip()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    received_digest = received_hmac.removeprefix("sha256=")
    hmac_valid = bool(received_digest) and hmac.compare_digest(received_digest.lower(), expected.lower())
    if not hmac_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura HMAC do webhook inválida.")

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload JSON inválido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload do webhook deve ser um objeto JSON.")

    event_name = request.headers.get("event", "unknown")[:120]
    envelope_id = _extract_envelope_id(payload)
    contract = None
    if envelope_id:
        contract = db.scalar(select(AdministrationContract).where(AdministrationContract.signing_envelope_id == envelope_id))
        if contract is not None:
            contract.signing_status = _provider_status_from_event(event_name, payload)

    db.add(
        SignatureWebhookEvent(
            provider="clicksign",
            event_name=event_name,
            envelope_id=envelope_id,
            contract_id=contract.id if contract else None,
            payload=payload,
            hmac_valid=True,
        )
    )
    db.commit()
    return {"status": "accepted"}
