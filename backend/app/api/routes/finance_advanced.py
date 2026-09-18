from fastapi import APIRouter

from app.api.routes.finance_billing import router as billing_router
from app.api.routes.finance_classifications import router as classifications_router
from app.api.routes.finance_commissions import router as commissions_router
from app.api.routes.finance_delinquency import router as delinquency_router
from app.api.routes.finance_inter import router as inter_router, webhook_router
from app.api.routes.finance_portal import admin_router as portal_admin_router, public_router
from app.api.routes.finance_reports import legacy_router as legacy_reports_router, router as reports_router

router = APIRouter(prefix="/finance/advanced", tags=["finance-advanced"])
router.include_router(billing_router)
router.include_router(delinquency_router)
router.include_router(reports_router)
router.include_router(legacy_reports_router)
router.include_router(commissions_router)
router.include_router(classifications_router)
router.include_router(portal_admin_router)
router.include_router(inter_router)

__all__ = ["router", "public_router", "webhook_router"]
