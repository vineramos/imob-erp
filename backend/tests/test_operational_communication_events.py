from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.core.database import SessionLocal
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.portfolio.models import Person, Property
from app.main import app


COMMUNICATION_PERMISSIONS = frozenset({"communications.view", "communications.manage", "communications.send"})


def _enable_permissions(identity):
    context = identity["context"]
    expanded = UserContext(user=context.user, permission_keys=context.permission_keys | COMMUNICATION_PERMISSIONS)
    app.dependency_overrides[get_current_user_context] = lambda: expanded


def _lease_context(identity):
    assert SessionLocal is not None
    with SessionLocal() as db:
        tenant = Person(
            organization_id=identity["organization_id"],
            person_type="individual",
            name="Locatário Operacional",
            document_number="52998224725",
            email="locatario.operacional@example.invalid",
            phone="41999991111",
            address={},
            is_active=True,
            created_by_user_id=identity["user_id"],
        )
        owner = Person(
            organization_id=identity["organization_id"],
            person_type="individual",
            name="Proprietário Operacional",
            document_number="16899535009",
            email="proprietario.operacional@example.invalid",
            phone="41999992222",
            address={},
            is_active=True,
            created_by_user_id=identity["user_id"],
        )
        prop = Property(
            organization_id=identity["organization_id"],
            property_type="apartment",
            purpose="rent",
            status="rented",
            address={"street": "Rua Operacional", "number": "42", "city": "Curitiba", "state": "PR"},
            rent_amount=Decimal("2400.00"),
            created_by_user_id=identity["user_id"],
        )
        db.add_all([tenant, owner, prop])
        db.flush()
        today = date.today()
        lease = LeaseContract(
            organization_id=identity["organization_id"],
            property_id=prop.id,
            status="signed",
            rent_amount=Decimal("2400.00"),
            due_day=10,
            adjustment_index="IPCA",
            adjustment_period_months=12,
            adjustment_base_date=today,
            next_adjustment_date=today + timedelta(days=365),
            term_months=30,
            start_date=today,
            end_date=today + timedelta(days=900),
            termination_fine_months=Decimal("3.00"),
            inspection_contest_days=5,
            guarantee_type="insurance",
            guarantee_details={},
            property_snapshot={"code": "000777", "address": dict(prop.address or {})},
            owner_snapshot=[{"person_id": str(owner.id), "name": owner.name, "email": owner.email, "phone": owner.phone}],
            tenant_snapshot=[{"person_id": str(tenant.id), "name": tenant.name, "email": tenant.email, "phone": tenant.phone}],
            rules_snapshot={},
            signers_snapshot=[],
            current_version=1,
            signing_provider="clicksign",
            signing_status="signed",
            signed_at=datetime.now(timezone.utc),
            archive_status="archived",
            final_document_hash="b" * 64,
            created_by_user_id=identity["user_id"],
        )
        db.add(lease)
        db.commit()
        return tenant.id, owner.id, prop.id, lease.id


def test_inspection_schedule_and_reschedule_supersede_unsent_suggestion(client, identity):
    _enable_permissions(identity)
    tenant_id, _, property_id, lease_id = _lease_context(identity)
    first_schedule = datetime.now(timezone.utc) + timedelta(days=3)

    assert SessionLocal is not None
    with SessionLocal() as db:
        lease = db.get(LeaseContract, lease_id)
        inspection = Inspection(
            organization_id=identity["organization_id"],
            lease_contract_id=lease.id,
            property_id=property_id,
            inspection_type="initial",
            status="draft",
            lease_snapshot={
                "lease_code": f"LOC-{lease.internal_number:06d}",
                "property": dict(lease.property_snapshot or {}),
                "owners": list(lease.owner_snapshot or []),
                "tenants": list(lease.tenant_snapshot or []),
                "inspection_contest_days": lease.inspection_contest_days,
            },
            environments=[],
            contestations=[],
            scheduled_at=first_schedule,
            current_version=1,
            created_by_user_id=identity["user_id"],
        )
        db.add(inspection)
        db.commit()
        inspection_id = inspection.id

    rows = client.get("/api/communications/messages", params={"category": "inspection_schedule"})
    assert rows.status_code == 200
    messages = rows.json()
    assert len(messages) == 1
    first = messages[0]
    assert first["person_id"] == str(tenant_id)
    assert first["origin"] == "suggestion"
    assert first["status"] == "pending"
    assert first["source_module"] == "inspections"
    assert first["source_type"] == "inspection"
    assert first["source_id"] == str(inspection_id)
    assert "VIN-" in first["body"]
    assert "agendada para" in first["body"]

    with SessionLocal() as db:
        inspection = db.get(Inspection, inspection_id)
        inspection.scheduled_at = first_schedule + timedelta(days=1)
        db.commit()

    rows = client.get("/api/communications/messages", params={"category": "inspection_schedule"})
    assert rows.status_code == 200
    messages = rows.json()
    assert len(messages) == 2
    assert len({item["id"] for item in messages}) == 2
    assert sum(item["status"] == "pending" for item in messages) == 1
    assert sum(item["status"] == "cancelled" for item in messages) == 1
    assert next(item for item in messages if item["id"] == first["id"])["status"] == "cancelled"


