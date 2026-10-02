from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.agenda import logic
from app.domains.agenda.models import AgendaDepartment, AgendaTask
from app.domains.communications.models import CommunicationMessage
from app.domains.finance.core_models import FinancialTitle
from app.domains.inspections.models import Inspection
from app.domains.lease_lifecycle.models import LeaseLifecycleCase
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person, Property


def _setup_lease(identity):
    assert SessionLocal is not None
    with SessionLocal() as db:
        tenant = Person(
            organization_id=identity["organization_id"],
            person_type="individual",
            name="Locatário Saída",
            document_number="52998224725",
            email="locatario.saida@example.invalid",
            phone="41999993333",
            address={},
            is_active=True,
            created_by_user_id=identity["user_id"],
        )
        owner = Person(
            organization_id=identity["organization_id"],
            person_type="individual",
            name="Proprietário Saída",
            document_number="16899535009",
            email="proprietario.saida@example.invalid",
            phone="41999994444",
            address={},
            is_active=True,
            created_by_user_id=identity["user_id"],
        )
        prop = Property(
            organization_id=identity["organization_id"],
            property_type="apartment",
            purpose="rent",
            status="rented",
            address={"street": "Rua da Saída", "number": "90", "city": "Curitiba", "state": "PR"},
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
            property_snapshot={"code": "000990", "address": dict(prop.address or {})},
            owner_snapshot=[{"person_id": str(owner.id), "name": owner.name, "email": owner.email, "phone": owner.phone}],
            tenant_snapshot=[{"person_id": str(tenant.id), "name": tenant.name, "email": tenant.email, "phone": tenant.phone}],
            rules_snapshot={},
            signers_snapshot=[],
            current_version=1,
            signing_provider="clicksign",
            signing_status="signed",
            signed_at=datetime.now(timezone.utc),
            archive_status="archived",
            final_document_hash="c" * 64,
            created_by_user_id=identity["user_id"],
        )
        db.add(lease)
        db.flush()
        case = LeaseLifecycleCase(
            organization_id=identity["organization_id"],
            lease_contract_id=lease.id,
            property_id=prop.id,
            process_type="termination",
            status="termination_requested",
            initiated_by="tenant",
            requested_at=datetime.now(timezone.utc),
            effective_date=today + timedelta(days=30),
            reason="Desocupação solicitada pelo locatário.",
            termination_fine_amount=Decimal("0.00"),
            fine_status="not_applicable",
            created_by_user_id=identity["user_id"],
        )
        db.add(case)
        db.commit()
        return tenant.id, owner.id, prop.id, lease.id, case.id


def _messages(db, identity, category):
    return db.scalars(
        select(CommunicationMessage).where(
            CommunicationMessage.organization_id == identity["organization_id"],
            CommunicationMessage.category == category,
        ).order_by(CommunicationMessage.internal_number.asc())
    ).all()


