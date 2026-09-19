from datetime import date
from decimal import Decimal
import uuid

from app.core.database import SessionLocal
from app.domains.finance.bank_models import BankReconciliationExceptionRecord
from app.domains.finance.core_models import FinancialTitle
from tests.helpers import assert_response, decimal


def _account(client, *, scope: str = "operating") -> dict:
    return assert_response(
        client.post(
            "/api/finance/banking/accounts",
            json={
                "name": "Conta de homologação",
                "bank_name": "Banco Genérico",
                "bank_code": "999",
                "account_type": "checking",
                "fund_scope": scope,
                "provider": "manual",
                "opening_balance": "0.00",
            },
        )
    ).json()


def _movement(client, account_id: str, *, amount: str, reference: str = "REF-SEM-TITULO") -> dict:
    return assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account_id}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": amount,
                "description": "Crédito para homologação da fila de exceções",
                "bank_reference": reference,
            },
        )
    ).json()


def test_exception_queue_persists_true_exceptions_and_supports_ignore_reopen(client, identity):
    account = _account(client)
    tx = _movement(client, account["id"], amount="123.45")

    items = assert_response(
        client.get(
            "/api/finance/banking/exceptions",
            params={"account_id": account["id"], "competence": date.today().replace(day=1).isoformat()},
        )
    ).json()
    item = next(entry for entry in items if entry["transaction_id"] == tx["id"])
    assert item["reason"] == "no_candidate"
    assert item["severity"] == "exception"
    assert item["status"] == "open"
    exception_id = item["id"]

    assert SessionLocal is not None
    with SessionLocal() as db:
        persisted = db.get(BankReconciliationExceptionRecord, uuid.UUID(exception_id))
        assert persisted is not None
        assert persisted.bank_transaction_id == uuid.UUID(tx["id"])
        assert persisted.status == "open"

    ignored = assert_response(
        client.post(
            f"/api/finance/banking/exceptions/{exception_id}/ignore",
            json={"note": "Movimento conhecido e tratado fora da competência."},
        )
    ).json()
    assert ignored["status"] == "ignored"
    assert "tratado fora" in ignored["resolution_note"]

    hidden = assert_response(
        client.get(
            "/api/finance/banking/exceptions",
            params={"account_id": account["id"], "competence": date.today().replace(day=1).isoformat()},
        )
    ).json()
    assert not any(entry["id"] == exception_id for entry in hidden)

    with_ignored = assert_response(
        client.get(
            "/api/finance/banking/exceptions",
            params={
                "account_id": account["id"],
                "competence": date.today().replace(day=1).isoformat(),
                "include_ignored": "true",
            },
        )
    ).json()
    assert next(entry for entry in with_ignored if entry["id"] == exception_id)["status"] == "ignored"

    reopened = assert_response(
        client.post(
            f"/api/finance/banking/exceptions/{exception_id}/reopen",
            json={"note": "Reavaliar no fechamento."},
        )
    ).json()
    assert reopened["status"] == "open"
    assert reopened["resolved_at"] is None


def test_routine_candidates_are_not_counted_as_true_exceptions_by_default(client, identity):
    account = _account(client)
    competence = date.today().replace(day=1)

    assert SessionLocal is not None
    with SessionLocal() as db:
        title = FinancialTitle(
            organization_id=identity["organization_id"],
            direction="receivable",
            fund_scope="operating",
            source_type="manual",
            source_id=None,
            category="Teste",
            description="Título com referência forte",
            counterparty_name="Cliente Teste",
            competence=competence,
            due_date=date.today(),
            amount=Decimal("200.00"),
            settled_amount=Decimal("0.00"),
            status="pending",
            payment_reference="FIN-REFERENCIA-FORTE",
            source_snapshot={},
            created_by_user_id=identity["user_id"],
        )
        db.add(title)
        db.commit()
        db.refresh(title)
        title_id = str(title.id)

    tx = _movement(client, account["id"], amount="200.00", reference="FIN-REFERENCIA-FORTE")

    default_items = assert_response(
        client.get(
            "/api/finance/banking/exceptions",
            params={"account_id": account["id"], "competence": competence.isoformat()},
        )
    ).json()
    assert not any(entry["transaction_id"] == tx["id"] for entry in default_items)

    all_items = assert_response(
        client.get(
            "/api/finance/banking/exceptions",
            params={
                "account_id": account["id"],
                "competence": competence.isoformat(),
                "include_routine": "true",
            },
        )
    ).json()
    routine = next(entry for entry in all_items if entry["transaction_id"] == tx["id"])
    assert routine["severity"] == "routine"
    assert routine["reason"] in {"identifier_detected", "strong_candidate"}
    assert routine["top_candidate_code"]

    candidates = assert_response(
        client.get(f"/api/finance/banking/transactions/{tx['id']}/candidates")
    ).json()
    candidate = next(entry for entry in candidates if entry["target_id"] == title_id)
    assert decimal(candidate["transaction_remaining_amount"]) == Decimal("200.00")
    assert decimal(candidate["suggested_allocation"]) == Decimal("200.00")
    assert decimal(candidate["difference_amount"]) == Decimal("0.00")
    assert candidate["difference_kind"] == "exact"
    assert candidate["settlement_compatible"] is True


