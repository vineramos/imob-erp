from __future__ import annotations

import calendar
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.domains.contracts.models import AdministrationContract
from app.domains.leases.models import LeaseContract


def assert_response(response, status_code: int = 200):
    assert response.status_code == status_code, (
        f"{response.request.method} {response.request.url}: esperado HTTP {status_code}, "
        f"recebido {response.status_code}. Corpo: {response.text}"
    )
    return response


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def first_month() -> date:
    # Mantém as jornadas financeiras em competências já encerradas para que\n    # regras que proíbem liquidações/pagamentos no futuro sejam testadas de forma determinística.\n    return add_months(date.today().replace(day=1), -2)


def midday(value: date) -> datetime:
    return datetime.combine(value, time(hour=15), tzinfo=timezone.utc)


def create_person(
    client: TestClient,
    *,
    name: str,
    document: str,
    email: str,
    role_keys: list[str],
) -> dict[str, Any]:
    safe_email = email.replace("@imob.invalid", "@example.com")
    response = client.post(
        "/api/people",
        json={
            "person_type": "individual",
            "name": name,
            "document_number": document,
            "email": safe_email,
            "phone": "(41) 99999-0000",
            "address": {
                "street": "Rua dos Testes",
                "number": "100",
                "complement": "",
                "neighborhood": "Centro",
                "city": "Curitiba",
                "state": "PR",
                "postal_code": "80000-000",
            },
            "notes": "Cadastro gerado pela suíte automatizada.",
            "role_keys": role_keys,
        },
    )
    return assert_response(response, 201).json()


def create_property(client: TestClient, owner_id: str, *, status: str = "available") -> dict[str, Any]:
    response = client.post(
        "/api/properties",
        json={
            "property_type": "apartment",
            "purpose": "rent",
            "status": status,
            "address": {
                "street": "Rua do Imóvel Automatizado",
                "number": "321",
                "complement": "Apto 42",
                "neighborhood": "Batel",
                "city": "Curitiba",
                "state": "PR",
                "postal_code": "80420-000",
            },
            "rent_amount": "2000.00",
            "condo_amount": "0.00",
            "iptu_amount": "0.00",
            "area_m2": "75.00",
            "bedrooms": 2,
            "suites": 1,
            "bathrooms": 2,
            "parking_spaces": 1,
            "furnished": False,
            "pets_allowed": True,
            "public_title": "Apartamento de teste no Batel",
            "public_description": "Apartamento criado automaticamente para validar a jornada completa de publicação do ERP.",
            "publication_enabled": False,
            "owners": [{"person_id": owner_id, "ownership_percent": "100.00"}],
        },
    )
    return assert_response(response, 201).json()


def publish_property(client: TestClient, property_id: str) -> dict[str, Any]:
    photo = client.post(
        f"/api/properties/{property_id}/photos",
        files={"file": ("fachada-teste.jpg", b"imagem-de-teste", "image/jpeg")},
    )
    assert_response(photo, 201)

    readiness = assert_response(client.get(f"/api/properties/{property_id}/publication-readiness")).json()
    assert readiness["ready"] is True, readiness

    published = assert_response(
        client.post(f"/api/properties/{property_id}/publication", json={"enabled": True, "reason": None})
    ).json()
    assert published["publication_enabled"] is True
    assert published["public_slug"]
    return published


def _simulate_provider_closed(model, contract_id: str) -> None:
    assert SessionLocal is not None
    with SessionLocal() as db:
        item = db.get(model, UUID(contract_id))
        assert item is not None
        item.signing_status = "provider_closed_pending_archive"
        db.commit()


