from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.agenda.models import AgendaTask
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.portfolio.models import Person, PersonRole
from app.main import app
from tests.helpers import _run_signature_flow, assert_response, create_person, create_property, publish_property


def _next_weekday(days_ahead: int = 3) -> date:
    value = date.today() + timedelta(days=days_ahead)
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def _public_inquiry(client, organization_id: str, slug: str, *, name: str, email: str, phone: str) -> None:
    assert_response(client.post(f"/api/public/sites/{organization_id}/properties/{slug}/inquiries", json={"name": name,"email": email,"phone": phone,"preferred_contact": "whatsapp","message": "Quero conhecer o imóvel e avaliar uma proposta de locação.","consent": True,"website": ""}), 201)


def test_site_lead_flows_through_visit_proposal_contract_and_closes_competitors(client, identity):
    owner = create_person(client,name="Proprietário Funil",document="81818181818",email="owner.funnel@example.com",role_keys=["owner"])
    property_item = create_property(client, owner["id"])
    publication = publish_property(client, property_item["id"])
    organization_id = str(identity["organization_id"])
    slug = publication["public_slug"]
    _public_inquiry(client, organization_id, slug, name="Interessado Principal", email="principal@example.com", phone="(41) 99991-1001")
    _public_inquiry(client, organization_id, slug, name="Interessado Concorrente", email="concorrente@example.com", phone="(41) 99991-1002")

    current = identity["context"]
    crm_context = UserContext(user=current.user,permission_keys=current.permission_keys | frozenset({"crm.view", "crm.manage"}))
    app.dependency_overrides[get_current_user_context] = lambda: crm_context
    inquiries = assert_response(client.get("/api/crm/site-inquiries")).json()
    by_email = {item["email"]: item for item in inquiries}
    principal, competitor = by_email["principal@example.com"], by_email["concorrente@example.com"]

    visit_start = datetime.combine(_next_weekday(), time(hour=17), tzinfo=timezone.utc)
    visit = assert_response(client.post(f"/api/crm/site-inquiries/{principal['id']}/visits",json={"starts_at": visit_start.isoformat(),"duration_minutes": 60,"notes": "Visita criada pelo funil comercial automatizado."}),201).json()
    assert visit["status"] == "scheduled" and visit["agenda_task_id"]
    funnel = assert_response(client.get(f"/api/crm/site-inquiries/{principal['id']}/funnel")).json()
    assert funnel["inquiry"]["status"] == "visit_scheduled" and funnel["person"] is not None and funnel["person"]["name"] == "Interessado Principal"
    linked_person_id = funnel["person"]["id"]

    assert SessionLocal is not None
    with SessionLocal() as db:
        person = db.get(Person, UUID(linked_person_id)); assert person is not None
        tenant_role = db.scalar(select(PersonRole).where(PersonRole.person_id == person.id, PersonRole.role_key == "tenant")); assert tenant_role is not None and tenant_role.is_active is True
        agenda = db.get(AgendaTask, UUID(visit["agenda_task_id"])); assert agenda is not None and agenda.source_module == "crm" and agenda.source_type == "commercial_visit" and agenda.source_id == visit["id"] and agenda.status == "pending"

    completed = assert_response(client.patch(f"/api/crm/visits/{visit['id']}", json={"status": "completed", "notes": None})).json(); assert completed["status"] == "completed"
    with SessionLocal() as db:
        agenda = db.get(AgendaTask, UUID(visit["agenda_task_id"])); assert agenda is not None and agenda.status == "completed"

    proposal_start = date.today() + timedelta(days=20)
    proposal_payload = {"rent_amount":"1950.00","start_date":proposal_start.isoformat(),"term_months":30,"guarantee_type":"insurance","notes":"Condição negociada no atendimento comercial."}
    proposal = assert_response(client.post(f"/api/crm/site-inquiries/{principal['id']}/proposals", json=proposal_payload),201).json()
    competing_proposal = assert_response(client.post(f"/api/crm/site-inquiries/{competitor['id']}/proposals",json={**proposal_payload,"rent_amount":"2000.00","notes":"Proposta concorrente."}),201).json()
    assert proposal["person_id"] == linked_person_id and competing_proposal["status"] == "submitted"
    proposal = assert_response(client.patch(f"/api/crm/proposals/{proposal['id']}", json={"status":"accepted","reason":None})).json()
    competing_proposal = assert_response(client.patch(f"/api/crm/proposals/{competing_proposal['id']}", json={"status":"accepted","reason":None})).json()
    assert proposal["status"] == "accepted" and competing_proposal["status"] == "accepted"

    composition = assert_response(client.get(f"/api/crm/proposals/{proposal['id']}/lease-composition")).json()
    assert Decimal(str(composition["rent_amount"])) == Decimal("1950.00")
    assert {row["key"] for row in composition["monthly_charges"]} >= {"iptu","condo","guarantee_insurance","fire_insurance"}
    assert next(row for row in composition["monthly_charges"] if row["key"] == "fire_insurance")["frequency"] == "annual"

    conversion = assert_response(client.post(f"/api/crm/proposals/{proposal['id']}/convert-to-lease", json={"monthly_charges":composition["monthly_charges"]}),201).json()
    assert conversion["lease_status"] == "draft" and conversion["lease_code"].startswith("LOC-") and conversion["proposal"]["status"] == "converted"

    properties = assert_response(client.get("/api/properties")).json(); current_property = next(item for item in properties if item["id"] == property_item["id"])
    assert current_property["status"] == "available" and current_property["publication_enabled"] is True
    signed = _run_signature_flow(client, kind="lease", contract_id=conversion["lease_contract_id"]); assert signed["status"] == "signed"
    properties = assert_response(client.get("/api/properties")).json(); current_property = next(item for item in properties if item["id"] == property_item["id"])
    assert current_property["status"] == "leased" and current_property["publication_enabled"] is False

    principal_funnel = assert_response(client.get(f"/api/crm/site-inquiries/{principal['id']}/funnel")).json()
    competitor_funnel = assert_response(client.get(f"/api/crm/site-inquiries/{competitor['id']}/funnel")).json()
    assert principal_funnel["inquiry"]["status"] == "won" and principal_funnel["proposals"][0]["status"] == "won" and principal_funnel["proposals"][0]["lease_code"] == conversion["lease_code"]
    assert competitor_funnel["inquiry"]["status"] == "lost" and competitor_funnel["proposals"][0]["status"] == "rejected" and competitor_funnel["proposals"][0]["closed_reason"] == "Imóvel locado por outra proposta."
