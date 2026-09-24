from fastapi import APIRouter

from app.api.routes.agenda import router as agenda_router
from app.api.routes.agenda_history import router as agenda_history_router
from app.api.routes.agenda_operations import router as agenda_operations_router
from app.api.routes.auth_proxy import router as auth_proxy_router
from app.api.routes.branding import router as branding_router
from app.api.routes.capture_workflow import router as capture_workflow_router
from app.api.routes.commercial import router as commercial_router
from app.api.routes.communications import router as communications_router
from app.api.routes.contracts import router as contracts_router
from app.api.routes.deep_links import router as deep_links_router
from app.api.routes.document_context import router as document_context_router
from app.api.routes.documents import router as documents_router
from app.api.routes.economic_indices import router as economic_indices_router
from app.api.routes.finance import router as finance_router
from app.api.routes.finance_advanced import public_router as portal_router
from app.api.routes.finance_advanced import router as finance_advanced_router
from app.api.routes.finance_advanced import webhook_router as inter_webhook_router
from app.api.routes.finance_bank_control import router as finance_bank_control_router
from app.api.routes.finance_bank_setup import router as finance_bank_setup_router
from app.api.routes.finance_banking import router as finance_banking_router
from app.api.routes.finance_cashflow import router as finance_cashflow_router
from app.api.routes.finance_contracts import router as finance_contracts_router
from app.api.routes.finance_core import router as finance_core_router
from app.api.routes.finance_manual import router as finance_manual_router
from app.api.routes.finance_monthly_cycle import router as finance_monthly_cycle_router
from app.api.routes.finance_maintenance import router as finance_maintenance_router
from app.api.routes.finance_overdue import router as finance_overdue_router
from app.api.routes.finance_reports import router as finance_reports_router
from app.api.routes.finance_treasury import router as finance_treasury_router
from app.api.routes.foundation import router as foundation_router
from app.api.routes.health import router as health_router
from app.api.routes.inspections import router as inspections_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.lease_exit import router as lease_exit_router
from app.api.routes.leases import router as leases_router
from app.api.routes.lease_lifecycle import router as lease_lifecycle_router
from app.api.routes.maintenance import router as maintenance_router
from app.api.routes.maintenance_v2 import router as maintenance_v2_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.owner_portal import context_router as portal_context_router
from app.api.routes.owner_portal import router as owner_portal_router
from app.api.routes.owner_portal_reports import router as owner_portal_reports_router
from app.api.routes.people_lifecycle import router as people_lifecycle_router
from app.api.routes.person_bank_details import router as person_bank_details_router
from app.api.routes.person_profile import router as person_profile_router
from app.api.routes.person_media import router as person_media_router
from app.api.routes.person_insights import router as person_insights_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.portal_feeds import router as portal_feeds_router
from app.api.routes.property_lifecycle import router as property_lifecycle_router
from app.api.routes.property_media import router as property_media_router
from app.api.routes.public_captures import router as public_captures_router
from app.api.routes.public_map import router as public_map_router
from app.api.routes.publication import router as publication_router
from app.api.routes.reports import router as reports_router
from app.api.routes.search import router as search_router
from app.api.routes.signature_events import router as signature_events_router
from app.api.routes.site_settings import router as site_settings_router
from app.api.routes.tenant_portal import admin_router as tenant_portal_admin_router
from app.api.routes.tenant_portal import public_router as tenant_portal_router
from app.api.routes.tenant_portal_account import router as tenant_portal_account_router
from app.api.routes.tenant_portal_charges import router as tenant_portal_charges_router
from app.api.routes.tenant_portal_experience import router as tenant_portal_experience_router
from app.api.routes.tenant_portal_passwords import admin_router as tenant_portal_password_admin_router
from app.api.routes.tenant_portal_passwords import public_router as tenant_portal_password_router
from app.api.routes.tenant_portal_recovery import router as tenant_portal_recovery_router
from app.api.routes.tenant_portal_reports import router as tenant_portal_reports_router
from app.domains.agenda.commercial_lead_rules import install_commercial_lead_agenda_rule
from app.domains.agenda.communication_rules import install_communication_agenda_rule
from app.domains.agenda.lease_handover_rules import install_lease_handover_agenda_rule
from app.domains.agenda.operational_rules import install_operational_agenda_rules
from app.domains.agenda.source_chain_rules import install_source_chain_rule
from app.domains.agenda.timezone_rules import install_event_collection_timezone_rule
from app.domains.communications.lease_exit_event_rules import install_lease_exit_communication_rules
from app.domains.communications.operational_event_rules import install_operational_communication_rules
from app.domains.communications.schedule_reconciliation_rules import install_schedule_reconciliation_rules
from app.domains.finance.late_charges import install_late_payment_contract_rule
from app.domains.finance.settlement_rules import install_settlement_rule
from app.domains.portfolio.commercial_rules import install_commercial_lease_rule

