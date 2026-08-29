from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.defaults import ERP_THEME_DEFAULT
from app.domains.foundation.models import AppUser, AuditLog, Organization, OrganizationSettings, Role
from app.domains.foundation.schemas import (
    AuditEventResponse,
    MeResponse,
    OrganizationProfile,
    OrganizationProfileUpdate,
    RoleResponse,
    ThemeConfig,
    UserResponse,
    UserRolesUpdate,
    UserStatusUpdate,
)

router = APIRouter(tags=["foundation"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _organization_or_404(db: Session, context: UserContext) -> Organization:
    organization = db.get(Organization, context.user.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada")
    return organization


def _settings_for_organization(db: Session, context: UserContext) -> OrganizationSettings:
    settings = db.scalar(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == context.user.organization_id)
    )
    if settings is None:
        settings = OrganizationSettings(
            organization_id=context.user.organization_id,
            erp_theme=dict(ERP_THEME_DEFAULT),
            site_theme={},
            operational_defaults={},
            integrations={},
            updated_by_user_id=context.user.id,
        )
        db.add(settings)
        db.flush()
    return settings


def _user_or_404(db: Session, context: UserContext, user_id: UUID) -> AppUser:
    user = db.scalar(
        select(AppUser)
        .options(selectinload(AppUser.roles))
        .where(
            AppUser.id == user_id,
            AppUser.organization_id == context.user.organization_id,
        )
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    return user


def _user_response(user: AppUser) -> UserResponse:
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        is_active=user.is_active and user.blocked_at is None,
        blocked_at=user.blocked_at,
        created_at=user.created_at,
        role_keys=sorted(role.key for role in user.roles if role.is_active),
    )


@router.get("/bootstrap/status")
def bootstrap_status(db: Session = Depends(get_db)) -> dict[str, bool]:
    user_count = db.scalar(select(func.count(AppUser.id))) or 0
    return {"bootstrap_open": user_count == 0}


@router.get("/me", response_model=MeResponse)
def me(
    context: UserContext = Depends(require_permission("dashboard.view")),
    db: Session = Depends(get_db),
) -> MeResponse:
    organization = _organization_or_404(db, context)
    return MeResponse(
        id=context.user.id,
        name=context.user.name,
        email=context.user.email,
        organization_id=context.user.organization_id,
        organization_name=organization.display_name,
        role_keys=sorted(role.key for role in context.user.roles if role.is_active),
        permissions=sorted(context.permission_keys),
    )


@router.get("/settings/company", response_model=OrganizationProfile)
def get_company_settings(
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> OrganizationProfile:
    organization = _organization_or_404(db, context)
    return OrganizationProfile.model_validate(
        {
            "id": organization.id,
            "legal_name": organization.legal_name,
            "display_name": organization.display_name,
            "document_number": organization.document_number,
            "creci_pj": organization.creci_pj,
            "contact_email": organization.contact_email,
            "contact_phone": organization.contact_phone,
            "address": organization.address,
        }
    )


@router.put("/settings/company", response_model=OrganizationProfile)
def update_company_settings(
    payload: OrganizationProfileUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
) -> OrganizationProfile:
    organization = _organization_or_404(db, context)
    before = {
        "legal_name": organization.legal_name,
        "display_name": organization.display_name,
        "document_number": organization.document_number,
        "creci_pj": organization.creci_pj,
        "contact_email": organization.contact_email,
        "contact_phone": organization.contact_phone,
        "address": organization.address,
    }
    after = payload.model_dump(mode="json")

    organization.legal_name = payload.legal_name
    organization.display_name = payload.display_name
    organization.document_number = payload.document_number
    organization.creci_pj = payload.creci_pj
    organization.contact_email = str(payload.contact_email) if payload.contact_email else None
    organization.contact_phone = payload.contact_phone
    organization.address = payload.address.model_dump()

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="settings.company.updated",
        module="settings",
        entity_type="organization",
        entity_id=str(organization.id),
        before_data=before,
        after_data=after,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return get_company_settings(context=context, db=db)


@router.get("/settings/appearance/erp", response_model=ThemeConfig)
def get_erp_theme(
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> ThemeConfig:
    settings = _settings_for_organization(db, context)
    source = settings.erp_theme or ERP_THEME_DEFAULT
    return ThemeConfig.model_validate(source)


@router.put("/settings/appearance/erp", response_model=ThemeConfig)
def update_erp_theme(
    payload: ThemeConfig,
    request: Request,
    context: UserContext = Depends(require_permission("settings.appearance.manage")),
    db: Session = Depends(get_db),
) -> ThemeConfig:
    settings = _settings_for_organization(db, context)
    before = dict(settings.erp_theme or ERP_THEME_DEFAULT)
    after = payload.model_dump(mode="json")
    settings.erp_theme = after
    settings.updated_by_user_id = context.user.id

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="settings.appearance.erp.updated",
        module="settings",
        entity_type="organization_settings",
        entity_id=str(settings.id),
        before_data=before,
        after_data=after,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return payload


@router.get("/settings/roles", response_model=list[RoleResponse])
def get_roles(
    context: UserContext = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> list[RoleResponse]:
    roles = db.scalars(
        select(Role)
        .options(selectinload(Role.permissions), selectinload(Role.users))
        .where(Role.organization_id == context.user.organization_id)
        .order_by(Role.name.asc())
    ).unique().all()

    return [
        RoleResponse(
            id=role.id,
            key=role.key,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            is_active=role.is_active,
            permissions=sorted(permission.key for permission in role.permissions),
            user_count=sum(1 for user in role.users if user.is_active and user.blocked_at is None),
        )
        for role in roles
    ]


@router.get("/settings/users", response_model=list[UserResponse])
def get_users(
    context: UserContext = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    users = db.scalars(
        select(AppUser)
        .options(selectinload(AppUser.roles))
        .where(AppUser.organization_id == context.user.organization_id)
        .order_by(AppUser.name.asc(), AppUser.email.asc())
    ).unique().all()
    return [_user_response(user) for user in users]


@router.patch("/settings/users/{user_id}/status", response_model=UserResponse)
def update_user_status(
    user_id: UUID,
    payload: UserStatusUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> UserResponse:
    target = _user_or_404(db, context, user_id)

    if target.id == context.user.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Você não pode bloquear o próprio usuário administrador em uso.",
        )
    if not payload.is_active and not (payload.reason or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o motivo para bloquear o usuário.",
        )

    before = {
        "is_active": target.is_active,
        "blocked_at": target.blocked_at.isoformat() if target.blocked_at else None,
    }
    target.is_active = payload.is_active
    target.blocked_at = None if payload.is_active else datetime.now(timezone.utc)
    after = {
        "is_active": target.is_active,
        "blocked_at": target.blocked_at.isoformat() if target.blocked_at else None,
    }

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="security.user.enabled" if payload.is_active else "security.user.blocked",
        module="security",
        entity_type="app_user",
        entity_id=str(target.id),
        before_data=before,
        after_data=after,
        reason=(payload.reason or "").strip() or None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(target)
    return _user_response(_user_or_404(db, context, target.id))


@router.put("/settings/users/{user_id}/roles", response_model=UserResponse)
def update_user_roles(
    user_id: UUID,
    payload: UserRolesUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("permissions.manage")),
    db: Session = Depends(get_db),
) -> UserResponse:
    target = _user_or_404(db, context, user_id)
    requested_keys = sorted(set(key.strip() for key in payload.role_keys if key.strip()))
    if not requested_keys:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Selecione ao menos um perfil.")

    roles = db.scalars(
        select(Role).where(
            Role.organization_id == context.user.organization_id,
            Role.key.in_(requested_keys),
            Role.is_active.is_(True),
        )
    ).all()
    found_keys = {role.key for role in roles}
    missing = sorted(set(requested_keys) - found_keys)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Perfil inválido ou inativo: {', '.join(missing)}",
        )

    before_keys = sorted(role.key for role in target.roles if role.is_active)
    if target.id == context.user.id and "admin" in before_keys and "admin" not in requested_keys:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Você não pode remover o próprio perfil Administrador durante a sessão.",
        )
    if before_keys != requested_keys and not (payload.reason or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o motivo da alteração de perfis.",
        )

    target.roles = sorted(roles, key=lambda role: role.key)
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="security.user.roles.updated",
        module="security",
        entity_type="app_user",
        entity_id=str(target.id),
        before_data={"role_keys": before_keys},
        after_data={"role_keys": requested_keys},
        reason=(payload.reason or "").strip() or None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return _user_response(_user_or_404(db, context, target.id))


@router.get("/settings/audit", response_model=list[AuditEventResponse])
def get_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    context: UserContext = Depends(require_permission("audit.view")),
    db: Session = Depends(get_db),
) -> list[AuditEventResponse]:
    rows = db.execute(
        select(AuditLog, AppUser.name)
        .outerjoin(AppUser, AuditLog.actor_user_id == AppUser.id)
        .where(AuditLog.organization_id == context.user.organization_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()

    return [
        AuditEventResponse(
            id=event.id,
            actor_user_id=event.actor_user_id,
            actor_name=actor_name,
            action=event.action,
            module=event.module,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            before_data=event.before_data,
            after_data=event.after_data,
            reason=event.reason,
            ip_address=event.ip_address,
            created_at=event.created_at,
        )
        for event, actor_name in rows
    ]
