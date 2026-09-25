from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.agenda import logic
from app.domains.agenda.models import AgendaTask
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.portfolio.models import Property
from tests.helpers import assert_response


def test_operational_center_surfaces_sla_and_preserves_claim(identity, client):
    assert SessionLocal is not None
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        administration = logic.department_by_name(db, identity["organization_id"], "Administração")
        logic._ensure_source_chain(
            db,
            organization_id=identity["organization_id"],
            source_module="agenda",
            source_type="operational_test",
            source_id="sla-claim-test",
            title="Pendência operacional de teste",
            description="Valida SLA e atribuição manual.",
            original_at=now - timedelta(hours=4),
            completion_at=None,
            assigned_user_id=None,
            department_id=administration.id,
            kind="task",
            all_day=True,
            duration_minutes=30,
            priority="high",
            due_at=now - timedelta(hours=1),
            daily_reschedule=False,
            mandatory_action=False,
        )
        db.commit()

    overview = assert_response(client.get("/api/agenda/operations?horizon_days=30&limit=40")).json()
    target = next(item for item in overview["items"] if item["source_id"] == "sla-claim-test")
    assert target["sla_state"] == "breached"
    assert target["assigned_user_id"] is None
    assert target["claimable"] is True
    assert overview["sla_breached"] >= 1

    claimed = assert_response(client.post(f"/api/agenda/operations/{target['id']}/claim")).json()
    assert claimed["assigned_user_id"] == str(identity["user_id"])
    assert claimed["assigned_user_name"] == "Administrador de Testes"

    # Nova reconciliação da origem sem responsável explícito não pode apagar
    # quem assumiu manualmente a pendência.
    with SessionLocal() as db:
        administration = logic.department_by_name(db, identity["organization_id"], "Administração")
        logic._ensure_source_chain(
            db,
            organization_id=identity["organization_id"],
            source_module="agenda",
            source_type="operational_test",
            source_id="sla-claim-test",
            title="Pendência operacional de teste atualizada",
            description="Origem reconciliada após a atribuição.",
            original_at=now - timedelta(hours=4),
            completion_at=None,
            assigned_user_id=None,
            department_id=administration.id,
            kind="task",
            all_day=True,
            duration_minutes=30,
            priority="urgent",
            due_at=now + timedelta(hours=2),
            daily_reschedule=False,
            mandatory_action=False,
        )
        db.commit()
        task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.organization_id == identity["organization_id"],
                AgendaTask.source_type == "operational_test",
                AgendaTask.source_id == "sla-claim-test",
            )
        )
        assert task is not None
        assert task.assigned_user_id == identity["user_id"]
        assert task.priority == "urgent"
        assert task.due_at is not None


def test_operational_rules_follow_source_truth_across_maintenance_inspection_and_contracts(identity):
    assert SessionLocal is not None
    now = datetime.now(timezone.utc)
    today = now.date()

    with SessionLocal() as db:
        prop = Property(
            organization_id=identity["organization_id"],
            property_type="apartment",
            purpose="rent",
            status="rented",
            address={"city": "Curitiba", "state": "PR"},
            rent_amount=Decimal("2000.00"),
            bedrooms=2,
            suites=0,
            bathrooms=1,
            parking_spaces=1,
            furnished=False,
            pets_allowed=True,
            publication_enabled=False,
            created_by_user_id=identity["user_id"],
        )
        db.add(prop)
        db.flush()

        lease = LeaseContract(
            organization_id=identity["organization_id"],
            property_id=prop.id,
            status="signed",
            rent_amount=Decimal("2000.00"),
            due_day=10,
            adjustment_index="IPCA",
            adjustment_period_months=12,
            adjustment_base_date=today - timedelta(days=345),
            next_adjustment_date=today + timedelta(days=20),
            term_months=30,
            start_date=today - timedelta(days=730),
            end_date=today + timedelta(days=80),
            termination_fine_months=Decimal("3.00"),
            inspection_contest_days=5,
            guarantee_type="insurance",
            guarantee_details={},
            property_snapshot={},
            owner_snapshot=[],
            tenant_snapshot=[],
            rules_snapshot={},
            signers_snapshot=[],
            created_by_user_id=identity["user_id"],
        )
        db.add(lease)
        db.flush()

        maintenance = MaintenanceRequest(
            organization_id=identity["organization_id"],
            property_id=prop.id,
            lease_contract_id=lease.id,
            title="Vazamento na cozinha",
            category="plumbing",
            priority="high",
            status="requested",
            description="Chamado usado para validar SLA operacional.",
            responsibility="pending",
            approval_required=True,
            services=[],
            quotes=[],
            history=[],
            reported_at=now - timedelta(hours=5),
            created_by_user_id=identity["user_id"],
        )
        db.add(maintenance)

        inspection = Inspection(
            organization_id=identity["organization_id"],
            lease_contract_id=lease.id,
            property_id=prop.id,
            inspection_type="final",
            status="completed",
            lease_snapshot={},
            environments=[],
            contestations=[],
            inspector_name="",
            performed_at=now - timedelta(days=2),
            contest_deadline=now + timedelta(days=3),
            created_by_user_id=identity["user_id"],
        )
        db.add(inspection)
        db.commit()
        maintenance_id = maintenance.id
        inspection_id = inspection.id
        lease_id = lease.id

    with SessionLocal() as db:
        logic.sync_system_tasks(db, identity["organization_id"])
        db.flush()

        maintenance_task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.source_type == "maintenance",
                AgendaTask.source_id == f"{maintenance_id}:followup",
            )
        )
        assert maintenance_task is not None
        assert maintenance_task.status == "pending"
        assert maintenance_task.mandatory_action is False
        assert maintenance_task.reschedule_sequence == 0
        assert maintenance_task.due_at is not None
        assert maintenance_task.due_at < now
        assert maintenance_task.priority == "high"

        contest_task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.source_type == "inspection",
                AgendaTask.source_id == f"{inspection_id}:contest",
            )
        )
        assert contest_task is not None
        assert contest_task.status == "pending"
        assert contest_task.due_at is not None
        assert contest_task.priority == "high"

        adjustment_task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.source_type == "adjustment",
                AgendaTask.source_id.like(f"{lease_id}:adjustment:%"),
            )
        )
        assert adjustment_task is not None
        assert adjustment_task.due_at is not None
        assert "revisão humana" in (adjustment_task.description or "").lower()

        expiry_task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.source_type == "contract_expiry",
                AgendaTask.source_id.like(f"{lease_id}:expiry:%"),
            )
        )
        assert expiry_task is not None
        assert expiry_task.due_at is not None

        maintenance = db.get(MaintenanceRequest, maintenance_id)
        assert maintenance is not None
        maintenance.status = "scheduled"
        maintenance.scheduled_at = now + timedelta(days=1)
        db.commit()

        logic.sync_system_tasks(db, identity["organization_id"])
        db.flush()
        db.refresh(maintenance_task)
        assert maintenance_task.status == "completed"
        assert maintenance_task.completed_at is not None

        scheduled_task = db.scalar(
            select(AgendaTask).where(
                AgendaTask.source_type == "maintenance",
                AgendaTask.source_id == str(maintenance_id),
                AgendaTask.reschedule_sequence == 0,
            )
        )
        assert scheduled_task is not None
        assert scheduled_task.status == "pending"
