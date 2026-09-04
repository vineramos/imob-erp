from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.documents import _content_response, _load as load_document, _system_reference
from app.core.database import get_db
from app.domains.documents.context import context_catalog
from app.domains.finance.advanced_models import BillingItem, PortalAccess
from app.domains.finance.models import RentCharge
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.models import Organization
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.portal.models import PortalAccount, PortalSession
from app.domains.portal.security import hash_password, new_session_token, normalize_email, token_digest, verify_password
from app.domains.portfolio.models import Person, Property
from app.integrations.document_storage import DocumentStorageError, get_document_storage

public_router = APIRouter(prefix="/tenant-portal", tags=["tenant-portal"])
admin_router = APIRouter(prefix="/finance/advanced/portal", tags=["finance-advanced"])
COOKIE_NAME = "imob_portal_session"
SESSION_DAYS = 30
LOCK_MINUTES = 15
MAX_FAILED_ATTEMPTS = 5
ZERO = Decimal("0.00")


class PortalLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=180)
    password: str = Field(min_length=8, max_length=200)


class PortalCredentialsRequest(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class PortalMaintenanceCreate(BaseModel):
    lease_contract_id: UUID
    title: str = Field(min_length=3, max_length=180)
    category: str = Field(default="general", min_length=2, max_length=40)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    description: str = Field(min_length=5, max_length=5000)


@dataclass(frozen=True)
class PortalIdentity:
    account: PortalAccount
    person: Person
    access: PortalAccess


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None)


def _active_access(db: Session, account: PortalAccount) -> PortalAccess:
    access = db.get(PortalAccess, account.portal_access_id)
    if access is None or not access.is_active or access.revoked_at is not None:
        raise HTTPException(status_code=403, detail="O acesso ao portal está desativado pela imobiliária.")
    return access


def require_portal_identity(request: Request, db: Session = Depends(get_db)) -> PortalIdentity:
    raw = request.cookies.get(COOKIE_NAME, "").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Faça login para acessar o portal.")
    now = datetime.now(timezone.utc)
    session = db.scalar(select(PortalSession).where(PortalSession.token_hash == token_digest(raw)))
    if session is None or session.expires_at <= now:
        if session is not None:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=401, detail="Sua sessão expirou. Entre novamente.")
    account = db.get(PortalAccount, session.account_id)
    if account is None or not account.is_active:
        raise HTTPException(status_code=401, detail="A conta do portal está desativada.")
    access = _active_access(db, account)
    person = db.get(Person, account.person_id)
    if person is None or not person.is_active:
        raise HTTPException(status_code=401, detail="O cadastro vinculado ao portal não está ativo.")
    session.last_seen_at = now
    access.last_used_at = now
    db.commit()
    return PortalIdentity(account=account, person=person, access=access)


def _tenant_leases(db: Session, identity: PortalIdentity) -> list[LeaseContract]:
    rows = db.scalars(
        select(LeaseContract).where(LeaseContract.organization_id == identity.account.organization_id)
    ).all()
    person_id = str(identity.person.id)
    result = [
        item for item in rows
        if any(isinstance(entry, dict) and str(entry.get("person_id") or "") == person_id for entry in list(item.tenant_snapshot or []))
    ]
    result.sort(key=lambda item: (item.status != "signed", item.start_date), reverse=False)
    return result


def _property_map(db: Session, leases: list[LeaseContract]) -> dict[UUID, Property]:
    ids = list({item.property_id for item in leases})
    if not ids:
        return {}
    return {item.id: item for item in db.scalars(select(Property).where(Property.id.in_(ids))).all()}


def _address(prop: Property | None, lease: LeaseContract) -> dict:
    if prop is not None:
        return dict(prop.address or {})
    return dict((lease.property_snapshot or {}).get("address") or {})


def _lease_payload(lease: LeaseContract, prop: Property | None) -> dict:
    return {
        "id": str(lease.id),
        "code": f"LOC-{lease.internal_number:06d}",
        "status": lease.status,
        "property_id": str(lease.property_id),
        "property_code": f"{prop.internal_number:06d}" if prop else str((lease.property_snapshot or {}).get("code") or "—"),
        "property_address": _address(prop, lease),
        "rent_amount": float(lease.rent_amount),
        "due_day": lease.due_day,
        "start_date": lease.start_date,
        "end_date": lease.end_date,
        "operational_end_date": lease.operational_end_date,
        "adjustment_index": lease.adjustment_index,
        "adjustment_period_months": lease.adjustment_period_months,
        "next_adjustment_date": lease.next_adjustment_date,
        "guarantee_type": lease.guarantee_type,
        "signed_at": lease.signed_at,
    }