def test_maintenance_reschedule_and_status_events_keep_only_current_unsent_update(client, identity):
    _enable_permissions(identity)
    tenant_id, owner_id, property_id, lease_id = _lease_context(identity)

    assert SessionLocal is not None
    with SessionLocal() as db:
        item = MaintenanceRequest(
            organization_id=identity["organization_id"],
            property_id=property_id,
            lease_contract_id=lease_id,
            requester_person_id=tenant_id,
            title="Reparo hidráulico no banheiro",
            category="plumbing",
            priority="normal",
            status="requested",
            description="Vazamento identificado pelo locatário.",
            responsibility="owner",
            approval_required=True,
            services=[],
            quotes=[{
                "partner_cost_total": "350.00",
                "client_price_total": "500.00",
                "margin_total": "150.00",
            }],
            history=[],
            created_by_user_id=identity["user_id"],
        )
        db.add(item)
        db.commit()
        maintenance_id = item.id

    scheduled_at = datetime.now(timezone.utc) + timedelta(days=2)
    with SessionLocal() as db:
        item = db.get(MaintenanceRequest, maintenance_id)
        item.status = "scheduled"
        item.scheduled_at = scheduled_at
        item.history = [*list(item.history or []), {
            "event": "Serviço agendado",
            "at": datetime.now(timezone.utc).isoformat(),
            "user_id": str(identity["user_id"]),
        }]
        db.commit()

    rows = client.get("/api/communications/messages", params={"category": "maintenance_update"})
    assert rows.status_code == 200
    messages = rows.json()
    assert len(messages) == 2
    assert {item["person_id"] for item in messages} == {str(tenant_id), str(owner_id)}
    assert all(item["status"] == "pending" for item in messages)
    assert all(item["source_module"] == "maintenance" for item in messages)
    assert all(item["source_type"] == "maintenance_request" for item in messages)
    assert all("serviço agendado" in item["body"] for item in messages)
    assert all("partner_cost" not in item["body"] for item in messages)
    assert all("margin" not in item["body"].lower() for item in messages)
    assert all("350.00" not in item["body"] and "500.00" not in item["body"] for item in messages)

    # Alterar somente a data, sem trocar o status, também precisa gerar a
    # comunicação atual e retirar a antiga da fila de revisão.
    with SessionLocal() as db:
        item = db.get(MaintenanceRequest, maintenance_id)
        item.scheduled_at = scheduled_at + timedelta(days=1)
        item.history = [*list(item.history or []), {
            "event": "Serviço reagendado",
            "at": datetime.now(timezone.utc).isoformat(),
            "user_id": str(identity["user_id"]),
        }]
        db.commit()

    rows = client.get("/api/communications/messages", params={"category": "maintenance_update"})
    assert rows.status_code == 200
    messages = rows.json()
    assert len(messages) == 4
    assert sum(item["status"] == "pending" for item in messages) == 2
    assert sum(item["status"] == "cancelled" for item in messages) == 2

    with SessionLocal() as db:
        item = db.get(MaintenanceRequest, maintenance_id)
        item.status = "in_progress"
        item.started_at = datetime.now(timezone.utc)
        item.history = [*list(item.history or []), {
            "event": "Execução iniciada",
            "at": item.started_at.isoformat(),
            "user_id": str(identity["user_id"]),
        }]
        db.commit()

    rows = client.get("/api/communications/messages", params={"category": "maintenance_update"})
    assert rows.status_code == 200
    messages = rows.json()
    assert len(messages) == 6
    assert sum("execução iniciada" in item["body"] for item in messages) == 2
    assert sum(item["status"] == "pending" for item in messages) == 2
    assert sum(item["status"] == "cancelled" for item in messages) == 4
    assert all("partner_cost" not in item["body"] for item in messages)
    assert all("margin" not in item["body"].lower() for item in messages)
