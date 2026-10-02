from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.defaults import ERP_THEME_DEFAULT, INTEGRATIONS_DEFAULTS, OPERATIONAL_DEFAULTS, SITE_THEME_DEFAULT
from app.domains.foundation.models import OrganizationSettings
from app.domains.foundation.schemas import SiteThemeConfig

router = APIRouter(tags=["site-settings"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _settings_for_organization(db: Session, context: UserContext) -> OrganizationSettings:
    settings = db.scalar(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == context.user.organization_id)
    )
    if settings is None:
        settings = OrganizationSettings(
            organization_id=context.user.organization_id,
            erp_theme=dict(ERP_THEME_DEFAULT),
            site_theme=dict(SITE_THEME_DEFAULT),
            operational_defaults=dict(OPERATIONAL_DEFAULTS),
            integrations=dict(INTEGRATIONS_DEFAULTS),
            updated_by_user_id=context.user.id,
        )
        db.add(settings)
        db.flush()
    return settings


def _site_theme(settings: OrganizationSettings) -> SiteThemeConfig:
    source = {**SITE_THEME_DEFAULT, **dict(settings.site_theme or {})}
    return SiteThemeConfig.model_validate(source)


@router.get("/settings/appearance/site", response_model=SiteThemeConfig)
def get_site_theme(
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
) -> SiteThemeConfig:
    return _site_theme(_settings_for_organization(db, context))


@router.put("/settings/appearance/site", response_model=SiteThemeConfig)
def update_site_theme(
    payload: SiteThemeConfig,
    request: Request,
    context: UserContext = Depends(require_permission("settings.appearance.manage")),
    db: Session = Depends(get_db),
) -> SiteThemeConfig:
    settings = _settings_for_organization(db, context)
    before = _site_theme(settings).model_dump(mode="json")
    after = payload.model_dump(mode="json")
    settings.site_theme = after
    settings.updated_by_user_id = context.user.id

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="settings.appearance.site.updated",
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


@router.post("/settings/appearance/site/reset", response_model=SiteThemeConfig)
def reset_site_theme(
    request: Request,
    context: UserContext = Depends(require_permission("settings.appearance.manage")),
    db: Session = Depends(get_db),
) -> SiteThemeConfig:
    settings = _settings_for_organization(db, context)
    before = _site_theme(settings).model_dump(mode="json")
    payload = SiteThemeConfig.model_validate(SITE_THEME_DEFAULT)
    after = payload.model_dump(mode="json")
    settings.site_theme = after
    settings.updated_by_user_id = context.user.id

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="settings.appearance.site.reset",
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
