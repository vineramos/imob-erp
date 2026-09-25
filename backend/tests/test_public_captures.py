from tests.helpers import assert_response, create_person, create_property, publish_property


def test_public_owner_form_creates_capture_without_mixing_property_interest(client, identity):
    owner = create_person(
        client,
        name="Proprietário do Estoque",
        document="72727272727",
        email="owner.stock@imob.invalid",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    publication = publish_property(client, property_item["id"])
    organization_id = identity["organization_id"]

    payload = {
        "name": "Nova Proprietária do Site",
        "phone": "(41) 98888-7766",
        "email": "nova.proprietaria@example.com",
        "preferred_contact": "whatsapp",
        "property_type": "apartment",
        "address": {
            "street": "Rua da Nova Captação",
            "number": "123",
            "complement": "Apto 45",
            "neighborhood": "Água Verde",
            "city": "Curitiba",
            "state": "pr",
            "postal_code": "80240-100",
        },
        "estimated_rent": 3200,
        "message": "Imóvel desocupado e disponível para avaliação.",
        "consent": True,
        "website": "",
    }

    created = assert_response(
        client.post(f"/api/public/sites/{organization_id}/captures", json=payload),
        201,
    ).json()
    assert created["accepted"] is True
    assert "captação" in created["message"].lower()

    # Reenvio acidental do mesmo proprietário e endereço não duplica a oportunidade.
    assert_response(client.post(f"/api/public/sites/{organization_id}/captures", json=payload), 201)

    # Honeypot responde de forma genérica, mas não cria outra captação.
    bot_payload = {
        **payload,
        "name": "Bot de Captação",
        "email": "bot.capture@example.com",
        "phone": None,
        "preferred_contact": "email",
        "website": "https://spam.invalid",
    }
    assert_response(client.post(f"/api/public/sites/{organization_id}/captures", json=bot_payload), 201)

    captures = assert_response(client.get("/api/captures")).json()
    site_captures = [item for item in captures if item["source"] == "site"]
    assert len(site_captures) == 1
    capture = site_captures[0]
    assert capture["status"] == "new"
    assert capture["contact_person_name"] == payload["name"]
    assert capture["property_type"] == "apartment"
    assert capture["property_address"] == {
        "street": "Rua da Nova Captação",
        "number": "123",
        "complement": "Apto 45",
        "neighborhood": "Água Verde",
        "city": "Curitiba",
        "state": "PR",
        "postal_code": "80240100",
    }
    assert float(capture["estimated_rent"]) == 3200
    assert "Preferência de contato: WhatsApp" in capture["notes"]
    assert payload["message"] in capture["notes"]

    people = assert_response(client.get("/api/people?role=owner&q=Nova%20Proprietária")).json()
    assert len(people) == 1
    assert people[0]["name"] == payload["name"]
    assert people[0]["phone"] == "41988887766"
    assert "owner" in people[0]["role_keys"]

    # Interesse em imóvel publicado continua sendo lead do CRM, nunca uma nova captação.
    inquiry_payload = {
        "name": "Interessado no Apartamento",
        "phone": "(41) 97777-6655",
        "email": "interessado.capture-separation@example.com",
        "preferred_contact": "whatsapp",
        "message": "Quero conhecer o imóvel publicado.",
        "consent": True,
        "website": "",
    }
    assert_response(
        client.post(
            f"/api/public/sites/{organization_id}/properties/{publication['public_slug']}/inquiries",
            json=inquiry_payload,
        ),
        201,
    )
    captures_after_inquiry = assert_response(client.get("/api/captures")).json()
    assert len([item for item in captures_after_inquiry if item["source"] == "site"]) == 1
