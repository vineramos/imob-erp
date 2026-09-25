from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.security import AuthIdentity
from app.domains.foundation.defaults import ERP_THEME_DEFAULT, OPERATIONAL_DEFAULTS
from app.domains.foundation.models import AppUser, Organization, OrganizationSettings, Permission, Role
from app.domains.foundation.permissions import PERMISSIONS
from app.domains.foundation.role_templates import ROLE_TEMPLATES


def bootstrap_first_admin(db: Session, identity: AuthIdentity) -> AppUser | None:
    settings = get_settings()
    configured_email = settings.bootstrap_admin_email.strip().lower()
    identity_email = (identity.email or "").strip().lower()

    if not configured_email or identity_email != configured_email:
        return None

    existing_users = db.scalar(select(func.count(AppUser.id))) or 0
    if existing_users > 0:
        return None

    organization = Organization(
        legal_name="Imobiliária",
        display_name="Imobiliária",
        contact_email=identity_email,
        address={},
    )
    db.add(organization)
    db.flush()

    permission_map: dict[str, Permission] = {}
    for definition in PERMISSIONS:
        permission = Permission(
            key=definition.key,
            module=definition.module,
            name=definition.name,
            description=definition.description,
        )
        db.add(permission)
        permission_map[definition.key] = permission
    db.flush()

    role_map: dict[str, Role] = {}
    for template in ROLE_TEMPLATES:
        role = Role(
            organization_id=organization.id,
            key=template.key,
            name=template.name,
            description=template.description,
            is_system=True,
            is_active=True,
        )
        role.permissions = [permission_map[key] for key in sorted(template.permissions)]
        db.add(role)
        role_map[template.key] = role
    db.flush()

    display_name = str(identity.claims.get("name") or identity_email.split("@", 1)[0]).strip()
    user = AppUser(
        organization_id=organization.id,
        auth_user_id=identity.subject,
        name=display_name or "Administrador",
        email=identity_email,
        is_active=True,
    )
    user.roles = [role_map["admin"]]
    db.add(user)
    db.flush()

    org_settings = OrganizationSettings(
        organization_id=organization.id,
        erp_theme=dict(ERP_THEME_DEFAULT),
        site_theme={},
        operational_defaults=dict(OPERATIONAL_DEFAULTS),
        integrations={},
        updated_by_user_id=user.id,
    )
    db.add(org_settings)
    db.commit()

    stmt = (
        select(AppUser)
        .options(selectinload(AppUser.roles).selectinload(Role.permissions))
        .where(AppUser.id == user.id)
    )
    return db.scalar(stmt)
