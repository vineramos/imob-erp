from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.domains.communications.models import (
    CommunicationEvent,
    CommunicationMessage,
    CommunicationPreference,
    CommunicationTemplate,
)
from app.domains.communications.schemas import (
    CommunicationMessageCreate,
    CommunicationMessageResponse,
    CommunicationMessageUpdate,
    CommunicationPreferenceUpdate,
    CommunicationSuggestionRefresh,
    CommunicationTemplateUpdate,
)
from app.domains.communications.service import (
    add_event,
    delivery_block_reason,
    ensure_default_templates,
    refresh_suggestions,
)
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person
from app.integrations.document_storage import DocumentStorageError, get_document_storage
from app.integrations.email import EmailDeliveryError, send_email_message, smtp_config_for_organization, smtp_configured
from app.integrations.whatsapp import (
    WhatsAppDeliveryError,
    extract_whatsapp_statuses,
    send_whatsapp_text,
    verify_whatsapp_webhook_challenge,
    verify_whatsapp_webhook_signature,
    whatsapp_configured,
    whatsapp_webhook_configured,
)

router = APIRouter(prefix="/communications", tags=["communications"])


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    action: str,
    message: CommunicationMessage | None,
    *,
    after: dict | None = None,
    reason: str | None = None,
) -> None:
    ip_address, user_agent = _request_meta(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="communications",
        entity_type="communication_message",
        entity_id=str(message.id) if message else None,
        after_data=after,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _load(db: Session, organization_id: UUID, message_id: UUID) -> CommunicationMessage:
    item = db.scalar(
        select(CommunicationMessage).where(
            CommunicationMessage.id == message_id,
            CommunicationMessage.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Comunicação não encontrada.")
    return item


def _events(db: Session, message: CommunicationMessage) -> list[CommunicationEvent]:
    return list(
        db.scalars(
            select(CommunicationEvent)
            .where(
                CommunicationEvent.organization_id == message.organization_id,
                CommunicationEvent.message_id == message.id,
            )
            .order_by(CommunicationEvent.created_at.asc())
        ).all()
    )


def _whatsapp_block_reason(db: Session, item: CommunicationMessage) -> str | None:
    if item.status in {"sent", "cancelled"}:
        return "Esta comunicação já foi encerrada."
    preference = None
    if item.person_id is not None:
        preference = db.scalar(
            select(CommunicationPreference).where(
                CommunicationPreference.organization_id == item.organization_id,
                CommunicationPreference.person_id == item.person_id,
            )
        )
    if preference is not None:
        if not preference.transactional_enabled:
            return "A pessoa desativou comunicações transacionais neste cadastro."
        if not preference.whatsapp_enabled:
            return "O canal WhatsApp está desativado para esta pessoa."
    if not item.recipient_phone:
        return "Destinatário sem telefone cadastrado."
    if not whatsapp_configured():
        return "WhatsApp Cloud API da Meta ainda não está configurada."
    return None


def _delivery_reason(db: Session, item: CommunicationMessage) -> str | None:
    if item.channel == "whatsapp":
        return _whatsapp_block_reason(db, item)
    try:
        configured = smtp_configured(smtp_config_for_organization(db, item.organization_id))
    except EmailDeliveryError:
        configured = False
    return delivery_block_reason(db, item, email_configured=configured)


def _response(db: Session, item: CommunicationMessage, *, include_events: bool = False) -> CommunicationMessageResponse:
    reason = _delivery_reason(db, item)
    return CommunicationMessageResponse(
        id=item.id,
        internal_number=item.internal_number,
        person_id=item.person_id,
        recipient_name=item.recipient_name,
        recipient_email=item.recipient_email,
        recipient_phone=item.recipient_phone,
        recipient_role=item.recipient_role,
        channel=item.channel,
        category=item.category,
        origin=item.origin,
        subject=item.subject,
        body=item.body,
        status=item.status,
        source_module=item.source_module,
        source_type=item.source_type,
        source_id=item.source_id,
        attachment_manifest=list(item.attachment_manifest or []),
        provider_name=item.provider_name,
        provider_message_id=item.provider_message_id,
        error_message=item.error_message,
        attempt_count=item.attempt_count,
        suggested_at=item.suggested_at,
        queued_at=item.queued_at,
        sent_at=item.sent_at,
        failed_at=item.failed_at,
        cancelled_at=item.cancelled_at,
        created_by_user_id=item.created_by_user_id,
        sent_by_user_id=item.sent_by_user_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        send_allowed=reason is None,
        blocked_reason=reason,
        events=[
            {
                "id": event.id,
                "event_type": event.event_type,
                "event_data": dict(event.event_data or {}),
                "created_by_user_id": event.created_by_user_id,
                "created_at": event.created_at,
            }
            for event in (_events(db, item) if include_events else [])
        ],
    )


def _resolve_attachments(db: Session, item: CommunicationMessage) -> list[dict]:
    resolved: list[dict] = []
    for entry in list(item.attachment_manifest or []):
        if entry.get("kind") != "lease_contract_pdf":
            continue
        raw_id = entry.get("source_id")
        try:
            lease_id = UUID(str(raw_id))
        except (TypeError, ValueError):
            continue
        lease = db.get(LeaseContract, lease_id)
        if lease is None or lease.organization_id != item.organization_id or not lease.archived_document_reference:
            continue
        storage = get_document_storage()
        if not storage.configured:
            continue
        try:
            content = storage.download_bytes(lease.archived_document_reference)
        except DocumentStorageError:
            continue
        resolved.append(
            {
                "filename": f"LOC-{lease.internal_number:06d}-assinado.pdf",
                "content_type": "application/pdf",
                "content": content,
            }
        )
    return resolved


@router.get("/capabilities")
def capabilities(
    context: UserContext = Depends(require_permission("communications.view")),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    email_configured = smtp_configured(smtp_config_for_organization(db, context.user.organization_id))
    return {
        "email": {
            "provider": "smtp",
            "configured": email_configured,
            "supports_attachments": True,
            "human_confirmation_required": True,
        },
        "whatsapp": {
            "provider": "meta_whatsapp_cloud",
            "configured": whatsapp_configured(),
            "webhook_configured": whatsapp_webhook_configured(),
            "api_version": settings.whatsapp_graph_version,
            "supports_attachments": False,
            "human_confirmation_required": True,
            "reason": None if whatsapp_configured() else "Informe token e Phone Number ID da WhatsApp Cloud API da Meta.",
        },
    }


@router.get("/overview")
def overview(
    context: UserContext = Depends(require_permission("communications.view")),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(
        select(CommunicationMessage).where(CommunicationMessage.organization_id == context.user.organization_id)
    ).all()
    counts = {key: 0 for key in ("draft", "pending", "sending", "sent", "failed", "cancelled")}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "total": len(rows),
        "counts": counts,
        "email_configured": smtp_configured(smtp_config_for_organization(db, context.user.organization_id)),
        "whatsapp_configured": whatsapp_configured(),
        "human_confirmation_required": True,
    }


@router.get("/whatsapp/webhook", response_class=PlainTextResponse)
def verify_whatsapp_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    challenge = verify_whatsapp_webhook_challenge(
        mode=hub_mode,
        verify_token=hub_verify_token,
        challenge=hub_challenge,
    )
    if challenge is None:
        raise HTTPException(status_code=403, detail="Falha na verificação do webhook do WhatsApp.")
    return PlainTextResponse(challenge)


@router.post("/whatsapp/webhook")
async def receive_whatsapp_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    if not whatsapp_webhook_configured():
        raise HTTPException(status_code=503, detail="Webhook do WhatsApp ainda não está configurado.")
    raw_body = await request.body()
    if not verify_whatsapp_webhook_signature(raw_body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=401, detail="Assinatura inválida do webhook do WhatsApp.")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Payload inválido do webhook do WhatsApp.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload inválido do webhook do WhatsApp.")

    matched = 0
    status_events = extract_whatsapp_statuses(payload)
    for provider_status in status_events:
        item = db.scalar(
            select(CommunicationMessage).where(
                CommunicationMessage.provider_name == "meta_whatsapp_cloud",
                CommunicationMessage.provider_message_id == provider_status["id"],
            )
        )
        if item is None:
            continue
        matched += 1
        status_name = str(provider_status["status"])
        add_event(db, item, f"whatsapp_{status_name}", data=provider_status)
        if status_name == "failed":
            item.status = "failed"
            item.failed_at = datetime.now(timezone.utc)
            errors = provider_status.get("errors") or []
            if errors and isinstance(errors[0], dict):
                item.error_message = str(errors[0].get("message") or errors[0].get("title") or "Falha de entrega reportada pela Meta.")[:1000]
            else:
                item.error_message = "Falha de entrega reportada pela Meta."
        elif status_name in {"sent", "delivered", "read"} and item.status == "sending":
            item.status = "sent"
            item.sent_at = item.sent_at or datetime.now(timezone.utc)
    db.commit()
    return {"received": True, "status_events": len(status_events), "matched_messages": matched}


@router.get("/messages", response_model=list[CommunicationMessageResponse])
def list_messages(
    status_filter: str | None = Query(default=None, alias="status"),
    channel: str | None = Query(default=None),
    category: str | None = Query(default=None),
    context: UserContext = Depends(require_permission("communications.view")),
    db: Session = Depends(get_db),
) -> list[CommunicationMessageResponse]:
    stmt = select(CommunicationMessage).where(CommunicationMessage.organization_id == context.user.organization_id)
    if status_filter:
        stmt = stmt.where(CommunicationMessage.status == status_filter)
    if channel:
        stmt = stmt.where(CommunicationMessage.channel == channel)
    if category:
        stmt = stmt.where(CommunicationMessage.category == category)
    rows = db.scalars(stmt.order_by(CommunicationMessage.created_at.desc()).limit(500)).all()
    return [_response(db, row) for row in rows]


@router.get("/messages/{message_id}", response_model=CommunicationMessageResponse)
def get_message(
    message_id: UUID,
    context: UserContext = Depends(require_permission("communications.view")),
    db: Session = Depends(get_db),
) -> CommunicationMessageResponse:
    return _response(db, _load(db, context.user.organization_id, message_id), include_events=True)


@router.post("/messages", response_model=CommunicationMessageResponse, status_code=status.HTTP_201_CREATED)
def create_message(
    payload: CommunicationMessageCreate,
    request: Request,
    context: UserContext = Depends(require_permission("communications.manage")),
    db: Session = Depends(get_db),
) -> CommunicationMessageResponse:
    person = None
    if payload.person_id:
        person = db.scalar(
            select(Person).where(
                Person.id == payload.person_id,
                Person.organization_id == context.user.organization_id,
                Person.is_active.is_(True),
            )
        )
        if person is None:
            raise HTTPException(status_code=404, detail="Pessoa destinatária não encontrada.")
    item = CommunicationMessage(
        organization_id=context.user.organization_id,
        person_id=person.id if person else None,
        recipient_name=person.name if person else payload.recipient_name.strip(),
        recipient_email=person.email if person else (str(payload.recipient_email) if payload.recipient_email else None),
        recipient_phone=person.phone if person else ((payload.recipient_phone or "").strip() or None),
        recipient_role=payload.recipient_role,
        channel=payload.channel,
        category=payload.category.strip() or "manual",
        origin="manual",
        subject=payload.subject.strip(),
        body=payload.body.strip(),
        status="draft",
        source_module=(payload.source_module or "").strip() or None,
        source_type=(payload.source_type or "").strip() or None,
        source_id=(payload.source_id or "").strip() or None,
        attachment_manifest=list(payload.attachment_manifest or []),
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    add_event(db, item, "created", user_id=context.user.id, data={"origin": "manual", "channel": item.channel})
    _audit(db, request, context, "communications.created", item, after={"channel": item.channel, "recipient": item.recipient_name})
    db.commit()
    return _response(db, item, include_events=True)


@router.patch("/messages/{message_id}", response_model=CommunicationMessageResponse)
def update_message(
    message_id: UUID,
    payload: CommunicationMessageUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("communications.manage")),
    db: Session = Depends(get_db),
) -> CommunicationMessageResponse:
    item = _load(db, context.user.organization_id, message_id)
    if item.status not in {"draft", "pending", "failed"}:
        raise HTTPException(status_code=409, detail="Somente rascunhos, pendentes ou falhas podem ser editados.")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "recipient_email" and value is not None:
            value = str(value)
        if key in {"recipient_name", "recipient_phone", "subject", "body"} and isinstance(value, str):
            value = value.strip()
        setattr(item, key, value)
    if item.status == "failed":
        item.status = "pending"
        item.failed_at = None
        item.error_message = None
    add_event(db, item, "edited", user_id=context.user.id, data={"fields": sorted(changes)})
    _audit(db, request, context, "communications.edited", item, after={"fields": sorted(changes)})
    db.commit()
    return _response(db, item, include_events=True)


def _send_message(db: Session, item: CommunicationMessage, request: Request, context: UserContext) -> CommunicationMessageResponse:
    reason = _delivery_reason(db, item)
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    organization = db.get(Organization, context.user.organization_id)
    organization_name = organization.display_name if organization else "Imobiliária"
    item.status = "sending"
    item.attempt_count += 1
    item.queued_at = datetime.now(timezone.utc)
    item.error_message = None
    add_event(db, item, "send_started", user_id=context.user.id, data={"attempt": item.attempt_count, "channel": item.channel})
    db.flush()
    attachments = _resolve_attachments(db, item) if item.channel == "email" else []
    provider_name: str | None = None
    provider_message_id: str | None = None
    try:
        if item.channel == "email":
            smtp_config = smtp_config_for_organization(db, context.user.organization_id)
            send_email_message(
                recipient=item.recipient_email or "",
                subject=item.subject,
                text_body=item.body,
                organization_name=organization_name,
                attachments=attachments,
                config=smtp_config,
            )
            provider_name = "smtp"
        elif item.channel == "whatsapp":
            result = send_whatsapp_text(recipient=item.recipient_phone or "", text_body=item.body)
            provider_name = "meta_whatsapp_cloud"
            provider_message_id = result.message_id
        else:
            raise WhatsAppDeliveryError("Provider do canal selecionado não está disponível.")
    except (EmailDeliveryError, WhatsAppDeliveryError) as exc:
        item.status = "failed"
        item.failed_at = datetime.now(timezone.utc)
        item.error_message = str(exc)[:1000]
        item.provider_name = provider_name or ("smtp" if item.channel == "email" else "meta_whatsapp_cloud" if item.channel == "whatsapp" else item.channel)
        add_event(db, item, "failed", user_id=context.user.id, data={"attempt": item.attempt_count, "error": item.error_message})
        _audit(db, request, context, "communications.failed", item, after={"attempt": item.attempt_count}, reason=item.error_message)
        db.commit()
        raise HTTPException(status_code=502, detail=item.error_message) from exc
    item.status = "sent"
    item.sent_at = datetime.now(timezone.utc)
    item.failed_at = None
    item.provider_name = provider_name
    item.provider_message_id = provider_message_id
    item.sent_by_user_id = context.user.id
    event_data = {"attempt": item.attempt_count, "attachments_delivered": len(attachments), "provider": provider_name}
    if provider_message_id:
        event_data["provider_message_id"] = provider_message_id
    add_event(db, item, "sent", user_id=context.user.id, data=event_data)
    _audit(db, request, context, "communications.sent", item, after=event_data)
    db.commit()
    return _response(db, item, include_events=True)


@router.post("/messages/{message_id}/send", response_model=CommunicationMessageResponse)
def send_message(
    message_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("communications.send")),
    db: Session = Depends(get_db),
) -> CommunicationMessageResponse:
    return _send_message(db, _load(db, context.user.organization_id, message_id), request, context)


@router.post("/messages/{message_id}/retry", response_model=CommunicationMessageResponse)
def retry_message(
    message_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("communications.send")),
    db: Session = Depends(get_db),
) -> CommunicationMessageResponse:
    item = _load(db, context.user.organization_id, message_id)
    if item.status != "failed":
        raise HTTPException(status_code=409, detail="Somente comunicações com falha podem ser reenviadas por esta ação.")
    add_event(db, item, "retry_requested", user_id=context.user.id, data={"previous_attempts": item.attempt_count})
    return _send_message(db, item, request, context)


@router.post("/messages/{message_id}/cancel", response_model=CommunicationMessageResponse)
def cancel_message(
    message_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("communications.manage")),
    db: Session = Depends(get_db),
) -> CommunicationMessageResponse:
    item = _load(db, context.user.organization_id, message_id)
    if item.status in {"sent", "cancelled"}:
        raise HTTPException(status_code=409, detail="Esta comunicação não pode mais ser cancelada.")
    item.status = "cancelled"
    item.cancelled_at = datetime.now(timezone.utc)
    add_event(db, item, "cancelled", user_id=context.user.id)
    _audit(db, request, context, "communications.cancelled", item)
    db.commit()
    return _response(db, item, include_events=True)


@router.post("/suggestions/refresh")
def refresh(
    payload: CommunicationSuggestionRefresh,
    request: Request,
    context: UserContext = Depends(require_permission("communications.manage")),
    db: Session = Depends(get_db),
) -> dict:
    created = refresh_suggestions(
        db,
        organization_id=context.user.organization_id,
        user_id=context.user.id,
        include_overdue_charges=payload.include_overdue_charges,
        include_contracts=payload.include_contracts,
        include_owner_repasses=payload.include_owner_repasses,
    )
    _audit(db, request, context, "communications.suggestions_refreshed", None, after={"created": len(created)})
    db.commit()
    return {"created": len(created), "message_ids": [str(item.id) for item in created]}


@router.get("/templates")
def list_templates(
    context: UserContext = Depends(require_permission("communications.view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = ensure_default_templates(db, context.user.organization_id, context.user.id)
    db.commit()
    return [
        {
            "id": str(row.id),
            "key": row.key,
            "channel": row.channel,
            "name": row.name,
            "subject_template": row.subject_template,
            "body_template": row.body_template,
            "is_active": row.is_active,
            "is_system_default": row.is_system_default,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.put("/templates/{template_id}")
def update_template(
    template_id: UUID,
    payload: CommunicationTemplateUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("communications.manage")),
    db: Session = Depends(get_db),
) -> dict:
    row = db.scalar(
        select(CommunicationTemplate).where(
            CommunicationTemplate.id == template_id,
            CommunicationTemplate.organization_id == context.user.organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Modelo de comunicação não encontrado.")
    row.name = payload.name.strip()
    row.subject_template = payload.subject_template.strip()
    row.body_template = payload.body_template.strip()
    row.is_active = payload.is_active
    row.is_system_default = False
    row.updated_by_user_id = context.user.id
    _audit(db, request, context, "communications.template_updated", None, after={"template_id": str(row.id), "key": row.key})
    db.commit()
    return {"id": str(row.id), "key": row.key, "name": row.name, "subject_template": row.subject_template, "body_template": row.body_template, "is_active": row.is_active}


@router.get("/preferences/{person_id}")
def get_preference(
    person_id: UUID,
    context: UserContext = Depends(require_permission("communications.view")),
    db: Session = Depends(get_db),
) -> dict:
    person = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == context.user.organization_id))
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")
    row = db.scalar(
        select(CommunicationPreference).where(
            CommunicationPreference.organization_id == context.user.organization_id,
            CommunicationPreference.person_id == person_id,
        )
    )
    return {
        "person_id": str(person.id),
        "person_name": person.name,
        "email": person.email,
        "phone": person.phone,
        "email_enabled": row.email_enabled if row else True,
        "whatsapp_enabled": row.whatsapp_enabled if row else False,
        "transactional_enabled": row.transactional_enabled if row else True,
        "preferred_channel": row.preferred_channel if row else "email",
        "notes": row.notes if row else None,
    }


@router.put("/preferences/{person_id}")
def update_preference(
    person_id: UUID,
    payload: CommunicationPreferenceUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("communications.manage")),
    db: Session = Depends(get_db),
) -> dict:
    person = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == context.user.organization_id))
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")
    row = db.scalar(
        select(CommunicationPreference).where(
            CommunicationPreference.organization_id == context.user.organization_id,
            CommunicationPreference.person_id == person_id,
        )
    )
    if row is None:
        row = CommunicationPreference(organization_id=context.user.organization_id, person_id=person_id)
        db.add(row)
    row.email_enabled = payload.email_enabled
    row.whatsapp_enabled = payload.whatsapp_enabled
    row.transactional_enabled = payload.transactional_enabled
    row.preferred_channel = payload.preferred_channel
    row.notes = (payload.notes or "").strip() or None
    row.updated_by_user_id = context.user.id
    _audit(db, request, context, "communications.preference_updated", None, after={"person_id": str(person_id), "preferred_channel": row.preferred_channel})
    db.commit()
    return get_preference(person_id, context, db)
