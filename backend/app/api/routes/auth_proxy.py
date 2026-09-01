from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

IMOB_SESSION_COOKIE = "imob_auth_session"
UPSTREAM_SESSION_COOKIE = "__Secure-neonauth.session_token"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7


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


def _auth_origin(request: Request) -> str:
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if origin:
        return origin

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip()
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip()
    proto = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def _auth_endpoint(path: str) -> str:
    base = get_settings().neon_auth_url.strip().rstrip("/")
    if not base:
        raise RuntimeError("Neon Auth não configurado")
    return f"{base}{path if path.startswith('/') else f'/{path}'}"


async def _upstream_request(
    method: str,
    path: str,
    *,
    request: Request,
    payload: dict[str, Any] | None = None,
    session_token: str | None = None,
) -> httpx.Response:
    headers = {"Accept": "application/json"}
    origin = _auth_origin(request)
    if origin:
        headers["Origin"] = origin
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if session_token:
        headers["Cookie"] = f"{UPSTREAM_SESSION_COOKIE}={session_token}"

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


def _extract_session_token(response: httpx.Response) -> str | None:
    for raw_cookie in response.headers.get_list("set-cookie"):
        pair = raw_cookie.split(";", 1)[0]
        name, separator, value = pair.partition("=")
        normalized_name = name.strip().lower()
        if separator and ("session_token" in normalized_name or "session-token" in normalized_name):
            token = value.strip().strip('"')
            if token:
                return token

    payload = _json_payload(response)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    session = data.get("session") if isinstance(data, dict) else None
    if isinstance(session, dict):
        token = session.get("token")
        if isinstance(token, str) and token.strip():
            return token.strip()
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


def _set_session_cookie(response: JSONResponse, session_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=IMOB_SESSION_COOKIE,
        value=session_token,
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

    session_token = _extract_session_token(upstream)
    if not session_token:
        return _response(
            {"detail": "A autenticação foi aceita, mas a sessão segura não foi criada"},
            status.HTTP_502_BAD_GATEWAY,
        )

    access_token = _extract_access_token(_json_payload(upstream))
    payload: dict[str, Any] = {"ok": True}
    if access_token:
        payload["token"] = access_token
    response = _response(payload)
    _set_session_cookie(response, session_token)
    return response


@router.post("/sign-in")
async def sign_in(payload: SignInPayload, request: Request) -> JSONResponse:
    try:
        upstream = await _upstream_request(
            "POST",
            "/sign-in/email",
            request=request,
            payload={"email": payload.email.strip().lower(), "password": payload.password},
        )
    except RuntimeError:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    return await _complete_sign_in(upstream, invalid_message="Confira e-mail e senha")


@router.post("/sign-up")
async def sign_up(payload: SignUpPayload, request: Request) -> JSONResponse:
    try:
        upstream = await _upstream_request(
            "POST",
            "/sign-up/email",
            request=request,
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


@router.post("/request-password-reset")
async def request_password_reset(payload: PasswordResetRequestPayload, request: Request) -> JSONResponse:
    try:
        upstream = await _upstream_request(
            "POST",
            "/request-password-reset",
            request=request,
            payload={"email": payload.email.strip().lower(), "redirectTo": payload.redirect_to},
        )
    except RuntimeError:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)

    if upstream.status_code >= 500:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    # Não revela se o endereço existe ou não.
    return _response({"ok": True})


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordPayload, request: Request) -> JSONResponse:
    try:
        upstream = await _upstream_request(
            "POST",
            "/reset-password",
            request=request,
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


async def _access_token_for_session(session_token: str, request: Request) -> str | None:
    session_response = await _upstream_request(
        "GET",
        "/get-session",
        request=request,
        session_token=session_token,
    )
    if session_response.status_code < 400:
        token = _extract_access_token(_json_payload(session_response))
        if token:
            return token

    # Compatibilidade com versões do Managed Better Auth em que o JWT é
    # exposto por endpoint próprio, mantendo get-session como primeira opção.
    for method in ("GET", "POST"):
        token_response = await _upstream_request(
            method,
            "/token",
            request=request,
            session_token=session_token,
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
    session_token = request.cookies.get(IMOB_SESSION_COOKIE)
    if not session_token:
        return _response({"detail": "Sessão não encontrada"}, status.HTTP_401_UNAUTHORIZED)

    try:
        token = await _access_token_for_session(session_token, request)
    except RuntimeError:
        return _response({"detail": "Serviço de autenticação temporariamente indisponível"}, status.HTTP_503_SERVICE_UNAVAILABLE)

    if not token:
        response = _response({"detail": "Sessão inválida ou expirada"}, status.HTTP_401_UNAUTHORIZED)
        _clear_session_cookie(response)
        return response
    return _response({"token": token})


@router.post("/sign-out")
async def sign_out(request: Request) -> JSONResponse:
    session_token = request.cookies.get(IMOB_SESSION_COOKIE)
    if session_token:
        try:
            await _upstream_request(
                "POST",
                "/sign-out",
                request=request,
                payload={},
                session_token=session_token,
            )
        except RuntimeError:
            pass

    response = _response({"ok": True})
    _clear_session_cookie(response)
    return response
