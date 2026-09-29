from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domains.foundation.models import OrganizationIntegrationCredential
from app.integrations.credential_crypto import CredentialCryptoError, decrypt_secret, encrypt_secret

PROVIDER = "instagram_meta"
DEFAULT_GRAPH_VERSION = "v26.0"
GRAPH_BASE = "https://graph.instagram.com"


@dataclass(frozen=True)
class InstagramCredentials:
    graph_version: str
    account_id: str
    username: str
    access_token: str

    @property
    def configured(self) -> bool:
        return bool(self.account_id and self.access_token)


def credential_row(db: Session, organization_id: UUID) -> OrganizationIntegrationCredential | None:
    return db.scalar(
        select(OrganizationIntegrationCredential).where(
            OrganizationIntegrationCredential.organization_id == organization_id,
            OrganizationIntegrationCredential.provider == PROVIDER,
        )
    )


def _secret_payload(row: OrganizationIntegrationCredential | None, organization_id: UUID) -> dict[str, str]:
    if row is None or not row.encrypted_secret:
        return {}
    try:
        raw = decrypt_secret(row.encrypted_secret, scope=f"{organization_id}:{PROVIDER}")
        payload = json.loads(raw)
    except (CredentialCryptoError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Não foi possível abrir as credenciais protegidas do Instagram.") from exc
    return payload if isinstance(payload, dict) else {}


def credentials(db: Session, organization_id: UUID) -> InstagramCredentials:
    row = credential_row(db, organization_id)
    config = dict(row.non_secret_config or {}) if row else {}
    secrets = _secret_payload(row, organization_id)
    return InstagramCredentials(
        graph_version=str(config.get("graph_version") or DEFAULT_GRAPH_VERSION),
        account_id=str(config.get("account_id") or "").strip(),
        username=str(config.get("username") or "").strip(),
        access_token=str(secrets.get("access_token") or "").strip(),
    )


def save_credentials(
    db: Session,
    organization_id: UUID,
    *,
    user_id: UUID,
    graph_version: str,
    account_id: str,
    username: str,
    access_token: str | None,
) -> OrganizationIntegrationCredential:
    row = credential_row(db, organization_id)
    if row is None:
        row = OrganizationIntegrationCredential(
            organization_id=organization_id,
            provider=PROVIDER,
            non_secret_config={},
            updated_by_user_id=user_id,
        )
        db.add(row)
        db.flush()

    secrets = _secret_payload(row, organization_id)
    if access_token is not None and access_token.strip():
        secrets["access_token"] = access_token.strip()
    if not str(secrets.get("access_token") or "").strip():
        raise HTTPException(status_code=422, detail="Informe o Access Token gerado pelo Meta for Developers.")

    try:
        row.encrypted_secret = encrypt_secret(
            json.dumps(secrets, ensure_ascii=False),
            scope=f"{organization_id}:{PROVIDER}",
        )
    except CredentialCryptoError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    row.non_secret_config = {
        "graph_version": graph_version.strip() or DEFAULT_GRAPH_VERSION,
        "account_id": account_id.strip(),
        "username": username.strip(),
    }
    row.updated_by_user_id = user_id
    return row


def _url(creds: InstagramCredentials, path: str) -> str:
    version = creds.graph_version.strip().lstrip("/") or DEFAULT_GRAPH_VERSION
    return f"{GRAPH_BASE}/{version}/{path.lstrip('/')}"


def _meta_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "").strip()
                code = str(error.get("code") or "").strip()
                if message:
                    return f"{message}{f' (Meta {code})' if code else ''}"
    except ValueError:
        pass
    return f"Meta retornou HTTP {response.status_code}."


def request_json(
    creds: InstagramCredentials,
    method: str,
    path: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
    timeout: float = 20.0,
) -> dict:
    if not creds.access_token:
        raise HTTPException(status_code=422, detail="Access Token do Instagram ainda não configurado.")
    headers = {"Authorization": f"Bearer {creds.access_token}"}
    try:
        response = httpx.request(method, _url(creds, path), headers=headers, params=params, data=data, timeout=timeout)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Não foi possível alcançar a API do Instagram.") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=_meta_error(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="A Meta retornou uma resposta inválida.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="A Meta retornou uma resposta inesperada.")
    return payload


