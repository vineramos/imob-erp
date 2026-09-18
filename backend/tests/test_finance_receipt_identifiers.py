from datetime import date
from decimal import Decimal

from app.api.routes.finance_banking import (
    _billing_identifier_match,
    _candidate_score,
    _exception_reason,
    _parse_csv_rows,
    _parse_ofx_rows,
)
from app.domains.finance.advanced_models import BillingItem
from app.domains.finance.bank_models import BankTransaction
from app.domains.finance.models import RentCharge
from app.domains.finance.providers import BankProviderError, bank_provider, bank_provider_descriptors


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


def test_exception_reason_prefers_identifier_over_score():
    from app.domains.finance.bank_schemas import ReconciliationCandidate

    candidate = ReconciliationCandidate(
        target_type="rent",
        target_id="00000000-0000-0000-0000-000000000001",
        target_code="COB-000123",
        direction="receivable",
        fund_scope="third_party",
        description="Cobrança mensal de locação",
        counterparty_name="Locatário",
        due_date=date(2026, 9, 10),
        remaining_amount=Decimal("1500.00"),
        score=1042,
        identifier_match=True,
        matched_identifier="PROVIDERABC123",
    )

    reason, label = _exception_reason([candidate])
    assert reason == "identifier_detected"
    assert "Referência bancária" in label


def test_exception_reason_detects_ambiguous_identifier():
    from app.domains.finance.bank_schemas import ReconciliationCandidate

    items = [
        ReconciliationCandidate(
            target_type="rent",
            target_id=f"00000000-0000-0000-0000-00000000000{index}",
            target_code=f"COB-00012{index}",
            direction="receivable",
            fund_scope="third_party",
            description="Cobrança mensal de locação",
            counterparty_name="Locatário",
            due_date=date(2026, 9, 10),
            remaining_amount=Decimal("1500.00"),
            score=1000,
            identifier_match=True,
            matched_identifier="MESMAREF",
        )
        for index in (1, 2)
    ]

    reason, _ = _exception_reason(items)
    assert reason == "ambiguous_identifier"


def test_matches_short_internal_charge_identifier():
    charge = _charge(7)
    item = _item(charge)
    transaction = _transaction(reference="C7")

    assert _billing_identifier_match(transaction, item, charge) == "C7"


def test_generic_csv_import_preserves_bank_reference_without_bank_specific_adapter():
    rows = _parse_csv_rows(
        "data;descricao;valor;tipo;referencia\n20/09/2026;Recebimento aluguel;1542,47;credito;C7\n".encode("utf-8")
    )

    assert len(rows) == 1
    assert rows[0]["direction"] == "credit"
    assert rows[0]["amount"] == Decimal("1542.47")
    assert rows[0]["bank_reference"] == "C7"


def test_generic_ofx_import_preserves_fitid_and_reference():
    rows = _parse_ofx_rows(
        b"<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260920<TRNAMT>1542.47<FITID>abc-987<REFNUM>C7<NAME>LOCATARIO<MEMO>ALUGUEL</STMTTRN></BANKTRANLIST></OFX>"
    )

    assert len(rows) == 1
    assert rows[0]["direction"] == "credit"
    assert rows[0]["external_id"] == "abc-987"
    assert rows[0]["bank_reference"] == "C7"


def test_bank_provider_registry_exposes_generic_manual_adapter_and_capabilities():
    descriptors = {item.key: item for item in bank_provider_descriptors()}

    assert "manual" in descriptors
    assert descriptors["manual"].direct_integration is False
    assert descriptors["manual"].capabilities.statement is False
    assert "inter" in descriptors


def test_unknown_bank_provider_is_rejected_without_changing_business_rules():
    try:
        bank_provider("banco-futuro")
    except BankProviderError as exc:
        assert "não suportado" in str(exc)
    else:
        raise AssertionError("Provider inexistente deveria ser rejeitado.")
