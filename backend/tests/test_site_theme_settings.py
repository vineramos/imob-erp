from tests.helpers import assert_response, create_person, create_property, publish_property


def test_site_theme_is_controlled_persisted_and_exposed_publicly(client, identity):
    defaults = assert_response(client.get("/api/settings/appearance/site")).json()
    assert defaults["primary"] == "#123a6b"
    assert defaults["headingFont"] == "playfair"
    assert defaults["heroTitle"]

    customized = {
        **defaults,
        "companyShortName": "Lume Imóveis",
        "primary": "#6f243c",
        "primaryStrong": "#491729",
        "primarySoft": "#f7eef1",
        "headingFont": "lora",
        "bodyFont": "manrope",
        "heroKicker": "UM NOVO JEITO DE MORAR",
        "heroTitle": "Seu próximo capítulo começa aqui",
        "heroSubtitle": "Imóveis escolhidos com cuidado para cada fase da sua vida.",
    }
    saved = assert_response(client.put("/api/settings/appearance/site", json=customized)).json()
    assert saved == customized
    assert assert_response(client.get("/api/settings/appearance/site")).json() == customized

    owner = create_person(client, name="Proprietário Site Theme", document="72727272727", role_keys=["owner"])
    property_item = create_property(client, owner["id"])
    publish_property(client, property_item["id"])
    public_profile = assert_response(client.get(f"/api/public/sites/{identity['organization_id']}")).json()
    assert public_profile["theme"]["primary"] == "#6f243c"
    assert public_profile["theme"]["heroTitle"] == "Seu próximo capítulo começa aqui"
    assert public_profile["theme"]["headingFont"] == "lora"

    invalid_color = {**customized, "primary": "marsala"}
    assert_response(client.put("/api/settings/appearance/site", json=invalid_color), 422)
    invalid_font = {**customized, "headingFont": "comic-sans"}
    assert_response(client.put("/api/settings/appearance/site", json=invalid_font), 422)

    reset = assert_response(client.post("/api/settings/appearance/site/reset")).json()
    assert reset["primary"] == "#123a6b"
    assert reset["heroTitle"] == defaults["heroTitle"]
