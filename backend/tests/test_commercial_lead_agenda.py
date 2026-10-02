from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.agenda.models import AgendaDepartment, AgendaTask
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.portfolio.models import Capture
from app.domains.portfolio.site_models import PublicSiteInquiry
from app.main import app
from tests.helpers import assert_response, create_person, create_property, publish_property


def test_public_site_lead_creates_commercial_agenda_task_and_closes_on_first_contact(client, identity):
    owner = create_person(
        client,
        name="Proprietário Lead Agenda",
        document="83838383838",
        email="owner.lead.agenda@example.com",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    publication = publish_property(client, property_item["id"])
    organization_id = identity["organization_id"]
    slug = publication["public_slug"]

    payload = {
        "name": "Lead Comercial do Site",
        "email": "lead.comercial.agenda@example.com",
        "phone": "(41) 99991-2200",
        "preferred_contact": "whatsapp",
        "message": "Quero visitar este imóvel e entender as condições da locação.",
        "consent": True,
        "website": "",
    }
    assert_response(
        client.post(f"/api/public/sites/{organization_id}/properties/{slug}/inquiries", json=payload),
        201,
    )
    # Reenvio acidental do mesmo contato no mesmo imóvel continua sendo um único lead.
    assert_response(
        client.post(f"/api/public/sites/{organization_id}/properties/{slug}/inquiries", json=payload),
        201,
    )

    assert SessionLocal is not None
    with SessionLocal() as db:
        leads = db.scalars(
            select(PublicSiteInquiry).where(
                PublicSiteInquiry.organization_id == organization_id,
                PublicSiteInquiry.email == payload["email"],
            )
        ).all()
        assert len(leads) == 1
        lead = leads[0]
        assert lead.status == "new"
        assert lead.source == "public_site"
        assert str(lead.property_id) == property_item["id"]

        tasks = db.scalars(
            select(AgendaTask).where(
                AgendaTask.organization_id == organization_id,
                AgendaTask.source_module == "crm",
                AgendaTask.source_type == "site_inquiry",
                AgendaTask.source_id == str(lead.id),
                AgendaTask.reschedule_sequence == 0,
            )
        ).all()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.status == "pending"
        assert task.automatic is True
        assert task.mandatory_action is True
        assert task.completion_source == "source"
        assert f"Imóvel #{lead.property_code}" in task.title
        assert payload["name"] in task.title
        assert "registrar o primeiro atendimento no CRM" in (task.description or "")

        department = db.get(AgendaDepartment, task.department_id)
        assert department is not None
        assert department.name == "Comercial"

        site_captures = db.scalars(
            select(Capture).where(
                Capture.organization_id == organization_id,
                Capture.source == "site",
            )
        ).all()
        assert site_captures == []
        lead_id = lead.id

    current = identity["context"]
    crm_context = UserContext(
        user=current.user,
        permission_keys=current.permission_keys | frozenset({"crm.view", "crm.manage"}),
    )
    app.dependency_overrides[get_current_user_context] = lambda: crm_context

    updated = assert_response(
        client.patch(f"/api/crm/site-inquiries/{lead_id}", json={"status": "contacted"}),
        200,
    ).json()
    assert updated["status"] == "contacted"

    with SessionLocal() as db:
        task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.organization_id == organization_id,
                AgendaTask.source_module == "crm",
                AgendaTask.source_type == "site_inquiry",
                AgendaTask.source_id == str(lead_id),
                AgendaTask.reschedule_sequence == 0,
            )
        )
        assert task is not None
        assert task.status == "completed"
        assert task.completed_at is not None
        assert task.immutable_history is True
        assert task.completion_source == "source"
