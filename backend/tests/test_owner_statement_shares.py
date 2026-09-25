from decimal import Decimal

from app.core.database import SessionLocal
from app.domains.finance.models import MaintenanceFinancialEntry
from app.domains.maintenance.models import MaintenanceRequest
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


def test_owner_statement_applies_each_ownership_share(client, identity):
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

    # Uma manutenção de responsabilidade dos proprietários não pode ser abatida
    # inteira do primeiro coproprietário que aparecer na fila de repasses.
    assert SessionLocal is not None
    with SessionLocal() as db:
        maintenance = MaintenanceRequest(
            organization_id=identity["organization_id"],
            property_id=property_item["id"],
            lease_contract_id=lease["id"],
            requester_person_id=tenant["id"],
            title="Manutenção rateada entre coproprietários",
            category="general",
            priority="normal",
            status="completed",
            description="Cenário de teste do rateio por participação no imóvel.",
            responsibility="owner",
            approval_required=False,
            services=[],
            quotes=[],
            history=[],
            created_by_user_id=identity["user_id"],
        )
        db.add(maintenance)
        db.flush()
        entry = MaintenanceFinancialEntry(
            organization_id=identity["organization_id"],
            maintenance_request_id=maintenance.id,
            property_id=property_item["id"],
            lease_contract_id=lease["id"],
            direction="receivable",
            counterparty_type="owner",
            counterparty_name="Proprietários",
            responsibility="owner",
            collection_method="owner_repasse_deduction",
            amount=Decimal("400.00"),
            settled_amount=Decimal("0.00"),
            margin_amount=Decimal("0.00"),
            status="pending",
            due_date=second_competence,
            source_snapshot={"maintenance_code": "MAN-RATEIO-TESTE"},
            created_by_user_id=identity["user_id"],
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        entry_id = str(entry.id)

    offset = assert_response(
        client.post(f"/api/finance/maintenance/receivables/{entry_id}/apply-owner-repasse")
    ).json()
    assert offset["status"] == "settled"
    assert decimal(offset["settled_amount"]) == decimal("400.00")

    repasses = assert_response(
        client.get("/api/finance/repasses", params={"competence": second_competence.isoformat()})
    ).json()
    current = {row["owner_person_id"]: row for row in repasses}
    assert decimal(current[owner_a["id"]]["amount"]) == decimal("700.00")
    assert decimal(current[owner_b["id"]]["amount"]) == decimal("700.00")

    # O direito econômico original continua em R$ 900 por proprietário, enquanto
    # o repasse previsto cai para R$ 700 após a dedução proporcional de R$ 200.
    for owner in (owner_a, owner_b):
        statement = assert_response(
            client.get(
                f"/api/finance/statements/{owner['id']}",
                params={"competence": second_competence.isoformat()},
            )
        ).json()
        assert decimal(statement["total_owner_entitlement"]) == decimal("900.00")
        assert decimal(statement["total_repasse"]) == decimal("700.00")
        assert decimal(statement["lines"][0]["repasse_amount"]) == decimal("700.00")
