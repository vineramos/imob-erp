from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.communications.models import CommunicationMessage
from app.domains.foundation.models import OrganizationIntegrationCredential
from app.domains.portfolio.models import Person
from app.domains.portfolio.site_models import CommercialActivity, PublicSiteInquiry
from app.integrations.credential_crypto import CredentialCryptoError, decrypt_secret, encrypt_secret

router = APIRouter(tags=["whatsapp"])
PROVIDER = "whatsapp_meta"
DEFAULT_GRAPH_VERSION = "v26.0"


class WhatsAppConfigurationResponse(BaseModel):
    provider: str = PROVIDER
    graph_version: str = DEFAULT_GRAPH_VERSION
    business_account_id: str = ""
    phone_number_id: str = ""
    display_phone_number: str = ""
    token_configured: bool = False
    verify_token_configured: bool = False
    app_secret_configured: bool = False
    configured: bool = False
    webhook_url: str = ""
    checked_at: datetime | None = None
    reachable: bool | None = None
    message: str = ""
    last_webhook_at: datetime | None = None
    last_webhook_status: str = "never"
    last_webhook_message_count: int = 0
    last_webhook_error: str = ""


class WhatsAppConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    graph_version: str = Field(default=DEFAULT_GRAPH_VERSION, pattern=r"^v\d+\.\d+$", max_length=16)
    business_account_id: str = Field(default="", max_length=120)
    phone_number_id: str = Field(min_length=1, max_length=120)
    display_phone_number: str = Field(default="", max_length=40)
    access_token: str | None = Field(default=None, max_length=1000)
    verify_token: str | None = Field(default=None, max_length=300)
    app_secret: str | None = Field(default=None, max_length=500)


class WhatsAppTestResponse(BaseModel):
    configured: bool
    reachable: bool
    verified_name: str | None = None
    display_phone_number: str | None = None
    message: str
    checked_at: datetime


class WhatsAppReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4096)


def _row(db: Session, organization_id: UUID) -> OrganizationIntegrationCredential | None:
    return db.scalar(
        select(OrganizationIntegrationCredential).where(
            OrganizationIntegrationCredential.organization_id == organization_id,
            OrganizationIntegrationCredential.provider == PROVIDER,
        )
    )


