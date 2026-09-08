from helpers import assert_response, create_person, create_property


def test_person_can_be_archived_and_restored(client):
    person = create_person(
        client,
        name="Pessoa para arquivar",
        document="52998224725",
        email="arquivar@example.com",
        role_keys=["tenant"],
    )

    archived = assert_response(client.post(f"/api/people/{person['id']}/archive")).json()
    assert archived["is_active"] is False
    assert archived["role_keys"] == ["tenant"]

    active_people = assert_response(client.get("/api/people")).json()
    assert all(item["id"] != person["id"] for item in active_people)

    archived_people = assert_response(client.get("/api/people/archived")).json()
    assert [item["id"] for item in archived_people] == [person["id"]]

    restored = assert_response(client.post(f"/api/people/{person['id']}/restore")).json()
    assert restored["is_active"] is True
    assert restored["role_keys"] == ["tenant"]

    active_people = assert_response(client.get("/api/people")).json()
    assert any(item["id"] == person["id"] for item in active_people)
    assert assert_response(client.get("/api/people/archived")).json() == []


def test_person_with_active_property_cannot_be_archived(client):
    owner = create_person(
        client,
        name="Proprietário ativo",
        document="39053344705",
        email="proprietario.ativo@example.com",
        role_keys=["owner"],
    )
    create_property(client, owner["id"], status="available")

    response = client.post(f"/api/people/{owner['id']}/archive")
    assert_response(response, 409)
    assert "proprietária de um imóvel ativo" in response.json()["detail"]

    people = assert_response(client.get("/api/people")).json()
    assert any(item["id"] == owner["id"] and item["is_active"] is True for item in people)
