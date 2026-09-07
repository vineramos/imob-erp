from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from app.core.database import SessionLocal
from app.domains.finance.late_charges import amount_due
from app.domains.finance.models import RentCharge
from tests.helpers import assert_response, build_signed_rental


def test_bank_reconciliation_uses_updated_late_balance(client):
    scenario = build_signed_rental(client, publish=False)
    generated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": scenario["start"].isoformat(), "lease_contract_id": scenario["lease"]["id"]},
        )
    ).json()
    charge = generated["charges"][0]

    assert SessionLocal is not None
    with SessionLocal() as db:
        stored = db.get(RentCharge, UUID(charge["id"]))
        assert stored is not None
        stored.due_date = date.today() - timedelta(days=10)
        stored.status = "sent"
        db.commit()

    with SessionLocal() as db:
        stored = db.get(RentCharge, UUID(charge["id"]))
        assert stored is not None
        updated = amount_due(db, stored, as_of=date.today())
    assert updated == Decimal("2046.67")

    account = assert_response(
        client.post(
            "/api/finance/banking/accounts",
            json={
                "name": "Conta de recebimentos",
                "bank_name": "Banco Teste",
                "bank_code": "999",
                "account_type": "checking",
                "fund_scope": "third_party",
                "provider": "manual",
                "opening_balance": "0.00",
            },
        ),
        200,
    ).json()

    transaction = assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account['id']}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": str(updated),
                "description": "Recebimento aluguel atualizado",
                "counterparty_name": scenario["tenant"]["name"],
                "bank_reference": "BANK-LATE-D10",
            },
        )
    ).json()

    candidates = assert_response(
        client.get(f"/api/finance/banking/transactions/{transaction['id']}/candidates")
    ).json()
    candidate = next(item for item in candidates if item["target_type"] == "rent" and item["target_id"] == charge["id"])
    assert Decimal(str(candidate["remaining_amount"])) == updated

    reconciled = assert_response(
        client.post(
            f"/api/finance/banking/transactions/{transaction['id']}/reconcile",
            json={"target_type": "rent", "target_id": charge["id"], "amount": None, "notes": "Baixa integral atualizada"},
        )
    ).json()
    assert reconciled["status"] == "reconciled"
    assert Decimal(str(reconciled["reconciled_amount"])) == updated
    assert Decimal(str(reconciled["remaining_amount"])) == Decimal("0.00")

    charges = assert_response(client.get("/api/finance/charges")).json()
    paid = next(item for item in charges if item["id"] == charge["id"])
    assert paid["status"] == "paid"
    assert Decimal(str(paid["gross_amount"])) == Decimal("2000.00")
    assert Decimal(str(paid["paid_amount"])) == updated
    assert Decimal(str(paid["late_fee_amount"])) == Decimal("40.00")
    assert Decimal(str(paid["late_interest_amount"])) == Decimal("6.67")
    assert Decimal(str(paid["settlement"]["owner_entitlement_amount"])) == Decimal("46.67")
