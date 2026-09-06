from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.agenda.models import AgendaTask
from app.domains.finance.advanced_models import DelinquencyCase
from app.domains.finance.delinquency_models import DelinquencyWorkflow
from app.domains.finance.models import RentCharge
from app.domains.leases.models import LeaseContract
from tests.helpers import assert_response, build_signed_rental


def _set_overdue(charge_id: str, *, days: int, provider: str = "Seguradora Teste", policy: str = "AP-2026-0001") -> None:
    assert SessionLocal is not None
    with SessionLocal() as db:
        charge = db.get(RentCharge, UUID(charge_id))
        assert charge is not None
        lease = db.get(LeaseContract, charge.lease_contract_id)
        assert lease is not None
        charge.due_date = date.today() - timedelta(days=days)
        charge.status = "sent"
        charge.sent_at = datetime.now(timezone.utc) - timedelta(days=days + 1)
        lease.guarantee_type = "insurance"
        lease.guarantee_details = {"provider_name": provider, "policy_number": policy, "test_mode": True}
        db.commit()


def _agenda(case_id: str) -> list[AgendaTask]:
    assert SessionLocal is not None
    with SessionLocal() as db:
        return list(db.scalars(
            select(AgendaTask).where(
                AgendaTask.source_module == "finance",
                AgendaTask.source_id == case_id,
            ).order_by(AgendaTask.starts_at, AgendaTask.source_type)
        ).all())


