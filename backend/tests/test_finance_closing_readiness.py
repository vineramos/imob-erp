from datetime import date
from decimal import Decimal
import uuid

from app.core.database import SessionLocal
from app.domains.finance.core_models import FinancialTitle
from tests.helpers import assert_response, decimal


def _account(client) -> dict:
    return assert_response(
        client.post(
            "/api/finance/banking/accounts",
            json={
                "name": "Conta fechamento",
                "bank_name": "Banco Genérico",
                "bank_code": "999",
                "account_type": "checking",
                "fund_scope": "operating",
                "provider": "manual",
                "opening_balance": "0.00",
            },
        )
    ).json()


def _title(identity, amount: str, *, reference: str | None = None) -> str:
    assert SessionLocal is not None
    with SessionLocal() as db:
        item = FinancialTitle(
            organization_id=identity["organization_id"],
            direction="receivable",
            fund_scope="operating",
            source_type="manual",
            source_id=None,
            category="Teste",
            description="Título de homologação",
            counterparty_name="Cliente Teste",
            competence=date.today().replace(day=1),
            due_date=date.today(),
            amount=Decimal(amount),
            settled_amount=Decimal("0.00"),
            status="pending",
            payment_reference=reference,
            source_snapshot={},
            created_by_user_id=identity["user_id"],
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return str(item.id)


def test_bank_residual_adjustment_closes_remaining_transaction(client, identity):
    account = _account(client)
    title_id = _title(identity, "1500.00")

    tx = assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account['id']}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": "1542.47",
                "description": "Recebimento com juros e multa",
                "bank_reference": "REC-154247",
            },
        )
    ).json()

    partial = assert_response(
        client.post(
            f"/api/finance/banking/transactions/{tx['id']}/reconcile",
            json={
                "target_type": "manual",
                "target_id": title_id,
                "amount": "1500.00",
                "notes": "Liquidação nominal.",
            },
        )
    ).json()
    assert partial["status"] == "partial"
    assert decimal(partial["remaining_amount"]) == Decimal("42.47")

    closed = assert_response(
        client.post(
            f"/api/finance/banking/transactions/{tx['id']}/residual-adjustment",
            json={
                "category": "interest",
                "description": "Juros recebidos no movimento bancário",
                "amount": "42.47",
                "note": "Classificação separada do principal.",
            },
        )
    ).json()
    assert closed["status"] == "reconciled"
    assert decimal(closed["remaining_amount"]) == Decimal("0.00")

    with SessionLocal() as db:
        adjustment = db.scalar(
            __import__("sqlalchemy").select(FinancialTitle).where(
                FinancialTitle.organization_id == identity["organization_id"],
                FinancialTitle.source_type == "bank_adjustment",
                FinancialTitle.source_id == uuid.UUID(tx["id"]),
            )
        )
        assert adjustment is not None
        assert adjustment.category == "Juros"
        assert adjustment.status == "settled"
        assert decimal(adjustment.amount) == Decimal("42.47")
        assert adjustment.source_snapshot["classification"] == "interest"


def test_exception_can_be_resolved_explicitly_against_selected_title(client, identity):
    account = _account(client)
    title_id = _title(identity, "321.00", reference="REF-321")

    tx = assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account['id']}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": "321.00",
                "description": "Crédito para resolução manual",
                "bank_reference": "REF-321",
            },
        )
    ).json()

    items = assert_response(
        client.get(
            "/api/finance/banking/exceptions",
            params={
                "account_id": account["id"],
                "competence": date.today().replace(day=1).isoformat(),
                "include_routine": "true",
            },
        )
    ).json()
    exception = next(item for item in items if item["transaction_id"] == tx["id"])

    resolved = assert_response(
        client.post(
            f"/api/finance/banking/exceptions/{exception['id']}/resolve",
            json={
                "target_type": "manual",
                "target_id": title_id,
                "amount": "321.00",
                "note": "Operador confirmou o título correto.",
            },
        )
    ).json()
    assert resolved["status"] == "reconciled"

    remaining = assert_response(
        client.get(
            "/api/finance/banking/exceptions",
            params={
                "account_id": account["id"],
                "competence": date.today().replace(day=1).isoformat(),
                "include_routine": "true",
                "include_ignored": "true",
            },
        )
    ).json()
    assert not any(item["transaction_id"] == tx["id"] for item in remaining)


def test_monthly_closing_readiness_reports_bank_blockers(client):
    account = _account(client)
    assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account['id']}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": "87.00",
                "description": "Movimento pendente de fechamento",
                "bank_reference": "PEND-87",
            },
        )
    )

    readiness = assert_response(
        client.get(
            "/api/finance/monthly-cycle/closing-readiness",
            params={"competence": date.today().replace(day=1).isoformat()},
        )
    ).json()
    assert readiness["can_close"] is False
    assert readiness["bank_accounts_count"] >= 1
    assert readiness["unclosed_accounts_count"] >= 1
    assert readiness["unreconciled_bank_transactions_count"] >= 1
    assert readiness["blocker_count"] >= 2
    assert readiness["blockers"]
