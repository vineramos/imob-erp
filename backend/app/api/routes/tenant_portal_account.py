from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.tenant_portal import COOKIE_NAME, PortalIdentity, require_portal_identity
from app.core.database import get_db
from app.domains.portal.models import PortalSession
from app.domains.portal.security import hash_password, token_digest, verify_password

router = APIRouter(prefix="/tenant-portal/account", tags=["tenant-portal"])


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> Response:
    account = identity.account
    if not verify_password(payload.current_password, account.password_hash):
        raise HTTPException(status_code=422, detail="A senha atual informada não confere.")
    if verify_password(payload.new_password, account.password_hash):
        raise HTTPException(status_code=422, detail="Escolha uma senha diferente da senha atual.")

    account.password_hash = hash_password(payload.new_password)
    account.password_changed_at = datetime.now(timezone.utc)
    account.failed_attempts = 0
    account.locked_until = None

    current_token = token_digest(request.cookies.get(COOKIE_NAME, "").strip())
    sessions = db.scalars(select(PortalSession).where(PortalSession.account_id == account.id)).all()
    for session in sessions:
        if session.token_hash != current_token:
            db.delete(session)

    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