def test_delinquency_ladder_promise_guarantee_portal_privacy_and_resolution(client):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    competence = journey["start"].isoformat()

    generated = assert_response(
        client.post("/api/finance/charges/generate", json={"competence": competence})
    ).json()
    assert generated["generated"] == 1
    charges = assert_response(client.get(f"/api/finance/charges?competence={competence}")).json()
    assert len(charges) == 1
    charge = charges[0]

    # D+2: abre caso e cria somente o primeiro marco da régua (D+1).
    _set_overdue(charge["id"], days=2)
    first_refresh = assert_response(client.post("/api/finance/advanced/delinquency/refresh")).json()
    active = [item for item in first_refresh if item["status"] != "resolved"]
    assert len(active) == 1
    case = active[0]
    case_id = case["id"]
    assert case["days_overdue"] == 2
    assert case["first_contact_after_days"] == 1
    assert case["followup_after_days"] == 3
    assert case["critical_after_days"] == 5
    assert case["critical"] is False
    assert case["workflow"]["guarantee_type"] == "insurance"
    assert case["workflow"]["guarantee_provider_name"] == "Seguradora Teste"
    assert case["workflow"]["guarantee_policy_number"] == "AP-2026-0001"
    tasks = _agenda(case_id)
    assert [task.source_type for task in tasks] == ["delinquency_first_contact"]
    assert tasks[0].automatic is True

    # Não permite registrar acionamento antes do marco crítico.
    too_early = client.post(
        f"/api/finance/advanced/delinquency/{case_id}/guarantee",
        json={
            "status": "submitted",
            "provider_name": "Seguradora Teste",
            "policy_number": "AP-2026-0001",
            "protocol": "SEG-TEST-EARLY",
            "claimed_amount": 2000,
        },
    )
    assert too_early.status_code == 409

    # D+6: D+3 e D+5 são materializados na Agenda sem duplicar o D+1.
    _set_overdue(charge["id"], days=6)
    critical_refresh = assert_response(client.post("/api/finance/advanced/delinquency/refresh")).json()
    case = next(item for item in critical_refresh if item["id"] == case_id)
    assert case["critical"] is True
    assert case["days_overdue"] == 6
    assert case["pending_agenda_tasks"] == 3
    tasks = _agenda(case_id)
    assert {task.source_type for task in tasks} == {
        "delinquency_first_contact",
        "delinquency_followup",
        "delinquency_guarantee",
    }
    guarantee_task = next(task for task in tasks if task.source_type == "delinquency_guarantee")
    assert guarantee_task.priority == "urgent"
    assert guarantee_task.mandatory_action is True

    # Refresh é idempotente: não cria novas tarefas para os mesmos marcos.
    assert_response(client.post("/api/finance/advanced/delinquency/refresh"))
    assert len(_agenda(case_id)) == 3

    contacted = assert_response(
        client.post(
            f"/api/finance/advanced/delinquency/{case_id}/action",
            json={
                "status": "contacted",
                "channel": "whatsapp",
                "notes": "Locatário respondeu e pediu prazo para regularizar.",
                "insurer_protocol": None,
                "next_action_at": None,
            },
        )
    ).json()
    assert contacted["status"] == "contacted"
    assert contacted["last_contact_at"] is not None
    assert any(row.get("action") == "contacted" and row.get("channel") == "whatsapp" for row in contacted["action_log"])

    # Promessa parcial é bloqueada; a regra do ERP continua sendo pagamento integral.
    partial = client.post(
        f"/api/finance/advanced/delinquency/{case_id}/promise",
        json={"due_date": (date.today() + timedelta(days=2)).isoformat(), "amount": 1000, "notes": "parcial"},
    )
    assert partial.status_code == 422
    assert "promessa parcial" in partial.json()["detail"].lower()

    promise_date = date.today() + timedelta(days=2)
    promised = assert_response(
        client.post(
            f"/api/finance/advanced/delinquency/{case_id}/promise",
            json={
                "due_date": promise_date.isoformat(),
                "amount": 2000,
                "notes": "Pagamento integral prometido via PIX.",
            },
        )
    ).json()
    assert promised["status"] == "negotiating"
    assert promised["workflow"]["promise_status"] == "pending"
    assert promised["workflow"]["promise_amount"] == 2000
    assert promised["workflow"]["promise_due_date"] == promise_date.isoformat()
    assert any(str(task.source_type).startswith("delinquency_promise_") for task in _agenda(case_id))

    # Simula passagem do prazo apenas no PostgreSQL descartável de teste.
    assert SessionLocal is not None
    with SessionLocal() as db:
        db_case = db.get(DelinquencyCase, UUID(case_id))
        assert db_case is not None
        workflow = db.scalar(select(DelinquencyWorkflow).where(DelinquencyWorkflow.delinquency_case_id == db_case.id))
        assert workflow is not None
        workflow.promise_due_date = date.today() - timedelta(days=1)
        db.commit()

    broken_refresh = assert_response(client.post("/api/finance/advanced/delinquency/refresh")).json()
    broken = next(item for item in broken_refresh if item["id"] == case_id)
    assert broken["status"] == "open"
    assert broken["workflow"]["promise_status"] == "broken"
    assert broken["workflow"]["promise_broken_at"] is not None
    assert any(row.get("action") == "promise_broken" for row in broken["action_log"])
    broken_task = next(task for task in _agenda(case_id) if str(task.source_type).startswith("delinquency_promise_broken_"))
    assert broken_task.priority == "urgent"
    assert broken_task.mandatory_action is True

    # Acionamento é um registro interno: exige protocolo, mas não chama seguradora externa.
    submitted = assert_response(
        client.post(
            f"/api/finance/advanced/delinquency/{case_id}/guarantee",
            json={
                "status": "submitted",
                "provider_name": "Seguradora Teste",
                "policy_number": "AP-2026-0001",
                "protocol": "SEG-TEST-123",
                "claimed_amount": 2000,
                "approved_amount": None,
                "received_amount": None,
                "payment_reference": None,
                "notes": "Protocolo aberto manualmente no canal da seguradora.",
                "next_action_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            },
        )
    ).json()
    assert submitted["status"] == "insurer_triggered"
    assert submitted["workflow"]["guarantee_status"] == "submitted"
    assert submitted["workflow"]["guarantee_protocol"] == "SEG-TEST-123"
    assert submitted["workflow"]["external_submission_performed"] is False

    approved = assert_response(
        client.post(
            f"/api/finance/advanced/delinquency/{case_id}/guarantee",
            json={
                "status": "approved",
                "provider_name": "Seguradora Teste",
                "policy_number": "AP-2026-0001",
                "protocol": "SEG-TEST-123",
                "claimed_amount": 2000,
                "approved_amount": 1800,
                "received_amount": None,
                "payment_reference": None,
                "notes": "Indenização aprovada parcialmente.",
                "next_action_at": None,
            },
        )
    ).json()
    assert approved["workflow"]["approved_amount"] == 1800

    received = assert_response(
        client.post(
            f"/api/finance/advanced/delinquency/{case_id}/guarantee",
            json={
                "status": "received",
                "provider_name": "Seguradora Teste",
                "policy_number": "AP-2026-0001",
                "protocol": "SEG-TEST-123",
                "claimed_amount": 2000,
                "approved_amount": 1800,
                "received_amount": 1800,
                "payment_reference": "PIX-SEGURADORA-001",
                "notes": "Indenização recebida e registrada para conferência financeira.",
                "next_action_at": None,
            },
        )
    ).json()
    assert received["workflow"]["guarantee_status"] == "received"
    assert received["workflow"]["received_amount"] == 1800
    assert received["workflow"]["guarantee_payment_reference"] == "PIX-SEGURADORA-001"

    # A indenização não quita nem altera silenciosamente o débito original do locatário.
    with SessionLocal() as db:
        original_charge = db.get(RentCharge, UUID(charge["id"]))
        assert original_charge is not None
        assert original_charge.status == "overdue"
        assert original_charge.paid_at is None

    overview = assert_response(client.get("/api/finance/advanced/delinquency/overview")).json()
    assert overview["guarantees_received"] == 1
    assert overview["guarantees_received_amount"] == 1800

    # Portal do inquilino continua exibindo a dívida, mas não expõe protocolo/log interno da garantia.
    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": tenant["id"], "label": "Portal da jornada de inadimplência"},
        ),
        201,
    ).json()
    assert_response(
        client.post(
            f"/api/finance/advanced/portal/access/{access['id']}/credentials",
            json={"password": "SenhaInadimplencia#2026"},
        )
    )
    assert_response(
        client.post(
            "/api/tenant-portal/auth/login",
            json={"email": tenant["email"], "password": "SenhaInadimplencia#2026"},
        )
    )
    portal = assert_response(client.get("/api/tenant-portal/overview"))
    portal_payload = portal.json()
    portal_charge = next(item for item in portal_payload["charges"] if item["id"] == charge["id"])
    assert portal_charge["status"] == "overdue"
    assert "SEG-TEST-123" not in portal.text
    assert "PIX-SEGURADORA-001" not in portal.text
    assert "action_log" not in portal.text

    # Ao receber integralmente do locatário, o caso fecha e as tarefas pendentes da régua são concluídas.
    assert_response(
        client.post(
            f"/api/finance/charges/{charge['id']}/payment",
            json={
                "paid_amount": 2000,
                "paid_at": datetime.now(timezone.utc).isoformat(),
                "payment_method": "pix",
                "payment_reference": "PIX-INQUILINO-QUITACAO",
                "payment_notes": "Quitação integral após inadimplência.",
            },
        )
    )
    final_refresh = assert_response(client.post("/api/finance/advanced/delinquency/refresh")).json()
    resolved = next(item for item in final_refresh if item["id"] == case_id)
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None
    assert resolved["pending_agenda_tasks"] == 0
    assert all(task.status == "completed" for task in _agenda(case_id))
