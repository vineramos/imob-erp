from app.domains.foundation.access import UserContext, get_current_user_context
from app.main import app
from tests.helpers import assert_response, create_person, create_property, publish_property


def test_public_site_interest_enters_crm_and_preserves_public_privacy(client, identity):
    owner = create_person(
        client,
        name="Proprietário Site",
        document="71717171717",
        email="owner.site@imob.invalid",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    assert_response(client.put(
        f"/api/properties/{property_item['id']}/additional-charges",
        json={"charges": [
            {
                "key": "fire_site", "kind": "fire_insurance", "label": "Seguro incêndio",
                "amount": "60.00", "active": True, "payer": "tenant",
                "beneficiary": "third_party", "beneficiary_name": "Seguradora",
                "frequency": "monthly", "include_in_invoice": True,
                "agency_retention_type": "none", "agency_retention_value": "0",
            },
            {
                "key": "owner_private", "kind": "other", "label": "Encargo interno",
                "amount": "99.00", "active": True, "payer": "owner",
                "beneficiary": "agency", "beneficiary_name": "Imobiliária",
                "frequency": "monthly", "include_in_invoice": True,
                "agency_retention_type": "none", "agency_retention_value": "0",
            },
        ]},
    ))
    publication = publish_property(client, property_item["id"])
    organization_id = identity["organization_id"]
    slug = publication["public_slug"]

    public_items = assert_response(client.get(f"/api/public/sites/{organization_id}/properties")).json()
    assert len(public_items) == 1
    published = public_items[0]
    assert published["cover_photo_url"]
    assert published["address"]["street"] == ""
    assert published["address"]["number"] == ""
    assert published["additional_charges"] == [{"label": "Seguro incêndio", "amount": "60.00", "frequency": "monthly"}]
    assert "beneficiary" not in published["additional_charges"][0]
    assert "agency_retention_value" not in published["additional_charges"][0]

    cover = assert_response(client.get(f"/api{published['cover_photo_url']}"))
    assert cover.content == b"imagem-de-teste"
    assert "public" in cover.headers.get("cache-control", "")

    payload = {
        "name": "Interessado do Site",
        "phone": "(41) 99999-1122",
        "email": "interessado@example.com",
        "preferred_contact": "whatsapp",
        "message": "Gostaria de visitar este imóvel amanhã à tarde.",
        "consent": True,
        "website": "",
    }
    created = assert_response(
        client.post(f"/api/public/sites/{organization_id}/properties/{slug}/inquiries", json=payload),
        201,
    ).json()
    assert created["accepted"] is True
    assert "contato" in created["message"].lower()

    # Reenvio acidental do mesmo contato para o mesmo imóvel não duplica o lead.
    assert_response(
        client.post(f"/api/public/sites/{organization_id}/properties/{slug}/inquiries", json=payload),
        201,
    )

    # Honeypot: resposta pública continua genérica, mas nenhum dado do bot é gravado.
    bot_payload = {
        **payload,
        "name": "Bot",
        "email": "bot@example.com",
        "phone": None,
        "preferred_contact": "email",
        "website": "https://spam.invalid",
    }
    assert_response(
        client.post(f"/api/public/sites/{organization_id}/properties/{slug}/inquiries", json=bot_payload),
        201,
    )

    current = identity["context"]
    crm_context = UserContext(
        user=current.user,
        permission_keys=current.permission_keys | frozenset({"crm.view", "crm.manage"}),
    )
    app.dependency_overrides[get_current_user_context] = lambda: crm_context

    inquiries = assert_response(client.get("/api/crm/site-inquiries")).json()
    assert len(inquiries) == 1
    inquiry = inquiries[0]
    assert inquiry["property_id"] == property_item["id"]
    assert inquiry["property_code"] == property_item["code"]
    assert inquiry["property_title"] == "Apartamento de teste no Batel"
    assert inquiry["name"] == payload["name"]
    assert inquiry["email"] == payload["email"]
    assert inquiry["phone"] == "41999991122"
    assert inquiry["status"] == "new"
    assert inquiry["source"] == "public_site"

    updated = assert_response(
        client.patch(f"/api/crm/site-inquiries/{inquiry['id']}", json={"status": "visit_scheduled"})
    ).json()
    assert updated["status"] == "visit_scheduled"

    filtered = assert_response(client.get("/api/crm/site-inquiries?status=visit_scheduled&q=Interessado")).json()
    assert [row["id"] for row in filtered] == [inquiry["id"]]

    # Ao sair do estoque público, a página e o formulário deixam de aceitar novos interesses.
    assert_response(
        client.post(
            f"/api/properties/{property_item['id']}/publication",
            json={"enabled": False, "reason": "Teste de retirada do estoque público."},
        )
    )
    assert_response(client.get(f"/api/public/sites/{organization_id}/properties/{slug}"), 404)
    assert_response(
        client.post(f"/api/public/sites/{organization_id}/properties/{slug}/inquiries", json=payload),
        404,
    )



def test_public_similar_properties_returns_only_other_published_inventory(client, identity):
    owner = create_person(
        client,
        name="Proprietário Similar",
        document="72727272727",
        email="owner.similar@imob.invalid",
        role_keys=["owner"],
    )
    first = create_property(client, owner["id"])
    second = create_property(client, owner["id"])
    first_publication = publish_property(client, first["id"])
    publish_property(client, second["id"])

    organization_id = identity["organization_id"]
    similar = assert_response(
        client.get(
            f"/api/public/sites/{organization_id}/properties/{first_publication['public_slug']}/similar"
        )
    ).json()

    assert 1 <= len(similar) <= 4
    assert all(item["slug"] != first_publication["public_slug"] for item in similar)
    assert any(item["code"] == second["code"] for item in similar)
