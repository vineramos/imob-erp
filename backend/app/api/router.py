from fastapi import APIRouter

from app.api.routes.branding import router as branding_router
from app.api.routes.contracts import router as contracts_router
from app.api.routes.foundation import router as foundation_router
from app.api.routes.health import router as health_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.publication import router as publication_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(branding_router)
api_router.include_router(foundation_router)
api_router.include_router(portfolio_router)
api_router.include_router(contracts_router)
api_router.include_router(integrations_router)
api_router.include_router(publication_router)
