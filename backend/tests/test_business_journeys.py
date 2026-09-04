from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from tests.helpers import (
    add_months,
    assert_response,
    build_signed_rental,
    create_person,
    create_property,
    decimal,
    first_month,
    midday,
    publish_property,
)


def test_portfolio_publication_journey(client, identity):
    """Proprietário -> imóvel -> foto -> checklist -> anúncio -> site público."""
    owner = create_person(
        client,
        name="Proprietário Publicação",
        document="33333333333",
        email="owner.publicacao@imob.invalid",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    publication = publish_property(client, property_item["id"])

    public_items = assert_response(
        client.get(f"/api/public/sites/{identity['organization_id']}/properties")
    ).json()
    assert len(public_items) == 1
    assert public_items[0]["slug"] == publication["public_slug"]
    assert public_items[0]["title"] == "Apartamento de teste no Batel"
    assert decimal(public_items[0]["rent_amount"]) == decimal("2000.00")

    detail = assert_response(
        client.get(
            f"/api/public/sites/{identity['organization_id']}/properties/{publication['public_slug']}"
        )
    ).json()
    assert detail["code"] == property_item["code"]
    assert detail["address"]["neighborhood"] == "Batel"
    # O site não deve expor rua/número completos do imóvel na consulta pública.
    assert detail["address"]["street"] == ""
    assert detail["address"]["number"] == ""


def test_rental_financial_journey_first_and_second_rent_with_commissions(client):
    """Locação assinada -> 1º aluguel -> comissões -> 2º aluguel -> repasse."""
    scenario = build_signed_rental(client)
    start = scenario["start"]
    lease = scenario["lease"]

    # Assinar a locação precisa retirar o imóvel automaticamente do anúncio.
    properties = assert_response(client.get("/api/properties")).json()
    current_property = next(row for row in properties if row["id"] == scenario["property"]["id"])
    assert current_property["status"] == "leased"
    assert current_property["publication_enabled"] is False

    broker = create_person(
        client,
        name="Corretor Teste",
        document="44444444444",
        email="corretor@imob.invalid",
        role_keys=["broker"],
    )
    referrer = create_person(
        client,
        name="Angariador Teste",
        document="55555555555",
        email="angariador@imob.invalid",
        role_keys=["referrer"],
    )

    commission_rules = [
        {
            "name": "Corretor · primeiro aluguel",
            "event_type": "first_rent",
            "basis": "intermediation_fee",
            "calculation_type": "percent",
            "value": 30,
            "beneficiary_type": "broker",
            "beneficiary_person_id": broker["id"],
            "property_id": scenario["property"]["id"],
            "lease_contract_id": lease["id"],
            "due_days": 0,
            "priority": 10,
            "notes": "Regra fictícia exclusiva dos testes.",
        },
        {
            "name": "Angariador · primeiro aluguel",
            "event_type": "first_rent",
            "basis": "intermediation_fee",
            "calculation_type": "percent",
            "value": 10,
            "beneficiary_type": "referrer",
            "beneficiary_person_id": referrer["id"],
            "property_id": scenario["property"]["id"],
            "lease_contract_id": lease["id"],
            "due_days": 0,
            "priority": 20,
            "notes": "Regra fictícia exclusiva dos testes.",
        },
    ]
    for rule in commission_rules:
        assert_response(client.post("/api/finance/advanced/commissions/rules", json=rule), 201)

    first_generated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": start.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()
    assert first_generated["generated"] == 1
    first_charge = first_generated["charges"][0]
    assert decimal(first_charge["gross_amount"]) == decimal("2000.00")

    first_paid_at = midday(start.replace(day=10))
    first_paid = assert_response(
        client.post(
            f"/api/finance/charges/{first_charge['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": first_paid_at.isoformat(),
                "payment_method": "pix",
                "payment_reference": "E2E-PRIMEIRO-ALUGUEL",
                "notes": "Pagamento fictício da suíte automatizada.",
            },
        )
    ).json()
    first_settlement = first_paid["settlement"]
    assert first_paid["status"] == "paid"
    assert decimal(first_settlement["admin_fee_calculated"]) == decimal("200.00")
    assert decimal(first_settlement["intermediation_fee_calculated"]) == decimal("2000.00")
    assert decimal(first_settlement["agency_fee_withheld"]) == decimal("2000.00")
    assert decimal(first_settlement["owner_entitlement_amount"]) == decimal("0.00")
    assert len(first_settlement["repasses"]) == 1
    assert decimal(first_settlement["repasses"][0]["amount"]) == decimal("0.00")
    assert first_settlement["repasses"][0]["status"] == "settled_zero"

    generated_commissions = assert_response(
        client.post(
            "/api/finance/advanced/commissions/generate",
            params={"start_date": first_paid_at.date().isoformat(), "end_date": first_paid_at.date().isoformat()},
        )
    ).json()
    assert len(generated_commissions) == 2
    by_type = {row["beneficiary_type"]: row for row in generated_commissions}
    assert decimal(by_type["broker"]["basis_amount"]) == decimal("2000.00")
    assert decimal(by_type["broker"]["amount"]) == decimal("600.00")
    assert decimal(by_type["referrer"]["amount"]) == decimal("200.00")

    # Aprova e liquida as obrigações de Corretor e Angariador pelo Financeiro.
    for entry in generated_commissions:
        approved = assert_response(
            client.post(f"/api/finance/advanced/commissions/{entry['id']}/approve")
        ).json()
        assert approved["status"] == "approved"
        assert approved["financial_title_id"]
        settled = assert_response(
            client.post(
                f"/api/finance/core/manual/{approved['financial_title_id']}/settle",
                json={
                    "amount": None,
                    "settled_at": first_paid_at.isoformat(),
                    "payment_method": "pix",
                    "payment_reference": f"E2E-COM-{approved['beneficiary_type']}",
                    "notes": "Liquidação fictícia da comissão.",
                },
            )
        ).json()
        assert settled["status"] == "settled"

    commissions_after_payment = assert_response(
        client.get("/api/finance/advanced/commissions", params={"competence": start.isoformat()})
    ).json()
    assert {row["status"] for row in commissions_after_payment} == {"paid"}

    second_competence = add_months(start, 1)
    second_generated = assert_response(
        client.post(
            "/api/finance/charges/generate",
            json={"competence": second_competence.isoformat(), "lease_contract_id": lease["id"]},
        )
    ).json()
    assert second_generated["generated"] == 1
    second_charge = second_generated["charges"][0]
    second_paid_at = midday(second_competence.replace(day=10))
    second_paid = assert_response(
        client.post(
            f"/api/finance/charges/{second_charge['id']}/payment",
            json={
                "paid_amount": "2000.00",
                "paid_at": second_paid_at.isoformat(),
                "payment_method": "pix",
                "payment_reference": "E2E-SEGUNDO-ALUGUEL",
                "notes": "Segundo aluguel fictício.",
            },
        )
    ).json()
    second_settlement = second_paid["settlement"]
    assert decimal(second_settlement["admin_fee_calculated"]) == decimal("200.00")
    assert decimal(second_settlement["intermediation_fee_calculated"]) == decimal("0.00")
    assert decimal(second_settlement["agency_fee_withheld"]) == decimal("200.00")
    assert decimal(second_settlement["owner_entitlement_amount"]) == decimal("1800.00")
    assert len(second_settlement["repasses"]) == 1
    second_repasse = second_settlement["repasses"][0]
    assert decimal(second_repasse["amount"]) == decimal("1800.00")
    assert second_repasse["status"] == "pending"

    dashboard_before_repasse = assert_response(
        client.get("/api/finance/dashboard", params={"competence": second_competence.isoformat()})
    ).json()
    assert decimal(dashboard_before_repasse["received_amount"]) == decimal("2000.00")
    assert decimal(dashboard_before_repasse["agency_revenue_amount"]) == decimal("200.00")
    assert decimal(dashboard_before_repasse["pending_repasse_amount"]) == decimal("1800.00")

    paid_repasse = assert_response(
        client.post(
            f"/api/finance/repasses/{second_repasse['id']}/payment",
            json={
                "paid_at": second_paid_at.isoformat(),
                "payment_reference": "E2E-REPASSE-PROPRIETARIO",
                "notes": "Repasse fictício do segundo aluguel.",
            },
        )
    ).json()
    assert paid_repasse["status"] == "paid"
    assert decimal(paid_repasse["amount"]) == decimal("1800.00")

    # Reexecutar geração de comissão sobre o segundo aluguel não pode repetir as regras de primeiro aluguel.
    second_commissions = assert_response(
        client.post(
            "/api/finance/advanced/commissions/generate",
            params={"start_date": second_paid_at.date().isoformat(), "end_date": second_paid_at.date().isoformat()},
        )
    ).json()
    assert second_commissions == []


