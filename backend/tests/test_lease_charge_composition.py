from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.api.routes.owner_portal import _repasse_payload
from app.api.routes.tenant_portal_charges import _safe_item, _safe_rule
from app.core.database import SessionLocal
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import FinancialSettlement, OwnerRepasse, RentCharge
from app.domains.leases.models import LeaseContract
from app.domains.leases.schemas import LeaseMonthlyChargePayload
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
            {"key":"condo","kind":"condo","label":"Condomínio","amount":"550.00","active":True,"payer":"tenant","beneficiary":"third_party","beneficiary_name":"Condomínio Teste","frequency":"monthly","include_in_invoice":True,"agency_retention_type":"none","agency_retention_value":"0.00","start_date":start.isoformat(),"end_date":end.isoformat()},
            {"key":"iptu","kind":"iptu","label":"IPTU","amount":"120.00","active":True,"payer":"tenant","beneficiary":"owner","beneficiary_name":"Proprietário","frequency":"monthly","include_in_invoice":True,"agency_retention_type":"none","agency_retention_value":"0.00","start_date":start.isoformat(),"end_date":end.isoformat()},
            {"key":"guarantee_insurance","kind":"guarantee_insurance","label":"Seguro fiança","amount":"500.00","active":True,"payer":"tenant","beneficiary":"third_party","beneficiary_name":"Seguradora Fiança","frequency":"monthly","include_in_invoice":True,"agency_retention_type":"percent","agency_retention_value":"30.00","start_date":start.isoformat(),"end_date":end.isoformat()},
            {"key":"fire_insurance","kind":"fire_insurance","label":"Seguro incêndio","amount":"360.00","active":True,"payer":"tenant","beneficiary":"third_party","beneficiary_name":"Seguradora Incêndio","frequency":"annual","include_in_invoice":True,"agency_retention_type":"fixed","agency_retention_value":"60.00","start_date":start.isoformat(),"end_date":end.isoformat()},
            {"key":"outside","kind":"other","label":"Cobrança fora do boleto","amount":"99.00","active":True,"payer":"tenant","beneficiary":"third_party","beneficiary_name":"Terceiro externo","frequency":"monthly","include_in_invoice":False,"agency_retention_type":"none","agency_retention_value":"0.00","start_date":start.isoformat(),"end_date":end.isoformat()},
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
    assert decimal(charge["gross_amount"]) == Decimal("3530.00")
    items = {item["key"]: item for item in charge["charge_items"]}
    assert set(items) == {"rent", "condo", "iptu", "guarantee_insurance", "fire_insurance"}
    assert items["fire_insurance"]["frequency"] == "annual"
    assert items["condo"]["beneficiary_name"] == "Condomínio Teste"
    assert "outside" not in items

    # Valor exibido/cobrado permanece bruto; a divisão é interna.
    assert decimal(items["guarantee_insurance"]["amount"]) == Decimal("500.00")
    assert items["guarantee_insurance"]["agency_retention_type"] == "percent"
    assert decimal(items["guarantee_insurance"]["agency_retention_value"]) == Decimal("30.00")
    assert decimal(items["guarantee_insurance"]["agency_retention_amount"]) == Decimal("150.00")
    assert decimal(items["guarantee_insurance"]["third_party_net_amount"]) == Decimal("350.00")
    assert items["fire_insurance"]["agency_retention_type"] == "fixed"
    assert decimal(items["fire_insurance"]["agency_retention_amount"]) == Decimal("60.00")
    assert decimal(items["fire_insurance"]["third_party_net_amount"]) == Decimal("300.00")

    next_competence = add_months(start, 1)
    second = assert_response(client.post("/api/finance/charges/generate", json={"competence":next_competence.isoformat(),"lease_contract_id":created["id"]})).json()
    assert decimal(second["charges"][0]["gross_amount"]) == Decimal("3170.00")
    assert "fire_insurance" not in {item["key"] for item in second["charges"][0]["charge_items"]}

    annual_competence = add_months(start, 12)
    annual = assert_response(client.post("/api/finance/charges/generate", json={"competence":annual_competence.isoformat(),"lease_contract_id":created["id"]})).json()
    assert decimal(annual["charges"][0]["gross_amount"]) == Decimal("3530.00")

    paid = assert_response(client.post(f"/api/finance/charges/{charge['id']}/payment", json={"paid_amount":"3530.00","paid_at":datetime.now(timezone.utc).isoformat(),"payment_method":"pix","payment_reference":"TEST-ENCARGOS","notes":None})).json()
    settlement = paid["settlement"]
    assert decimal(settlement["third_party_amount"]) == Decimal("1200.00")
    assert decimal(settlement["agency_retention_amount"]) == Decimal("210.00")
    assert decimal(settlement["owner_entitlement_amount"]) == Decimal("120.00")
    assert decimal(settlement["agency_fee_withheld"]) == Decimal("2000.00")
    assert len(settlement["repasses"]) == 1
    assert decimal(settlement["repasses"][0]["amount"]) == Decimal("120.00")

    dashboard = assert_response(client.get(f"/api/finance/dashboard?competence={start.isoformat()}")).json()
    assert decimal(dashboard["agency_revenue_amount"]) == Decimal("2210.00")

    assert SessionLocal is not None
    with SessionLocal() as db:
        titles = db.query(FinancialTitle).filter(FinancialTitle.source_id == UUID(charge["id"])).all()
        assert len(titles) == 3
        assert sum((decimal(item.amount) for item in titles), Decimal("0.00")) == Decimal("1200.00")
        by_counterparty = {item.counterparty_name: item for item in titles}
        assert decimal(by_counterparty["Condomínio Teste"].amount) == Decimal("550.00")
        assert decimal(by_counterparty["Seguradora Fiança"].amount) == Decimal("350.00")
        assert decimal(by_counterparty["Seguradora Incêndio"].amount) == Decimal("300.00")
        assert all(item.direction == "payable" and item.fund_scope == "third_party" and item.status == "pending" for item in titles)
        assert all((item.source_snapshot or {}).get("origin") == "lease_charge_component" for item in titles)
        assert (by_counterparty["Seguradora Fiança"].source_snapshot or {}).get("agency_retention_amount") == "150.00"
        assert (by_counterparty["Seguradora Fiança"].source_snapshot or {}).get("third_party_net_amount") == "350.00"

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
        guarantee = next(item for item in rules if item["key"] == "guarantee_insurance")
        assert fire["frequency"] == "annual"
        assert fire["beneficiary_name"] == "Seguradora Incêndio"
        assert fire["agency_retention_type"] == "fixed"
        assert fire["agency_retention_value"] == "60.00"
        assert guarantee["agency_retention_type"] == "percent"
        assert guarantee["agency_retention_value"] == "30.00"
        assert next(item for item in rules if item["key"] == "outside")["include_in_invoice"] is False


