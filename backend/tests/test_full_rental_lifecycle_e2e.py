from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.finance.late_charges import amount_due
from app.domains.finance.models import RentCharge
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.lease_lifecycle.models import LeaseExitAdjustment
from app.domains.portfolio.models import Property
from app.main import app
from tests.helpers import (
    _run_signature_flow,
    add_months,
    assert_response,
    create_person,
    create_property,
    create_signed_administration_contract,
    decimal,
    first_month,
    midday,
    publish_property,
)


def _next_weekday(days_ahead: int = 2) -> date:
    value = date.today() + timedelta(days=days_ahead)
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def _inspection_environment(condition: str, notes: str) -> list[dict]:
    return [
        {
            "key": "sala",
            "name": "Sala",
            "notes": None,
            "items": [
                {
                    "key": "parede-principal",
                    "label": "Parede principal",
                    "condition": condition,
                    "notes": notes,
                    "photos": [],
                }
            ],
        }
    ]


def _set_late_defaults(client) -> None:
    payload = assert_response(client.get("/api/settings/operations")).json()
    payload.update(
        {
            "late_fee_percent": 2.0,
            "late_interest_percent_monthly": 1.0,
            "late_interest_type": "simple",
            "late_interest_compounding": "daily",
        }
    )
    saved = assert_response(client.put("/api/settings/operations", json=payload)).json()
    assert saved["late_fee_percent"] == 2.0
    assert saved["late_interest_percent_monthly"] == 1.0
    assert saved["late_interest_type"] == "simple"


def _bank_account(client, *, name: str, fund_scope: str) -> dict:
    return assert_response(
        client.post(
            "/api/finance/banking/accounts",
            json={
                "name": name,
                "bank_name": "Banco E2E",
                "bank_code": "999",
                "branch": "0001",
                "account_number": "987654",
                "account_digit": "0",
                "account_type": "checking",
                "fund_scope": fund_scope,
                "provider": "manual",
                "opening_balance": "0.00",
            },
        )
    ).json()


