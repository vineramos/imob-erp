from fastapi import APIRouter

from app.api.routes.branding import router as branding_router
from app.api.routes.contracts import router as contracts_router
from app.api.routes.finance import router as finance_router
from app.api.routes.finance_contracts import router as finance_contracts_router
from app.api.routes.foundation import router as foundation_router
from app.api.routes.health import router as health_router
from app.api.routes.inspections import router as inspections_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.leases import router as leases_router
from app.api.routes.maintenance import router as maintenance_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.property_media import router as property_media_router
from app.api.routes.publication import router as publication_router
from app.api.routes.signature_events import router as signature_events_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(branding_router)
api_router.include_router(foundation_router)
api_router.include_router(portfolio_router)
api_router.include_router(property_media_router)
api_router.include_router(contracts_router)
api_router.include_router(leases_router)
api_router.include_router(inspections_router)
api_router.include_router(maintenance_router)
api_router.include_router(finance_router)
api_router.include_router(finance_contracts_router)
api_router.include_router(signature_events_router)
api_router.include_router(integrations_router)
api_router.include_router(publication_router)
