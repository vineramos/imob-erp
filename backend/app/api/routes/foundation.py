from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.defaults import ERP_THEME_DEFAULT
from app.domains.foundation.models import Organization, OrganizationSettings
from app.domains.foundation.schemas import MeResponse, OrganizationProfile, OrganizationProfileUpdate, ThemeConfig

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
