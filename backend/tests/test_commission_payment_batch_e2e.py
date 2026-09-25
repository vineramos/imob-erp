from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID

from app.core.database import SessionLocal
from app.domains.finance.advanced_models import CommissionEntry, CommissionPaymentBatchItem
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import FinancialSettlement, RentCharge
from tests.helpers import (
    add_months,
    assert_response,
    create_person,
    create_property,
    create_signed_lease_contract,
    first_month,
)


def _paid_at(day: date) -> datetime:
    return datetime.combine(day, time(hour=14), tzinfo=timezone.utc)


def test_commission_monthly_batch_report_invoice_finance_approval_and_payment(client, identity):
    """Jornada fictícia completa: aluguel pago -> lote -> relatório -> NF -> financeiro -> pago."""
    owner = create_person(
        client,
        name="Proprietário Comissão Teste",
        document="33333333333",
        email="owner.commission@example.com",
        role_keys=["owner"],
    )
    property_item = create_property(client, owner["id"])
    tenant = create_person(
        client,
        name="Inquilino Comissão Teste",
        document="44444444444",
        email="tenant.commission@example.com",
        role_keys=["tenant"],
    )
    lease = create_signed_lease_contract(
        client,
        property_item["id"],
        tenant["id"],
        start=first_month(),
    )

    broker = assert_response(
        client.post(
            "/api/people",
            json={
                "person_type": "individual",
                "name": "Corretor Fictício Homologação",
                "document_number": "55555555555",
                "email": "corretor.homologacao@example.com",
                "phone": "(41) 99999-5555",
                "address": {
                    "street": "Rua da Homologação",
                    "number": "10",
                    "neighborhood": "Centro",
                    "city": "Curitiba",
                    "state": "PR",
                    "postal_code": "80000-000",
                },
                "notes": "Corretor fictício exclusivo da homologação automatizada.",
                "billing_legal_name": "Corretor Fictício Serviços Imobiliários Ltda.",
                "billing_document_number": "55.555.555/0001-55",
                "role_keys": ["broker"],
            },
        ),
        201,
    ).json()

    rule = assert_response(
        client.post(
            "/api/finance/advanced/commissions/rules",
            json={
                "name": "Comissão recorrente homologação",
                "event_type": "recurring",
                "basis": "rent",
                "calculation_type": "percent",
                "value": 10,
                "beneficiary_type": "broker",
                "beneficiary_person_id": broker["id"],
                "property_id": property_item["id"],
                "lease_contract_id": lease["id"],
                "due_days": 0,
                "priority": 10,
                "notes": "Regra fictícia para homologar lote mensal.",
            },
        ),
        201,
    ).json()
    assert rule["beneficiary_name"] == "Corretor Fictício Homologação"

    competence = add_months(date.today().replace(day=1), -1)
    payment_day = competence.replace(day=min(15, 28))
    assert SessionLocal is not None
    with SessionLocal() as db:
        charge = RentCharge(
            organization_id=identity["organization_id"],
            lease_contract_id=UUID(lease["id"]),
            property_id=UUID(property_item["id"]),
            competence=competence,
            due_date=competence.replace(day=10),
            status="paid",
            rent_amount=Decimal("2000.00"),
            gross_amount=Decimal("2000.00"),
            charge_items=[],
            tenant_snapshot=[{"person_id": tenant["id"], "name": tenant["name"]}],
            property_snapshot={
                "code": property_item.get("code") or "IMV-HOMOLOG",
                "address": property_item.get("address") or {},
            },
            owner_snapshot=[{"person_id": owner["id"], "name": owner["name"], "ownership_percent": "100.00"}],
            admin_terms_snapshot={},
            paid_at=_paid_at(payment_day),
            paid_amount=Decimal("2000.00"),
            payment_method="bank_reconciliation",
            payment_reference="HOMOLOG-RECEBIMENTO-2000",
            created_by_user_id=identity["user_id"],
        )
        db.add(charge)
        db.flush()
        settlement = FinancialSettlement(
            organization_id=identity["organization_id"],
            charge_id=charge.id,
            lease_contract_id=charge.lease_contract_id,
            property_id=charge.property_id,
            administration_contract_id=None,
            admin_fee_calculated=Decimal("0.00"),
            intermediation_fee_calculated=Decimal("0.00"),
            agency_fee_withheld=Decimal("0.00"),
            agency_reimbursement_amount=Decimal("0.00"),
            owner_entitlement_amount=Decimal("2000.00"),
            third_party_amount=Decimal("0.00"),
        )
        db.add(settlement)
        db.commit()

    batches = assert_response(
        client.post(
            "/api/finance/advanced/commissions/batches/ensure",
            params={"competence": competence.isoformat()},
        )
    ).json()
    assert len(batches) == 1
    batch = batches[0]
    assert batch["beneficiary_person_id"] == broker["id"]
    assert batch["status"] == "report_released"
    assert Decimal(str(batch["total_amount"])) == Decimal("200.0")
    assert batch["broker_legal_name"] == "Corretor Fictício Serviços Imobiliários Ltda."
    assert batch["broker_document_number"] == "55.555.555/0001-55"
    assert batch["organization_legal_name"] == "Imob Testes Ltda"
    assert "Relatório de Comissões nº" in batch["service_description"]
    assert len(batch["items"]) == 1

    report = assert_response(
        client.post(f"/api/finance/advanced/commissions/batches/{batch['id']}/report")
    )
    assert report.content.startswith(b"%PDF")
    assert "attachment" in report.headers.get("content-disposition", "").lower()

    issued = assert_response(
        client.get(
            "/api/finance/advanced/commissions/batches",
            params={"beneficiary_person_id": broker["id"]},
        )
    ).json()[0]
    assert issued["status"] == "report_issued"
    assert issued["report_issued_at"]

    invoice = assert_response(
        client.post(
            f"/api/finance/advanced/commissions/batches/{batch['id']}/invoice",
            files={"file": ("nf-homologacao.pdf", b"%PDF-1.4\nnota fiscal ficticia\n%%EOF", "application/pdf")},
        )
    ).json()
    assert invoice["status"] == "awaiting_finance_approval"
    assert invoice["invoice_filename"] == "nf-homologacao.pdf"

    returned = assert_response(
        client.post(
            f"/api/finance/advanced/commissions/batches/{batch['id']}/return",
            params={"reason": "NF fictícia devolvida para testar o fluxo de correção."},
        )
    ).json()
    assert returned["status"] == "returned"
    assert "fluxo de correção" in returned["finance_review_notes"]

    resubmitted = assert_response(
        client.post(
            f"/api/finance/advanced/commissions/batches/{batch['id']}/invoice",
            files={"file": ("nf-homologacao-corrigida.pdf", b"%PDF-1.4\nnota fiscal corrigida\n%%EOF", "application/pdf")},
        )
    ).json()
    assert resubmitted["status"] == "awaiting_finance_approval"
    assert resubmitted["invoice_filename"] == "nf-homologacao-corrigida.pdf"

    approved = assert_response(
        client.post(f"/api/finance/advanced/commissions/batches/{batch['id']}/approve")
    ).json()
    assert approved["status"] == "scheduled"
    assert approved["approved_at"]
    assert approved["payment_due_date"]

    with SessionLocal() as db:
        item = db.query(CommissionPaymentBatchItem).filter(
            CommissionPaymentBatchItem.batch_id == UUID(batch["id"])
        ).one()
        entry = db.get(CommissionEntry, item.commission_entry_id)
        assert entry is not None
        assert entry.status == "approved"
        assert entry.financial_title_id is not None
        title = db.get(FinancialTitle, entry.financial_title_id)
        assert title is not None
        assert title.status == "pending"
        title.status = "settled"
        title.settled_amount = title.amount
        title.settled_at = datetime.now(timezone.utc)
        title.payment_reference = "HOMOLOG-PAGAMENTO-CORRETOR"
        db.commit()

    paid = assert_response(
        client.get(
            "/api/finance/advanced/commissions/batches",
            params={"beneficiary_person_id": broker["id"]},
        )
    ).json()[0]
    assert paid["status"] == "paid"
    assert paid["paid_at"]
    assert paid["payment_reference"] == "HOMOLOG-PAGAMENTO-CORRETOR"
