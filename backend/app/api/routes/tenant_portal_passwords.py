from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.advanced_models import PortalAccess
from app.domains.foundation.access import UserContext, require_permission
from app.domains.leases.models import LeaseContract
from app.domains.portal.models import PortalAccount, PortalSession, PortalTemporaryCredential
from app.domains.portal.security import hash_password, new_session_token, normalize_email, token_digest, verify_password
from app.domains.portfolio.models import Person

public_router = APIRouter(prefix="/tenant-portal/auth", tags=["tenant-portal"])
admin_router = APIRouter(prefix="/finance/advanced/portal", tags=["finance-advanced"])

COOKIE_NAME = "imob_portal_session"
SESSION_DAYS = 30
LOCK_MINUTES = 15
MAX_FAILED_ATTEMPTS = 5
TEMPORARY_PASSWORD_DAYS = 7
CHANGE_TOKEN_MINUTES = 15
MAX_TEMP_ATTEMPTS = 5
TEMP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


class DocumentLoginRequest(BaseModel):
    identifier: str = Field(min_length=5, max_length=30)
    password: str = Field(min_length=8, max_length=200)


class TemporaryPasswordChangeRequest(BaseModel):
    identifier: str = Field(min_length=5, max_length=30)
    change_token: str = Field(min_length=32, max_length=200)
    password: str = Field(min_length=8, max_length=200)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None)


def _document_identifier(value: str | None) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _new_temporary_password() -> str:
    return "-".join(
        "".join(secrets.choice(TEMP_ALPHABET) for _ in range(4))
        for _ in range(3)
    )


def _has_tenant_lease(db: Session, person: Person) -> bool:
    rows = db.scalars(
        select(LeaseContract).where(LeaseContract.organization_id == person.organization_id)
    ).all()
    person_id = str(person.id)
    return any(
        any(
            isinstance(entry, dict) and str(entry.get("person_id") or "") == person_id
            for entry in list(lease.tenant_snapshot or [])
        )
        for lease in rows
    )


def _active_access(db: Session, person: Person) -> PortalAccess | None:
    return db.scalar(
        select(PortalAccess)
        .where(
            PortalAccess.organization_id == person.organization_id,
            PortalAccess.person_id == person.id,
            PortalAccess.is_active.is_(True),
            PortalAccess.revoked_at.is_(None),
        )
        .order_by(PortalAccess.created_at.desc())
        .limit(1)
    )


def _person_for_identifier(db: Session, identifier: str) -> Person | None:
    normalized = _document_identifier(identifier)
    if len(normalized) not in {11, 14}:
        return None
    people = db.scalars(
        select(Person).where(
            Person.is_active.is_(True),
            func.regexp_replace(func.coalesce(Person.document_number, ""), "[^0-9]", "", "g") == normalized,
        )
    ).all()
    eligible = [person for person in people if _active_access(db, person) is not None and _has_tenant_lease(db, person)]
    return eligible[0] if len(eligible) == 1 else None


def _account_for_person(db: Session, person: Person) -> PortalAccount | None:
    return db.scalar(select(PortalAccount).where(PortalAccount.person_id == person.id))


def _latest_temporary(db: Session, person: Person, now: datetime) -> PortalTemporaryCredential | None:
    return db.scalar(
        select(PortalTemporaryCredential)
        .where(
            PortalTemporaryCredential.person_id == person.id,
            PortalTemporaryCredential.used_at.is_(None),
            PortalTemporaryCredential.expires_at > now,
        )
        .order_by(PortalTemporaryCredential.created_at.desc())
        .limit(1)
    )


