from datetime import date, datetime, timezone
from decimal import Decimal

from app.core.database import SessionLocal
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.monthly_closing_models import FinanceMonthlyClosure
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.foundation.models import AppUser
from app.main import app
from tests.helpers import assert_response, decimal


def _account(client, *, opening_balance: str = "5000.00") -> dict:
    return assert_response(
        client.post(
            "/api/finance/banking/accounts",
            json={
                "name": "Conta governança",
                "bank_name": "Banco Governança",
                "bank_code": "999",
                "account_type": "checking",
                "fund_scope": "operating",
                "provider": "manual",
                "opening_balance": opening_balance,
            },
        )
    ).json()


def _payable(identity, amount: str = "900.00") -> str:
    assert SessionLocal is not None
    with SessionLocal() as db:
        title = FinancialTitle(
            organization_id=identity["organization_id"],
            direction="payable",
            fund_scope="operating",
            source_type="manual",
            source_id=None,
            category="Governança",
            description="Obrigação para validar segregação de funções",
            counterparty_name="Fornecedor Governança",
            competence=date.today().replace(day=1),
            due_date=date.today(),
            amount=Decimal(amount),
            settled_amount=Decimal("0.00"),
            status="pending",
            source_snapshot={"governance_test": True},
            created_by_user_id=identity["user_id"],
        )
        db.add(title)
        db.commit()
        db.refresh(title)
        return str(title.id)


def _user_context(identity, *, suffix: str, permissions: set[str]) -> UserContext:
    assert SessionLocal is not None
    with SessionLocal() as db:
        user = AppUser(
            organization_id=identity["organization_id"],
            auth_user_id=f"governance-{suffix}",
            name=f"Usuário {suffix.title()}",
            email=f"{suffix}@governance.invalid",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        # Carrega os campos escalares antes de desconectar a instância.
        _ = (user.id, user.name, user.email, user.organization_id)
        return UserContext(user=user, permission_keys=frozenset(permissions))


def _use(context: UserContext) -> None:
    app.dependency_overrides[get_current_user_context] = lambda: context


def test_payment_batch_requires_distinct_preparer_approver_and_executor(client, identity):
    account = _account(client)
    title_id = _payable(identity)

    batch = assert_response(
        client.post(
            "/api/finance/treasury/payment-batches",
            json={
                "name": "Lote segregado",
                "bank_account_id": account["id"],
                "scheduled_date": date.today().isoformat(),
                "payment_method": "pix",
                "items": [{"target_type": "manual", "target_id": title_id}],
            },
        )
    ).json()
    prepared = assert_response(
        client.post(f"/api/finance/treasury/payment-batches/{batch['id']}/prepare")
    ).json()
    assert prepared["prepared_by_user_id"] == str(identity["user_id"])

    own_approval = client.post(
        f"/api/finance/treasury/payment-batches/{batch['id']}/approve",
        json={},
    )
    assert own_approval.status_code == 409
    assert "segregação" in own_approval.json()["detail"].lower()

    approver = _user_context(
        identity,
        suffix="aprovador",
        permissions={"finance.view", "finance.payment.approve", "finance.payment.execute"},
    )
    _use(approver)
    approved = assert_response(
        client.post(f"/api/finance/treasury/payment-batches/{batch['id']}/approve", json={})
    ).json()
    assert approved["status"] == "approved"
    assert approved["approved_by_user_id"] == str(approver.user.id)
    assert approved["approved_by_name"] == approver.user.name

    own_execution = client.post(
        f"/api/finance/treasury/payment-batches/{batch['id']}/execute",
        json={"execution_date": date.today().isoformat(), "reference": "GOV-900"},
    )
    assert own_execution.status_code == 409
    assert "segregação" in own_execution.json()["detail"].lower()

    executor = _user_context(
        identity,
        suffix="executor",
        permissions={"finance.view", "finance.payment.execute"},
    )
    _use(executor)
    executed = assert_response(
        client.post(
            f"/api/finance/treasury/payment-batches/{batch['id']}/execute",
            json={"execution_date": date.today().isoformat(), "reference": "GOV-900"},
        )
    ).json()
    assert executed["status"] == "executed"
    assert executed["executed_by_user_id"] == str(executor.user.id)
    assert executed["executed_by_name"] == executor.user.name
    assert decimal(executed["total_amount"]) == Decimal("900.00")


def test_sod_override_requires_explicit_permission_and_reason(client, identity):
    account = _account(client)
    title_id = _payable(identity, "300.00")
    batch = assert_response(
        client.post(
            "/api/finance/treasury/payment-batches",
            json={
                "name": "Lote override",
                "bank_account_id": account["id"],
                "scheduled_date": date.today().isoformat(),
                "payment_method": "pix",
                "items": [{"target_type": "manual", "target_id": title_id}],
            },
        )
    ).json()
    assert_response(client.post(f"/api/finance/treasury/payment-batches/{batch['id']}/prepare"))

    no_reason = client.post(
        f"/api/finance/treasury/payment-batches/{batch['id']}/approve",
        json={"override_sod": True, "reason": "curto"},
    )
    assert no_reason.status_code == 422

    approved = assert_response(
        client.post(
            f"/api/finance/treasury/payment-batches/{batch['id']}/approve",
            json={
                "override_sod": True,
                "reason": "Exceção formal de homologação para contingência administrativa.",
            },
        )
    ).json()
    assert approved["status"] == "approved"


def test_period_close_and_reopen_use_distinct_permissions(client, identity):
    competence = date.today().replace(day=1)
    assert SessionLocal is not None
    with SessionLocal() as db:
        closure = FinanceMonthlyClosure(
            organization_id=identity["organization_id"],
            competence=competence,
            status="closed",
            readiness_snapshot={"governance_test": True},
            closing_note="Fechado para teste de permissão",
            closed_by_user_id=identity["user_id"],
            closed_at=datetime.now(timezone.utc),
        )
        db.add(closure)
        db.commit()

    closer = _user_context(
        identity,
        suffix="fechador",
        permissions={"finance.view", "finance.period.close"},
    )
    _use(closer)
    denied = client.post(
        "/api/finance/monthly-cycle/closure/reopen",
        params={"competence": competence.isoformat()},
        json={"reason": "Correção necessária no período fechado."},
    )
    assert denied.status_code == 403

    controller = _user_context(
        identity,
        suffix="controlador",
        permissions={"finance.view", "finance.period.reopen"},
    )
    _use(controller)
    reopened = assert_response(
        client.post(
            "/api/finance/monthly-cycle/closure/reopen",
            params={"competence": competence.isoformat()},
            json={"reason": "Correção necessária no período fechado."},
        )
    ).json()
    assert reopened["status"] == "open"
    assert reopened["reopen_reason"].startswith("Correção necessária")