def validate_account(creds: InstagramCredentials) -> dict:
    payload = request_json(
        creds,
        "GET",
        "me",
        params={"fields": "id,username,account_type"},
    )
    if not str(payload.get("id") or "").strip():
        raise HTTPException(status_code=502, detail="A Meta respondeu, mas não retornou o ID da conta do Instagram.")
    return payload


def _media_signing_key() -> bytes:
    settings = get_settings()
    material = settings.credentials_encryption_key.strip() or settings.database_url.strip()
    if not material:
        raise HTTPException(status_code=503, detail="Chave do servidor indisponível para assinar mídia temporária.")
    return hashlib.sha256(f"instagram-media:{material}".encode("utf-8")).digest()


def sign_media_path(organization_id: UUID, property_id: UUID, photo_id: UUID, expires: int) -> str:
    message = f"{organization_id}:{property_id}:{photo_id}:{expires}".encode("utf-8")
    return hmac.new(_media_signing_key(), message, hashlib.sha256).hexdigest()


def validate_media_signature(
    organization_id: UUID,
    property_id: UUID,
    photo_id: UUID,
    expires: int,
    signature: str,
) -> bool:
    if expires < int(time.time()):
        return False
    expected = sign_media_path(organization_id, property_id, photo_id, expires)
    return hmac.compare_digest(expected, signature)


def public_media_url(
    *,
    base_url: str,
    organization_id: UUID,
    property_id: UUID,
    photo_id: UUID,
    ttl_seconds: int = 3600,
) -> str:
    expires = int(time.time()) + ttl_seconds
    signature = sign_media_path(organization_id, property_id, photo_id, expires)
    query = urlencode({"expires": expires, "signature": signature})
    return f"{base_url.rstrip('/')}/api/public/instagram-media/{organization_id}/{property_id}/{photo_id}?{query}"


def sign_story_media_path(
    organization_id: UUID,
    property_id: UUID,
    photo_id: UUID,
    expires: int,
    zoom: float,
) -> str:
    normalized_zoom = f"{zoom:.2f}"
    message = f"{organization_id}:{property_id}:{photo_id}:{expires}:story:{normalized_zoom}".encode("utf-8")
    return hmac.new(_media_signing_key(), message, hashlib.sha256).hexdigest()


def validate_story_media_signature(
    organization_id: UUID,
    property_id: UUID,
    photo_id: UUID,
    expires: int,
    zoom: float,
    signature: str,
) -> bool:
    if expires < int(time.time()):
        return False
    expected = sign_story_media_path(organization_id, property_id, photo_id, expires, zoom)
    return hmac.compare_digest(expected, signature)


def public_story_media_url(
    *,
    base_url: str,
    organization_id: UUID,
    property_id: UUID,
    photo_id: UUID,
    zoom: float,
    ttl_seconds: int = 3600,
) -> str:
    expires = int(time.time()) + ttl_seconds
    normalized_zoom = round(max(0.2, min(2.0, zoom)), 2)
    signature = sign_story_media_path(organization_id, property_id, photo_id, expires, normalized_zoom)
    query = urlencode({"expires": expires, "zoom": f"{normalized_zoom:.2f}", "signature": signature})
    return f"{base_url.rstrip('/')}/api/public/instagram-story-media/{organization_id}/{property_id}/{photo_id}?{query}"


def wait_for_container(creds: InstagramCredentials, creation_id: str, *, attempts: int = 8) -> None:
    for index in range(attempts):
        payload = request_json(creds, "GET", creation_id, params={"fields": "status_code"})
        status_code = str(payload.get("status_code") or "").upper()
        if status_code in {"FINISHED", "PUBLISHED"}:
            return
        if status_code in {"ERROR", "EXPIRED"}:
            raise HTTPException(status_code=502, detail=f"A Meta não conseguiu processar a mídia ({status_code}).")
        if index < attempts - 1:
            time.sleep(1.0)
    raise HTTPException(status_code=502, detail="A mídia ainda não ficou pronta para publicação na Meta.")


