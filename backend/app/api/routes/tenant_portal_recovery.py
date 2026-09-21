from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.advanced_models import PortalAccess
from app.domains.foundation.models import Organization
from app.domains.leases.models import LeaseContract
from app.domains.portal.models import PortalAccount, PortalPasswordChallenge, PortalSession
from app.domains.portal.security import hash_password, normalize_email, token_digest, verify_password
from app.domains.portfolio.models import Person
from app.integrations.email import EmailDeliveryError, send_portal_verification_email, smtp_config_for_organization, smtp_configured

router = APIRouter(prefix="/tenant-portal/auth/access", tags=["tenant-portal"])
CHALLENGE_MINUTES = 10
RESEND_SECONDS = 60
MAX_CODE_ATTEMPTS = 5
GENERIC_MESSAGE = (
    "Se o e-mail estiver vinculado a uma locação habilitada, enviaremos um código de 6 dígitos."
)


class PortalAccessRequest(BaseModel):
    email: str = Field(min_length=3, max_length=180)
    purpose: Literal["first_access", "forgot_password"] = "first_access"


class PortalAccessConfirm(BaseModel):
    email: str = Field(min_length=3, max_length=180)
    code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=8, max_length=200)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None)


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


def _eligible_person(db: Session, email: str) -> Person | None:
    account = db.scalar(select(PortalAccount).where(PortalAccount.email == email))
    if account is not None:
        person = db.get(Person, account.person_id)
        if (
            account.is_active
            and person is not None
            and person.is_active
            and normalize_email(person.email or "") == email
            and _has_tenant_lease(db, person)
        ):
            return person
        return None

    people = db.scalars(
        select(Person).where(
            Person.is_active.is_(True),
            func.lower(func.trim(Person.email)) == email,
        )
    ).all()
    eligible = [person for person in people if _has_tenant_lease(db, person)]
    return eligible[0] if len(eligible) == 1 else None


def _latest_access(db: Session, person: Person) -> PortalAccess | None:
    return db.scalar(
        select(PortalAccess)
        .where(
            PortalAccess.organization_id == person.organization_id,
            PortalAccess.person_id == person.id,
        )
        .order_by(PortalAccess.created_at.desc())
        .limit(1)
    )


def _revoked(access: PortalAccess | None) -> bool:
    return access is not None and (not access.is_active or access.revoked_at is not None)


@router.post("/request")
def request_access_code(
    payload: PortalAccessRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    email = normalize_email(payload.email)
    generic = {
        "message": GENERIC_MESSAGE,
        "expires_in_seconds": CHALLENGE_MINUTES * 60,
        "resend_after_seconds": RESEND_SECONDS,
    }
    person = _eligible_person(db, email)
    if person is None:
        return generic

    access = _latest_access(db, person)
    if _revoked(access):
        return generic

    recent = db.scalar(
        select(PortalPasswordChallenge)
        .where(
            PortalPasswordChallenge.person_id == person.id,
            PortalPasswordChallenge.email == email,
            PortalPasswordChallenge.used_at.is_(None),
            PortalPasswordChallenge.expires_at > now,
            PortalPasswordChallenge.created_at >= now - timedelta(seconds=RESEND_SECONDS),
        )
        .order_by(PortalPasswordChallenge.created_at.desc())
        .limit(1)
    )
    if recent is not None:
        return generic

    for challenge in db.scalars(
        select(PortalPasswordChallenge).where(
            PortalPasswordChallenge.person_id == person.id,
            PortalPasswordChallenge.used_at.is_(None),
        )
    ).all():
        challenge.used_at = now

    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = PortalPasswordChallenge(
        organization_id=person.organization_id,
        person_id=person.id,
        email=email,
        purpose=payload.purpose,
        code_hash=hash_password(code),
        expires_at=now + timedelta(minutes=CHALLENGE_MINUTES),
        attempts=0,
        max_attempts=MAX_CODE_ATTEMPTS,
        requested_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(challenge)
    db.flush()

    organization = db.get(Organization, person.organization_id)
    try:
        smtp_config = smtp_config_for_organization(db, person.organization_id)
        if not (smtp_configured() or smtp_config.configured):
            raise EmailDeliveryError("O envio de e-mail do Portal do Inquilino ainda não está configurado.")
        send_portal_verification_email(
            recipient=email,
            code=code,
            organization_name=organization.display_name if organization else "Imobiliária",
            purpose=payload.purpose,
            config=smtp_config,
        )
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    db.commit()
    return generic


@router.post("/confirm")
def confirm_access_code(
    payload: PortalAccessConfirm,
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    email = normalize_email(payload.email)
    challenge = db.scalar(
        select(PortalPasswordChallenge)
        .where(
            PortalPasswordChallenge.email == email,
            PortalPasswordChallenge.used_at.is_(None),
        )
        .order_by(PortalPasswordChallenge.created_at.desc())
        .limit(1)
    )
    if (
        challenge is None
        or challenge.expires_at <= now
        or challenge.attempts >= challenge.max_attempts
    ):
        raise HTTPException(status_code=422, detail="Código inválido ou expirado.")

    if not verify_password(payload.code, challenge.code_hash):
        challenge.attempts += 1
        if challenge.attempts >= challenge.max_attempts:
            challenge.used_at = now
        db.commit()
        raise HTTPException(status_code=422, detail="Código inválido ou expirado.")

    person = db.get(Person, challenge.person_id)
    if (
        person is None
        or not person.is_active
        or normalize_email(person.email or "") != email
        or not _has_tenant_lease(db, person)
    ):
        challenge.used_at = now
        db.commit()
        raise HTTPException(status_code=422, detail="Código inválido ou expirado.")

    access = _latest_access(db, person)
    if _revoked(access):
        challenge.used_at = now
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="O acesso ao portal está desativado pela imobiliária.",
        )

    if access is None:
        access = PortalAccess(
            organization_id=person.organization_id,
            person_id=person.id,
            portal_type="tenant",
            token_hash=token_digest(secrets.token_urlsafe(48)),
            label="Portal do Inquilino",
            is_active=True,
            expires_at=now + timedelta(days=3650),
            created_by_user_id=None,
        )
        db.add(access)
        db.flush()

    conflict = db.scalar(
        select(PortalAccount).where(
            PortalAccount.email == email,
            PortalAccount.person_id != person.id,
        )
    )
    if conflict is not None:
        challenge.used_at = now
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="Este e-mail já está vinculado a outra conta de portal.",
        )

    account = db.scalar(select(PortalAccount).where(PortalAccount.person_id == person.id))
    password_hash = hash_password(payload.password)
    if account is None:
        account = PortalAccount(
            organization_id=person.organization_id,
            person_id=person.id,
            portal_access_id=access.id,
            email=email,
            password_hash=password_hash,
            is_active=True,
            password_changed_at=now,
            created_by_user_id=None,
        )
        db.add(account)
        db.flush()
    else:
        if not account.is_active:
            challenge.used_at = now
            db.commit()
            raise HTTPException(
                status_code=403,
                detail="A conta do portal está desativada pela imobiliária.",
            )
        account.portal_access_id = access.id
        account.email = email
        account.password_hash = password_hash
        account.failed_attempts = 0
        account.locked_until = None
        account.password_changed_at = now

    for session in db.scalars(
        select(PortalSession).where(PortalSession.account_id == account.id)
    ).all():
        db.delete(session)

    challenge.used_at = now
    db.commit()
    return {
        "message": "Senha criada com sucesso. Agora você já pode entrar no portal.",
        "login_path": "/portal",
    }
