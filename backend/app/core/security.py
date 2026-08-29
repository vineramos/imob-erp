from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import get_settings

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthIdentity:
    subject: str
    email: str | None
    claims: dict[str, Any]


@lru_cache(maxsize=1)
def get_jwks_client() -> PyJWKClient:
    settings = get_settings()
    jwks_url = settings.effective_neon_auth_jwks_url
    if not jwks_url:
        raise RuntimeError("Neon Auth JWKS não configurado")
    return PyJWKClient(jwks_url, cache_keys=True)


def get_auth_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação necessária")

    token = credentials.credentials
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm not in {"RS256", "ES256", "EdDSA"}:
            raise jwt.InvalidAlgorithmError("Algoritmo JWT não permitido")

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            options={"verify_aud": False, "require": ["exp", "sub"]},
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada") from exc

    subject = str(payload.get("sub", "")).strip()
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identidade inválida")

    email = payload.get("email")
    return AuthIdentity(subject=subject, email=str(email) if email else None, claims=payload)
