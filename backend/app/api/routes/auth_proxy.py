from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_auth_identity
from app.domains.foundation.models import AppUser, AuditLog, UserInvitation

router = APIRouter(prefix="/auth", tags=["auth"])

IMOB_SESSION_COOKIE = "imob_auth_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
_SESSION_ENVELOPE_PREFIX = "v1."


class SignInPayload(BaseModel):
    email: str
    password: str


class SignUpPayload(SignInPayload):
    name: str


class PasswordResetRequestPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    redirect_to: str = Field(alias="redirectTo")


class ResetPasswordPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    new_password: str = Field(alias="newPassword")
    token: str


class AcceptInvitationPayload(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=200)


def _auth_endpoint(path: str) -> str:
    base = get_settings().neon_auth_url.strip().rstrip("/")
    if not base:
        raise RuntimeError("Neon Auth não configurado")
    return f"{base}{path if path.startswith('/') else f'/{path}'}"


def _normalized_origin(value: str) -> str:
    source = (value or "").strip()
    if not source:
        return ""
    try:
        parsed = urlsplit(source)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _trusted_password_reset_redirect(db: Session, requested_redirect: str) -> str:
    """Resolve password-reset redirects from Neon Auth's trusted origins."""
    requested_origin = _normalized_origin(requested_redirect)
    trusted: list[str] = []
    try:
        raw = db.execute(
            text(
                "SELECT trusted_origins FROM neon_auth.project_config "
                "ORDER BY updated_at DESC NULLS LAST LIMIT 1"
            )
        ).scalar_one_or_none()
    except Exception:
        raw = None

    if isinstance(raw, list):
        for item in raw:
            candidate = item.get("domain") if isinstance(item, dict) else item
            if isinstance(candidate, str):
                origin = _normalized_origin(candidate)
                if origin and origin not in trusted:
                    trusted.append(origin)

    if requested_origin and requested_origin in trusted:
        return f"{requested_origin}/"

    secure = [origin for origin in trusted if origin.startswith("https://")]
    if secure:
        return f"{secure[0]}/"
    if trusted:
        return f"{trusted[0]}/"
    return requested_redirect


def _encode_upstream_cookie(name: str, value: str) -> str:
    raw = f"{name}\0{value}".encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{_SESSION_ENVELOPE_PREFIX}{encoded}"


def _decode_upstream_cookie(state: str) -> str | None:
    source = (state or "").strip()
    if not source:
        return None

    if source.startswith(_SESSION_ENVELOPE_PREFIX):
        encoded = source[len(_SESSION_ENVELOPE_PREFIX):]
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            name, value = decoded.split("\0", 1)
        except (ValueError, UnicodeDecodeError):
            return None
        name = name.strip()
        value = value.strip()
        if not name or not value or any(char in name for char in "\r\n;=") or any(char in value for char in "\r\n;"):
            return None
        return f"{name}={value}"

    # Compatibilidade somente com cookies criados pelas revisões anteriores.
    # Envia o mesmo token sob os prefixos conhecidos para permitir que uma
    # sessão antiga sobreviva ao deploy. Novos logins sempre usam o nome exato
    # devolvido pelo Neon Auth no Set-Cookie.
    legacy_names = (
        "__Secure-neonauth.session_token",
        "__Secure-better-auth.session_token",
        "neonauth.session_token",
        "better-auth.session_token",
    )
    if any(char in source for char in "\r\n;"):
        return None
    return "; ".join(f"{name}={source}" for name in legacy_names)


async def _upstream_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    session_cookie: str | None = None,
) -> httpx.Response:
    # Este é um hop servidor→servidor. Não replica o Origin do navegador para
    # o Neon Auth: aliases do Cloud Run podem não estar entre trusted_origins,
    # e CSRF/origin validation pertence ao limite navegador→Imob.
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if session_cookie:
        headers["Cookie"] = session_cookie

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            return await client.request(
                method,
                _auth_endpoint(path),
                headers=headers,
                json=payload,
            )
    except RuntimeError:
        raise
    except httpx.HTTPError as exc:
        raise RuntimeError("Neon Auth indisponível") from exc


def _json_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _upstream_message(response: httpx.Response, fallback: str) -> str:
    payload = _json_payload(response)
    detail = payload.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    if isinstance(error, dict):
        nested_message = error.get("message")
        if isinstance(nested_message, str) and nested_message.strip():
            return nested_message.strip()
    return fallback


def _extract_upstream_session_cookie(response: httpx.Response) -> tuple[str, str] | None:
    for raw_cookie in response.headers.get_list("set-cookie"):
        pair = raw_cookie.split(";", 1)[0]
        name, separator, value = pair.partition("=")
        normalized_name = name.strip().lower().replace("-", "_")
        if not separator or "session_token" not in normalized_name:
            continue
        cookie_name = name.strip()
        cookie_value = value.strip().strip('"')
        if cookie_name and cookie_value:
            return cookie_name, cookie_value
    return None


