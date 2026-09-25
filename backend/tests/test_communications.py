from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.api.routes import communications as communication_routes
from app.core.database import SessionLocal
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person, Property
from app.domains.finance.models import RentCharge
from app.main import app


COMMUNICATION_PERMISSIONS = frozenset({"communications.view", "communications.manage", "communications.send"})


def _enable_permissions(identity):
    context = identity["context"]
    expanded = UserContext(user=context.user, permission_keys=context.permission_keys | COMMUNICATION_PERMISSIONS)
    app.dependency_overrides[get_current_user_context] = lambda: expanded


def _tenant_and_overdue_charge(identity):
    assert SessionLocal is not None
    with SessionLocal() as db:
        tenant = Person(
            organization_id=identity["organization_id"],
            person_type="individual",
            name="Locatário Comunicação",
            document_number="39053344705",
            email="locatario@example.invalid",
            phone="41999990000",
            address={},
            is_active=True,
            created_by_user_id=identity["user_id"],
        )
        prop = Property(
            organization_id=identity["organization_id"],
            property_type="apartment",
            purpose="rent",
            status="rented",
            address={"street": "Rua Teste", "number": "10", "city": "Curitiba", "state": "PR"},
            rent_amount=Decimal("2000.00"),
            created_by_user_id=identity["user_id"],
        )
        db.add_all([tenant, prop]); db.flush()
        today = date.today()
        lease = LeaseContract(
            organization_id=identity["organization_id"],
            property_id=prop.id,
            status="signed",
            rent_amount=Decimal("2000.00"),
            due_day=10,
            adjustment_index="IPCA",
            adjustment_period_months=12,
            adjustment_base_date=today - timedelta(days=365),
            next_adjustment_date=today + timedelta(days=200),
            term_months=30,
            start_date=today - timedelta(days=200),
            end_date=today + timedelta(days=500),
            termination_fine_months=Decimal("3.00"),
            inspection_contest_days=5,
            guarantee_type="insurance",
            guarantee_details={},
            property_snapshot={"code": "000001"},
            owner_snapshot=[],
            tenant_snapshot=[{"person_id": str(tenant.id), "name": tenant.name, "email": tenant.email, "phone": tenant.phone}],
            rules_snapshot={},
            signers_snapshot=[],
            current_version=1,
            signing_provider="clicksign",
            signing_status="signed",
            signed_at=datetime.now(timezone.utc),
            archive_status="archived",
            final_document_hash="a" * 64,
            created_by_user_id=identity["user_id"],
        )
        db.add(lease); db.flush()
        charge = RentCharge(
            organization_id=identity["organization_id"],
            lease_contract_id=lease.id,
            property_id=prop.id,
            competence=today.replace(day=1),
            due_date=today - timedelta(days=6),
            status="overdue",
            rent_amount=Decimal("2000.00"),
            gross_amount=Decimal("2350.00"),
            charge_items=[{"kind": "guarantee_insurance", "amount": 350, "agency_retention_amount": 100, "third_party_net_amount": 250}],
            tenant_snapshot=[{"person_id": str(tenant.id), "name": tenant.name, "email": tenant.email, "phone": tenant.phone}],
            property_snapshot={"code": "000001"},
            owner_snapshot=[],
            admin_terms_snapshot={},
            created_by_user_id=identity["user_id"],
        )
        db.add(charge); db.commit(); db.refresh(tenant); db.refresh(charge)
        return tenant.id, charge.id