def _document_rows(db: Session, identity: PortalIdentity, leases: list[LeaseContract]) -> list[dict]:
    unique: dict[str, object] = {}
    for lease in leases:
        for row in context_catalog(
            db,
            organization_id=identity.account.organization_id,
            entity_type="lease_contract",
            entity_id=lease.id,
        ) or []:
            if row.entity_type in {"lease_contract", "inspection"}:
                unique[row.key] = row
    ordered = sorted(unique.values(), key=lambda row: row.updated_at or row.created_at, reverse=True)
    return [
        {
            "key": row.key,
            "title": row.title,
            "category": row.category,
            "filename": row.filename,
            "content_type": row.content_type,
            "status": row.status,
            "entity_label": row.entity_label,
            "updated_at": row.updated_at,
            "download_path": f"/tenant-portal/documents/{row.key}/content",
        }
        for row in ordered
    ]


def _allowed_document_keys(db: Session, identity: PortalIdentity) -> set[str]:
    keys: set[str] = set()
    for lease in _tenant_leases(db, identity):
        rows = context_catalog(
            db,
            organization_id=identity.account.organization_id,
            entity_type="lease_contract",
            entity_id=lease.id,
        ) or []
        keys.update(row.key for row in rows if row.entity_type in {"lease_contract", "inspection"})
    return keys


def _charge_belongs_to_identity(db: Session, identity: PortalIdentity, charge: RentCharge) -> bool:
    return any(lease.id == charge.lease_contract_id for lease in _tenant_leases(db, identity))


