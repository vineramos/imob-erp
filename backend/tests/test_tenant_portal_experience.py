from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.api.routes import tenant_portal_charges
from app.core.database import SessionLocal
from app.domains.communications.models import CommunicationMessage
from app.domains.portfolio.models import Person
from tests.helpers import (
    assert_response,
    build_signed_rental,
    create_person,
    create_property,
    create_signed_administration_contract,
    create_signed_lease_contract,
    first_month,
)


def _enable_portal(client, person: dict, password: str) -> None:
    access = assert_response(
        client.post(
            "/api/finance/advanced/portal/access",
            json={"person_id": person["id"], "label": "Portal do inquilino"},
        ),
        201,
    ).json()
    assert_response(
        client.post(
            f"/api/finance/advanced/portal/access/{access['id']}/credentials",
            json={"password": password},
        )
    )
    assert_response(
        client.post(
            "/api/tenant-portal/auth/login",
            json={"email": person["email"], "password": password},
        )
    )


def _second_signed_rental(client) -> dict:
    start = first_month()
    owner = create_person(
        client,
        name="Segundo Proprietário",
        document="33333333333",
        email="segundo-proprietario@example.com",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    tenant = create_person(
        client,
        name="Segundo Inquilino",
        document="44444444444",
        email="segundo-inquilino@example.com",
        role_keys=["tenant"],
    )
    administration = create_signed_administration_contract(client, property_item["id"], start=start)
    lease = create_signed_lease_contract(client, property_item["id"], tenant["id"], start=start)
    return {"owner": owner, "property": property_item, "tenant": tenant, "administration": administration, "lease": lease}


def test_tenant_portal_receipt_exit_communications_and_cross_tenant_isolation(client):
    journey = build_signed_rental(client, publish=False)
    tenant = journey["tenant"]
    lease = journey["lease"]
    _enable_portal(client, tenant, "PortalTenant#2026")

    generated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": journey["start"].isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()
    assert generated["generated"] == 1
    charge = generated["charges"][0]

    assert client.get(f"/api/tenant-portal/charges/{charge['id']}/receipt.pdf").status_code == 409
    paid = assert_response(
        client.post(
            f"/api/finance/charges/{charge['id']}/payment",
            json={
                "paid_amount": str(charge["gross_amount"]),
                "paid_at": datetime.now(timezone.utc).isoformat(),
                "payment_method": "pix",
                "payment_reference": "PIX-PORTAL-TESTE",
                "notes": "Liquidação integral da jornada do portal.",
            },
        )
    ).json()
    assert paid["status"] == "paid"

    receipt = assert_response(client.get(f"/api/tenant-portal/charges/{charge['id']}/receipt.pdf"))
    assert receipt.headers["content-type"].startswith("application/pdf")
    assert receipt.content.startswith(b"%PDF")

    overview = assert_response(client.get("/api/tenant-portal/overview")).json()
    signed_document = next(
        item for item in overview["documents"]
        if item["key"].startswith(f"system:lease_contract:{lease['id']}:") and "Assinado" in item["title"]
    )

    assert SessionLocal is not None
    with SessionLocal() as db:
        person = db.get(Person, UUID(tenant["id"]))
        assert person is not None
        now = datetime.now(timezone.utc)
        db.add_all([
            CommunicationMessage(
                organization_id=person.organization_id,
                person_id=person.id,
                recipient_name=person.name,
                recipient_email=person.email,
                recipient_role="tenant",
                channel="email",
                category="lease_signed",
                origin="manual",
                subject="Mensagem entregue ao inquilino",
                body="Conteúdo externo seguro e já enviado.",
                status="sent",
                sent_at=now,
            ),
            CommunicationMessage(
                organization_id=person.organization_id,
                person_id=person.id,
                recipient_name=person.name,
                recipient_email=person.email,
                recipient_role="tenant",
                channel="email",
                category="manual",
                origin="manual",
                subject="Rascunho interno",
                body="Não deve aparecer no portal.",
                status="draft",
            ),
            CommunicationMessage(
                organization_id=person.organization_id,
                person_id=person.id,
                recipient_name=person.name,
                recipient_email=person.email,
                recipient_role="owner",
                channel="email",
                category="owner_repasse_paid",
                origin="manual",
                subject="Mensagem do papel proprietário",
                body="Também não deve aparecer no portal do inquilino.",
                status="sent",
                sent_at=now,
            ),
        ])
        db.commit()

    experience = assert_response(client.get("/api/tenant-portal/experience")).json()
    assert [item["subject"] for item in experience["communications"]] == ["Mensagem entregue ao inquilino"]
    assert experience["lifecycle"] == []

    effective = date.today() + timedelta(days=30)
    lifecycle = assert_response(
        client.post(
            "/api/tenant-portal/termination",
            json={
                "lease_contract_id": lease["id"],
                "effective_date": effective.isoformat(),
                "reason": "Mudança para outra cidade por motivo profissional.",
            },
        ),
        201,
    ).json()
    assert lifecycle["status"] == "termination_requested"
    assert lifecycle["initiated_by"] == "tenant"
    assert lifecycle["effective_date"] == effective.isoformat()
    assert "financial_clearance" not in lifecycle
    assert "fine_title_id" not in lifecycle
    assert "returned_keys" not in lifecycle

    refreshed = assert_response(client.get("/api/tenant-portal/experience")).json()
    tenant_case = next(item for item in refreshed["lifecycle"] if item["lease_contract_id"] == lease["id"])
    assert tenant_case["status"] == "termination_requested"
    assert tenant_case["financial_pending_count"] == 0

    # O endpoint externo nunca aceita que o locatário force outro iniciador.
    assert client.post(
        "/api/tenant-portal/termination",
        json={
            "lease_contract_id": lease["id"],
            "effective_date": effective.isoformat(),
            "reason": "Tentativa inválida",
            "initiated_by": "owner",
        },
    ).status_code == 422

    assert_response(client.post("/api/tenant-portal/auth/logout"), 204)
    second = _second_signed_rental(client)
    _enable_portal(client, second["tenant"], "SegundoTenant#2026")

    assert client.get(f"/api/tenant-portal/charges/{charge['id']}/receipt.pdf").status_code == 404
    assert client.get(f"/api/tenant-portal/documents/{signed_document['key']}/content").status_code == 404
    assert client.post(
        "/api/tenant-portal/termination",
        json={
            "lease_contract_id": lease["id"],
            "effective_date": effective.isoformat(),
            "reason": "Não pertence a este locatário.",
        },
    ).status_code == 404
    second_experience = assert_response(client.get("/api/tenant-portal/experience")).json()
    assert all(item["lease_contract_id"] != lease["id"] for item in second_experience["lifecycle"])
    assert all(item["subject"] != "Mensagem entregue ao inquilino" for item in second_experience["communications"])


def test_tenant_charge_rule_does_not_expose_internal_beneficiary_or_split():
    safe = tenant_portal_charges._safe_rule({
        "key": "insurance",
        "kind": "insurance",
        "label": "Seguro",
        "amount": "500.00",
        "payer": "tenant",
        "beneficiary": "third_party",
        "beneficiary_name": "Seguradora Interna",
        "agency_retention_type": "percent",
        "agency_retention_value": "30.00",
        "agency_retention_amount": "150.00",
        "third_party_net_amount": "350.00",
        "frequency": "monthly",
    })
    assert safe["label"] == "Seguro"
    assert safe["amount"] == 500.0
    forbidden = {
        "beneficiary",
        "beneficiary_name",
        "agency_retention_type",
        "agency_retention_value",
        "agency_retention_amount",
        "third_party_net_amount",
    }
    assert forbidden.isdisjoint(safe)
