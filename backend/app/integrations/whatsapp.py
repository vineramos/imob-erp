from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings


class WhatsAppDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class WhatsAppSendResult:
    message_id: str
    wa_id: str | None = None


def whatsapp_configured() -> bool:
    return get_settings().whatsapp_configured


def whatsapp_webhook_configured() -> bool:
    return get_settings().whatsapp_webhook_configured


def normalize_whatsapp_recipient(phone: str) -> str:
    settings = get_settings()
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    country = re.sub(r"\D", "", settings.whatsapp_default_country_code or "")
    if country and len(digits) <= 11 and not digits.startswith(country):
        digits = f"{country}{digits}"
    if not 8 <= len(digits) <= 15:
        raise WhatsAppDeliveryError("Telefone inválido para WhatsApp. Informe DDI + número, sem caracteres especiais.")
    return digits


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            code = error.get("code")
            subcode = error.get("error_subcode")
            suffix = ""
            if code is not None:
                suffix = f" (Meta {code}"
                if subcode is not None:
                    suffix += f"/{subcode}"
                suffix += ")"
            if message:
                return f"{message}{suffix}"
    return f"WhatsApp Cloud API respondeu HTTP {response.status_code}."


def send_whatsapp_text(*, recipient: str, text_body: str, preview_url: bool = False) -> WhatsAppSendResult:
    settings = get_settings()
    if not settings.whatsapp_configured:
        raise WhatsAppDeliveryError("WhatsApp Cloud API da Meta ainda não está configurada.")
    to = normalize_whatsapp_recipient(recipient)
    body = (text_body or "").strip()
    if not body:
        raise WhatsAppDeliveryError("A mensagem do WhatsApp não pode estar vazia.")

    try:
        response = httpx.post(
            settings.whatsapp_messages_url,
            headers={
                "Authorization": f"Bearer {settings.whatsapp_access_token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": preview_url, "body": body},
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise WhatsAppDeliveryError("Não foi possível conectar à WhatsApp Cloud API da Meta.") from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise WhatsAppDeliveryError(_error_detail(response))

    try:
        payload = response.json()
    except ValueError as exc:
        raise WhatsAppDeliveryError("A Meta respondeu ao envio do WhatsApp em formato inesperado.") from exc
    messages = payload.get("messages") if isinstance(payload, dict) else None
    message_id = None
    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
        message_id = str(messages[0].get("id") or "").strip() or None
    if not message_id:
        raise WhatsAppDeliveryError("A Meta aceitou a requisição, mas não retornou o ID da mensagem.")
    contacts = payload.get("contacts") if isinstance(payload, dict) else None
    wa_id = None
    if isinstance(contacts, list) and contacts and isinstance(contacts[0], dict):
        wa_id = str(contacts[0].get("wa_id") or "").strip() or None
    return WhatsAppSendResult(message_id=message_id, wa_id=wa_id)


def verify_whatsapp_webhook_challenge(*, mode: str | None, verify_token: str | None, challenge: str | None) -> str | None:
    settings = get_settings()
    if not settings.whatsapp_webhook_verify_token:
        return None
    if mode != "subscribe" or not verify_token or not challenge:
        return None
    if not hmac.compare_digest(verify_token, settings.whatsapp_webhook_verify_token):
        return None
    return challenge


def verify_whatsapp_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    settings = get_settings()
    secret = settings.whatsapp_app_secret
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    supplied = signature_header.removeprefix("sha256=").strip().lower()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


def extract_whatsapp_statuses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("object") != "whatsapp_business_account":
        return []
    statuses: list[dict[str, Any]] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            for raw in value.get("statuses") or []:
                if not isinstance(raw, dict):
                    continue
                message_id = str(raw.get("id") or "").strip()
                status_name = str(raw.get("status") or "").strip().lower()
                if not message_id or not status_name:
                    continue
                statuses.append(
                    {
                        "id": message_id,
                        "status": status_name,
                        "timestamp": raw.get("timestamp"),
                        "recipient_id": raw.get("recipient_id"),
                        "conversation": raw.get("conversation"),
                        "pricing": raw.get("pricing"),
                        "errors": raw.get("errors") or [],
                    }
                )
    return statuses
