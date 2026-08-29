from fastapi import APIRouter

from app.api.routes.branding import router as branding_router
from app.api.routes.foundation import router as foundation_router
from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(branding_router)
api_router.include_router(foundation_router)
