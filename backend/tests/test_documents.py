from __future__ import annotations

from app.domains.foundation.access import UserContext, get_current_user_context
from app.main import app
from tests.helpers import assert_response, build_signed_rental, create_person, create_property


def test_managed_documents_preserve_versions_and_archive(client):
    owner = create_person(
        client,
        name="Proprietário Documentos",
        document="33333333333",
        email="documentos-owner@example.com",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])

    first_bytes = b"%PDF-1.4\nprimeira-versao\n%%EOF"
    created = assert_response(
        client.post(
            "/api/documents",
            data={
                "title": "Matrícula atualizada do imóvel",
                "category": "property",
                "entity_type": "property",
                "entity_id": property_item["id"],
                "notes": "Documento da matrícula para a pasta do imóvel.",
            },
            files={"file": ("matricula.pdf", first_bytes, "application/pdf")},
        ),
        201,
    ).json()
    assert created["code"] == "DOC-000001"
    assert created["current_version"] == 1
    assert created["entity_type"] == "property"
    assert created["entity_id"] == property_item["id"]
    assert created["entity_label"].startswith("Imóvel ")
    assert len(created["versions"]) == 1

    listed = assert_response(client.get("/api/documents", params={"source_kind": "managed"})).json()
    assert len(listed) == 1
    assert listed[0]["title"] == "Matrícula atualizada do imóvel"
    assert listed[0]["version"] == 1
    assert listed[0]["version_count"] == 1
    assert listed[0]["can_version"] is True

    first_download = assert_response(client.get(f"/api{created['versions'][0]['download_path']}"))
    assert first_download.content == first_bytes

    second_bytes = b"%PDF-1.4\nsegunda-versao\n%%EOF"
    revised = assert_response(
        client.post(
            f"/api/documents/managed/{created['id']}/versions",
            data={"notes": "Matrícula renovada no cartório."},
            files={"file": ("matricula-2026.pdf", second_bytes, "application/pdf")},
        )
    ).json()
    assert revised["current_version"] == 2
    assert [version["version_number"] for version in revised["versions"]] == [1, 2]
    assert revised["versions"][0]["hash_sha256"] != revised["versions"][1]["hash_sha256"]

    old_download = assert_response(client.get(f"/api{revised['versions'][0]['download_path']}"))
    new_download = assert_response(client.get(f"/api{revised['versions'][1]['download_path']}"))
    assert old_download.content == first_bytes
    assert new_download.content == second_bytes

    archived = assert_response(
        client.post(f"/api/documents/managed/{created['id']}/archive", data={"reason": "Substituído por outro dossiê."})
    ).json()
    assert archived["status"] == "archived"
    assert archived["current_version"] == 2
    assert_response(
        client.post(
            f"/api/documents/managed/{created['id']}/versions",
            files={"file": ("v3.pdf", b"%PDF-v3", "application/pdf")},
        ),
        409,
    )


def test_system_documents_are_catalogued_without_copying_source_files(client):
    scenario = build_signed_rental(client, publish=False)
    rows = assert_response(client.get("/api/documents", params={"source_kind": "system", "category": "contract"})).json()

    assert len(rows) == 4
    keys = {row["key"] for row in rows}
    assert f"system:administration_contract:{scenario['administration']['id']}:generated" in keys
    assert f"system:administration_contract:{scenario['administration']['id']}:archived" in keys
    assert f"system:lease_contract:{scenario['lease']['id']}:generated" in keys
    assert f"system:lease_contract:{scenario['lease']['id']}:archived" in keys
    assert all(row["document_id"] is None for row in rows)
    assert all(row["can_version"] is False for row in rows)

    signed_lease = next(row for row in rows if row["key"].endswith(f"{scenario['lease']['id']}:archived"))
    content = assert_response(client.get(f"/api{signed_lease['download_path']}"))
    assert content.content.startswith(b"%PDF")


def test_documents_manage_is_separate_from_view(client, identity):
    base = identity["context"]
    restricted = UserContext(
        user=base.user,
        permission_keys=frozenset((set(base.permission_keys) | {"documents.view"}) - {"documents.manage"}),
    )
    app.dependency_overrides[get_current_user_context] = lambda: restricted

    assert_response(client.get("/api/documents"))
    assert_response(
        client.post(
            "/api/documents",
            data={"title": "Documento bloqueado", "category": "general"},
            files={"file": ("arquivo.pdf", b"%PDF-test", "application/pdf")},
        ),
        403,
    )