@admin_router.get("/accounts")
def portal_accounts(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.scalars(
        select(PortalAccount)
        .where(PortalAccount.organization_id == context.user.organization_id)
        .order_by(PortalAccount.updated_at.desc())
    ).all()
    return [
        {
            "id": str(item.id),
            "access_id": str(item.portal_access_id),
            "person_id": str(item.person_id),
            "email": item.email,
            "is_active": item.is_active,
            "last_login_at": item.last_login_at,
            "locked_until": item.locked_until,
            "password_changed_at": item.password_changed_at,
        }
        for item in rows
    ]


@admin_router.post("/access/{access_id}/credentials")
def configure_portal_credentials(
    access_id: UUID,
    payload: PortalCredentialsRequest,
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
    person = db.scalar(
        select(Person).where(Person.id == access.person_id, Person.organization_id == context.user.organization_id)
    )
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa vinculada ao acesso não encontrada.")
    email = normalize_email(person.email or "")
    if not email:
        raise HTTPException(status_code=422, detail="Cadastre um e-mail na pessoa antes de configurar o login do portal.")
    conflict = db.scalar(select(PortalAccount).where(PortalAccount.email == email, PortalAccount.person_id != person.id))
    if conflict is not None:
        raise HTTPException(status_code=409, detail="Este e-mail já está vinculado a outra conta de portal.")
    account = db.scalar(select(PortalAccount).where(PortalAccount.person_id == person.id))
    now = datetime.now(timezone.utc)
    if account is None:
        account = PortalAccount(
            organization_id=context.user.organization_id,
            person_id=person.id,
            portal_access_id=access.id,
            email=email,
            password_hash=hash_password(payload.password),
            is_active=True,
            password_changed_at=now,
            created_by_user_id=context.user.id,
        )
        db.add(account)
        db.flush()
    else:
        account.portal_access_id = access.id
        account.email = email
        account.password_hash = hash_password(payload.password)
        account.is_active = True
        account.failed_attempts = 0
        account.locked_until = None
        account.password_changed_at = now
        for session in db.scalars(select(PortalSession).where(PortalSession.account_id == account.id)).all():
            db.delete(session)
    access.is_active = True
    access.revoked_at = None
    db.commit()
    return {
        "id": str(account.id),
        "access_id": str(access.id),
        "person_id": str(person.id),
        "email": account.email,
        "is_active": True,
        "login_path": "/portal",
    }


@public_router.post("/auth/login")
def portal_login(payload: PortalLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    email = normalize_email(payload.email)
    account = db.scalar(select(PortalAccount).where(PortalAccount.email == email))
    if account is None or not account.is_active:
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")
    if account.locked_until and account.locked_until > now:
        raise HTTPException(status_code=429, detail="Muitas tentativas incorretas. Tente novamente em alguns minutos.")
    if not verify_password(payload.password, account.password_hash):
        account.failed_attempts += 1
        if account.failed_attempts >= MAX_FAILED_ATTEMPTS:
            account.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            account.failed_attempts = 0
        db.commit()
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")
    access = _active_access(db, account)
    person = db.get(Person, account.person_id)
    if person is None or not person.is_active:
        raise HTTPException(status_code=401, detail="O cadastro vinculado ao portal não está ativo.")
    raw_token = new_session_token()
    session = PortalSession(
        account_id=account.id,
        token_hash=token_digest(raw_token),
        expires_at=now + timedelta(days=SESSION_DAYS),
        last_seen_at=now,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    account.failed_attempts = 0
    account.locked_until = None
    account.last_login_at = now
    access.last_used_at = now
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return {"person_name": person.name, "email": account.email}


@public_router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def portal_logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    raw = request.cookies.get(COOKIE_NAME, "").strip()
    if raw:
        session = db.scalar(select(PortalSession).where(PortalSession.token_hash == token_digest(raw)))
        if session is not None:
            db.delete(session)
            db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@public_router.get("/me")
def portal_me(identity: PortalIdentity = Depends(require_portal_identity), db: Session = Depends(get_db)) -> dict:
    organization = db.get(Organization, identity.account.organization_id)
    return {
        "person_id": str(identity.person.id),
        "person_name": identity.person.name,
        "email": identity.account.email,
        "document_number": identity.person.document_number,
        "organization_name": organization.display_name if organization else "Imobiliária",
        "organization_email": organization.contact_email if organization else None,
        "organization_phone": organization.contact_phone if organization else None,
    }


@public_router.get("/overview")
def portal_overview(identity: PortalIdentity = Depends(require_portal_identity), db: Session = Depends(get_db)) -> dict:
    organization = db.get(Organization, identity.account.organization_id)
    leases = _tenant_leases(db, identity)
    lease_ids = [item.id for item in leases]
    properties = _property_map(db, leases)
    charges = db.scalars(
        select(RentCharge)
        .where(RentCharge.organization_id == identity.account.organization_id, RentCharge.lease_contract_id.in_(lease_ids))
        .order_by(RentCharge.due_date.desc())
        .limit(200)
    ).all() if lease_ids else []
    billing = {
        item.charge_id: item
        for item in db.scalars(select(BillingItem).where(BillingItem.charge_id.in_([charge.id for charge in charges]))).all()
    } if charges else {}
    charge_rows = []
    open_amount = ZERO
    for charge in charges:
        bill = billing.get(charge.id)
        if charge.status in {"generated", "sent", "overdue"}:
            open_amount += Decimal(str(charge.gross_amount))
        charge_rows.append({
            "id": str(charge.id),
            "code": f"COB-{charge.internal_number:06d}",
            "lease_contract_id": str(charge.lease_contract_id),
            "competence": charge.competence,
            "due_date": charge.due_date,
            "amount": float(charge.gross_amount),
            "status": charge.status,
            "paid_at": charge.paid_at,
            "paid_amount": float(charge.paid_amount) if charge.paid_amount is not None else None,
            "boleto_line": bill.boleto_line if bill else None,
            "pix_copy_paste": bill.pix_copy_paste if bill else None,
            "billing_pdf_available": bool(bill and bill.pdf_reference),
        })
    maintenance = db.scalars(
        select(MaintenanceRequest)
        .where(MaintenanceRequest.organization_id == identity.account.organization_id, MaintenanceRequest.lease_contract_id.in_(lease_ids))
        .order_by(MaintenanceRequest.reported_at.desc())
        .limit(100)
    ).all() if lease_ids else []
    inspections = db.scalars(
        select(Inspection)
        .where(Inspection.organization_id == identity.account.organization_id, Inspection.lease_contract_id.in_(lease_ids))
        .order_by(Inspection.created_at.desc())
    ).all() if lease_ids else []
    next_open = next((row for row in sorted(charges, key=lambda item: item.due_date) if row.status in {"generated", "sent", "overdue"}), None)
    return {
        "person": {
            "id": str(identity.person.id),
            "name": identity.person.name,
            "email": identity.account.email,
            "document_number": identity.person.document_number,
        },
        "organization": {
            "name": organization.display_name if organization else "Imobiliária",
            "email": organization.contact_email if organization else None,
            "phone": organization.contact_phone if organization else None,
        },
        "metrics": {
            "active_leases": sum(1 for item in leases if item.status == "signed"),
            "open_amount": float(open_amount),
            "open_charges": sum(1 for item in charges if item.status in {"generated", "sent", "overdue"}),
            "maintenance_open": sum(1 for item in maintenance if item.status not in {"completed", "cancelled"}),
            "next_due_date": next_open.due_date if next_open else None,
        },
        "leases": [_lease_payload(item, properties.get(item.property_id)) for item in leases],
        "charges": charge_rows,
        "documents": _document_rows(db, identity, leases),
        "inspections": [
            {
                "id": str(item.id),
                "code": f"VIS-{item.internal_number:06d}",
                "lease_contract_id": str(item.lease_contract_id),
                "inspection_type": item.inspection_type,
                "status": item.status,
                "scheduled_at": item.scheduled_at,
                "performed_at": item.performed_at,
                "contest_deadline": item.contest_deadline,
                "finalized_at": item.finalized_at,
                "report_available": bool(item.report_reference),
            }
            for item in inspections
        ],
        "maintenance": [
            {
                "id": str(item.id),
                "code": f"MAN-{item.internal_number:06d}",
                "lease_contract_id": str(item.lease_contract_id) if item.lease_contract_id else None,
                "title": item.title,
                "category": item.category,
                "priority": item.priority,
                "status": item.status,
                "description": item.description,
                "reported_at": item.reported_at,
                "scheduled_at": item.scheduled_at,
                "completed_at": item.completed_at,
            }
            for item in maintenance
        ],
    }


@public_router.post("/maintenance", status_code=status.HTTP_201_CREATED)
def portal_create_maintenance(
    payload: PortalMaintenanceCreate,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> dict:
    lease = next((item for item in _tenant_leases(db, identity) if item.id == payload.lease_contract_id), None)
    if lease is None:
        raise HTTPException(status_code=404, detail="Contrato de locação não encontrado neste portal.")
    if lease.status != "signed":
        raise HTTPException(status_code=409, detail="Chamados novos só podem ser abertos para uma locação ativa.")
    now = datetime.now(timezone.utc)
    item = MaintenanceRequest(
        organization_id=identity.account.organization_id,
        property_id=lease.property_id,
        lease_contract_id=lease.id,
        requester_person_id=identity.person.id,
        title=payload.title.strip(),
        category=payload.category.strip().lower(),
        priority=payload.priority,
        status="requested",
        description=payload.description.strip(),
        responsibility="pending",
        approval_required=True,
        history=[{"at": now.isoformat(), "action": "requested", "source": "tenant_portal", "note": "Chamado aberto pelo locatário."}],
        reported_at=now,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": str(item.id), "code": f"MAN-{item.internal_number:06d}", "status": item.status, "reported_at": item.reported_at}


@public_router.get("/charges/{charge_id}/billing.pdf")
def portal_billing_pdf(
    charge_id: UUID,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> Response:
    charge = db.scalar(select(RentCharge).where(RentCharge.id == charge_id, RentCharge.organization_id == identity.account.organization_id))
    if charge is None or not _charge_belongs_to_identity(db, identity, charge):
        raise HTTPException(status_code=404, detail="Cobrança não encontrada neste portal.")
    billing = db.scalar(select(BillingItem).where(BillingItem.charge_id == charge.id))
    if billing is None or not billing.pdf_reference:
        raise HTTPException(status_code=404, detail="PDF da cobrança ainda não está disponível.")
    try:
        content = get_document_storage().download_bytes(billing.pdf_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _content_response(content, content_type="application/pdf", filename=f"{charge.internal_number:06d}-cobranca.pdf")


@public_router.get("/documents/{document_key}/content")
def portal_document_content(
    document_key: str,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> Response:
    if document_key not in _allowed_document_keys(db, identity):
        raise HTTPException(status_code=404, detail="Documento não encontrado neste portal.")
    parts = document_key.split(":")
    if len(parts) == 2 and parts[0] == "managed":
        document_id = UUID(parts[1])
        item = load_document(db, identity.account.organization_id, document_id)
        version = next((row for row in item.versions if row.version_number == item.current_version), None)
        if version is None:
            raise HTTPException(status_code=404, detail="Versão do documento não encontrada.")
        try:
            content = get_document_storage().download_bytes(version.storage_reference)
        except DocumentStorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _content_response(content, content_type=version.content_type, filename=version.original_filename)
    if len(parts) == 4 and parts[0] == "system":
        entity_type, entity_id_raw, variant = parts[1], parts[2], parts[3]
        reference, filename = _system_reference(db, identity.account.organization_id, entity_type, UUID(entity_id_raw), variant)
        try:
            content = get_document_storage().download_bytes(reference)
        except DocumentStorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _content_response(content, content_type="application/pdf", filename=filename)
    raise HTTPException(status_code=422, detail="Identificador de documento inválido.")
