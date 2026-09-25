from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.api.routes.finance_billing import _issue_payload
from app.core.database import SessionLocal
from app.domains.finance.late_charges import LatePaymentTerms, calculate_late_charges
from app.domains.finance.models import RentCharge
from app.domains.leases.models import LeaseContract
from tests.helpers import (
    add_months,
    assert_response,
    create_person,
    create_property,
    create_signed_administration_contract,
    create_signed_lease_contract,
    decimal,
    first_month,
    midday,
)


def _operations(client) -> dict:
    return assert_response(client.get("/api/settings/operations")).json()


def _set_late_defaults(client, *, fee: float, interest: float, kind: str = "simple", compounding: str = "daily") -> dict:
    payload = _operations(client)
    payload.update(
        {
            "late_fee_percent": fee,
            "late_interest_percent_monthly": interest,
            "late_interest_type": kind,
            "late_interest_compounding": compounding,
        }
    )
    return assert_response(client.put("/api/settings/operations", json=payload)).json()


def _draft_lease_payload(property_id: str, tenant_id: str, start: date) -> dict:
    return {
        "property_id": property_id,
        "tenant_ids": [tenant_id],
        "rent_amount": "2000.00",
        "due_day": 10,
        "adjustment_index": "IPCA",
        "adjustment_period_months": 12,
        "adjustment_base_date": start.isoformat(),
        "next_adjustment_date": add_months(start, 12).isoformat(),
        "term_months": 30,
        "start_date": start.isoformat(),
        "end_date": add_months(start, 30).isoformat(),
        "termination_fine_months": "3.00",
        "inspection_contest_days": 5,
        "guarantee_type": "insurance",
        "guarantee_details": {"test_mode": True},
        "monthly_charges": [],
        "notes": "Contrato de teste da mora.",
        "signers": [],
    }


def test_late_charge_math_simple_and_compound():
    due = date(2026, 9, 10)
    simple = calculate_late_charges(
        nominal_amount=Decimal("2000.00"),
        due_date=due,
        as_of=due + timedelta(days=10),
        terms=LatePaymentTerms(
            fee_percent=Decimal("2.00"),
            interest_percent_monthly=Decimal("1.00"),
            interest_type="simple",
            compounding="daily",
        ),
    )
    assert simple.days_overdue == 10
    assert simple.fee_amount == Decimal("40.00")
    assert simple.interest_amount == Decimal("6.67")
    assert simple.updated_amount == Decimal("2046.67")

    compound = calculate_late_charges(
        nominal_amount=Decimal("2000.00"),
        due_date=due,
        as_of=due + timedelta(days=60),
        terms=LatePaymentTerms(
            fee_percent=Decimal("2.00"),
            interest_percent_monthly=Decimal("1.00"),
            interest_type="compound",
            compounding="monthly",
        ),
    )
    assert compound.fee_amount == Decimal("40.00")
    assert compound.interest_amount == Decimal("40.20")
    assert compound.updated_amount == Decimal("2080.20")


def test_operational_defaults_freeze_into_contract_and_versions(client):
    _set_late_defaults(client, fee=3.0, interest=1.5, kind="compound", compounding="monthly")
    start = first_month()
    owner = create_person(
        client,
        name="Proprietário Mora Versionada",
        document="70111111111",
        email="owner.mora.versionada@example.com",
        role_keys=["owner"],
    )
    prop = create_property(client, owner["id"])
    tenant = create_person(
        client,
        name="Locatário Mora Versionada",
        document="70222222222",
        email="tenant.mora.versionada@example.com",
        role_keys=["tenant"],
    )
    payload = _draft_lease_payload(prop["id"], tenant["id"], start)
    created = assert_response(client.post("/api/lease-contracts", json=payload), 201).json()

    assert SessionLocal is not None
    with SessionLocal() as db:
        contract = db.get(LeaseContract, UUID(created["id"]))
        assert contract is not None
        frozen = dict(contract.rules_snapshot["late_payment"])
        assert frozen["fee_percent"] == "3.00"
        assert frozen["interest_percent_monthly"] == "1.50"
        assert frozen["interest_type"] == "compound"
        assert frozen["compounding"] == "monthly"
        assert dict(contract.versions[0].snapshot["rules"]["late_payment"]) == frozen

    # Mudar a configuração da imobiliária não pode alterar o contrato existente.
    _set_late_defaults(client, fee=9.0, interest=7.0, kind="simple", compounding="daily")
    update_payload = {**payload, "notes": "Nova versão sem alterar a mora.", "change_summary": "Ajuste apenas de observação"}
    update_payload.pop("property_id")
    updated = assert_response(client.put(f"/api/lease-contracts/{created['id']}", json=update_payload)).json()
    assert updated["current_version"] == 2

    with SessionLocal() as db:
        contract = db.get(LeaseContract, UUID(created["id"]))
        assert contract is not None
        frozen = dict(contract.rules_snapshot["late_payment"])
        assert frozen["fee_percent"] == "3.00"
        assert frozen["interest_percent_monthly"] == "1.50"
        assert frozen["interest_type"] == "compound"
        assert frozen["compounding"] == "monthly"
        versions = sorted(contract.versions, key=lambda item: item.version_number)
        assert dict(versions[-1].snapshot["rules"]["late_payment"]) == frozen


