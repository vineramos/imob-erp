from datetime import date
from decimal import Decimal

from app.api.routes.finance_banking import _billing_identifier_match, _candidate_score
from app.domains.finance.advanced_models import BillingItem
from app.domains.finance.bank_models import BankTransaction
from app.domains.finance.models import RentCharge


def _charge(number: int = 123) -> RentCharge:
    return RentCharge(
        internal_number=number,
        organization_id=None,
        lease_contract_id=None,
        property_id=None,
        competence=date(2026, 9, 1),
        due_date=date(2026, 9, 10),
        status="generated",
        rent_amount=Decimal("1500.00"),
        gross_amount=Decimal("1500.00"),
        charge_items=[],
        tenant_snapshot=[],
        property_snapshot={},
        owner_snapshot=[],
        admin_terms_snapshot={},
    )


def _item(charge: RentCharge) -> BillingItem:
    return BillingItem(
        organization_id=None,
        billing_batch_id=None,
        charge_id=None,
        provider="inter",
        provider_charge_id="provider-abc-123",
        pix_txid="pix-tx-987654",
        request_snapshot={"seuNumero": f"C{charge.internal_number}"},
        response_snapshot={"cobranca": {"codigoSolicitacao": "provider-abc-123"}},
    )


def _transaction(*, amount: str = "1542.47", reference: str | None = None, description: str = "Recebimento") -> BankTransaction:
    transaction = BankTransaction(
        organization_id=None,
        bank_account_id=None,
        fingerprint="x" * 64,
        transaction_date=date(2026, 9, 20),
        direction="credit",
        amount=Decimal(amount),
        description=description,
        bank_reference=reference,
        source="inter",
        status="pending",
        raw_data={},
    )
    transaction.reconciliations = []
    return transaction


def test_matches_provider_charge_id_even_when_amount_differs_from_nominal():
    charge = _charge()
    item = _item(charge)
    transaction = _transaction(amount="1542.47", reference="provider-abc-123")

    assert charge.gross_amount == Decimal("1500.00")
    assert transaction.amount == Decimal("1542.47")
    assert _billing_identifier_match(transaction, item, charge) == "PROVIDERABC123"


def test_matches_seu_numero_and_internal_charge_code():
    charge = _charge(456)
    item = _item(charge)

    by_seu_numero = _transaction(reference="C456")
    by_charge_code = _transaction(description="Crédito aluguel COB-000456 com acréscimos")

    assert _billing_identifier_match(by_seu_numero, item, charge) == "C456"
    assert _billing_identifier_match(by_charge_code, item, charge) == "COB000456"


def test_matches_pix_txid_from_bank_payload():
    charge = _charge()
    item = _item(charge)
    transaction = _transaction()
    transaction.raw_data = {"detalhes": {"txId": "pix-tx-987654"}}

    assert _billing_identifier_match(transaction, item, charge) == "PIXTX987654"


def test_identifier_match_outranks_amount_heuristic():
    charge = _charge()
    item = _item(charge)

    identified = _transaction(amount="1542.47", reference="provider-abc-123")
    unidentified = _transaction(amount="1500.00")

    details = {
        "target_type": "rent",
        "remaining": Decimal("1500.00"),
        "due_date": charge.due_date,
        "counterparty": "",
        "billing_item": item,
        "object": charge,
    }

    assert _candidate_score(identified, details) > _candidate_score(unidentified, details)