def _extract_access_token(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("access_token", "accessToken"):
            value = payload.get(key)
            if isinstance(value, str) and value.count(".") == 2:
                return value
        token = payload.get("token")
        if isinstance(token, str) and token.count(".") == 2:
            return token
        for value in payload.values():
            found = _extract_access_token(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _extract_access_token(value)
            if found:
                return found
    return None


def _response(payload: dict[str, Any], status_code: int = status.HTTP_200_OK) -> JSONResponse:
    response = JSONResponse(payload, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    return response


def _set_session_cookie(response: JSONResponse, session_state: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=IMOB_SESSION_COOKIE,
        value=session_state,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=settings.app_env.strip().lower() == "production",
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: JSONResponse) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=IMOB_SESSION_COOKIE,
        httponly=True,
        secure=settings.app_env.strip().lower() == "production",
        samesite="lax",
        path="/",
    )


async def _complete_sign_in(
    upstream: httpx.Response,
    *,
    invalid_message: str,
) -> JSONResponse:
    if upstream.status_code >= 500:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    if upstream.status_code >= 400:
        return _response({"detail": invalid_message}, status.HTTP_401_UNAUTHORIZED)

    session_cookie = _extract_upstream_session_cookie(upstream)
    if not session_cookie:
        return _response(
            {"detail": "A autenticação foi aceita, mas a sessão segura não foi criada"},
            status.HTTP_502_BAD_GATEWAY,
        )

    cookie_name, cookie_value = session_cookie
    session_state = _encode_upstream_cookie(cookie_name, cookie_value)
    access_token = _extract_access_token(_json_payload(upstream))
    payload: dict[str, Any] = {"ok": True}
    if access_token:
        payload["token"] = access_token
    response = _response(payload)
    _set_session_cookie(response, session_state)
    return response


@router.post("/sign-in")
async def sign_in(payload: SignInPayload, request: Request) -> JSONResponse:
    del request
    try:
        upstream = await _upstream_request(
            "POST",
            "/sign-in/email",
            payload={"email": payload.email.strip().lower(), "password": payload.password},
        )
    except RuntimeError:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    return await _complete_sign_in(upstream, invalid_message="Confira e-mail e senha")


@router.post("/sign-up")
async def sign_up(payload: SignUpPayload, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    del request
    if (db.scalar(select(func.count(AppUser.id))) or 0) > 0:
        return _response(
            {"detail": "O cadastro público está encerrado. Solicite um convite ao administrador."},
            status.HTTP_403_FORBIDDEN,
        )
    try:
        upstream = await _upstream_request(
            "POST",
            "/sign-up/email",
            payload={
                "name": payload.name.strip(),
                "email": payload.email.strip().lower(),
                "password": payload.password,
            },
        )
    except RuntimeError:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)

    if upstream.status_code >= 500:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    if upstream.status_code >= 400:
        return _response(
            {"detail": _upstream_message(upstream, "Não foi possível criar o acesso")},
            status.HTTP_400_BAD_REQUEST,
        )
    return await _complete_sign_in(upstream, invalid_message="Não foi possível criar o acesso")


def _invitation_for_token(db: Session, raw_token: str, *, lock: bool = False) -> UserInvitation | None:
    digest = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    query = select(UserInvitation).where(UserInvitation.token_digest == digest)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def _invitation_error(invitation: UserInvitation | None) -> str | None:
    if invitation is None:
        return "Convite inválido."
    if invitation.revoked_at is not None:
        return "Este convite foi cancelado."
    if invitation.accepted_at is not None:
        return "Este convite já foi utilizado."
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return "Este convite expirou. Solicite um novo ao administrador."
    return None


@router.get("/invitations/{token}")
def invitation_details(token: str, db: Session = Depends(get_db)) -> JSONResponse:
    invitation = _invitation_for_token(db, token)
    error = _invitation_error(invitation)
    if error or invitation is None:
        return _response({"detail": error or "Convite inválido."}, status.HTTP_404_NOT_FOUND)
    user = db.get(AppUser, invitation.user_id)
    if user is None:
        return _response({"detail": "Convite inválido."}, status.HTTP_404_NOT_FOUND)
    return _response({"name": user.name, "email": user.email, "expires_at": invitation.expires_at.isoformat()})


@router.post("/accept-invitation")
async def accept_invitation(payload: AcceptInvitationPayload, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    invitation = _invitation_for_token(db, payload.token, lock=True)
    error = _invitation_error(invitation)
    if error or invitation is None:
        return _response({"detail": error or "Convite inválido."}, status.HTTP_400_BAD_REQUEST)
    user = db.scalar(select(AppUser).options(selectinload(AppUser.roles)).where(AppUser.id == invitation.user_id))
    if user is None or not user.auth_user_id.startswith("pending:"):
        return _response({"detail": "Convite inválido."}, status.HTTP_400_BAD_REQUEST)

    try:
        upstream = await _upstream_request(
            "POST",
            "/sign-up/email",
            payload={"name": user.name, "email": user.email, "password": payload.password},
        )
    except RuntimeError:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    if upstream.status_code >= 500:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    if upstream.status_code >= 400:
        return _response(
            {"detail": _upstream_message(upstream, "Não foi possível ativar o convite. Se o e-mail já possui acesso, fale com o administrador.")},
            status.HTTP_400_BAD_REQUEST,
        )

    session_pair = _extract_upstream_session_cookie(upstream)
    if session_pair is None:
        return _response({"detail": "A conta foi criada, mas a sessão segura não foi emitida."}, status.HTTP_502_BAD_GATEWAY)
    access_token = _extract_access_token(_json_payload(upstream))
    if access_token is None:
        access_token = await _access_token_for_session(f"{session_pair[0]}={session_pair[1]}")
    if access_token is None:
        return _response({"detail": "A conta foi criada, mas sua identidade não pôde ser confirmada."}, status.HTTP_502_BAD_GATEWAY)
    try:
        identity = get_auth_identity(HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_token))
        subject = identity.subject
        claimed_email = (identity.email or "").strip().lower()
    except HTTPException:
        subject, claimed_email = "", ""
    if not subject or (claimed_email and claimed_email != user.email.lower()):
        return _response({"detail": "A identidade criada não corresponde ao convite."}, status.HTTP_502_BAD_GATEWAY)

    now = datetime.now(timezone.utc)
    user.auth_user_id = subject
    invitation.accepted_at = now
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    db.add(AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action="security.user.invitation_accepted",
        module="settings",
        entity_type="app_user",
        entity_id=str(user.id),
        after_data={"email": user.email, "role_keys": sorted(role.key for role in user.roles)},
        ip_address=forwarded_for or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    ))
    db.commit()
    return await _complete_sign_in(upstream, invalid_message="Não foi possível ativar o convite")


@router.post("/request-password-reset")
async def request_password_reset(
    payload: PasswordResetRequestPayload,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    del request
    trusted_redirect = _trusted_password_reset_redirect(db, payload.redirect_to)
    try:
        upstream = await _upstream_request(
            "POST",
            "/request-password-reset",
            payload={
                "email": payload.email.strip().lower(),
                "redirectTo": trusted_redirect,
            },
        )
    except RuntimeError:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)

    if upstream.status_code >= 500:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    if upstream.status_code >= 400:
        return _response(
            {"detail": "Não foi possível iniciar a recuperação de senha neste ambiente"},
            status.HTTP_502_BAD_GATEWAY,
        )
    return _response({"ok": True})


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordPayload, request: Request) -> JSONResponse:
    del request
    try:
        upstream = await _upstream_request(
            "POST",
            "/reset-password",
            payload={"newPassword": payload.new_password, "token": payload.token},
        )
    except RuntimeError:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)

    if upstream.status_code >= 500:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    if upstream.status_code >= 400:
        return _response(
            {"detail": _upstream_message(upstream, "Link inválido ou expirado")},
            status.HTTP_400_BAD_REQUEST,
        )
    return _response({"ok": True})