def test_full_rental_lifecycle_from_public_lead_to_key_return(client, identity):
    """Jornada canônica: lead -> locação -> financeiro -> manutenção -> desocupação.

    O teste usa somente PostgreSQL descartável e providers fake da suíte. Onde o
    relógio precisaria avançar vários dias, apenas datas do banco de teste são
    deslocadas; nenhuma integração externa real é acionada.
    """
    _set_late_defaults(client)
    start = first_month()

    # 1) Estoque publicado e contrato de administração vigente.
    owner = create_person(
        client,
        name="Proprietário Jornada Completa",
        document="81111111111",
        email="owner.full.e2e@example.com",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    publication = publish_property(client, property_item["id"])
    create_signed_administration_contract(client, property_item["id"], start=start)

    # 2) Interessado entra pelo site público e cai no CRM.
    organization_id = str(identity["organization_id"])
    lead_email = "tenant.full.e2e@example.com"
    assert_response(
        client.post(
            f"/api/public/sites/{organization_id}/properties/{publication['public_slug']}/inquiries",
            json={
                "name": "Locatário Jornada Completa",
                "email": lead_email,
                "phone": "(41) 99991-7711",
                "preferred_contact": "whatsapp",
                "message": "Quero visitar e apresentar proposta para este imóvel.",
                "consent": True,
                "website": "",
            },
        ),
        201,
    )

    base_context = identity["context"]
    expanded = UserContext(
        user=base_context.user,
        permission_keys=base_context.permission_keys
        | frozenset({"crm.view", "crm.manage", "communications.view", "communications.manage", "communications.send"}),
    )
    app.dependency_overrides[get_current_user_context] = lambda: expanded

    inquiries = assert_response(client.get("/api/crm/site-inquiries")).json()
    lead = next(item for item in inquiries if item["email"] == lead_email)
    assert lead["status"] == "new"
    assert lead["property_id"] == property_item["id"]

    # 3) Atendimento comercial: visita -> proposta -> contrato.
    visit_start = datetime.combine(_next_weekday(), time(hour=16), tzinfo=timezone.utc)
    visit = assert_response(
        client.post(
            f"/api/crm/site-inquiries/{lead['id']}/visits",
            json={
                "starts_at": visit_start.isoformat(),
                "duration_minutes": 60,
                "notes": "Visita da jornada E2E completa.",
            },
        ),
        201,
    ).json()
    assert visit["agenda_task_id"]
    assert_response(client.patch(f"/api/crm/visits/{visit['id']}", json={"status": "completed", "notes": None}))

    funnel = assert_response(client.get(f"/api/crm/site-inquiries/{lead['id']}/funnel")).json()
    tenant = funnel["person"]
    assert tenant is not None
    assert tenant["name"] == "Locatário Jornada Completa"

    proposal = assert_response(
        client.post(
            f"/api/crm/site-inquiries/{lead['id']}/proposals",
            json={
                "rent_amount": "2000.00",
                "start_date": start.isoformat(),
                "term_months": 30,
                "guarantee_type": "insurance",
                "notes": "Proposta aprovada na jornada completa.",
            },
        ),
        201,
    ).json()
    proposal = assert_response(
        client.patch(f"/api/crm/proposals/{proposal['id']}", json={"status": "accepted", "reason": None})
    ).json()
    assert proposal["status"] == "accepted"

    composition = assert_response(client.get(f"/api/crm/proposals/{proposal['id']}/lease-composition")).json()
    conversion = assert_response(
        client.post(
            f"/api/crm/proposals/{proposal['id']}/convert-to-lease",
            json={"monthly_charges": composition["monthly_charges"]},
        ),
        201,
    ).json()
    lease_id = conversion["lease_contract_id"]
    lease = _run_signature_flow(client, kind="lease", contract_id=lease_id)
    assert lease["status"] == "signed"

    funnel = assert_response(client.get(f"/api/crm/site-inquiries/{lead['id']}/funnel")).json()
    assert funnel["inquiry"]["status"] == "won"
    properties = assert_response(client.get("/api/properties")).json()
    current_property = next(item for item in properties if item["id"] == property_item["id"])
    assert current_property["status"] == "leased"
    assert current_property["publication_enabled"] is False

    # 4) Vistoria inicial e entrega das chaves.
    initial = assert_response(
        client.post(
            "/api/inspections",
            json={
                "lease_contract_id": lease_id,
                "scheduled_at": midday(start).isoformat(),
                "inspector_name": "Vistoriador Jornada Completa",
                "environments": _inspection_environment("good", "Pintura íntegra na entrada."),
                "notes": "Vistoria inicial da jornada completa.",
            },
        ),
        201,
    ).json()
    assert initial["inspection_type"] == "initial"
    initial = assert_response(
        client.post(f"/api/inspections/{initial['id']}/workflow", json={"action": "complete", "reason": None})
    ).json()
    assert initial["status"] == "ready"
    initial = assert_response(
        client.post(
            f"/api/inspections/{initial['id']}/keys",
            json={
                "handed_over_at": midday(start).isoformat(),
                "recipient_name": tenant["name"],
                "recipient_document": None,
                "keys": [{"label": "Porta principal", "quantity": 2, "notes": None}],
                "meter_readings": {"energia": "1000", "agua": "500"},
                "notes": "Chaves entregues ao locatário.",
            },
        ),
        201,
    ).json()
    assert initial["key_handover"] is not None
    initial = assert_response(
        client.post(f"/api/inspections/{initial['id']}/workflow", json={"action": "finalize", "reason": None})
    ).json()
    assert initial["status"] == "finalized"

    # 5) Primeiro aluguel: intermediação de 100%, sem taxa de administração paralela.
    first_charge = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": start.isoformat(), "lease_contract_id": lease_id},
        )
    ).json()["charges"][0]
    first_due = date.fromisoformat(first_charge["due_date"])
    first_paid = assert_response(
        client.post(
            f"/api/finance/charges/{first_charge['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": midday(first_due).isoformat(),
                "payment_method": "pix",
                "payment_reference": "FULL-E2E-FIRST-RENT",
                "notes": None,
            },
        )
    ).json()
    assert decimal(first_paid["settlement"]["intermediation_fee_calculated"]) == decimal("2000.00")
    assert decimal(first_paid["settlement"]["admin_fee_calculated"]) == decimal("0.00")

    # 6) Segundo aluguel: simula D+6 no banco descartável, abre inadimplência,
    # sugere comunicação humana e exige a mora atualizada na baixa.
    second_competence = add_months(start, 1)
    second_charge = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": second_competence.isoformat(), "lease_contract_id": lease_id},
        )
    ).json()["charges"][0]

    assert SessionLocal is not None
    with SessionLocal() as db:
        stored_charge = db.get(RentCharge, UUID(second_charge["id"]))
        assert stored_charge is not None
        stored_charge.due_date = date.today() - timedelta(days=6)
        stored_charge.status = "sent"
        stored_charge.sent_at = datetime.now(timezone.utc) - timedelta(days=7)
        db.commit()

    cases = assert_response(client.post("/api/finance/advanced/delinquency/refresh")).json()
    delinquency = next(item for item in cases if item["charge_id"] == second_charge["id"])
    assert delinquency["days_overdue"] == 6
    assert delinquency["critical"] is True
    assert delinquency["pending_agenda_tasks"] >= 3

    communication_refresh = assert_response(
        client.post(
            "/api/communications/suggestions/refresh",
            json={
                "include_overdue_charges": True,
                "include_contracts": False,
                "include_owner_repasses": False,
            },
        )
    ).json()
    assert communication_refresh["created"] >= 1
    messages = assert_response(client.get("/api/communications/messages")).json()
    overdue_message = next(
        item for item in messages
        if item.get("source_id") == second_charge["id"] and item.get("category") == "rent_overdue"
    )
    assert overdue_message["status"] == "pending"
    assert overdue_message["attempt_count"] == 0

    with SessionLocal() as db:
        stored_charge = db.get(RentCharge, UUID(second_charge["id"]))
        assert stored_charge is not None
        updated_due = amount_due(db, stored_charge, as_of=date.today())
    assert updated_due > Decimal("2000.00")

    nominal_attempt = client.post(
        f"/api/finance/charges/{second_charge['id']}/payment",
        json={
            "paid_amount": "2000.00",
            "paid_at": datetime.now(timezone.utc).isoformat(),
            "payment_method": "pix",
            "payment_reference": "FULL-E2E-NOMINAL-BLOCKED",
            "notes": None,
        },
    )
    assert nominal_attempt.status_code == 409

    second_paid = assert_response(
        client.post(
            f"/api/finance/charges/{second_charge['id']}/payment",
            json={
                "paid_amount": str(updated_due),
                "paid_at": datetime.now(timezone.utc).isoformat(),
                "payment_method": "pix",
                "payment_reference": "FULL-E2E-LATE-RENT",
                "notes": "Pagamento integral atualizado.",
            },
        )
    ).json()
    assert second_paid["status"] == "paid"
    assert decimal(second_paid["late_fee_amount"]) > decimal("0.00")
    assert decimal(second_paid["late_interest_amount"]) > decimal("0.00")
    second_settlement = second_paid["settlement"]
    assert decimal(second_settlement["admin_fee_calculated"]) == decimal("200.00")
    assert decimal(second_settlement["owner_entitlement_amount"]) == decimal(updated_due - Decimal("200.00"))
    repasse = second_settlement["repasses"][0]
    assert repasse["status"] == "pending"

    resolved_cases = assert_response(client.post("/api/finance/advanced/delinquency/refresh")).json()
    resolved = next(item for item in resolved_cases if item["id"] == delinquency["id"])
    assert resolved["status"] == "resolved"

    # 7) Manutenção do proprietário: parceiro recebe o custo real, proprietário
    # recebe o preço comercial como dedução do repasse e a margem fica separada.
    partner = assert_response(
        client.post(
            "/api/maintenance/partners",
            json={
                "name": "Parceiro Jornada Completa",
                "legal_name": "Parceiro Jornada Completa Ltda",
                "document_number": "88999999000188",
                "contact_name": "Técnico E2E",
                "email": "partner.full.e2e@example.com",
                "phone": "(41) 3333-1000",
                "whatsapp": "(41) 99999-1000",
                "address": {"city": "Curitiba", "state": "PR"},
                "specialties": ["Pintura"],
                "pix_key": "partner.full.e2e@example.com",
                "bank_details": {},
                "notes": None,
                "is_active": True,
            },
        ),
        201,
    ).json()
    maintenance_payload = {
        "property_id": property_item["id"],
        "lease_contract_id": lease_id,
        "requester_person_id": tenant["id"],
        "title": "Reparo durante a locação",
        "category": "general",
        "priority": "normal",
        "description": "Reparo de pintura da jornada completa.",
        "notes": None,
    }
    maintenance = assert_response(client.post("/api/maintenance-v2", json=maintenance_payload), 201).json()
    maintenance = assert_response(
        client.post(
            f"/api/maintenance-v2/{maintenance['id']}/services",
            json={"title": "Pintura", "description": "Reparo localizado", "quantity": "1", "unit": "serviço"},
        )
    ).json()
    service_id = maintenance["services"][0]["id"]
    maintenance = assert_response(
        client.put(f"/api/maintenance-v2/{maintenance['id']}", json={**maintenance_payload, "responsibility": "owner"})
    ).json()
    assert maintenance["responsibility"] == "owner"
    maintenance = assert_response(
        client.post(
            f"/api/maintenance-v2/{maintenance['id']}/workflow",
            json={"action": "request_quotes", "reason": None, "scheduled_at": None},
        )
    ).json()
    maintenance = assert_response(
        client.post(
            f"/api/maintenance-v2/{maintenance['id']}/quotes",
            json={
                "partner_id": partner["id"],
                "items": [{"service_id": service_id, "partner_cost": "300.00", "client_price": "400.00"}],
                "valid_until": (date.today() + timedelta(days=10)).isoformat(),
                "payment_terms": "À vista",
                "notes": None,
            },
        )
    ).json()
    quote_id = maintenance["quotes"][0]["id"]
    maintenance = assert_response(client.post(f"/api/maintenance-v2/{maintenance['id']}/quotes/{quote_id}/select")).json()
    maintenance = assert_response(
        client.post(
            f"/api/maintenance-v2/{maintenance['id']}/workflow",
            json={"action": "approve", "reason": None, "scheduled_at": None},
        )
    ).json()
    scheduled_at = datetime.combine(_next_weekday(4), time(hour=14), tzinfo=timezone.utc)
    for action, scheduled in (("schedule", scheduled_at.isoformat()), ("start", None), ("complete", None)):
        maintenance = assert_response(
            client.post(
                f"/api/maintenance-v2/{maintenance['id']}/workflow",
                json={"action": action, "reason": None, "scheduled_at": scheduled},
            )
        ).json()
    assert maintenance["status"] == "completed"
    assert decimal(maintenance["partner_cost_total"]) == decimal("300.00")
    assert decimal(maintenance["client_charge_total"]) == decimal("400.00")
    assert decimal(maintenance["margin_total"]) == decimal("100.00")

    finance_maintenance = assert_response(client.get("/api/finance/maintenance")).json()
    maintenance_case = next(item for item in finance_maintenance["cases"] if item["maintenance_id"] == maintenance["id"])
    assert decimal(maintenance_case["payable"]["amount"]) == decimal("300.00")
    assert decimal(maintenance_case["receivable"]["amount"]) == decimal("400.00")
    assert maintenance_case["receivable"]["collection_method"] == "owner_repasse_deduction"

    assert_response(
        client.post(
            f"/api/finance/maintenance/payables/{maintenance_case['payable']['id']}/payment",
            json={
                "settled_at": datetime.now(timezone.utc).isoformat(),
                "payment_reference": "FULL-E2E-PARTNER",
                "notes": None,
            },
        )
    )
    offset = assert_response(
        client.post(f"/api/finance/maintenance/receivables/{maintenance_case['receivable']['id']}/apply-owner-repasse")
    ).json()
    assert offset["status"] == "settled"
    assert decimal(offset["settled_amount"]) == decimal("400.00")

    repasses = assert_response(client.get("/api/finance/repasses", params={"competence": second_competence.isoformat()})).json()
    current_repasse = next(item for item in repasses if item["id"] == repasse["id"])
    expected_repasse = decimal(second_settlement["owner_entitlement_amount"]) - decimal("400.00")
    assert decimal(current_repasse["amount"]) == expected_repasse

    statement = assert_response(
        client.get(f"/api/finance/statements/{owner['id']}", params={"competence": second_competence.isoformat()})
    ).json()
    assert decimal(statement["total_owner_entitlement"]) == decimal(second_settlement["owner_entitlement_amount"])
    assert decimal(statement["total_repasse"]) == expected_repasse

    paid_repasse = assert_response(
        client.post(
            f"/api/finance/repasses/{repasse['id']}/payment",
            json={
                "paid_at": midday(second_competence.replace(day=12)).isoformat(),
                "payment_reference": "FULL-E2E-OWNER-REPASSE",
                "notes": None,
            },
        )
    ).json()
    assert paid_repasse["status"] == "paid"
    assert decimal(paid_repasse["amount"]) == expected_repasse

    # 8) Desocupação: vistoria final gera evidência, humano aprova o acerto,
    # título automático é conciliado no banco correto e só então a locação fecha.
    effective = add_months(start, 12)
    lifecycle = assert_response(
        client.post(
            f"/api/lease-contracts/{lease_id}/lifecycle/termination",
            json={
                "effective_date": effective.isoformat(),
                "initiated_by": "tenant",
                "reason": "Encerramento da jornada E2E completa.",
            },
        )
    ).json()
    assert lifecycle["fine_status"] == "pending"
    lifecycle = assert_response(
        client.post(
            f"/api/lease-contracts/{lease_id}/lifecycle/fine",
            json={
                "action": "waive",
                "beneficiary": None,
                "amount": None,
                "due_date": None,
                "notes": "Dispensa controlada no cenário E2E.",
            },
        )
    ).json()
    assert lifecycle["fine_status"] == "waived"

    lifecycle = assert_response(
        client.post(
            f"/api/lease-contracts/{lease_id}/lifecycle/exit-inspection",
            json={
                "scheduled_at": midday(effective).isoformat(),
                "inspector_name": "Vistoriador Saída E2E",
                "notes": "Vistoria final da jornada completa.",
            },
        )
    ).json()
    exit_inspection_id = lifecycle["exit_inspection_id"]
    final_inspection = assert_response(
        client.put(
            f"/api/inspections/{exit_inspection_id}",
            json={
                "scheduled_at": midday(effective).isoformat(),
                "inspector_name": "Vistoriador Saída E2E",
                "environments": _inspection_environment("damaged", "Pintura danificada na saída."),
                "notes": "Dano verificado.",
                "change_summary": "Registrar dano final",
            },
        )
    ).json()
    assert final_inspection["environments"][0]["items"][0]["condition"] == "damaged"
    final_inspection = assert_response(
        client.post(f"/api/inspections/{exit_inspection_id}/workflow", json={"action": "complete", "reason": None})
    ).json()
    assert final_inspection["status"] == "ready"

    workspace = assert_response(client.get(f"/api/lease-contracts/{lease_id}/lifecycle/exit-workspace")).json()
    assert workspace["inspection_ready_for_adjustments"] is True
    assert len(workspace["inspection_differences"]) == 1
    assert workspace["financial_blocking_count"] == 0

    workspace = assert_response(
        client.post(
            f"/api/lease-contracts/{lease_id}/lifecycle/exit-adjustments",
            json={
                "kind": "damage",
                "description": "Pintura da parede principal",
                "beneficiary": "owner",
                "amount": "450.00",
                "due_date": effective.isoformat(),
                "source_context": {
                    "source": "inspection_difference",
                    "environment_key": "sala",
                    "item_key": "parede-principal",
                    "initial_condition": "good",
                    "final_condition": "damaged",
                },
                "notes": "Valor aprovado humanamente após comparar os laudos.",
            },
        ),
        201,
    ).json()
    assert workspace["financial_blocking_count"] == 1
    adjustment = workspace["adjustments"][0]

    keys = assert_response(
        client.post(
            f"/api/lease-contracts/{lease_id}/lifecycle/keys-return",
            json={
                "returned_at": midday(effective).isoformat(),
                "received_by": "Administrativo Jornada E2E",
                "received_document": None,
                "keys": [{"label": "Chaves do imóvel", "quantity": 2, "notes": None}],
                "meter_readings": {"energia": "1400", "agua": "700"},
                "notes": "Chaves devolvidas após vistoria final.",
            },
        )
    ).json()
    assert keys["exit_inspection_status"] == "finalized"
    assert keys["can_close"] is False

    blocked_close = client.post(
        f"/api/lease-contracts/{lease_id}/lifecycle/close",
        json={"property_disposition": "available", "notes": "Ainda deve bloquear."},
    )
    assert blocked_close.status_code == 409

    with SessionLocal() as db:
        db_adjustment = db.get(LeaseExitAdjustment, UUID(adjustment["id"]))
        assert db_adjustment is not None
        assert db_adjustment.financial_title_id is not None
        title_id = str(db_adjustment.financial_title_id)

    third_party_account = _bank_account(client, name="Conta de recebimentos de terceiros E2E", fund_scope="third_party")
    bank_tx = assert_response(
        client.post(
            f"/api/finance/banking/accounts/{third_party_account['id']}/transactions",
            json={
                "transaction_date": date.today().isoformat(),
                "direction": "credit",
                "amount": "450.00",
                "description": "Acerto de dano da saída",
                "counterparty_name": tenant["name"],
                "bank_reference": "FULL-E2E-EXIT-450",
            },
        )
    ).json()
    candidates = assert_response(client.get(f"/api/finance/banking/transactions/{bank_tx['id']}/candidates")).json()
    assert any(item["target_id"] == title_id for item in candidates)
    reconciled = assert_response(
        client.post(
            f"/api/finance/banking/transactions/{bank_tx['id']}/reconcile",
            json={
                "target_type": "financial_title",
                "target_id": title_id,
                "amount": "450.00",
                "notes": "Acerto final conciliado pela jornada E2E.",
            },
        )
    ).json()
    assert reconciled["status"] == "reconciled"

    workspace = assert_response(client.get(f"/api/lease-contracts/{lease_id}/lifecycle/exit-workspace")).json()
    assert workspace["financial_blocking_count"] == 0
    assert workspace["can_close"] is True

    closed = assert_response(
        client.post(
            f"/api/lease-contracts/{lease_id}/lifecycle/close",
            json={"property_disposition": "available", "notes": "Jornada E2E concluída."},
        )
    ).json()
    assert closed["status"] == "closed"

    with SessionLocal() as db:
        prop = db.get(Property, UUID(property_item["id"]))
        assert prop is not None
        assert prop.status == "available"

    final_funnel = assert_response(client.get(f"/api/crm/site-inquiries/{lead['id']}/funnel")).json()
    assert final_funnel["inquiry"]["status"] == "won"

    # A vida comercial fica histórica, enquanto a locação operacional terminou.
    terminations = assert_response(client.get("/api/lease-lifecycle/terminations")).json()
    final_case = next(item for item in terminations if item["lease_contract_id"] == lease_id)
    assert final_case["lifecycle_status"] == "closed"
    assert final_case["financial_blocking_count"] == 0