def test_lease_exit_milestones_create_human_review_messages_and_agenda_tasks(identity):
    tenant_id, owner_id, property_id, lease_id, case_id = _setup_lease(identity)
    assert SessionLocal is not None

    with SessionLocal() as db:
        requested = _messages(db, identity, "lease_exit_requested")
        assert len(requested) == 2
        assert {item.person_id for item in requested} == {tenant_id, owner_id}
        assert all(item.status == "pending" and item.origin == "suggestion" for item in requested)

    scheduled_at = datetime.now(timezone.utc) + timedelta(days=5)
    with SessionLocal() as db:
        lease = db.get(LeaseContract, lease_id)
        case = db.get(LeaseLifecycleCase, case_id)
        inspection = Inspection(
            organization_id=identity["organization_id"],
            lease_contract_id=lease.id,
            property_id=property_id,
            inspection_type="final",
            status="draft",
            lease_snapshot={
                "lease_code": f"LOC-{lease.internal_number:06d}",
                "property": dict(lease.property_snapshot or {}),
                "owners": list(lease.owner_snapshot or []),
                "tenants": list(lease.tenant_snapshot or []),
                "inspection_contest_days": lease.inspection_contest_days,
                "lifecycle_case_id": str(case.id),
                "inspection_purpose": "lease_exit",
            },
            environments=[],
            contestations=[],
            scheduled_at=scheduled_at,
            current_version=1,
            created_by_user_id=identity["user_id"],
        )
        db.add(inspection)
        db.flush()
        case.exit_inspection_id = inspection.id
        case.status = "exit_inspection_pending"
        db.commit()

    with SessionLocal() as db:
        inspection_messages = _messages(db, identity, "inspection_schedule")
        assert len(inspection_messages) == 1
        assert inspection_messages[0].person_id == tenant_id
        assert "agendada para" in inspection_messages[0].body

    returned_at = datetime.now(timezone.utc)
    with SessionLocal() as db:
        case = db.get(LeaseLifecycleCase, case_id)
        case.keys_returned_at = returned_at
        case.status = "financial_clearance_pending"
        db.commit()

    with SessionLocal() as db:
        keys = _messages(db, identity, "lease_exit_keys_returned")
        assert len(keys) == 2
        assert {item.person_id for item in keys} == {tenant_id, owner_id}

    with SessionLocal() as db:
        title = FinancialTitle(
            organization_id=identity["organization_id"],
            direction="receivable",
            fund_scope="third_party",
            source_type="lease_exit_adjustment",
            source_id=case_id,
            property_id=property_id,
            lease_contract_id=lease_id,
            category="Acerto final da locação",
            description="Reparo identificado na vistoria final",
            counterparty_name="Locatário Saída",
            competence=date.today().replace(day=1),
            due_date=date.today() + timedelta(days=10),
            amount=Decimal("650.00"),
            settled_amount=Decimal("0.00"),
            status="pending",
            source_snapshot={
                "origin": "lease_exit_adjustment",
                "lifecycle_case_id": str(case_id),
                "beneficiary": "owner",
            },
            created_by_user_id=identity["user_id"],
        )
        db.add(title)
        db.commit()
        title_id = title.id

    with SessionLocal() as db:
        pending = _messages(db, identity, "lease_exit_financial_pending")
        assert len(pending) == 2
        assert {item.person_id for item in pending} == {tenant_id, owner_id}
        assert all("R$ 650,00" in item.body for item in pending)
        assert all("third_party" not in item.body and "fund_scope" not in item.body and "beneficiary" not in item.body for item in pending)

    settled_at = datetime.now(timezone.utc)
    with SessionLocal() as db:
        title = db.get(FinancialTitle, title_id)
        title.status = "paid"
        title.settled_amount = title.amount
        title.settled_at = settled_at
        db.commit()

    with SessionLocal() as db:
        resolved = _messages(db, identity, "lease_exit_financial_resolved")
        assert len(resolved) == 2
        assert {item.person_id for item in resolved} == {tenant_id, owner_id}
        assert all("não está mais em aberto" in item.body for item in resolved)

    with SessionLocal() as db:
        case = db.get(LeaseLifecycleCase, case_id)
        case.status = "closed"
        case.closed_at = datetime.now(timezone.utc)
        case.closed_by_user_id = identity["user_id"]
        db.commit()

    with SessionLocal() as db:
        closed = _messages(db, identity, "lease_exit_closed")
        assert len(closed) == 2
        assert {item.person_id for item in closed} == {tenant_id, owner_id}

        logic.sync_system_tasks(db, identity["organization_id"])
        db.flush()
        expected_departments = {
            "lease_exit_requested": "Operações",
            "inspection_schedule": "Operações",
            "lease_exit_keys_returned": "Operações",
            "lease_exit_financial_pending": "Financeiro",
            "lease_exit_financial_resolved": "Financeiro",
            "lease_exit_closed": "Operações",
        }
        messages = db.scalars(
            select(CommunicationMessage).where(
                CommunicationMessage.organization_id == identity["organization_id"],
                CommunicationMessage.category.in_(tuple(expected_departments)),
            )
        ).all()
        assert messages
        for message in messages:
            task = db.scalar(
                select(AgendaTask).where(
                    AgendaTask.organization_id == identity["organization_id"],
                    AgendaTask.source_module == "communications",
                    AgendaTask.source_type == "communication_review",
                    AgendaTask.source_id == str(message.id),
                    AgendaTask.reschedule_sequence == 0,
                )
            )
            assert task is not None
            assert task.status == "pending"
            assert task.mandatory_action is True
            department = db.get(AgendaDepartment, task.department_id)
            assert department is not None
            assert department.name == expected_departments[message.category]