def create_image_container(creds: InstagramCredentials, *, image_url: str, is_carousel_item: bool) -> str:
    if not creds.account_id:
        raise HTTPException(status_code=422, detail="ID da conta do Instagram ainda não configurado.")
    data: dict[str, str] = {"image_url": image_url}
    if is_carousel_item:
        data["is_carousel_item"] = "true"
    payload = request_json(creds, "POST", f"{creds.account_id}/media", data=data)
    creation_id = str(payload.get("id") or "").strip()
    if not creation_id:
        raise HTTPException(status_code=502, detail="A Meta não retornou o ID do container de mídia.")
    wait_for_container(creds, creation_id)
    return creation_id


def publish_single(creds: InstagramCredentials, *, image_url: str, caption: str) -> str:
    if not creds.account_id:
        raise HTTPException(status_code=422, detail="ID da conta do Instagram ainda não configurado.")
    payload = request_json(
        creds,
        "POST",
        f"{creds.account_id}/media",
        data={"image_url": image_url, "caption": caption},
    )
    creation_id = str(payload.get("id") or "").strip()
    if not creation_id:
        raise HTTPException(status_code=502, detail="A Meta não retornou o ID do container.")
    wait_for_container(creds, creation_id)
    published = request_json(
        creds,
        "POST",
        f"{creds.account_id}/media_publish",
        data={"creation_id": creation_id},
    )
    media_id = str(published.get("id") or "").strip()
    if not media_id:
        raise HTTPException(status_code=502, detail="A Meta não retornou o ID da publicação.")
    return media_id


def publish_story(creds: InstagramCredentials, *, image_url: str) -> str:
    if not creds.account_id:
        raise HTTPException(status_code=422, detail="ID da conta do Instagram ainda não configurado.")
    payload = request_json(
        creds,
        "POST",
        f"{creds.account_id}/media",
        data={"media_type": "STORIES", "image_url": image_url},
    )
    creation_id = str(payload.get("id") or "").strip()
    if not creation_id:
        raise HTTPException(status_code=502, detail="A Meta não retornou o ID do container do Story.")
    wait_for_container(creds, creation_id)
    published = request_json(
        creds,
        "POST",
        f"{creds.account_id}/media_publish",
        data={"creation_id": creation_id},
    )
    media_id = str(published.get("id") or "").strip()
    if not media_id:
        raise HTTPException(status_code=502, detail="A Meta não retornou o ID do Story publicado.")
    return media_id


def publish_carousel(creds: InstagramCredentials, *, image_urls: list[str], caption: str) -> str:
    if not creds.account_id:
        raise HTTPException(status_code=422, detail="ID da conta do Instagram ainda não configurado.")
    children = [
        create_image_container(creds, image_url=image_url, is_carousel_item=True)
        for image_url in image_urls
    ]
    payload = request_json(
        creds,
        "POST",
        f"{creds.account_id}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": caption,
        },
    )
    creation_id = str(payload.get("id") or "").strip()
    if not creation_id:
        raise HTTPException(status_code=502, detail="A Meta não retornou o ID do carrossel.")
    wait_for_container(creds, creation_id)
    published = request_json(
        creds,
        "POST",
        f"{creds.account_id}/media_publish",
        data={"creation_id": creation_id},
    )
    media_id = str(published.get("id") or "").strip()
    if not media_id:
        raise HTTPException(status_code=502, detail="A Meta não retornou o ID da publicação.")
    return media_id


def media_details(creds: InstagramCredentials, media_id: str) -> dict:
    return request_json(creds, "GET", media_id, params={"fields": "id,permalink,media_type,timestamp"})


def checked_at() -> datetime:
    return datetime.now(timezone.utc)
