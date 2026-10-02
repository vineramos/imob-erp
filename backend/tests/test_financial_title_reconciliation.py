from datetime import date
from decimal import Decimal
import uuid

from app.core.database import SessionLocal
from app.domains.finance.core_models import FinancialTitle
from tests.helpers import assert_response, decimal


def _bank_account(client, *, name: str, fund_scope: str) -> dict:
    return assert_response(
        client.post(
            "/api/finance/banking/accounts",
            json={
                "name": name,
                "bank_name": "Banco Teste",
                "bank_code": "999",
                "branch": "0001",
                "account_number": "12345",
                "account_digit": "0",
                "account_type": "checking",
                "fund_scope": fund_scope,
                "provider": "manual",
                "opening_balance": "0.00",
            },
        ),
        200,
    ).json()


def _credit(client, *, account_id: str, amount: str, reference: str) -> dict:
    return assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account_id}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": amount,
                "description": "Recebimento de acerto final da locação",
                "counterparty_name": "Locatário Teste",
                "bank_reference": reference,
            },
        )
    ).json()


def test_automatic_financial_title_keeps_source_and_can_be_bank_reconciled(client, identity):
    competence = date.today().replace(day=1)
    source_id = uuid.uuid4()
    assert SessionLocal is not None
    with SessionLocal() as db:
        title = FinancialTitle(
            organization_id=identity["organization_id"],
            direction="receivable",
            fund_scope="operating",
            source_type="lease_exit_adjustment",
            source_id=source_id,
            category="Acerto de saída",
            description="Reposição aprovada após vistoria final",
            counterparty_name="Locatário Teste",
            competence=competence,
            due_date=date.today(),
            amount=Decimal("275.00"),
            settled_amount=Decimal("0.00"),
            status="pending",
            source_snapshot={"origin": "lease_exit_adjustment"},
            created_by_user_id=identity["user_id"],
        )
        db.add(title)
        db.commit()
        db.refresh(title)
        title_id = str(title.id)

    overview = assert_response(
        client.get("/api/finance/core/overview", params={"competence": competence.isoformat()})
    ).json()
    row = next(item for item in overview["items"] if item["id"] == title_id)
    assert row["source_type"] == "lease_exit_adjustment"
    assert row["source_id"] == str(source_id)
    assert row["manual"] is False
    assert decimal(row["remaining_amount"]) == Decimal("275.00")

    # Um título automático não pode ser baixado pela rota de lançamentos manuais.
    manual_settle = client.post(
        f"/api/finance/core/manual/{title_id}/settle",
        json={
            "amount": "275.00",
            "settled_at": None,
            "payment_method": "pix",
            "payment_reference": "NAO-DEVE-BAIXAR",
            "notes": None,
        },
    )
    assert manual_settle.status_code == 404

    wrong_account = _bank_account(client, name="Conta de terceiros", fund_scope="third_party")
    wrong_tx = _credit(client, account_id=wrong_account["id"], amount="275.00", reference="EXT-ERRADO")
    wrong_candidates = assert_response(
        client.get(f"/api/finance/banking/transactions/{wrong_tx['id']}/candidates")
    ).json()
    assert not any(item["target_id"] == title_id for item in wrong_candidates)

    wrong_reconcile = client.post(
        f"/api/finance/banking/transactions/{wrong_tx['id']}/reconcile",
        json={"target_type": "financial_title", "target_id": title_id, "amount": "275.00", "notes": None},
    )
    assert wrong_reconcile.status_code == 409
    assert "naturezas de recurso diferentes" in wrong_reconcile.json()["detail"]

    operating_account = _bank_account(client, name="Conta operacional", fund_scope="operating")
    transaction = _credit(client, account_id=operating_account["id"], amount="275.00", reference="EXT-ACERTO")
    candidates = assert_response(
        client.get(f"/api/finance/banking/transactions/{transaction['id']}/candidates")
    ).json()
    candidate = next(item for item in candidates if item["target_id"] == title_id)
    assert candidate["target_type"] == "financial_title"
    assert candidate["fund_scope"] == "operating"
    assert decimal(candidate["remaining_amount"]) == Decimal("275.00")

    reconciled = assert_response(
        client.post(
            f"/api/finance/banking/transactions/{transaction['id']}/reconcile",
            json={
                "target_type": "financial_title",
                "target_id": title_id,
                "amount": "275.00",
                "notes": "Baixa vinculada à origem automática.",
            },
        )
    ).json()
    assert reconciled["status"] == "reconciled"
    assert decimal(reconciled["remaining_amount"]) == Decimal("0.00")
    assert reconciled["reconciliations"][0]["target_type"] == "financial_title"

    with SessionLocal() as db:
        settled = db.get(FinancialTitle, uuid.UUID(title_id))
        assert settled is not None
        assert settled.source_type == "lease_exit_adjustment"
        assert settled.source_id == source_id
        assert settled.status == "settled"
        assert settled.payment_method == "transfer"
        assert settled.payment_reference == reconciled["code"]
        assert decimal(settled.settled_amount) == Decimal("275.00")

    refreshed = assert_response(
        client.get("/api/finance/core/overview", params={"competence": competence.isoformat()})
    ).json()
    settled_row = next(item for item in refreshed["items"] if item["id"] == title_id)
    assert settled_row["source_type"] == "lease_exit_adjustment"
    assert settled_row["manual"] is False
    assert settled_row["status"] == "settled"
    assert decimal(settled_row["remaining_amount"]) == Decimal("0.00")
