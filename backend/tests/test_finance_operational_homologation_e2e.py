from datetime import date, timedelta
from decimal import Decimal

from app.core.database import SessionLocal
from app.domains.finance.core_models import FinancialTitle
from tests.helpers import add_months, assert_response, decimal


def _account(client, *, name: str, opening_balance: str = "0.00") -> dict:
    return assert_response(
        client.post(
            "/api/finance/banking/accounts",
            json={
                "name": name,
                "bank_name": "Banco Homologação",
                "bank_code": "999",
                "account_type": "checking",
                "fund_scope": "operating",
                "provider": "manual",
                "opening_balance": opening_balance,
            },
        )
    ).json()


def _manual_payable(identity, *, amount: str, competence: date, due_date: date) -> str:
    assert SessionLocal is not None
    with SessionLocal() as db:
        title = FinancialTitle(
            organization_id=identity["organization_id"],
            direction="payable",
            fund_scope="operating",
            source_type="manual",
            source_id=None,
            category="Homologação",
            description="Despesa operacional homologada ponta a ponta",
            counterparty_name="Fornecedor Homologação",
            competence=competence,
            due_date=due_date,
            amount=Decimal(amount),
            settled_amount=Decimal("0.00"),
            status="pending",
            source_snapshot={"homologation": True},
            created_by_user_id=identity["user_id"],
        )
        db.add(title)
        db.commit()
        db.refresh(title)
        return str(title.id)


def test_homologation_treasury_prepare_approve_execute_and_daily_close(client, identity):
    """Tesouraria real: título -> lote -> aprovação -> execução -> banco -> fechamento diário."""
    account = _account(client, name="Conta E2E Tesouraria", opening_balance="5000.00")
    title_id = _manual_payable(
        identity,
        amount="750.00",
        competence=date.today().replace(day=1),
        due_date=date.today(),
    )

    candidates = assert_response(
        client.get(
            "/api/finance/treasury/payment-candidates",
            params={"account_id": account["id"], "until": date.today().isoformat()},
        )
    ).json()
    candidate = next(item for item in candidates if item["target_id"] == title_id)
    assert decimal(candidate["remaining_amount"]) == Decimal("750.00")

    batch = assert_response(
        client.post(
            "/api/finance/treasury/payment-batches",
            json={
                "name": "Homologação tesouraria E2E",
                "bank_account_id": account["id"],
                "scheduled_date": date.today().isoformat(),
                "payment_method": "pix",
                "notes": "Lote criado pela homologação automatizada.",
                "items": [{"target_type": "manual", "target_id": title_id}],
            },
        )
    ).json()
    assert batch["status"] == "draft"
    assert decimal(batch["total_amount"]) == Decimal("750.00")
    assert batch["item_count"] == 1

    prepared = assert_response(
        client.post(f"/api/finance/treasury/payment-batches/{batch['id']}/prepare")
    ).json()
    assert prepared["status"] == "ready"
    assert prepared["prepared_at"]

    approved = assert_response(
        client.post(
            f"/api/finance/treasury/payment-batches/{batch['id']}/approve",
            json={
                "override_sod": True,
                "reason": "Homologação automatizada usa um único usuário de teste.",
            },
        )
    ).json()
    assert approved["status"] == "approved"
    assert approved["approved_at"]

    executed = assert_response(
        client.post(
            f"/api/finance/treasury/payment-batches/{batch['id']}/execute",
            json={
                "execution_date": date.today().isoformat(),
                "reference": "HOMOLOG-E2E-750",
                "override_sod": True,
                "reason": "Homologação automatizada usa um único usuário de teste.",
            },
        )
    ).json()
    assert executed["status"] == "executed"
    assert executed["executed_at"]
    assert executed["execution_reference"] == "HOMOLOG-E2E-750"
    assert executed["items"][0]["status"] == "executed"
    assert executed["items"][0]["bank_transaction_id"]

    with SessionLocal() as db:
        title = db.get(FinancialTitle, __import__("uuid").UUID(title_id))
        assert title is not None
        assert title.status == "settled"
        assert decimal(title.settled_amount) == Decimal("750.00")
        assert title.payment_reference and title.payment_reference.startswith("EXT-")

    preview = assert_response(
        client.post(
            "/api/finance/bank-control/daily-closes/preview",
            json={
                "bank_account_id": account["id"],
                "closing_date": date.today().isoformat(),
                "bank_balance": 4250.00,
            },
        )
    ).json()
    assert preview["can_close"] is True
    assert preview["pending_transactions_count"] == 0
    assert decimal(preview["erp_balance"]) == Decimal("4250.00")
    assert decimal(preview["difference"]) == Decimal("0.00")

    closed = assert_response(
        client.post(
            "/api/finance/bank-control/daily-closes",
            json={
                "bank_account_id": account["id"],
                "closing_date": date.today().isoformat(),
                "bank_balance": 4250.00,
                "notes": "Fechamento diário homologado após execução do lote.",
            },
        )
    ).json()
    assert closed["status"] == "confirmed"
    assert decimal(closed["bank_balance"]) == Decimal("4250.00")


def test_homologation_clean_month_can_close_and_retroactive_change_is_blocked(client):
    """Fechamento mensal: conta fechada -> prontidão limpa -> mês fechado -> trava retroativa."""
    competence = add_months(date.today().replace(day=1), -1)
    period_end = add_months(competence, 1) - timedelta(days=1)
    account = _account(client, name="Conta E2E Fechamento", opening_balance="0.00")

    daily = assert_response(
        client.post(
            "/api/finance/bank-control/daily-closes",
            json={
                "bank_account_id": account["id"],
                "closing_date": period_end.isoformat(),
                "bank_balance": 0.00,
                "notes": "Último dia da competência homologado sem divergência.",
            },
        )
    ).json()
    assert daily["status"] == "confirmed"

    readiness = assert_response(
        client.get(
            "/api/finance/monthly-cycle/closing-readiness",
            params={"competence": competence.isoformat()},
        )
    ).json()
    assert readiness["can_close"] is True
    assert readiness["blocker_count"] == 0
    assert readiness["unclosed_accounts_count"] == 0
    assert readiness["unreconciled_bank_transactions_count"] == 0
    assert readiness["open_bank_exceptions_count"] == 0
    assert readiness["pending_owner_repasses_count"] == 0
    assert readiness["open_payment_batches_count"] == 0

    closed = assert_response(
        client.post(
            "/api/finance/monthly-cycle/closure/close",
            params={"competence": competence.isoformat()},
            json={"note": "Competência aprovada pela homologação E2E."},
        )
    ).json()
    assert closed["status"] == "closed"
    assert closed["closed_at"]
    assert any(item["action"] == "closed" for item in closed["events"])

    blocked = client.post(
        f"/api/finance/banking/accounts/{account['id']}/transactions",
        json={
            "transaction_date": period_end.isoformat(),
            "direction": "credit",
            "amount": "1.00",
            "description": "Alteração retroativa que deve ser bloqueada",
            "bank_reference": "HOMOLOG-LOCK-1",
        },
    )
    assert blocked.status_code == 409
    assert "fechada" in blocked.json()["detail"].lower()