def test_suggestions_are_human_controlled_idempotent_and_tenant_safe(client, identity, monkeypatch):
    _enable_permissions(identity)
    tenant_id, charge_id = _tenant_and_overdue_charge(identity)

    first = client.post("/api/communications/suggestions/refresh", json={"include_overdue_charges": True, "include_contracts": False, "include_owner_repasses": False})
    assert first.status_code == 200
    assert first.json()["created"] == 1
    second = client.post("/api/communications/suggestions/refresh", json={"include_overdue_charges": True, "include_contracts": False, "include_owner_repasses": False})
    assert second.status_code == 200
    assert second.json()["created"] == 0

    messages = client.get("/api/communications/messages").json()
    assert len(messages) == 1
    message = messages[0]
    assert message["person_id"] == str(tenant_id)
    assert message["source_id"] == str(charge_id)
    assert message["status"] == "pending"
    assert "R$ 2.350,00" in message["body"]
    assert "agency_retention" not in message["body"]
    assert "third_party" not in message["body"]
    assert message["attempt_count"] == 0

    # Sem SMTP real, o ERP não finge que enviou.
    blocked = client.post(f"/api/communications/messages/{message['id']}/send")
    assert blocked.status_code == 409
    current = client.get(f"/api/communications/messages/{message['id']}").json()
    assert current["status"] == "pending"
    assert current["attempt_count"] == 0

    delivered = []
    monkeypatch.setattr(communication_routes, "smtp_configured", lambda: True)
    monkeypatch.setattr(communication_routes, "send_email_message", lambda **kwargs: delivered.append(kwargs))
    sent = client.post(f"/api/communications/messages/{message['id']}/send")
    assert sent.status_code == 200
    payload = sent.json()
    assert payload["status"] == "sent"
    assert payload["attempt_count"] == 1
    assert payload["sent_by_user_id"] == str(identity["user_id"])
    assert delivered and delivered[0]["recipient"] == "locatario@example.invalid"
    assert any(event["event_type"] == "sent" for event in payload["events"])
    assert client.patch(f"/api/communications/messages/{message['id']}", json={"subject": "alteração indevida"}).status_code == 409


def test_preferences_and_unavailable_whatsapp_block_external_delivery(client, identity, monkeypatch):
    _enable_permissions(identity)
    tenant_id, _ = _tenant_and_overdue_charge(identity)
    monkeypatch.setattr(communication_routes, "smtp_configured", lambda: True)
    calls = []
    monkeypatch.setattr(communication_routes, "send_email_message", lambda **kwargs: calls.append(kwargs))

    created = client.post("/api/communications/messages", json={
        "person_id": str(tenant_id), "recipient_role": "tenant", "channel": "email", "category": "manual",
        "subject": "Teste", "body": "Mensagem de teste controlada"
    })
    assert created.status_code == 201
    message_id = created.json()["id"]

    preference = client.put(f"/api/communications/preferences/{tenant_id}", json={
        "email_enabled": False, "whatsapp_enabled": False, "transactional_enabled": True, "preferred_channel": "email", "notes": "Não enviar e-mail"
    })
    assert preference.status_code == 200
    blocked = client.post(f"/api/communications/messages/{message_id}/send")
    assert blocked.status_code == 409
    assert "desativado" in blocked.json()["detail"].lower()
    assert calls == []

    whatsapp = client.post("/api/communications/messages", json={
        "recipient_name": "Contato WhatsApp", "recipient_phone": "41999990000", "recipient_role": "other",
        "channel": "whatsapp", "category": "manual", "subject": "", "body": "Mensagem futura"
    })
    assert whatsapp.status_code == 201
    whats_id = whatsapp.json()["id"]
    blocked_whatsapp = client.post(f"/api/communications/messages/{whats_id}/send")
    assert blocked_whatsapp.status_code == 409
    assert "whatsapp" in blocked_whatsapp.json()["detail"].lower()
    assert client.get("/api/communications/capabilities").json()["whatsapp"]["configured"] is False


def test_templates_are_safe_and_customizable(client, identity):
    _enable_permissions(identity)
    templates = client.get("/api/communications/templates")
    assert templates.status_code == 200
    rows = templates.json()
    overdue = next(item for item in rows if item["key"] == "rent_overdue")
    updated = client.put(f"/api/communications/templates/{overdue['id']}", json={
        "name": "Cobrança amigável",
        "subject_template": "{{charge_code}} · {{organization_name}}",
        "body_template": "Olá, {{recipient_name}}. Valor: {{amount}}. Campo desconhecido permanece: {{nao_existe}}.",
        "is_active": True,
    })
    assert updated.status_code == 200
    assert updated.json()["name"] == "Cobrança amigável"
    # A sintaxe é substituição de tokens; não existe eval/expressão executável.
    assert "{{charge_code}}" in updated.json()["subject_template"]
