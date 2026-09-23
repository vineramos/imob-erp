"""Property broker and CRM user are separate assignments; keep their records coherent."""

from app.domains.foundation.access import UserContext, get_current_user_context
from app.main import app
from tests.helpers import assert_response, create_person, create_property, publish_property


def test_property_broker_appears_in_crm_and_broker_leads_without_user_link(client, identity):
    owner = create_person(
        client, name="Proprietário Vínculo", document="73737373737",
        email="owner.broker.link@example.com", role_keys=["owner"],
    )
    prop = create_property(client, owner["id"])
    broker = create_person(
        client, name="Corretor de Testes", document="74747474747",
        email="unlinked.broker@example.com", role_keys=["broker"],
    )
    assigned = assert_response(client.patch(
        f"/api/properties/{prop['id']}/responsible-broker",
        json={"broker_person_id": broker["id"]},
    )).json()
    assert assigned["responsible_broker_person_id"] == broker["id"]
    publication = publish_property(client, prop["id"])
    assert_response(client.post(
        f"/api/public/sites/{identity['organization_id']}/properties/{publication['public_slug']}/inquiries",
        json={
            "name": "Interessado Teste", "email": "lead.broker.link@example.com",
            "phone": "(41) 99999-1234", "preferred_contact": "whatsapp",
            "message": "Quero visitar o imóvel.", "consent": True, "website": "",
        },
    ), 201)

    original = identity["context"]
    crm = UserContext(
        user=original.user,
        permission_keys=original.permission_keys | frozenset({"crm.view", "crm.manage"}),
    )
    app.dependency_overrides[get_current_user_context] = lambda: crm
    inquiries = assert_response(client.get("/api/crm/site-inquiries")).json()
    assert len(inquiries) == 1
    lead = inquiries[0]
    assert lead["responsible_user_id"] is None
    assert lead["property_broker_person_id"] == broker["id"]
    assert lead["property_broker_name"] == broker["name"]

    funnel = assert_response(client.get(f"/api/crm/site-inquiries/{lead['id']}/funnel")).json()
    assert funnel["property_broker"]["id"] == broker["id"]
    assert funnel["responsible"] is None

    activity = assert_response(client.get(f"/api/crm/brokers/{broker['id']}/activity")).json()
    assert activity["link_status"] == "property_portfolio_only"
    assert activity["linked_user"] is None
    assert [entry["id"] for entry in activity["leads"]] == [lead["id"]]

    # An explicit assignment to a different CRM user is never overwritten by
    # the property's broker relationship or included in that broker's own leads.
    changed = assert_response(client.patch(
        f"/api/crm/site-inquiries/{lead['id']}/workflow",
        json={"responsible_user_id": str(identity["user_id"])},
    )).json()
    assert changed["responsible_user_id"] == str(identity["user_id"])
    after = assert_response(client.get(f"/api/crm/brokers/{broker['id']}/activity")).json()
    assert after["leads"] == []
    listed = assert_response(client.get("/api/crm/site-inquiries")).json()[0]
    assert listed["property_broker_person_id"] == broker["id"]
    assert listed["responsible_user_id"] == str(identity["user_id"])
