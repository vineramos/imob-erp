from datetime import date, datetime, timezone
from uuid import UUID

from app.core.database import SessionLocal
from app.domains.finance.monthly_closing_models import FinanceMonthlyClosure
from tests.helpers import assert_response


def _account(client) -> dict:
    return assert_response(
        client.post(
            "/api/finance/banking/accounts",
            json={
                "name": "Conta trava fechamento",
                "bank_name": "Banco Genérico",
                "bank_code": "999",
                "account_type": "checking",
                "fund_scope": "operating",
                "provider": "manual",
                "opening_balance": "0.00",
            },
        )
    ).json()


def _force_closed(identity, competence: date) -> str:
    assert SessionLocal is not None
    with SessionLocal() as db:
        item = FinanceMonthlyClosure(
            organization_id=identity["organization_id"],
            competence=competence,
            status="closed",
            readiness_snapshot={"test": True},
            closing_note="Fechamento de homologação",
            closed_by_user_id=identity["user_id"],
            closed_at=datetime.now(timezone.utc),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return str(item.id)


def test_monthly_closure_state_and_reopen_history(client, identity):
    competence = date.today().replace(day=1)
    closure_id = _force_closed(identity, competence)

    state = assert_response(
        client.get(
            "/api/finance/monthly-cycle/closure",
            params={"competence": competence.isoformat()},
        )
    ).json()
    assert state["id"] == closure_id
    assert state["status"] == "closed"

    invalid = client.post(
        "/api/finance/monthly-cycle/closure/reopen",
        params={"competence": competence.isoformat()},
        json={"reason": "x"},
    )
    assert invalid.status_code == 422

    reopened = assert_response(
        client.post(
            "/api/finance/monthly-cycle/closure/reopen",
            params={"competence": competence.isoformat()},
            json={"reason": "Correção necessária na conciliação bancária."},
        )
    ).json()
    assert reopened["status"] == "open"
    assert reopened["reopen_reason"].startswith("Correção necessária")
    assert any(item["action"] == "reopened" for item in reopened["events"])


def test_closed_competence_blocks_bank_reconciliation_and_reopen_releases_it(client, identity):
    account = _account(client)
    competence = date.today().replace(day=1)

    tx = assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account['id']}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": "100.00",
                "description": "Movimento retroativo protegido",
                "bank_reference": "LOCK-100",
            },
        )
    ).json()
    _force_closed(identity, competence)

    blocked = client.post(
        f"/api/finance/banking/transactions/{tx['id']}/residual-adjustment",
        json={
            "category": "revenue",
            "description": "Receita para testar trava",
            "amount": "100.00",
        },
    )
    assert blocked.status_code == 409
    assert "competência" in blocked.json()["detail"].lower()

    assert_response(
        client.post(
            "/api/finance/monthly-cycle/closure/reopen",
            params={"competence": competence.isoformat()},
            json={"reason": "Necessário classificar movimento bancário pendente."},
        )
    )

    released = assert_response(
        client.post(
            f"/api/finance/banking/transactions/{tx['id']}/residual-adjustment",
            json={
                "category": "revenue",
                "description": "Receita após reabertura",
                "amount": "100.00",
            },
        )
    ).json()
    assert released["status"] == "reconciled"


def test_monthly_close_is_refused_while_readiness_has_blockers(client):
    account = _account(client)
    assert_response(
        client.post(
            f"/api/finance/banking/accounts/{account['id']}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": "55.00",
                "description": "Pendência que impede fechamento",
                "bank_reference": "BLOCK-55",
            },
        )
    )

    response = client.post(
        "/api/finance/monthly-cycle/closure/close",
        params={"competence": date.today().replace(day=1).isoformat()},
        json={"note": "Tentativa com bloqueadores."},
    )
    assert response.status_code == 409
    assert "bloqueadores" in response.json()["detail"].lower()



def test_closed_competence_blocks_new_bank_transaction(client, identity):
    account = _account(client)
    competence = date.today().replace(day=1)
    _force_closed(identity, competence)

    response = client.post(
        f"/api/finance/banking/accounts/{account['id']}/transactions",
        json={
            "transaction_date": date.today().isoformat(),
            "direction": "credit",
            "amount": "10.00",
            "description": "Movimento que não deve entrar",
            "bank_reference": "LOCK-NEW-10",
        },
    )
    assert response.status_code == 409
    assert "fechada" in response.json()["detail"].lower()