def test_overdue_payment_recalculates_and_surcharge_belongs_to_owner(client):
    _set_late_defaults(client, fee=2.0, interest=1.0, kind="simple", compounding="daily")
    start = add_months(first_month(), -1)
    owner = create_person(
        client,
        name="Proprietário Mora Financeira",
        document="70333333333",
        email="owner.mora.financeira@example.com",
        role_keys=["owner"],
    )
    prop = create_property(client, owner["id"])
    tenant = create_person(
        client,
        name="Locatário Mora Financeira",
        document="70444444444",
        email="tenant.mora.financeira@example.com",
        role_keys=["tenant"],
    )
    create_signed_administration_contract(client, prop["id"], start=start)
    lease = create_signed_lease_contract(client, prop["id"], tenant["id"], start=start)

    generated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": start.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()
    charge = generated["charges"][0]
    due = date.fromisoformat(charge["due_date"])
    paid_at = midday(due + timedelta(days=10))

    # A listagem financeira recalcula para a data consultada; para provar D+10
    # usamos a própria baixa, que reavalia exatamente na data informada.
    nominal_attempt = client.post(
        f"/api/finance/charges/{charge['id']}/payment",
        json={
            "paid_amount": "2000.00",
            "paid_at": paid_at.isoformat(),
            "payment_method": "pix",
            "payment_reference": "MORA-NOMINAL-INVALIDA",
        },
    )
    assert nominal_attempt.status_code == 409
    assert "2046.67" in nominal_attempt.text

    paid = assert_response(
        client.post(
            f"/api/finance/charges/{charge['id']}/payment",
            json={
                "paid_amount": "2046.67",
                "paid_at": paid_at.isoformat(),
                "payment_method": "pix",
                "payment_reference": "MORA-D10",
            },
        )
    ).json()
    assert paid["status"] == "paid"
    assert decimal(paid["gross_amount"]) == decimal("2000.00")
    assert decimal(paid["paid_amount"]) == decimal("2046.67")
    assert decimal(paid["late_fee_amount"]) == decimal("40.00")
    assert decimal(paid["late_interest_amount"]) == decimal("6.67")

    settlement = paid["settlement"]
    # Primeiro aluguel = intermediação de 100% do aluguel nominal. A mora não
    # aumenta receita da imobiliária: o acréscimo pertence ao proprietário.
    assert decimal(settlement["intermediation_fee_calculated"]) == decimal("2000.00")
    assert decimal(settlement["agency_fee_withheld"]) == decimal("2000.00")
    assert decimal(settlement["owner_entitlement_amount"]) == decimal("46.67")
    assert decimal(settlement["third_party_amount"]) == decimal("0.00")
    assert len(settlement["repasses"]) == 1
    assert decimal(settlement["repasses"][0]["amount"]) == decimal("46.67")
    assert settlement["repasses"][0]["status"] == "pending"

    with SessionLocal() as db:
        stored = db.get(RentCharge, UUID(charge["id"]))
        assert stored is not None
        memo = dict(stored.admin_terms_snapshot.get("late_payment_settlement") or {})
        assert memo["days_overdue"] == 10
        assert memo["updated_amount"] == "2046.67"


def test_inter_payload_uses_simple_mora_and_rejects_compound(client):
    _set_late_defaults(client, fee=2.0, interest=1.0, kind="simple", compounding="daily")
    start = first_month()
    owner = create_person(
        client,
        name="Proprietário Boleto Mora",
        document="70555555555",
        email="owner.boleto.mora@example.com",
        role_keys=["owner"],
    )
    prop = create_property(client, owner["id"])
    tenant = create_person(
        client,
        name="Locatário Boleto Mora",
        document="70666666666",
        email="tenant.boleto.mora@example.com",
        role_keys=["tenant"],
    )
    create_signed_administration_contract(client, prop["id"], start=start)
    lease = create_signed_lease_contract(client, prop["id"], tenant["id"], start=start)
    generated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": start.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()

    assert SessionLocal is not None
    with SessionLocal() as db:
        charge = db.get(RentCharge, UUID(generated["charges"][0]["id"]))
        assert charge is not None
        payload = _issue_payload(db, charge)
        assert payload["multa"] == {"codigo": "PERCENTUAL", "taxa": 2.0}
        assert payload["mora"] == {"codigo": "TAXAMENSAL", "taxa": 1.0}

        contract = db.get(LeaseContract, UUID(lease["id"]))
        assert contract is not None
        rules = dict(contract.rules_snapshot or {})
        rules["late_payment"] = {
            "fee_percent": "2.00",
            "interest_percent_monthly": "1.00",
            "interest_type": "compound",
            "compounding": "daily",
            "starts_after_days": 1,
            "base": "gross_charge",
        }
        contract.rules_snapshot = rules
        db.flush()
        with pytest.raises(ValueError, match="juros compostos"):
            _issue_payload(db, charge)
