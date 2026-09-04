from fastapi import APIRouter

from app.api.routes.agenda import router as agenda_router
from app.api.routes.agenda_history import router as agenda_history_router
from app.api.routes.auth_proxy import router as auth_proxy_router
from app.api.routes.branding import router as branding_router
from app.api.routes.contracts import router as contracts_router
from app.api.routes.deep_links import router as deep_links_router
from app.api.routes.economic_indices import router as economic_indices_router
from app.api.routes.finance import router as finance_router
from app.api.routes.finance_advanced import public_router as portal_router
from app.api.routes.finance_advanced import router as finance_advanced_router
from app.api.routes.finance_advanced import webhook_router as inter_webhook_router
from app.api.routes.finance_bank_control import router as finance_bank_control_router
from app.api.routes.finance_banking import router as finance_banking_router
from app.api.routes.finance_cashflow import router as finance_cashflow_router
from app.api.routes.finance_contracts import router as finance_contracts_router
from app.api.routes.finance_core import router as finance_core_router
from app.api.routes.finance_manual import router as finance_manual_router
from app.api.routes.finance_maintenance import router as finance_maintenance_router
from app.api.routes.finance_overdue import router as finance_overdue_router
from app.api.routes.finance_treasury import router as finance_treasury_router
from app.api.routes.foundation import router as foundation_router
from app.api.routes.health import router as health_router
from app.api.routes.inspections import router as inspections_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.leases import router as leases_router
from app.api.routes.maintenance import router as maintenance_router
from app.api.routes.maintenance_v2 import router as maintenance_v2_router
from app.api.routes.person_bank_details import router as person_bank_details_router
from app.api.routes.person_profile import router as person_profile_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.property_media import router as property_media_router
from app.api.routes.publication import router as publication_router
from app.api.routes.search import router as search_router
from app.api.routes.signature_events import router as signature_events_router
from app.domains.finance.settlement_rules import install_settlement_rule

install_settlement_rule()

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_proxy_router)
api_router.include_router(branding_router)
api_router.include_router(foundation_router)
api_router.include_router(portfolio_router)
api_router.include_router(economic_indices_router)
api_router.include_router(person_bank_details_router)
api_router.include_router(person_profile_router)
api_router.include_router(property_media_router)
api_router.include_router(contracts_router)
api_router.include_router(leases_router)
api_router.include_router(inspections_router)
api_router.include_router(maintenance_router)
api_router.include_router(maintenance_v2_router)
api_router.include_router(finance_router)
api_router.include_router(finance_banking_router)
api_router.include_router(finance_cashflow_router)
api_router.include_router(finance_contracts_router)
api_router.include_router(finance_core_router)
api_router.include_router(finance_manual_router)
api_router.include_router(finance_overdue_router)
api_router.include_router(finance_maintenance_router)
api_router.include_router(finance_treasury_router)
api_router.include_router(finance_bank_control_router)
api_router.include_router(finance_advanced_router)
api_router.include_router(agenda_router)
api_router.include_router(agenda_history_router)
api_router.include_router(search_router)
api_router.include_router(deep_links_router)
api_router.include_router(portal_router)
api_router.include_router(inter_webhook_router)
api_router.include_router(signature_events_router)
api_router.include_router(integrations_router)
api_router.include_router(publication_router)