def _secrets(row: OrganizationIntegrationCredential | None, organization_id: UUID) -> dict[str, str]:
    if row is None or not row.encrypted_secret:
        return {}
    try:
        raw = decrypt_secret(row.encrypted_secret, scope=f"{organization_id}:{PROVIDER}")
        value = json.loads(raw)
    except (CredentialCryptoError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Não foi possível abrir as credenciais protegidas do WhatsApp.") from exc
    return value if isinstance(value, dict) else {}


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _extract_inbound_messages(payload: dict) -> list[dict]:
    result: list[dict] = []
    if payload.get("object") != "whatsapp_business_account":
        return result
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            contacts = {
                str(item.get("wa_id") or ""): str(((item.get("profile") or {}).get("name") or "")).strip()
                for item in (value.get("contacts") or [])
                if isinstance(item, dict)
            }
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                message_id = str(message.get("id") or "").strip()
                sender = _digits(str(message.get("from") or ""))
                if not message_id or not sender:
                    continue
                kind = str(message.get("type") or "unknown")
                body = ""
                if kind == "text":
                    body = str(((message.get("text") or {}).get("body") or "")).strip()
                elif kind == "button":
                    body = str(((message.get("button") or {}).get("text") or "")).strip()
                elif kind == "interactive":
                    interactive = message.get("interactive") or {}
                    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    body = str(reply.get("title") or reply.get("id") or "").strip()
                else:
                    body = f"[Mensagem do WhatsApp: {kind}]"
                result.append({
                    "id": message_id,
                    "from": sender,
                    "name": contacts.get(sender) or f"WhatsApp {sender[-4:]}",
                    "body": body or "[Mensagem sem texto]",
                    "type": kind,
                    "timestamp": str(message.get("timestamp") or ""),
                })
    return result


def _find_person_by_phone(db: Session, organization_id: UUID, phone: str) -> Person | None:
    return db.scalar(
        select(Person).where(
            Person.organization_id == organization_id,
            Person.is_active.is_(True),
            func.regexp_replace(func.coalesce(Person.phone, ""), r"\D", "", "g") == phone,
        ).limit(1)
    )


def _find_inquiry_by_phone(db: Session, organization_id: UUID, phone: str) -> PublicSiteInquiry | None:
    active = db.scalar(
        select(PublicSiteInquiry).where(
            PublicSiteInquiry.organization_id == organization_id,
            func.regexp_replace(func.coalesce(PublicSiteInquiry.phone, ""), r"\D", "", "g") == phone,
            PublicSiteInquiry.status.not_in(("won", "lost")),
        ).order_by(PublicSiteInquiry.updated_at.desc()).limit(1)
    )
    if active is not None:
        return active
    return db.scalar(
        select(PublicSiteInquiry).where(
            PublicSiteInquiry.organization_id == organization_id,
            func.regexp_replace(func.coalesce(PublicSiteInquiry.phone, ""), r"\D", "", "g") == phone,
        ).order_by(PublicSiteInquiry.updated_at.desc()).limit(1)
    )


def _ensure_whatsapp_lead(db: Session, organization_id: UUID, *, phone: str, name: str, body: str) -> tuple[Person, PublicSiteInquiry]:
    person = _find_person_by_phone(db, organization_id, phone)
    if person is None:
        person = Person(
            organization_id=organization_id,
            person_type="individual",
            name=name[:180],
            phone=phone,
            address={},
            notes="Cadastro criado automaticamente a partir de uma conversa recebida pelo WhatsApp Business.",
        )
        db.add(person)
        db.flush()
    elif person.name.startswith("WhatsApp ") and name and not name.startswith("WhatsApp "):
        person.name = name[:180]

    inquiry = _find_inquiry_by_phone(db, organization_id, phone)
    if inquiry is None or inquiry.status in {"won", "lost"}:
        inquiry = PublicSiteInquiry(
            organization_id=organization_id,
            property_id=None,
            person_id=person.id,
            property_code="WHATSAPP",
            property_title="Atendimento iniciado pelo WhatsApp",
            name=person.name,
            email=person.email,
            phone=phone,
            preferred_contact="whatsapp",
            message=body[:2000],
            consent_at=datetime.now(timezone.utc),
            status="new",
            source="whatsapp",
        )
        db.add(inquiry)
        db.flush()
    else:
        inquiry.person_id = inquiry.person_id or person.id
        inquiry.phone = inquiry.phone or phone
        inquiry.name = inquiry.name or person.name
    return person, inquiry


def _meta_send_text(db: Session, organization_id: UUID, recipient: str, body: str) -> tuple[str, str | None]:
    row = _row(db, organization_id)
    if row is None:
        raise HTTPException(status_code=422, detail="WhatsApp Business não configurado.")
    config = dict(row.non_secret_config or {})
    secrets = _secrets(row, organization_id)
    phone_number_id = str(config.get("phone_number_id") or "").strip()
    token = str(secrets.get("access_token") or "").strip()
    version = str(config.get("graph_version") or DEFAULT_GRAPH_VERSION)
    if not phone_number_id or not token:
        raise HTTPException(status_code=422, detail="Phone Number ID ou Access Token ainda não configurado.")
    try:
        response = httpx.post(
            f"https://graph.facebook.com/{version}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": _digits(recipient),
                "type": "text",
                "text": {"preview_url": False, "body": body.strip()},
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Não foi possível alcançar a API do WhatsApp.") from exc
    if response.status_code >= 400:
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
        except ValueError:
            detail = None
        raise HTTPException(status_code=502, detail=detail or f"Meta retornou HTTP {response.status_code}.")
    payload = response.json()
    messages = payload.get("messages") if isinstance(payload, dict) else None
    contacts = payload.get("contacts") if isinstance(payload, dict) else None
    message_id = str(messages[0].get("id") or "") if isinstance(messages, list) and messages else ""
    wa_id = str(contacts[0].get("wa_id") or "") if isinstance(contacts, list) and contacts else None
    if not message_id:
        raise HTTPException(status_code=502, detail="A Meta aceitou a mensagem, mas não retornou o ID.")
    return message_id, wa_id


def _public_base_url(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    if forwarded_proto in {"http", "https"} and "://" in base:
        base = forwarded_proto + "://" + base.split("://", 1)[1]
    elif request.url.hostname and request.url.hostname.endswith(".run.app") and base.startswith("http://"):
        base = "https://" + base.removeprefix("http://")
    return base


def _response(db: Session, organization_id: UUID, request: Request) -> WhatsAppConfigurationResponse:
    row = _row(db, organization_id)
    config = dict(row.non_secret_config or {}) if row else {}
    secrets = _secrets(row, organization_id) if row and row.encrypted_secret else {}
    configured = bool(config.get("phone_number_id") and secrets.get("access_token") and secrets.get("verify_token"))
    return WhatsAppConfigurationResponse(
        graph_version=str(config.get("graph_version") or DEFAULT_GRAPH_VERSION),
        business_account_id=str(config.get("business_account_id") or ""),
        phone_number_id=str(config.get("phone_number_id") or ""),
        display_phone_number=str(config.get("display_phone_number") or ""),
        token_configured=bool(secrets.get("access_token")),
        verify_token_configured=bool(secrets.get("verify_token")),
        app_secret_configured=bool(secrets.get("app_secret")),
        configured=configured,
        webhook_url=f"{_public_base_url(request)}/api/webhooks/whatsapp/{organization_id}",
        checked_at=None,
        reachable=None,
        message="Configuração pronta para testar." if configured else "Cadastre o Phone Number ID, Access Token e Verify Token da Meta.",
        last_webhook_at=config.get("last_webhook_at"),
        last_webhook_status=str(config.get("last_webhook_status") or "never"),
        last_webhook_message_count=int(config.get("last_webhook_message_count") or 0),
        last_webhook_error=str(config.get("last_webhook_error") or ""),
    )


@router.get("/meta-whatsapp/config", response_model=WhatsAppConfigurationResponse)
def get_whatsapp_configuration(
    request: Request,
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> WhatsAppConfigurationResponse:
    return _response(db, context.user.organization_id, request)


@router.put("/meta-whatsapp/config", response_model=WhatsAppConfigurationResponse)
def update_whatsapp_configuration(
    payload: WhatsAppConfigurationUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> WhatsAppConfigurationResponse:
    row = _row(db, context.user.organization_id)
    before = _response(db, context.user.organization_id, request).model_dump(mode="json")
    if row is None:
        row = OrganizationIntegrationCredential(
            organization_id=context.user.organization_id,
            provider=PROVIDER,
            non_secret_config={},
            updated_by_user_id=context.user.id,
        )
        db.add(row)
        db.flush()

    current_secrets = _secrets(row, context.user.organization_id)
    for key, supplied in (
        ("access_token", payload.access_token),
        ("verify_token", payload.verify_token),
        ("app_secret", payload.app_secret),
    ):
        if supplied is not None and supplied.strip():
            current_secrets[key] = supplied.strip()

    if not current_secrets.get("access_token"):
        raise HTTPException(status_code=422, detail="Informe o Access Token permanente da WhatsApp Cloud API.")
    if not current_secrets.get("verify_token"):
        raise HTTPException(status_code=422, detail="Informe um Verify Token para validar o webhook da Meta.")

    try:
        row.encrypted_secret = encrypt_secret(
            json.dumps(current_secrets, ensure_ascii=False),
            scope=f"{context.user.organization_id}:{PROVIDER}",
        )
    except CredentialCryptoError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    row.non_secret_config = {
        "graph_version": payload.graph_version,
        "business_account_id": payload.business_account_id.strip(),
        "phone_number_id": payload.phone_number_id.strip(),
        "display_phone_number": payload.display_phone_number.strip(),
    }
    row.updated_by_user_id = context.user.id
    safe_after = {
        **row.non_secret_config,
        "token_configured": True,
        "verify_token_configured": True,
        "app_secret_configured": bool(current_secrets.get("app_secret")),
    }
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action="settings.integrations.whatsapp.updated",
        module="settings",
        entity_type="organization_integration_credential",
        entity_id=str(row.id),
        before_data=before,
        after_data=safe_after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return _response(db, context.user.organization_id, request)


@router.post("/meta-whatsapp/test", response_model=WhatsAppTestResponse)
def test_whatsapp_connection(
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> WhatsAppTestResponse:
    row = _row(db, context.user.organization_id)
    if row is None:
        raise HTTPException(status_code=422, detail="Configure o WhatsApp Business primeiro.")
    config = dict(row.non_secret_config or {})
    secrets = _secrets(row, context.user.organization_id)
    phone_number_id = str(config.get("phone_number_id") or "").strip()
    token = str(secrets.get("access_token") or "").strip()
    if not phone_number_id or not token:
        raise HTTPException(status_code=422, detail="Phone Number ID ou Access Token ainda não configurado.")

    version = str(config.get("graph_version") or DEFAULT_GRAPH_VERSION)
    url = f"https://graph.facebook.com/{version}/{phone_number_id}"
    try:
        response = httpx.get(
            url,
            params={"fields": "display_phone_number,verified_name"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=12.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Não foi possível alcançar a API da Meta.") from exc
    if response.status_code >= 400:
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
        except ValueError:
            detail = None
        raise HTTPException(status_code=502, detail=detail or f"Meta retornou HTTP {response.status_code}.")

    data = response.json()
    return WhatsAppTestResponse(
        configured=True,
        reachable=True,
        verified_name=str(data.get("verified_name") or "") or None,
        display_phone_number=str(data.get("display_phone_number") or "") or None,
        message="Credencial e Phone Number ID validados na WhatsApp Cloud API.",
        checked_at=datetime.now(timezone.utc),
    )


@router.get("/webhooks/whatsapp/{organization_id}")
def verify_whatsapp_webhook(
    organization_id: UUID,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    db: Session = Depends(get_db),
) -> Response:
    row = _row(db, organization_id)
    secrets = _secrets(row, organization_id)
    expected = str(secrets.get("verify_token") or "")
    if hub_mode != "subscribe" or not expected or not hub_verify_token or not hmac.compare_digest(hub_verify_token, expected):
        raise HTTPException(status_code=403, detail="Verificação do webhook recusada.")
    return Response(content=hub_challenge or "", media_type="text/plain")


@router.post("/webhooks/whatsapp/{organization_id}")
async def receive_whatsapp_webhook(
    organization_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    row = _row(db, organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Integração WhatsApp não encontrada.")
    secrets = _secrets(row, organization_id)
    app_secret = str(secrets.get("app_secret") or "")
    body = await request.body()
    diagnostics = dict(row.non_secret_config or {})
    diagnostics["last_webhook_at"] = datetime.now(timezone.utc).isoformat()
    diagnostics["last_webhook_status"] = "received"
    diagnostics["last_webhook_message_count"] = 0
    diagnostics["last_webhook_error"] = ""
    if app_secret:
        supplied = request.headers.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        if not supplied or not hmac.compare_digest(supplied, expected):
            diagnostics["last_webhook_status"] = "rejected_signature"
            diagnostics["last_webhook_error"] = "Assinatura HMAC inválida ou ausente."
            row.non_secret_config = diagnostics
            db.commit()
            raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Payload inválido do WhatsApp.") from exc
    if not isinstance(payload, dict):
        diagnostics["last_webhook_status"] = "rejected_payload"
        diagnostics["last_webhook_error"] = "Payload recebido não é um objeto JSON."
        row.non_secret_config = diagnostics
        db.commit()
        raise HTTPException(status_code=400, detail="Payload inválido do WhatsApp.")

    incoming_messages = _extract_inbound_messages(payload)
    diagnostics["last_webhook_message_count"] = len(incoming_messages)
    diagnostics["last_webhook_status"] = "processed" if incoming_messages else "processed_no_messages"
    row.non_secret_config = diagnostics

    created = 0
    for incoming in incoming_messages:
        dedupe_key = f"whatsapp-in:{incoming['id']}"
        duplicate = db.scalar(
            select(CommunicationMessage.id).where(
                CommunicationMessage.organization_id == organization_id,
                CommunicationMessage.dedupe_key == dedupe_key,
            ).limit(1)
        )
        if duplicate is not None:
            continue
        person, inquiry = _ensure_whatsapp_lead(
            db,
            organization_id,
            phone=incoming["from"],
            name=incoming["name"],
            body=incoming["body"],
        )
        message = CommunicationMessage(
            organization_id=organization_id,
            person_id=person.id,
            recipient_name=person.name,
            recipient_phone=incoming["from"],
            recipient_role="other",
            channel="whatsapp",
            category="commercial",
            origin="provider",
            subject="WhatsApp recebido",
            body=incoming["body"],
            status="received",
            source_module="crm",
            source_type="public_site_inquiry",
            source_id=str(inquiry.id),
            dedupe_key=dedupe_key,
            provider_name="meta_whatsapp_cloud",
            provider_message_id=incoming["id"],
            sent_at=datetime.now(timezone.utc),
        )
        db.add(message)
        db.add(CommercialActivity(
            organization_id=organization_id,
            inquiry_id=inquiry.id,
            activity_type="contact",
            title="WhatsApp recebido",
            notes=incoming["body"][:4000],
        ))
        created += 1
    db.commit()
    return {"received": True, "messages_created": created}


@router.get("/crm/site-inquiries/{inquiry_id}/whatsapp/messages")
def list_inquiry_whatsapp_messages(
    inquiry_id: UUID,
    context: UserContext = Depends(require_permission("crm.view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    inquiry = db.scalar(select(PublicSiteInquiry).where(
        PublicSiteInquiry.id == inquiry_id,
        PublicSiteInquiry.organization_id == context.user.organization_id,
    ))
    if inquiry is None:
        raise HTTPException(status_code=404, detail="Atendimento comercial não encontrado.")
    rows = db.scalars(
        select(CommunicationMessage).where(
            CommunicationMessage.organization_id == context.user.organization_id,
            CommunicationMessage.channel == "whatsapp",
            CommunicationMessage.source_type == "public_site_inquiry",
            CommunicationMessage.source_id == str(inquiry.id),
        ).order_by(CommunicationMessage.created_at.asc()).limit(200)
    ).all()
    return [{
        "id": str(item.id),
        "direction": "inbound" if item.origin == "provider" else "outbound",
        "body": item.body,
        "status": item.status,
        "provider_message_id": item.provider_message_id,
        "created_at": item.created_at,
        "sent_at": item.sent_at,
    } for item in rows]


@router.post("/crm/site-inquiries/{inquiry_id}/whatsapp/messages", status_code=201)
def reply_inquiry_whatsapp(
    inquiry_id: UUID,
    payload: WhatsAppReplyRequest,
    context: UserContext = Depends(require_permission("crm.manage")),
    db: Session = Depends(get_db),
) -> dict:
    inquiry = db.scalar(select(PublicSiteInquiry).where(
        PublicSiteInquiry.id == inquiry_id,
        PublicSiteInquiry.organization_id == context.user.organization_id,
    ))
    if inquiry is None:
        raise HTTPException(status_code=404, detail="Atendimento comercial não encontrado.")
    phone = _digits(inquiry.phone)
    if not phone:
        raise HTTPException(status_code=422, detail="O lead não possui telefone para WhatsApp.")
    message_id, wa_id = _meta_send_text(db, context.user.organization_id, phone, payload.body)
    now = datetime.now(timezone.utc)
    item = CommunicationMessage(
        organization_id=context.user.organization_id,
        person_id=inquiry.person_id,
        recipient_name=inquiry.name,
        recipient_phone=phone,
        recipient_role="other",
        channel="whatsapp",
        category="commercial",
        origin="manual",
        subject="WhatsApp enviado",
        body=payload.body.strip(),
        status="sent",
        source_module="crm",
        source_type="public_site_inquiry",
        source_id=str(inquiry.id),
        provider_name="meta_whatsapp_cloud",
        provider_message_id=message_id,
        attempt_count=1,
        sent_at=now,
        created_by_user_id=context.user.id,
        sent_by_user_id=context.user.id,
    )
    db.add(item)
    db.add(CommercialActivity(
        organization_id=context.user.organization_id,
        inquiry_id=inquiry.id,
        activity_type="contact",
        title="WhatsApp enviado",
        notes=payload.body.strip()[:4000],
        created_by_user_id=context.user.id,
    ))
    if inquiry.status == "new":
        inquiry.status = "contacted"
    db.commit()
    return {
        "id": str(item.id),
        "direction": "outbound",
        "body": item.body,
        "status": item.status,
        "provider_message_id": message_id,
        "wa_id": wa_id,
        "created_at": item.created_at,
        "sent_at": item.sent_at,
    }