def test_candidate_reports_bank_excess_without_forcing_unsafe_settlement(client, identity):
    account = _account(client)
    competence = date.today().replace(day=1)

    assert SessionLocal is not None
    with SessionLocal() as db:
        title = FinancialTitle(
            organization_id=identity["organization_id"],
            direction="receivable",
            fund_scope="operating",
            source_type="manual",
            source_id=None,
            category="Teste",
            description="Título nominal menor que crédito bancário",
            counterparty_name="Cliente Teste",
            competence=competence,
            due_date=date.today(),
            amount=Decimal("1500.00"),
            settled_amount=Decimal("0.00"),
            status="pending",
            source_snapshot={},
            created_by_user_id=identity["user_id"],
        )
        db.add(title)
        db.commit()
        db.refresh(title)
        title_id = str(title.id)

    tx = _movement(client, account["id"], amount="1542.47", reference="AJUSTE-154247")
    candidates = assert_response(
        client.get(f"/api/finance/banking/transactions/{tx['id']}/candidates")
    ).json()
    candidate = next(entry for entry in candidates if entry["target_id"] == title_id)

    assert decimal(candidate["remaining_amount"]) == Decimal("1500.00")
    assert decimal(candidate["transaction_remaining_amount"]) == Decimal("1542.47")
    assert decimal(candidate["suggested_allocation"]) == Decimal("1500.00")
    assert decimal(candidate["difference_amount"]) == Decimal("42.47")
    assert candidate["difference_kind"] == "bank_excess"
    assert candidate["settlement_compatible"] is True


def test_bank_excess_can_settle_title_and_keep_residual_transaction_open(client, identity):
    account = _account(client)
    competence = date.today().replace(day=1)

    assert SessionLocal is not None
    with SessionLocal() as db:
        title = FinancialTitle(
            organization_id=identity["organization_id"],
            direction="receivable",
            fund_scope="operating",
            source_type="manual",
            source_id=None,
            category="Teste",
            description="Título com diferença bancária",
            counterparty_name="Cliente Teste",
            competence=competence,
            due_date=date.today(),
            amount=Decimal("1500.00"),
            settled_amount=Decimal("0.00"),
            status="pending",
            source_snapshot={},
            created_by_user_id=identity["user_id"],
        )
        db.add(title)
        db.commit()
        db.refresh(title)
        title_id = str(title.id)

    tx = _movement(client, account["id"], amount="1542.47", reference="RESIDUAL-42-47")
    candidates = assert_response(
        client.get(f"/api/finance/banking/transactions/{tx['id']}/candidates")
    ).json()
    candidate = next(entry for entry in candidates if entry["target_id"] == title_id)
    assert candidate["difference_kind"] == "bank_excess"
    assert decimal(candidate["suggested_allocation"]) == Decimal("1500.00")

    reconciled = assert_response(
        client.post(
            f"/api/finance/banking/transactions/{tx['id']}/reconcile",
            json={
                "target_type": "manual",
                "target_id": title_id,
                "amount": candidate["suggested_allocation"],
                "notes": "Liquidação do título; residual bancário permanece para classificação separada.",
            },
        )
    ).json()
    assert reconciled["status"] == "partial"
    assert decimal(reconciled["reconciled_amount"]) == Decimal("1500.00")
    assert decimal(reconciled["remaining_amount"]) == Decimal("42.47")

    with SessionLocal() as db:
        settled = db.get(FinancialTitle, uuid.UUID(title_id))
        assert settled is not None
        assert settled.status == "settled"
        assert decimal(settled.settled_amount) == Decimal("1500.00")
