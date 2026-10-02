from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domains.finance.models import FinancialSettlement, RentCharge
from app.domains.leases.models import LeaseContract


def months_since(start, competence) -> int:
    return (competence.year - start.year) * 12 + competence.month - start.month


def administration_applies_on_charge(db: Session, charge: RentCharge, terms: dict) -> bool:
    """A administração começa depois das parcelas de intermediação.

    Regra padrão do negócio: quando houver intermediação no início da locação,
    ela substitui a taxa de administração nessas competências. Ex.: 100% do
    primeiro aluguel em 1 parcela => administração apenas do 2º aluguel em diante.
    """
    intermediation_percent = Decimal(str(terms.get("intermediation_percent") or 0))
    if intermediation_percent <= 0:
        return True

    lease = db.get(LeaseContract, charge.lease_contract_id)
    lease_start = lease.start_date if lease else charge.competence
    installment_number = months_since(lease_start, charge.competence) + 1
    installments = max(1, int(terms.get("intermediation_installments") or 1))
    return installment_number > installments


def apply_administration_exclusivity(db: Session, charge: RentCharge) -> dict:
    """Retorna os termos efetivos para a liquidação sem alterar o snapshot original."""
    terms = dict(charge.admin_terms_snapshot or {})
    if administration_applies_on_charge(db, charge, terms):
        return terms

    if terms.get("admin_fee_type") == "fixed":
        terms["admin_fee_amount"] = "0"
    else:
        terms["admin_fee_percent"] = "0"
    return terms


def install_settlement_rule() -> None:
    """Instala a política no cálculo atual sem quebrar snapshots/versionamento existentes."""
    from app.domains.finance import service

    original = service.calculate_settlement
    if getattr(original, "_administration_exclusivity_installed", False):
        return

    def calculate_settlement(db: Session, charge: RentCharge, paid_at: datetime) -> FinancialSettlement:
        if charge.settlement is not None:
            return charge.settlement

        original_snapshot = charge.admin_terms_snapshot
        effective_terms = apply_administration_exclusivity(db, charge)
        try:
            charge.admin_terms_snapshot = effective_terms
            return original(db, charge, paid_at)
        finally:
            charge.admin_terms_snapshot = original_snapshot

    setattr(calculate_settlement, "_administration_exclusivity_installed", True)
    service.calculate_settlement = calculate_settlement