def _set_session_cookie(response: Response, request: Request, raw_token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def _create_session(
    db: Session,
    *,
    account: PortalAccount,
    access: PortalAccess,
    request: Request,
    response: Response,
    now: datetime,
) -> None:
    raw_token = new_session_token()
    db.add(
        PortalSession(
            account_id=account.id,
            token_hash=token_digest(raw_token),
            expires_at=now + timedelta(days=SESSION_DAYS),
            last_seen_at=now,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    )
    account.last_login_at = now
    account.failed_attempts = 0
    account.locked_until = None
    access.last_used_at = now
    _set_session_cookie(response, request, raw_token)


@admin_router.get("/temporary-credentials")
def list_temporary_credentials(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(PortalTemporaryCredential)
        .where(
            PortalTemporaryCredential.organization_id == context.user.organization_id,
            PortalTemporaryCredential.used_at.is_(None),
            PortalTemporaryCredential.expires_at > now,
        )
        .order_by(PortalTemporaryCredential.created_at.desc())
    ).all()
    latest: dict[UUID, PortalTemporaryCredential] = {}
    for row in rows:
        latest.setdefault(row.portal_access_id, row)
    return [
        {
            "id": str(row.id),
            "access_id": str(row.portal_access_id),
            "person_id": str(row.person_id),
            "expires_at": row.expires_at,
            "attempts": row.attempts,
            "max_attempts": row.max_attempts,
            "created_at": row.created_at,
        }
        for row in latest.values()
    ]


@admin_router.post("/access/{access_id}/temporary-password")
def issue_temporary_password(
    access_id: UUID,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> dict:
    access = db.scalar(
        select(PortalAccess).where(
            PortalAccess.id == access_id,
            PortalAccess.organization_id == context.user.organization_id,
        )
    )
    if access is None:
        raise HTTPException(status_code=404, detail="Acesso externo não encontrado.")
    if not access.is_active or access.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Reative o acesso externo antes de gerar uma nova senha temporária.")

    person = db.scalar(
        select(Person).where(
            Person.id == access.person_id,
            Person.organization_id == context.user.organization_id,
            Person.is_active.is_(True),
        )
    )
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa vinculada ao acesso não encontrada.")
    if not _has_tenant_lease(db, person):
        raise HTTPException(status_code=422, detail="A pessoa não possui contrato de locação como inquilino.")

    identifier = _document_identifier(person.document_number)
    if len(identifier) not in {11, 14}:
        raise HTTPException(status_code=422, detail="Cadastre um CPF ou CNPJ válido na pessoa antes de liberar o Portal do Inquilino.")

    now = datetime.now(timezone.utc)
    for credential in db.scalars(
        select(PortalTemporaryCredential).where(
            PortalTemporaryCredential.person_id == person.id,
            PortalTemporaryCredential.used_at.is_(None),
        )
    ).all():
        credential.used_at = now

    temporary_password = _new_temporary_password()
    credential = PortalTemporaryCredential(
        organization_id=context.user.organization_id,
        person_id=person.id,
        portal_access_id=access.id,
        password_hash=hash_password(temporary_password),
        expires_at=now + timedelta(days=TEMPORARY_PASSWORD_DAYS),
        attempts=0,
        max_attempts=MAX_TEMP_ATTEMPTS,
        issued_by_user_id=context.user.id,
    )
    db.add(credential)

    account = _account_for_person(db, person)
    if account is not None:
        account.password_hash = hash_password(secrets.token_urlsafe(48))
        account.failed_attempts = 0
        account.locked_until = None
        for session in db.scalars(select(PortalSession).where(PortalSession.account_id == account.id)).all():
            db.delete(session)

    db.commit()
    return {
        "access_id": str(access.id),
        "person_id": str(person.id),
        "person_name": person.name,
        "login_identifier": person.document_number or identifier,
        "temporary_password": temporary_password,
        "expires_at": credential.expires_at,
        "login_path": "/portal",
        "must_change_password": True,
    }


@public_router.post("/document-login")
def document_login(
    payload: DocumentLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    person = _person_for_identifier(db, payload.identifier)
    if person is None:
        raise HTTPException(status_code=401, detail="CPF/CNPJ ou senha inválidos.")
    access = _active_access(db, person)
    if access is None:
        raise HTTPException(status_code=403, detail="O acesso ao portal está desativado pela imobiliária.")

    temporary = _latest_temporary(db, person, now)
    if temporary is not None:
        if temporary.attempts >= temporary.max_attempts:
            raise HTTPException(status_code=429, detail="Muitas tentativas incorretas. Solicite uma nova senha temporária à imobiliária.")
        if not verify_password(payload.password, temporary.password_hash):
            temporary.attempts += 1
            db.commit()
            raise HTTPException(status_code=401, detail="CPF/CNPJ ou senha inválidos.")
        raw_change_token = new_session_token()
        temporary.change_token_hash = token_digest(raw_change_token)
        temporary.change_token_expires_at = now + timedelta(minutes=CHANGE_TOKEN_MINUTES)
        temporary.attempts = 0
        db.commit()
        return {
            "person_name": person.name,
            "login_identifier": person.document_number,
            "must_change_password": True,
            "change_token": raw_change_token,
            "change_token_expires_in_seconds": CHANGE_TOKEN_MINUTES * 60,
        }

    account = _account_for_person(db, person)
    if account is None or not account.is_active:
        raise HTTPException(status_code=401, detail="CPF/CNPJ ou senha inválidos.")
    if account.locked_until and account.locked_until > now:
        raise HTTPException(status_code=429, detail="Muitas tentativas incorretas. Tente novamente em alguns minutos.")
    if not verify_password(payload.password, account.password_hash):
        account.failed_attempts += 1
        if account.failed_attempts >= MAX_FAILED_ATTEMPTS:
            account.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            account.failed_attempts = 0
        db.commit()
        raise HTTPException(status_code=401, detail="CPF/CNPJ ou senha inválidos.")

    _create_session(db, account=account, access=access, request=request, response=response, now=now)
    db.commit()
    return {
        "person_name": person.name,
        "login_identifier": person.document_number,
        "must_change_password": False,
    }


@public_router.post("/temporary-change")
def change_temporary_password(
    payload: TemporaryPasswordChangeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    person = _person_for_identifier(db, payload.identifier)
    if person is None:
        raise HTTPException(status_code=422, detail="A solicitação de troca de senha não é mais válida.")
    access = _active_access(db, person)
    if access is None:
        raise HTTPException(status_code=403, detail="O acesso ao portal está desativado pela imobiliária.")

    credential = _latest_temporary(db, person, now)
    if (
        credential is None
        or not credential.change_token_hash
        or not credential.change_token_expires_at
        or credential.change_token_expires_at <= now
        or not secrets.compare_digest(token_digest(payload.change_token), credential.change_token_hash)
    ):
        raise HTTPException(status_code=422, detail="A solicitação de troca de senha não é mais válida. Entre novamente com a senha temporária.")
    if verify_password(payload.password, credential.password_hash):
        raise HTTPException(status_code=422, detail="Escolha uma senha diferente da senha temporária.")

    account = _account_for_person(db, person)
    real_email = normalize_email(person.email or "")
    login_storage = real_email or _document_identifier(person.document_number)
    conflict = db.scalar(
        select(PortalAccount).where(
            PortalAccount.email == login_storage,
            PortalAccount.person_id != person.id,
        )
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail="Este identificador já está vinculado a outra conta de portal.")

    if account is None:
        account = PortalAccount(
            organization_id=person.organization_id,
            person_id=person.id,
            portal_access_id=access.id,
            email=login_storage,
            password_hash=hash_password(payload.password),
            is_active=True,
            password_changed_at=now,
            created_by_user_id=credential.issued_by_user_id,
        )
        db.add(account)
        db.flush()
    else:
        account.portal_access_id = access.id
        account.email = login_storage
        account.password_hash = hash_password(payload.password)
        account.is_active = True
        account.failed_attempts = 0
        account.locked_until = None
        account.password_changed_at = now
        for session in db.scalars(select(PortalSession).where(PortalSession.account_id == account.id)).all():
            db.delete(session)

    credential.used_at = now
    credential.change_token_hash = None
    credential.change_token_expires_at = None
    _create_session(db, account=account, access=access, request=request, response=response, now=now)
    db.commit()
    return {
        "person_name": person.name,
        "login_identifier": person.document_number,
        "must_change_password": False,
        "message": "Senha pessoal criada com sucesso.",
    }
