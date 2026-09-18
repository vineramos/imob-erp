from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.core.database import SessionLocal
from app.domains.finance.models import MaintenanceFinancialEntry
from app.domains.finance.owner_portal_service import owner_annual_income_values
from app.domains.maintenance.models import MaintenanceRequest
from tests.helpers import (
    add_months,
    assert_response,
    build_signed_rental,
    create_person,
    create_property,
    create_signed_administration_contract,
    create_signed_lease_contract,
    decimal,
    first_month,
    midday,
)


def _owner_login(client, owner: dict) -> None:
    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": owner["id"], "label": "Portal coproprietário"},
        ),
        201,
    ).json()
    issued = assert_response(
        client.post(f"/api/finance/advanced/portal/access/{access['id']}/temporary-password")
    ).json()
    first = assert_response(
        client.post(
            "/api/tenant-portal/auth/document-login",
            json={"identifier": owner["document_number"], "password": issued["temporary_password"]},
        )
    ).json()
    assert_response(
        client.post(
            "/api/tenant-portal/auth/temporary-change",
            json={
                "identifier": owner["document_number"],
                "change_token": first["change_token"],
                "password": "SenhaCoproprietarioPortal#2026",
            },
        )
    )


def test_owner_portal_respects_coproperty_share_deductions_and_cash_year(client, identity):
    # Usa competência do ano anterior para validar o informe pelo ano-caixa\n    # sem registrar um pagamento futuro.\n    start = add_months(first_month(), -12)
    owner = create_person(
        client,
        name="Coproprietário Portal A",
        document="74374374373",
        email="coproprietario.portal.a@example.com",
        role_keys=["owner"],
    )
    other_owner = create_person(
        client,
        name="Coproprietário Portal B",
        document="74474474474",
        email="coproprietario.portal.b@example.com",
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
                    "street": "Rua da Copropriedade Portal",
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
                "public_title": "Imóvel 50/50 do Portal",
                "public_description": "Cenário automatizado para validar o Portal do Proprietário.",
                "publication_enabled": False,
                "owners": [
                    {"person_id": owner["id"], "ownership_percent": "50.00"},
                    {"person_id": other_owner["id"], "ownership_percent": "50.00"},
                ],
            },
        ),
        201,
    ).json()
    tenant = create_person(
        client,
        name="Locatário da Copropriedade Portal",
        document="74574574575",
        email="locatario.copropriedade.portal@example.com",
        role_keys=["tenant"],
    )
    create_signed_administration_contract(client, property_item["id"], start=start)
    lease = create_signed_lease_contract(client, property_item["id"], tenant["id"], start=start)

    # Primeiro aluguel pertence à intermediação (100%). A segunda competência é
    # a primeira em que o proprietário recebe aluguel menos administração.
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
                "payment_reference": "OWNER-PORTAL-COPRO-FIRST",
                "notes": None,
            },
        )
    )

    competence = add_months(start, 1)
    charge = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": competence.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()["charges"][0]
    paid = assert_response(
        client.post(
            f"/api/finance/charges/{charge['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": midday(competence.replace(day=10)).isoformat(),
                "payment_method": "pix",
                "payment_reference": "OWNER-PORTAL-COPRO",
                "notes": None,
            },
        )
    ).json()
    repasse = next(row for row in paid["settlement"]["repasses"] if row["owner_person_id"] == owner["id"])
    assert decimal(repasse["amount"]) == decimal("900.00")

    quote_id = str(uuid4())
    assert SessionLocal is not None
    with SessionLocal() as db:
        pending = MaintenanceRequest(
            organization_id=identity["organization_id"],
            property_id=UUID(property_item["id"]),
            lease_contract_id=UUID(lease["id"]),
            requester_person_id=UUID(tenant["id"]),
            title="Pintura aprovada por coproprietários",
            category="general",
            priority="normal",
            status="awaiting_approval",
            description="Serviço com preço comercial de R$ 1.000,00.",
            responsibility="owner",
            approval_required=True,
            services=[],
            selected_quote_id=quote_id,
            quotes=[{
                "id": quote_id,
                "status": "selected",
                "partner_cost_total": "700.00",
                "client_price_total": "1000.00",
                "margin_total": "300.00",
                "partner_snapshot": {"name": "Fornecedor interno"},
            }],
            history=[],
            reported_at=datetime.now(timezone.utc),
        )
        db.add(pending)
        db.flush()

        completed = MaintenanceRequest(
            organization_id=identity["organization_id"],
            property_id=UUID(property_item["id"]),
            lease_contract_id=UUID(lease["id"]),
            requester_person_id=UUID(tenant["id"]),
            title="Manutenção já abatida",
            category="general",
            priority="normal",
            status="completed",
            description="Despesa rateada entre os coproprietários.",
            responsibility="owner",
            approval_required=False,
            services=[],
            quotes=[],
            history=[],
            reported_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(completed)
        db.flush()
        entry = MaintenanceFinancialEntry(
            organization_id=identity["organization_id"],
            maintenance_request_id=completed.id,
            property_id=UUID(property_item["id"]),
            lease_contract_id=UUID(lease["id"]),
            direction="receivable",
            counterparty_type="owner",
            counterparty_name="Proprietários",
            responsibility="owner",
            collection_method="owner_repasse_deduction",
            amount=Decimal("400.00"),
            settled_amount=Decimal("0.00"),
            margin_amount=Decimal("0.00"),
            status="pending",
            due_date=competence,
            source_snapshot={"maintenance_code": "MAN-PORTAL-RATEIO"},
            created_by_user_id=identity["user_id"],
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        pending_id = str(pending.id)
        completed_id = str(completed.id)
        entry_id = str(entry.id)

    assert_response(client.post(f"/api/finance/maintenance/receivables/{entry_id}/apply-owner-repasse"))
    _owner_login(client, owner)
    overview = assert_response(client.get("/api/owner-portal/overview")).json()

    owner_property = next(row for row in overview["properties"] if row["id"] == property_item["id"])
    assert decimal(owner_property["ownership_percent"]) == decimal("50.00")

    repasse_row = next(row for row in overview["repasses"] if row["id"] == repasse["id"])
    assert decimal(repasse_row["owner_rent_share"]) == decimal("1000.00")
    assert decimal(repasse_row["owner_entitlement_amount"]) == decimal("900.00")
    assert decimal(repasse_row["other_adjustments"]) == decimal("-200.00")
    assert decimal(repasse_row["amount"]) == decimal("700.00")

    pending_row = next(row for row in overview["maintenance"] if row["id"] == pending_id)
    assert decimal(pending_row["owner_charge_total_amount"]) == decimal("1000.00")
    assert decimal(pending_row["owner_charge_amount"]) == decimal("500.00")
    assert decimal(pending_row["ownership_percent"]) == decimal("50.00")
    assert "partner_cost_total" not in pending_row
    assert "margin_total" not in pending_row

    completed_row = next(row for row in overview["maintenance"] if row["id"] == completed_id)
    assert decimal(completed_row["owner_deduction_applied_amount"]) == decimal("200.00")

    # O ano do informe é o ano em que o proprietário recebeu o repasse.
    cash_year = competence.year + 1
    assert_response(
        client.post(
            f"/api/finance/repasses/{repasse['id']}/payment",
            json={
                "paid_at": midday(competence.replace(year=cash_year, day=12)).isoformat(),
                "payment_reference": "OWNER-CASH-YEAR",
                "notes": None,
            },
        )
    )
    with SessionLocal() as db:
        _, wrong_year_lines, _ = owner_annual_income_values(
            db,
            organization_id=identity["organization_id"],
            year=competence.year,
            person_id=UUID(owner["id"]),
        )
        _, cash_year_lines, _ = owner_annual_income_values(
            db,
            organization_id=identity["organization_id"],
            year=cash_year,
            person_id=UUID(owner["id"]),
        )
    assert wrong_year_lines == []
    assert len(cash_year_lines) == 1
    line = cash_year_lines[0]
    assert decimal(line["rent_amount"]) == decimal("1000.00")
    assert decimal(line["administration_fee"]) == decimal("100.00")
    assert decimal(line["additional_charges"]) == decimal("-200.00")
    assert decimal(line["owner_net_amount"]) == decimal("700.00")

    annual = client.get(f"/api/owner-portal/reports/{cash_year}/income.pdf")
    assert annual.status_code == 200
    assert annual.content.startswith(b"%PDF")


def test_owner_portal_does_not_expose_other_owners_property_or_maintenance(client, identity):
    journey = build_signed_rental(client, publish=False)
    owner = journey["owner"]
    outsider = create_person(
        client,
        name="Outro proprietário isolado",
        document="75575575575",
        email="outro.proprietario.isolado@example.com",
        role_keys=["owner"],
    )
    other_property = create_property(client, outsider["id"])

    assert SessionLocal is not None
    with SessionLocal() as db:
        maintenance = MaintenanceRequest(
            organization_id=identity["organization_id"],
            property_id=UUID(other_property["id"]),
            lease_contract_id=None,
            requester_person_id=UUID(outsider["id"]),
            title="Chamado de outro proprietário",
            category="general",
            priority="normal",
            status="awaiting_approval",
            description="Não pode aparecer no portal alheio.",
            responsibility="owner",
            approval_required=True,
            services=[],
            selected_quote_id=str(uuid4()),
            quotes=[],
            history=[],
            reported_at=datetime.now(timezone.utc),
        )
        db.add(maintenance)
        db.commit()
        db.refresh(maintenance)
        maintenance_id = str(maintenance.id)

    _owner_login(client, owner)
    overview = assert_response(client.get("/api/owner-portal/overview")).json()
    assert other_property["id"] not in {row["id"] for row in overview["properties"]}
    assert maintenance_id not in {row["id"] for row in overview["maintenance"]}
    assert client.post(
        f"/api/owner-portal/maintenance/{maintenance_id}/decision",
        json={"decision": "approve"},
    ).status_code == 404
