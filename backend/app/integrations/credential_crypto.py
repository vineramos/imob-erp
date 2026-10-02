from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class CredentialCryptoError(RuntimeError):
    pass


def _key() -> bytes:
    settings = get_settings()
    material = settings.credentials_encryption_key.strip() or settings.database_url.strip()
    if not material:
        raise CredentialCryptoError("A chave de criptografia de credenciais não está configurada.")
    return hashlib.sha256(f"imob-erp:integration-credentials:v1:{material}".encode()).digest()


def encrypt_secret(value: str, *, scope: str) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, value.encode(), scope.encode())
    return "v1." + base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt_secret(value: str, *, scope: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(value.removeprefix("v1."))
        return AESGCM(_key()).decrypt(raw[:12], raw[12:], scope.encode()).decode()
    except Exception as exc:
        raise CredentialCryptoError("Não foi possível abrir a credencial protegida.") from exc