def test_insurance_retention_validates_percent_fixed_and_kind_limits():
    base = {
        "key": "insurance",
        "kind": "guarantee_insurance",
        "label": "Seguro fiança",
        "amount": "500.00",
        "beneficiary": "third_party",
    }
    percent = LeaseMonthlyChargePayload(**base, agency_retention_type="percent", agency_retention_value="30")
    assert percent.agency_retention_value == Decimal("30")
    fixed = LeaseMonthlyChargePayload(**base, agency_retention_type="fixed", agency_retention_value="150")
    assert fixed.agency_retention_value == Decimal("150")

    with pytest.raises(ValidationError):
        LeaseMonthlyChargePayload(**base, agency_retention_type="percent", agency_retention_value="101")
    with pytest.raises(ValidationError):
        LeaseMonthlyChargePayload(**base, agency_retention_type="fixed", agency_retention_value="501")
    with pytest.raises(ValidationError):
        LeaseMonthlyChargePayload(
            key="condo",
            kind="condo",
            label="Condomínio",
            amount="500.00",
            beneficiary="third_party",
            agency_retention_type="percent",
            agency_retention_value="10",
        )


def test_tenant_charge_views_do_not_expose_internal_insurance_retention():
    internal = {
        "key": "guarantee_insurance",
        "kind": "guarantee_insurance",
        "label": "Seguro fiança",
        "amount": "500.00",
        "active": True,
        "payer": "tenant",
        "beneficiary": "third_party",
        "beneficiary_name": "Seguradora",
        "frequency": "monthly",
        "include_in_invoice": True,
        "agency_retention_type": "percent",
        "agency_retention_value": "30.00",
        "agency_retention_amount": "150.00",
        "third_party_net_amount": "350.00",
    }
    safe_rule = _safe_rule(internal)
    safe_item = _safe_item(internal)
    assert safe_rule["amount"] == 500.0
    assert safe_item["amount"] == 500.0
    assert not any(key.startswith("agency_retention") for key in safe_rule)
    assert not any(key.startswith("agency_retention") for key in safe_item)
    assert "third_party_net_amount" not in safe_rule
    assert "third_party_net_amount" not in safe_item
