from __future__ import annotations

from tests.helpers import assert_response, build_signed_rental


def test_contextual_document_folders_follow_operational_relationships(client):
    scenario = build_signed_rental(client, publish=False)

    property_rows = assert_response(
        client.get(f"/api/documents/context/property/{scenario['property']['id']}")
    ).json()
    property_keys = {row["key"] for row in property_rows}
    assert f"system:administration_contract:{scenario['administration']['id']}:generated" in property_keys
    assert f"system:administration_contract:{scenario['administration']['id']}:archived" in property_keys
    assert f"system:lease_contract:{scenario['lease']['id']}:generated" in property_keys
    assert f"system:lease_contract:{scenario['lease']['id']}:archived" in property_keys

    owner_rows = assert_response(
        client.get(f"/api/documents/context/person/{scenario['owner']['id']}")
    ).json()
    owner_keys = {row["key"] for row in owner_rows}
    assert f"system:administration_contract:{scenario['administration']['id']}:archived" in owner_keys
    assert f"system:lease_contract:{scenario['lease']['id']}:archived" in owner_keys

    tenant_rows = assert_response(
        client.get(f"/api/documents/context/person/{scenario['tenant']['id']}")
    ).json()
    tenant_keys = {row["key"] for row in tenant_rows}
    assert f"system:lease_contract:{scenario['lease']['id']}:generated" in tenant_keys
    assert not any("administration_contract" in key for key in tenant_keys)

    admin_rows = assert_response(
        client.get(f"/api/documents/context/administration_contract/{scenario['administration']['id']}")
    ).json()
    assert {row["key"] for row in admin_rows} == {
        f"system:administration_contract:{scenario['administration']['id']}:generated",
        f"system:administration_contract:{scenario['administration']['id']}:archived",
    }

    lease_rows = assert_response(
        client.get(f"/api/documents/context/lease_contract/{scenario['lease']['id']}")
    ).json()
    lease_keys = {row["key"] for row in lease_rows}
    assert f"system:lease_contract:{scenario['lease']['id']}:generated" in lease_keys
    assert f"system:lease_contract:{scenario['lease']['id']}:archived" in lease_keys

    assert_response(
        client.get('/api/documents/context/property/00000000-0000-0000-0000-000000000000'),
        404,
    )
