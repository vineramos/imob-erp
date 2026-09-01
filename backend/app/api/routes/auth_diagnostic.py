from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

_DIAGNOSTIC_KEY_HASH = "7ffc83223cc62c81d3acec3b35bdf59130de34071f6dea2411d414dc6013a958"


def _mask_email(value: str) -> str:
    source = (value or "").strip().lower()
    if "@" not in source:
        return "<invalid>"
    local, domain = source.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _sanitized(value: Any, key: str = "") -> Any:
    low = key.lower()
    if any(marker in low for marker in ("password", "secret", "token", "private", "credential", "apikey", "api_key")):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _sanitized(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitized(item, key) for item in value]
    if isinstance(value, str):
        source = value.strip()
        if re.fullmatch(r"[^\s@]+@[^\s@]+", source):
            return _mask_email(source)
        if source.startswith(("http://", "https://")):
            parsed = urlsplit(source)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path[:80]}"
        return source[:240]
    return value


def _json_rows(db: Session, schema: str, table: str) -> list[dict[str, Any]]:
    quoted_schema = '"' + schema.replace('"', '""') + '"'
    quoted_table = '"' + table.replace('"', '""') + '"'
    result = db.execute(text(f"SELECT to_jsonb(t) AS payload FROM {quoted_schema}.{quoted_table} AS t"))
    rows: list[dict[str, Any]] = []
    for row in result.mappings():
        payload = row.get("payload")
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _first_key(row: dict[str, Any], *names: str) -> str | None:
    wanted = {re.sub(r"[^a-z0-9]", "", name.lower()) for name in names}
    for key in row:
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalized in wanted:
            return key
    return None


@router.get("/diagnostic", include_in_schema=False)
def auth_diagnostic(
    key: str = Query(..., min_length=20),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    supplied = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(supplied, _DIAGNOSTIC_KEY_HASH):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    erp_rows = db.execute(
        text(
            "SELECT email, auth_user_id::text AS auth_user_id, is_active, "
            "blocked_at IS NOT NULL AS blocked FROM public.app_users ORDER BY email"
        )
    ).mappings().all()

    auth_users = _json_rows(db, "neon_auth", "user")
    auth_accounts = _json_rows(db, "neon_auth", "account")
    project_configs = _json_rows(db, "neon_auth", "project_config")

    auth_email_key = _first_key(auth_users[0], "email") if auth_users else None
    auth_id_key = _first_key(auth_users[0], "id") if auth_users else None
    account_provider_key = _first_key(auth_accounts[0], "providerId", "provider_id", "provider") if auth_accounts else None
    account_user_key = _first_key(auth_accounts[0], "userId", "user_id") if auth_accounts else None

    auth_ids = {
        str(row.get(auth_id_key))
        for row in auth_users
        if auth_id_key and row.get(auth_id_key) is not None
    }
    account_user_ids = {
        str(row.get(account_user_key))
        for row in auth_accounts
        if account_user_key and row.get(account_user_key) is not None
    }
    erp_auth_ids = {str(row["auth_user_id"]) for row in erp_rows if row.get("auth_user_id")}
    providers = Counter(
        str(row.get(account_provider_key) or "<unknown>") for row in auth_accounts
    ) if account_provider_key else Counter()

    return {
        "erp": {
            "user_count": len(erp_rows),
            "active_count": sum(1 for row in erp_rows if bool(row["is_active"]) and not bool(row["blocked"])),
            "emails": [_mask_email(str(row["email"] or "")) for row in erp_rows],
            "linked_to_auth_count": len(erp_auth_ids),
            "linked_ids_found_in_auth": len(erp_auth_ids & auth_ids),
        },
        "neon_auth": {
            "user_count": len(auth_users),
            "emails": [
                _mask_email(str(row.get(auth_email_key) or ""))
                for row in auth_users
            ] if auth_email_key else [],
            "users_with_account_rows": len(auth_ids & account_user_ids),
            "account_providers": dict(providers),
            "project_config_count": len(project_configs),
            "project_config": _sanitized(project_configs[0]) if project_configs else None,
        },
    }
