from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.api.routes.owner_portal import _repasse_payload
from app.core.database import SessionLocal
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import FinancialSettlement, OwnerRepasse, RentCharge
from app.domains.leases.models import LeaseContract
from tests.helpers import (
    _run_signature_flow,
    add_months,
    assert_response,
    create_person,
    create_property,
    create_signed_administration_contract,
    decimal,
    first_month,
)


def test_lease_charge_composition_generates_only_scheduled_items_and_third_party_payables(client):
    start = first_month()
    owner = create_person(client, name="Proprietário Encargos", document="33333333333", email="owner-charges@example.com", role_keys=["owner"])
    prop = create_property(client, owner["id"])
    tenant = create_person(client, name="Locatário Encargos", document="44444444444", email="tenant-charges@example.com", role_keys=["tenant"])
    create_signed_administration_contract(client, prop["id"], start=start)

    end = add_months(start, 30)
    payload = {
        "property_id": prop["id"],
        "tenant_ids": [tenant["id"]],
        "rent_amount": "2000.00",
        "due_day": 10,
        "adjustment_index": "IPCA",
        "adjustment_period_months": 12,
        "adjustment_base_date": start.isoformat(),
        "next_adjustment_date": add_months(start, 12).isoformat(),
        "term_months": 30,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "termination_fine_months": "3.00",
        "inspection_contest_days": 5,
        "guarantee_type": "insurance",
        "guarantee_details": {"provider": "Teste"},
        "monthly_charges": [
            {"key":"condo","kind":"condo","label":"Condomínio","amount":"550.00","active":True,"payer":"tenant","beneficiary":"third_party","beneficiary_name":"Condomínio Teste","frequency":"monthly","include_in_invoice":True,"start_date":start.isoformat(),"end_date":end.isoformat()},
            {"key":"iptu","kind":"iptu","label":"IPTU","amount":"120.00","active":True,"payer":"tenant","beneficiary":"owner","beneficiary_name":"Proprietário","frequency":"monthly","include_in_invoice":True,"start_date":start.isoformat(),"end_date":end.isoformat()},
            {"key":"guarantee_insurance","kind":"guarantee_insurance","label":"Seguro fiança","amount":"235.00","active":True,"payer":"tenant","beneficiary":"third_party","beneficiary_name":"Seguradora Fiança","frequency":"monthly","include_in_invoice":True,"start_date":start.isoformat(),"end_date":end.isoformat()},
            {"key":"fire_insurance","kind":"fire_insurance","label":"Seguro incêndio","amount":"360.00","active":True,"payer":"tenant","beneficiary":"third_party","beneficiary_name":"Seguradora Incêndio","frequency":"annual","include_in_invoice":True,"start_date":start.isoformat(),"end_date":end.isoformat()},
            {"key":"outside","kind":"other","label":"Cobrança fora do boleto","amount":"99.00","active":True,"payer":"tenant","beneficiary":"third_party","beneficiary_name":"Terceiro externo","frequency":"monthly","include_in_invoice":False,"start_date":start.isoformat(),"end_date":end.isoformat()},
        ],
        "notes": "Composição financeira completa.",
        "signers": [],
    }
    created = assert_response(client.post("/api/lease-contracts", json=payload), 201).json()
    signed = _run_signature_flow(client, kind="lease", contract_id=created["id"])
    assert signed["status"] == "signed"

    first = assert_response(client.post("/api/finance/charges/generate", json={"competence":start.isoformat(),"lease_contract_id":created["id"]})).json()
    assert first["generated"] == 1
    charge = first["charges"][0]
    assert decimal(charge["gross_amount"]) == Decimal("3265.00")
    items = {item["key"]: item for item in charge["charge_items"]}
    assert set(items) == {"rent", "condo", "iptu", "guarantee_insurance", "fire_insurance"}
    assert items["fire_insurance"]["frequency"] == "annual"
    assert items["condo"]["beneficiary_name"] == "Condomínio Teste"
    assert "outside" not in items

    next_competence = add_months(start, 1)
    second = assert_response(client.post("/api/finance/charges/generate", json={"competence":next_competence.isoformat(),"lease_contract_id":created["id"]})).json()
    assert decimal(second["charges"][0]["gross_amount"]) == Decimal("2905.00")
    assert "fire_insurance" not in {item["key"] for item in second["charges"][0]["charge_items"]}

    annual_competence = add_months(start, 12)
    annual = assert_response(client.post("/api/finance/charges/generate", json={"competence":annual_competence.isoformat(),"lease_contract_id":created["id"]})).json()
    assert decimal(annual["charges"][0]["gross_amount"]) == Decimal("3265.00")

    paid = assert_response(client.post(f"/api/finance/charges/{charge['id']}/payment", json={"paid_amount":"3265.00","paid_at":datetime.now(timezone.utc).isoformat(),"payment_method":"pix","payment_reference":"TEST-ENCARGOS","notes":None})).json()
    settlement = paid["settlement"]
    assert decimal(settlement["third_party_amount"]) == Decimal("1145.00")
    assert decimal(settlement["owner_entitlement_amount"]) == Decimal("120.00")
    assert decimal(settlement["agency_fee_withheld"]) == Decimal("2000.00")
    assert len(settlement["repasses"]) == 1
    assert decimal(settlement["repasses"][0]["amount"]) == Decimal("120.00")

    assert SessionLocal is not None
    with SessionLocal() as db:
        titles = db.query(FinancialTitle).filter(FinancialTitle.source_id == UUID(charge["id"])).all()
        assert len(titles) == 3
        assert sum((decimal(item.amount) for item in titles), Decimal("0.00")) == Decimal("1145.00")
        assert {item.counterparty_name for item in titles} == {"Condomínio Teste", "Seguradora Fiança", "Seguradora Incêndio"}
        assert all(item.direction == "payable" and item.fund_scope == "third_party" and item.status == "pending" for item in titles)
        assert all((item.source_snapshot or {}).get("origin") == "lease_charge_component" for item in titles)

        repasse = db.get(OwnerRepasse, UUID(settlement["repasses"][0]["id"]))
        charge_model = db.get(RentCharge, UUID(charge["id"]))
        settlement_model = db.get(FinancialSettlement, UUID(settlement["id"]))
        assert repasse is not None and charge_model is not None and settlement_model is not None
        owner_view = _repasse_payload(repasse, charge_model, settlement_model)
        assert decimal(owner_view["other_adjustments"]) == Decimal("120.00")

        lease = db.get(LeaseContract, UUID(created["id"]))
        assert lease is not None
        rules = list((lease.rules_snapshot or {}).get("monthly_charges") or [])
        fire = next(item for item in rules if item["key"] == "fire_insurance")
        assert fire["frequency"] == "annual"
        assert fire["beneficiary_name"] == "Seguradora Incêndio"
        assert next(item for item in rules if item["key"] == "outside")["include_in_invoice"] is False
