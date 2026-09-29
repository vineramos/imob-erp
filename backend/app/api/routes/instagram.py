from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.integrations.instagram import (
    DEFAULT_GRAPH_VERSION,
    checked_at,
    credential_row,
    credentials,
    save_credentials,
    validate_account,
)

router = APIRouter(tags=["instagram"])


class InstagramConfigurationResponse(BaseModel):
    provider: str = "instagram_meta"
    graph_version: str = DEFAULT_GRAPH_VERSION
    account_id: str = ""
    username: str = ""
    token_configured: bool = False
    configured: bool = False
    reachable: bool | None = None
    account_type: str | None = None
    message: str = ""
    checked_at: datetime | None = None


class InstagramConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_version: str = Field(default=DEFAULT_GRAPH_VERSION, pattern=r"^v\d+\.\d+$", max_length=16)
    account_id: str = Field(default="", max_length=120)
    username: str = Field(default="", max_length=120)
    access_token: str | None = Field(default=None, max_length=2000)


class InstagramTestResponse(BaseModel):
    configured: bool
    reachable: bool
    account_id: str
    username: str
    account_type: str | None = None
    message: str
    checked_at: datetime


def _response(db: Session, organization_id: UUID) -> InstagramConfigurationResponse:
    creds = credentials(db, organization_id)
    return InstagramConfigurationResponse(
        graph_version=creds.graph_version,
        account_id=creds.account_id,
        username=creds.username,
        token_configured=bool(creds.access_token),
        configured=creds.configured,
        reachable=None,
        message=(
            "Credencial protegida salva. Execute o teste para validar a conta profissional na Meta."
            if creds.configured
            else "Cole o token gerado no Meta for Developers e salve a integração."
        ),
    )


@router.get("/meta-instagram/config", response_model=InstagramConfigurationResponse)
def get_instagram_configuration(
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> InstagramConfigurationResponse:
    return _response(db, context.user.organization_id)


@router.put("/meta-instagram/config", response_model=InstagramConfigurationResponse)
def update_instagram_configuration(
    payload: InstagramConfigurationUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> InstagramConfigurationResponse:
    before = _response(db, context.user.organization_id).model_dump(mode="json")
    row = save_credentials(
        db,
        context.user.organization_id,
        user_id=context.user.id,
        graph_version=payload.graph_version,
        account_id=payload.account_id,
        username=payload.username,
        access_token=payload.access_token,
    )
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action="settings.integrations.instagram.updated",
        module="settings",
        entity_type="organization_integration_credential",
        entity_id=str(row.id),
        before_data=before,
        after_data={
            "provider": "instagram_meta",
            "graph_version": payload.graph_version,
            "account_id": payload.account_id.strip(),
            "username": payload.username.strip(),
            "token_configured": True,
        },
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return _response(db, context.user.organization_id)


@router.post("/meta-instagram/test", response_model=InstagramTestResponse)
def test_instagram_configuration(
    request: Request,
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> InstagramTestResponse:
    creds = credentials(db, context.user.organization_id)
    if not creds.access_token:
        raise HTTPException(status_code=422, detail="Salve primeiro o Access Token do Instagram.")
    account = validate_account(creds)
    account_id = str(account.get("id") or "").strip()
    username = str(account.get("username") or "").strip()
    account_type = str(account.get("account_type") or "").strip() or None

    row = credential_row(db, context.user.organization_id)
    if row is None:
        raise HTTPException(status_code=422, detail="Configuração do Instagram não encontrada.")
    config = dict(row.non_secret_config or {})
    config["account_id"] = account_id
    config["username"] = username
    config["last_tested_at"] = checked_at().isoformat()
    config["last_test_status"] = "success"
    row.non_secret_config = config
    row.updated_by_user_id = context.user.id

    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action="settings.integrations.instagram.tested",
        module="settings",
        entity_type="organization_integration_credential",
        entity_id=str(row.id),
        after_data={"account_id": account_id, "username": username, "account_type": account_type, "reachable": True},
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return InstagramTestResponse(
        configured=True,
        reachable=True,
        account_id=account_id,
        username=username,
        account_type=account_type,
        message=f"Instagram conectado à conta @{username}." if username else "Conta profissional do Instagram validada.",
        checked_at=checked_at(),
    )
