from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.defaults import ERP_THEME_DEFAULT
from app.domains.foundation.models import OrganizationSettings
from app.domains.foundation.schemas import ThemeConfig

router = APIRouter(tags=["branding"])


@router.get("/theme/erp", response_model=ThemeConfig)
def get_erp_branding(
    context: UserContext = Depends(require_permission("dashboard.view")),
    db: Session = Depends(get_db),
) -> ThemeConfig:
    settings = db.scalar(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == context.user.organization_id
        )
    )
    source = settings.erp_theme if settings and settings.erp_theme else ERP_THEME_DEFAULT
    return ThemeConfig.model_validate(source)
