from datetime import date
from decimal import Decimal

from app.core.database import SessionLocal
from app.domains.finance.core_models import FinancialTitle
from tests.helpers import assert_response


def _account(client) -> dict:
    return assert_response(
        client.post(
            "/api/finance/banking/accounts",
            json={
                "name": "Conta operacional",
                "bank_name": "Banco Genérico",
                "bank_code": "999",
                "account_type": "checking",
                "fund_scope": "operating",
                "provider": "manual",
                "opening_balance": "0.00",
            },
        )
    ).json()


def test_statement_import_history_and_exact_file_duplicate_guard(client):
    account = _account(client)
    content = (
        "data;descricao;valor;tipo;referencia\n"
        "19/09/2026;Recebimento teste;250,00;credito;REF-250\n"
    ).encode("utf-8")

    first = assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account['id']}/import",
            files={"file": ("extrato-setembro.csv", content, "text/csv")},
        )
    ).json()
    assert first["created_rows"] == 1
    assert first["duplicate_rows"] == 0

    repeated = client.post(
        f"/api/finance/banking/accounts/{account['id']}/import",
        files={"file": ("extrato-setembro.csv", content, "text/csv")},
    )
    assert repeated.status_code == 409
    assert "mesmo arquivo" in repeated.json()["detail"].lower()

    history = assert_response(
        client.get(f"/api/finance/banking/accounts/{account['id']}/imports")
    ).json()
    assert len(history) == 1
    assert history[0]["filename"] == "extrato-setembro.csv"
    assert history[0]["source"] == "csv"
    assert history[0]["total_rows"] == 1
    assert history[0]["created_rows"] == 1
    assert history[0]["duplicate_rows"] == 0
    assert history[0]["imported_at"]


def test_reconciliation_summary_separates_routine_from_true_exception(client, identity):
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
            description="Título com referência determinística",
            counterparty_name="Cliente Teste",
            competence=competence,
            due_date=date.today(),
            amount=Decimal("300.00"),
            settled_amount=Decimal("0.00"),
            status="pending",
            payment_reference="REF-DETERMINISTICA-300",
            source_snapshot={},
            created_by_user_id=identity["user_id"],
        )
        db.add(title)
        db.commit()

    assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account['id']}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": "300.00",
                "description": "Crédito com referência conhecida",
                "bank_reference": "REF-DETERMINISTICA-300",
            },
        )
    )
    assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account['id']}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": "987.65",
                "description": "Crédito sem correspondência",
                "bank_reference": "SEM-CANDIDATO-98765",
            },
        )
    )

    summary = assert_response(
        client.get(
            "/api/finance/banking/reconciliation-summary",
            params={"account_id": account["id"], "competence": competence.isoformat()},
        )
    ).json()

    assert summary["pending_count"] == 2
    assert summary["routine_count"] >= 1
    assert summary["exception_count"] >= 1
    assert summary["deterministic_count"] >= 1
    assert summary["no_candidate_count"] + summary["review_required_count"] >= 1

    default_exceptions = assert_response(
        client.get(
            "/api/finance/banking/exceptions",
            params={"account_id": account["id"], "competence": competence.isoformat()},
        )
    ).json()
    assert len(default_exceptions) == 1
    assert default_exceptions[0]["reason"] in {"no_candidate", "review_required"}