def _run_signature_flow(client: TestClient, *, kind: str, contract_id: str) -> dict[str, Any]:
    if kind == "administration":
        base = f"/api/administration-contracts/{contract_id}"
        model = AdministrationContract
    elif kind == "lease":
        base = f"/api/lease-contracts/{contract_id}"
        model = LeaseContract
    else:  # pragma: no cover - erro de programação do teste
        raise AssertionError(f"Tipo de contrato desconhecido: {kind}")

    for action, expected_status in (("submit_review", "review"), ("approve", "approved"), ("prepare_signature", "pending_signature")):
        payload = assert_response(client.post(f"{base}/workflow", json={"action": action, "reason": None})).json()
        assert payload["status"] == expected_status

    document = assert_response(client.post(f"{base}/document")).json()
    assert document["hash_sha256"]
    assert document["reference"].startswith("fake://")

    sent = assert_response(client.post(f"{base}/signature/send")).json()
    assert sent["signing_status"] == "provider_running"
    assert str(sent["signing_envelope_id"]).startswith("test-envelope-")

    # Único passo que representa o mundo externo: o webhook/provider confirma que
    # todos assinaram. A partir daqui o arquivamento e os efeitos são do Imob.
    _simulate_provider_closed(model, contract_id)
    archived = assert_response(client.post(f"{base}/signature/archive")).json()
    assert archived["status"] == "signed"
    assert archived["archive_status"] == "archived"
    assert archived["signing_status"] == "signed_archived"
    assert archived["final_document_hash"]
    return archived


def create_signed_administration_contract(
    client: TestClient,
    property_id: str,
    *,
    start: date,
) -> dict[str, Any]:
    response = client.post(
        "/api/administration-contracts",
        json={
            "property_id": property_id,
            "plan": "essential",
            "admin_fee_type": "percent",
            "admin_fee_percent": "10.00",
            "admin_fee_amount": None,
            "intermediation_percent": "100.00",
            "intermediation_installments": 1,
            "owner_repasse_business_days": 2,
            "condo_operational_payer": "tenant",
            "iptu_operational_payer": "tenant",
            "publication_requires_owner_approval": False,
            "maintenance_limit_amount": None,
            "emergency_limit_amount": None,
            "start_date": start.isoformat(),
            "end_date": add_months(start, 60).isoformat(),
            "end_of_term_action": "renew_indefinite",
            "notes": "Contrato de administração da jornada automatizada.",
            "signers": [],
        },
    )
    created = assert_response(response, 201).json()
    return _run_signature_flow(client, kind="administration", contract_id=created["id"])


def create_signed_lease_contract(
    client: TestClient,
    property_id: str,
    tenant_id: str,
    *,
    start: date,
) -> dict[str, Any]:
    response = client.post(
        "/api/lease-contracts",
        json={
            "property_id": property_id,
            "tenant_ids": [tenant_id],
            "rent_amount": "2000.00",
            "due_day": 10,
            "adjustment_index": "IPCA",
            "adjustment_period_months": 12,
            "adjustment_base_date": start.isoformat(),
            "next_adjustment_date": add_months(start, 12).isoformat(),
            "term_months": 30,
            "start_date": start.isoformat(),
            "end_date": add_months(start, 30).isoformat(),
            "termination_fine_months": "3.00",
            "inspection_contest_days": 5,
            "guarantee_type": "insurance",
            "guarantee_details": {"test_mode": True},
            "monthly_charges": [],
            "notes": "Locação fictícia da jornada automatizada.",
            "signers": [],
        },
    )
    created = assert_response(response, 201).json()
    return _run_signature_flow(client, kind="lease", contract_id=created["id"])


def build_signed_rental(client: TestClient, *, publish: bool = True) -> dict[str, Any]:
    start = first_month()
    owner = create_person(
        client,
        name="Proprietário Teste",
        document="11111111111",
        email="proprietario@example.com",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    publication = publish_property(client, property_item["id"]) if publish else None
    tenant = create_person(
        client,
        name="Inquilino Teste",
        document="22222222222",
        email="inquilino@example.com",
        role_keys=["tenant"],
    )
    administration = create_signed_administration_contract(client, property_item["id"], start=start)
    lease = create_signed_lease_contract(client, property_item["id"], tenant["id"], start=start)
    return {
        "start": start,
        "owner": owner,
        "property": property_item,
        "publication": publication,
        "tenant": tenant,
        "administration": administration,
        "lease": lease,
    }


def decimal(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))