def test_inspection_maintenance_finance_and_agenda_journey(client):
    """Contrato assinado -> vistoria -> manutenção -> financeiro -> agenda."""
    scenario = build_signed_rental(client)
    lease = scenario["lease"]
    today = date.today()
    scheduled_at = datetime.combine(today, time(hour=15), tzinfo=timezone.utc)

    inspection = assert_response(
        client.post(
            "/api/inspections",
            json={
                "lease_contract_id": lease["id"],
                "scheduled_at": scheduled_at.isoformat(),
                "inspector_name": "Administrador de Testes",
                "environments": [
                    {
                        "key": "sala",
                        "name": "Sala",
                        "notes": None,
                        "items": [
                            {
                                "key": "paredes",
                                "label": "Paredes",
                                "condition": "good",
                                "notes": "Sem avarias.",
                                "photos": [],
                            }
                        ],
                    }
                ],
                "notes": "Vistoria inicial fictícia.",
            },
        ),
        201,
    ).json()
    assert inspection["status"] == "draft"

    inspection_ready = assert_response(
        client.post(f"/api/inspections/{inspection['id']}/workflow", json={"action": "complete", "reason": None})
    ).json()
    assert inspection_ready["status"] == "ready"
    assert inspection_ready["report_hash"]

    handed = assert_response(
        client.post(
            f"/api/inspections/{inspection['id']}/keys",
            json={
                "handed_over_at": scheduled_at.isoformat(),
                "recipient_name": scenario["tenant"]["name"],
                "recipient_document": scenario["tenant"]["document_number"],
                "keys": [{"label": "Porta principal", "quantity": 2, "notes": None}],
                "meter_readings": {"energia": "12345", "agua": "678"},
                "notes": "Entrega fictícia de chaves.",
            },
        ),
        201,
    ).json()
    assert handed["key_handover"] is not None
    assert handed["contest_deadline"] is not None

    finalized = assert_response(
        client.post(f"/api/inspections/{inspection['id']}/workflow", json={"action": "finalize", "reason": None})
    ).json()
    assert finalized["status"] == "finalized"

    partner = assert_response(
        client.post(
            "/api/maintenance/partners",
            json={
                "name": "Parceiro Hidráulica Teste",
                "legal_name": "Parceiro Hidráulica Teste Ltda",
                "document_number": "12345678000199",
                "contact_name": "Técnico Teste",
                "email": "parceiro@imob.invalid",
                "phone": "(41) 3333-0000",
                "whatsapp": "(41) 99999-1111",
                "address": {"city": "Curitiba", "state": "PR"},
                "specialties": ["Hidráulica"],
                "pix_key": "parceiro@imob.invalid",
                "bank_details": {},
                "notes": "Parceiro fictício.",
                "is_active": True,
            },
        ),
        201,
    ).json()

    maintenance_payload = {
        "property_id": scenario["property"]["id"],
        "lease_contract_id": lease["id"],
        "requester_person_id": scenario["tenant"]["id"],
        "title": "Reparo hidráulico de teste",
        "category": "plumbing",
        "priority": "normal",
        "description": "Corrigir vazamento fictício para validar o processo de manutenção.",
        "notes": "Chamado automatizado.",
    }
    maintenance = assert_response(client.post("/api/maintenance-v2", json=maintenance_payload), 201).json()
    assert maintenance["status"] == "requested"
    # Abertura do chamado não pode criar valores financeiros.
    finance_empty = assert_response(client.get("/api/finance/maintenance")).json()
    assert finance_empty["cases"] == []

    maintenance = assert_response(
        client.post(
            f"/api/maintenance-v2/{maintenance['id']}/services",
            json={"title": "Troca de reparo", "description": "Serviço de teste", "quantity": "1", "unit": "serviço"},
        )
    ).json()
    service_id = maintenance["services"][0]["id"]
    assert maintenance["status"] == "triage"

    maintenance_with_responsibility = {
        **maintenance_payload,
        "responsibility": "tenant",
    }
    maintenance = assert_response(
        client.put(f"/api/maintenance-v2/{maintenance['id']}", json=maintenance_with_responsibility)
    ).json()
    assert maintenance["responsibility"] == "tenant"

    maintenance = assert_response(
        client.post(f"/api/maintenance-v2/{maintenance['id']}/workflow", json={"action": "request_quotes", "reason": None, "scheduled_at": None})
    ).json()
    assert maintenance["status"] == "awaiting_quote"

    maintenance = assert_response(
        client.post(
            f"/api/maintenance-v2/{maintenance['id']}/quotes",
            json={
                "partner_id": partner["id"],
                "items": [{"service_id": service_id, "partner_cost": "1000.00", "client_price": "1400.00"}],
                "valid_until": (today + timedelta(days=10)).isoformat(),
                "payment_terms": "À vista",
                "notes": "Orçamento fictício.",
            },
        )
    ).json()
    quote_id = maintenance["quotes"][0]["id"]
    assert decimal(maintenance["partner_cost_total"]) == decimal("1000.00")
    assert decimal(maintenance["client_charge_total"]) == decimal("1400.00")
    assert decimal(maintenance["margin_total"]) == decimal("400.00")

    maintenance = assert_response(
        client.post(f"/api/maintenance-v2/{maintenance['id']}/quotes/{quote_id}/select")
    ).json()
    assert maintenance["status"] == "awaiting_approval"
    maintenance = assert_response(
        client.post(f"/api/maintenance-v2/{maintenance['id']}/workflow", json={"action": "approve", "reason": None, "scheduled_at": None})
    ).json()
    assert maintenance["status"] == "approved"
    maintenance = assert_response(
        client.post(
            f"/api/maintenance-v2/{maintenance['id']}/workflow",
            json={"action": "schedule", "reason": None, "scheduled_at": scheduled_at.isoformat()},
        )
    ).json()
    assert maintenance["status"] == "scheduled"
    maintenance = assert_response(
        client.post(f"/api/maintenance-v2/{maintenance['id']}/workflow", json={"action": "start", "reason": None, "scheduled_at": None})
    ).json()
    assert maintenance["status"] == "in_progress"
    maintenance = assert_response(
        client.post(f"/api/maintenance-v2/{maintenance['id']}/workflow", json={"action": "complete", "reason": None, "scheduled_at": None})
    ).json()
    assert maintenance["status"] == "completed"
    assert decimal(maintenance["partner_cost_total"]) == decimal("1000.00")
    assert decimal(maintenance["client_charge_total"]) == decimal("1400.00")
    assert decimal(maintenance["margin_total"]) == decimal("400.00")

    maintenance_finance = assert_response(client.get("/api/finance/maintenance")).json()
    assert len(maintenance_finance["cases"]) == 1
    case = maintenance_finance["cases"][0]
    assert decimal(case["partner_cost"]) == decimal("1000.00")
    assert decimal(case["client_charge"]) == decimal("1400.00")
    assert decimal(case["margin"]) == decimal("400.00")
    assert decimal(case["payable"]["amount"]) == decimal("1000.00")
    assert decimal(case["receivable"]["amount"]) == decimal("1400.00")

    paid_partner = assert_response(
        client.post(
            f"/api/finance/maintenance/payables/{case['payable']['id']}/payment",
            json={"settled_at": scheduled_at.isoformat(), "payment_reference": "E2E-PARCEIRO", "notes": "Pagamento fictício."},
        )
    ).json()
    assert paid_partner["status"] == "settled"
    assert decimal(paid_partner["settled_amount"]) == decimal("1000.00")

    received_client = assert_response(
        client.post(
            f"/api/finance/maintenance/receivables/{case['receivable']['id']}/receipt",
            json={"settled_at": scheduled_at.isoformat(), "payment_reference": "E2E-MANUTENCAO", "notes": "Recebimento fictício."},
        )
    ).json()
    assert received_client["status"] == "settled"
    assert decimal(received_client["settled_amount"]) == decimal("1400.00")

    # Agenda manual recorrente + eventos automáticos gerados pelos módulos operacionais.
    agenda_start = today + timedelta(days=1)
    while agenda_start.weekday() >= 5:
        agenda_start += timedelta(days=1)
    task_start = datetime.combine(agenda_start, time(hour=15), tzinfo=timezone.utc)
    recurrence_until = agenda_start + timedelta(days=14)
    created_task = assert_response(
        client.post(
            "/api/agenda/tasks",
            json={
                "title": "Acompanhamento pós-locação",
                "description": "Tarefa recorrente fictícia da jornada E2E.",
                "kind": "task",
                "starts_at": task_start.isoformat(),
                "ends_at": None,
                "due_at": None,
                "all_day": True,
                "priority": "normal",
                "privacy": "normal",
                "location": None,
                "assigned_user_id": None,
                "recurrence": "weekly",
                "recurrence_until": recurrence_until.isoformat(),
                "allow_conflict": True,
            },
        ),
        201,
    ).json()
    assert created_task["title"] == "Acompanhamento pós-locação"

    events = assert_response(
        client.get(
            "/api/agenda/events",
            params={"start": today.isoformat(), "end": recurrence_until.isoformat(), "mine": "true"},
        )
    ).json()["events"]
    assert any(event["title"] == "Acompanhamento pós-locação" for event in events)
    assert any(event["module"] == "inspections" for event in events)
    assert any(event["module"] == "maintenance" for event in events)