install_source_chain_rule()
install_event_collection_timezone_rule()
install_commercial_lead_agenda_rule()
install_communication_agenda_rule()
install_operational_agenda_rules()
install_lease_handover_agenda_rule()
install_operational_communication_rules()
install_schedule_reconciliation_rules()
install_lease_exit_communication_rules()
install_late_payment_contract_rule()
install_settlement_rule()
install_commercial_lease_rule()

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_proxy_router)
api_router.include_router(branding_router)
api_router.include_router(foundation_router)
api_router.include_router(site_settings_router)
api_router.include_router(portfolio_router)
api_router.include_router(portal_feeds_router)
api_router.include_router(property_lifecycle_router)
api_router.include_router(people_lifecycle_router)
api_router.include_router(capture_workflow_router)
api_router.include_router(economic_indices_router)
api_router.include_router(person_bank_details_router)
api_router.include_router(person_profile_router)
api_router.include_router(person_media_router)
api_router.include_router(person_insights_router)
api_router.include_router(property_media_router)
api_router.include_router(contracts_router)
api_router.include_router(leases_router)
api_router.include_router(lease_lifecycle_router)
api_router.include_router(lease_exit_router)
api_router.include_router(inspections_router)
api_router.include_router(maintenance_router)
api_router.include_router(maintenance_v2_router)
api_router.include_router(finance_router)
api_router.include_router(finance_banking_router)
api_router.include_router(finance_bank_setup_router)
api_router.include_router(finance_cashflow_router)
api_router.include_router(finance_contracts_router)
api_router.include_router(finance_core_router)
api_router.include_router(finance_manual_router)
api_router.include_router(finance_monthly_cycle_router)
api_router.include_router(finance_overdue_router)
api_router.include_router(finance_reports_router)
api_router.include_router(finance_maintenance_router)
api_router.include_router(finance_treasury_router)
api_router.include_router(finance_bank_control_router)
api_router.include_router(finance_advanced_router)
api_router.include_router(communications_router)
api_router.include_router(tenant_portal_admin_router)
api_router.include_router(tenant_portal_password_admin_router)
api_router.include_router(agenda_router)
api_router.include_router(agenda_operations_router)
api_router.include_router(agenda_history_router)
api_router.include_router(reports_router)
api_router.include_router(documents_router)
api_router.include_router(document_context_router)
api_router.include_router(search_router)
api_router.include_router(deep_links_router)
api_router.include_router(notifications_router)
api_router.include_router(portal_router)
api_router.include_router(tenant_portal_recovery_router)
api_router.include_router(tenant_portal_password_router)
api_router.include_router(tenant_portal_account_router)
api_router.include_router(tenant_portal_router)
api_router.include_router(tenant_portal_charges_router)
api_router.include_router(tenant_portal_experience_router)
api_router.include_router(tenant_portal_reports_router)
api_router.include_router(portal_context_router)
api_router.include_router(owner_portal_router)
api_router.include_router(owner_portal_reports_router)
api_router.include_router(inter_webhook_router)
api_router.include_router(signature_events_router)
api_router.include_router(integrations_router)
api_router.include_router(public_captures_router)
api_router.include_router(public_map_router)
api_router.include_router(publication_router)
api_router.include_router(commercial_router)