async def _access_token_for_session(session_cookie: str) -> str | None:
    session_response = await _upstream_request(
        "GET",
        "/get-session",
        session_cookie=session_cookie,
    )
    if session_response.status_code < 400:
        token = _extract_access_token(_json_payload(session_response))
        if token:
            return token

    for method in ("GET", "POST"):
        token_response = await _upstream_request(
            method,
            "/token",
            session_cookie=session_cookie,
            payload={} if method == "POST" else None,
        )
        if token_response.status_code < 400:
            token = _extract_access_token(_json_payload(token_response))
            if token:
                return token
        if token_response.status_code not in (status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED):
            break
    return None


@router.get("/token")
async def auth_token(request: Request) -> JSONResponse:
    session_state = request.cookies.get(IMOB_SESSION_COOKIE)
    if not session_state:
        return _response({"detail": "Sessão não encontrada"}, status.HTTP_401_UNAUTHORIZED)

    session_cookie = _decode_upstream_cookie(session_state)
    if not session_cookie:
        response = _response({"detail": "Sessão inválida ou expirada"}, status.HTTP_401_UNAUTHORIZED)
        _clear_session_cookie(response)
        return response

    try:
        token = await _access_token_for_session(session_cookie)
    except RuntimeError:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)

    if not token:
        response = _response({"detail": "Sessão inválida ou expirada"}, status.HTTP_401_UNAUTHORIZED)
        _clear_session_cookie(response)
        return response
    return _response({"token": token})


@router.post("/sign-out")
async def sign_out(request: Request) -> JSONResponse:
    session_state = request.cookies.get(IMOB_SESSION_COOKIE)
    session_cookie = _decode_upstream_cookie(session_state or "") if session_state else None
    if session_cookie:
        try:
            await _upstream_request(
                "POST",
                "/sign-out",
                payload={},
                session_cookie=session_cookie,
            )
        except RuntimeError:
            pass

    response = _response({"ok": True})
    _clear_session_cookie(response)
    return response
