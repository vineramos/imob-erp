from tests.helpers import (
    add_months,
    assert_response,
    create_person,
    create_signed_administration_contract,
    create_signed_lease_contract,
    decimal,
    first_month,
    midday,
)


def test_owner_statement_applies_each_ownership_share(client):
    start = first_month()
    owner_a = create_person(
        client,
        name="Coproprietário A",
        document="70170170101",
        email="coproprietario.a@example.com",
        role_keys=["owner"],
    )
    owner_b = create_person(
        client,
        name="Coproprietário B",
        document="70270270202",
        email="coproprietario.b@example.com",
        role_keys=["owner"],
    )
    property_item = assert_response(
        client.post(
            "/api/properties",
            json={
                "property_type": "apartment",
                "purpose": "rent",
                "status": "available",
                "address": {
                    "street": "Rua dos Coproprietários",
                    "number": "50",
                    "complement": "Apto 5",
                    "neighborhood": "Centro",
                    "city": "Curitiba",
                    "state": "PR",
                    "postal_code": "80000-050",
                },
                "rent_amount": "2000.00",
                "condo_amount": "0.00",
                "iptu_amount": "0.00",
                "area_m2": "70.00",
                "bedrooms": 2,
                "suites": 1,
                "bathrooms": 2,
                "parking_spaces": 1,
                "furnished": False,
                "pets_allowed": True,
                "public_title": "Imóvel com dois proprietários",
                "public_description": "Cenário automatizado para validar rateio financeiro.",
                "publication_enabled": False,
                "owners": [
                    {"person_id": owner_a["id"], "ownership_percent": "50.00"},
                    {"person_id": owner_b["id"], "ownership_percent": "50.00"},
                ],
            },
        ),
        201,
    ).json()
    tenant = create_person(
        client,
        name="Locatário Copropriedade",
        document="70370370303",
        email="locatario.copropriedade@example.com",
        role_keys=["tenant"],
    )

    create_signed_administration_contract(client, property_item["id"], start=start)
    lease = create_signed_lease_contract(client, property_item["id"], tenant["id"], start=start)

    first = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": start.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()["charges"][0]
    assert_response(
        client.post(
            f"/api/finance/charges/{first['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": midday(start.replace(day=10)).isoformat(),
                "payment_method": "pix",
                "payment_reference": "E2E-COPRO-PRIMEIRO",
                "notes": None,
            },
        )
    )

    second_competence = add_months(start, 1)
    second = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": second_competence.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()["charges"][0]
    paid = assert_response(
        client.post(
            f"/api/finance/charges/{second['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": midday(second_competence.replace(day=10)).isoformat(),
                "payment_method": "pix",
                "payment_reference": "E2E-COPRO-SEGUNDO",
                "notes": None,
            },
        )
    ).json()

    settlement = paid["settlement"]
    assert decimal(settlement["owner_entitlement_amount"]) == decimal("1800.00")
    assert len(settlement["repasses"]) == 2
    assert {decimal(row["amount"]) for row in settlement["repasses"]} == {decimal("900.00")}

    for owner in (owner_a, owner_b):
        statement = assert_response(
            client.get(
                f"/api/finance/statements/{owner['id']}",
                params={"competence": second_competence.isoformat()},
            )
        ).json()
        assert decimal(statement["total_received_from_tenants"]) == decimal("2000.00")
        assert decimal(statement["total_agency_fees"]) == decimal("200.00")
        assert decimal(statement["total_owner_entitlement"]) == decimal("900.00")
        assert decimal(statement["total_repasse"]) == decimal("900.00")
        assert len(statement["lines"]) == 1
        line = statement["lines"][0]
        assert decimal(line["owner_total_before_share"]) == decimal("1800.00")
        assert decimal(line["ownership_percent"]) == decimal("50.00")
        assert decimal(line["repasse_amount"]) == decimal("900.00")
