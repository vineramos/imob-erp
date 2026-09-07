from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.domains.finance.models import OwnerRepasse, RentCharge
from app.domains.foundation.defaults import OPERATIONAL_DEFAULTS
from app.domains.foundation.models import OrganizationSettings
from app.domains.leases.models import LeaseContract, LeaseContractVersion

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
LateInterestType = Literal["simple", "compound"]
LateCompounding = Literal["daily", "monthly"]


def money(value) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LatePaymentTerms:
    fee_percent: Decimal
    interest_percent_monthly: Decimal
    interest_type: LateInterestType
    compounding: LateCompounding

    def as_snapshot(self) -> dict:
        return {
            "fee_percent": str(money(self.fee_percent)),
            "interest_percent_monthly": str(money(self.interest_percent_monthly)),
            "interest_type": self.interest_type,
            "compounding": self.compounding,
            "starts_after_days": 1,
            "base": "gross_charge",
        }


@dataclass(frozen=True)
class LateChargeBreakdown:
    as_of: date
    days_overdue: int
    nominal_amount: Decimal
    fee_amount: Decimal
    interest_amount: Decimal
    updated_amount: Decimal
    terms: LatePaymentTerms

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "days_overdue": self.days_overdue,
            "nominal_amount": str(self.nominal_amount),
            "late_fee_amount": str(self.fee_amount),
            "late_interest_amount": str(self.interest_amount),
            "updated_amount": str(self.updated_amount),
            "late_fee_percent": str(self.terms.fee_percent),
            "late_interest_percent_monthly": str(self.terms.interest_percent_monthly),
            "late_interest_type": self.terms.interest_type,
            "late_interest_compounding": self.terms.compounding,
        }


def _normalized_terms(source: dict | None, *, default_zero: bool = True) -> LatePaymentTerms:
    source = dict(source or {})
    fallback_fee = 0 if default_zero else OPERATIONAL_DEFAULTS["late_fee_percent"]
    fallback_interest = 0 if default_zero else OPERATIONAL_DEFAULTS["late_interest_percent_monthly"]
    interest_type = str(source.get("interest_type") or ("simple" if default_zero else OPERATIONAL_DEFAULTS["late_interest_type"]))
    compounding = str(source.get("compounding") or ("daily" if default_zero else OPERATIONAL_DEFAULTS["late_interest_compounding"]))
    if interest_type not in {"simple", "compound"}:
        interest_type = "simple"
    if compounding not in {"daily", "monthly"}:
        compounding = "daily"
    return LatePaymentTerms(
        fee_percent=money(source.get("fee_percent", fallback_fee)),
        interest_percent_monthly=money(source.get("interest_percent_monthly", fallback_interest)),
        interest_type=interest_type,  # type: ignore[arg-type]
        compounding=compounding,  # type: ignore[arg-type]
    )


def contract_late_payment_terms(contract: LeaseContract) -> LatePaymentTerms:
    # Ausência da cláusula significa zero. Isso protege contratos históricos:
    # uma configuração nova da imobiliária nunca cria mora retroativamente.
    rules = dict(contract.rules_snapshot or {})
    return _normalized_terms(rules.get("late_payment"), default_zero=True)


def organization_late_payment_terms(db: Session, organization_id: UUID) -> LatePaymentTerms:
    row = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    source = {**OPERATIONAL_DEFAULTS, **(dict(row.operational_defaults or {}) if row else {})}
    return _normalized_terms(
        {
            "fee_percent": source.get("late_fee_percent"),
            "interest_percent_monthly": source.get("late_interest_percent_monthly"),
            "interest_type": source.get("late_interest_type"),
            "compounding": source.get("late_interest_compounding"),
        },
        default_zero=False,
    )


def charge_late_payment_terms(db: Session, charge: RentCharge) -> LatePaymentTerms:
    lease = db.get(LeaseContract, charge.lease_contract_id)
    return contract_late_payment_terms(lease) if lease is not None else _normalized_terms(None)


def calculate_late_charges(*, nominal_amount, due_date: date, as_of: date, terms: LatePaymentTerms) -> LateChargeBreakdown:
    nominal = money(nominal_amount)
    days = max(0, (as_of - due_date).days)
    if days <= 0 or nominal <= ZERO:
        return LateChargeBreakdown(as_of, 0, nominal, ZERO, ZERO, nominal, terms)

    fee = money(nominal * terms.fee_percent / Decimal("100"))
    monthly_rate = terms.interest_percent_monthly / Decimal("100")
    if monthly_rate <= ZERO:
        interest = ZERO
    elif terms.interest_type == "simple":
        interest = money(nominal * monthly_rate * Decimal(days) / Decimal("30"))
    elif terms.compounding == "monthly":
        full_months, remainder = divmod(days, 30)
        factor = (Decimal("1") + monthly_rate) ** full_months
        factor *= Decimal("1") + (monthly_rate * Decimal(remainder) / Decimal("30"))
        interest = money(nominal * (factor - Decimal("1")))
    else:
        # Capitalização diária a partir de uma taxa mensal efetiva. Decimal não
        # oferece potência fracionária de forma uniforme entre versões; a
        # aproximação float é usada só no fator e o resultado financeiro volta
        # imediatamente para Decimal/centavos.
        rate_float = float(monthly_rate)
        factor = (1.0 + rate_float) ** (days / 30.0)
        interest = money(nominal * Decimal(str(factor - 1.0)))

    return LateChargeBreakdown(
        as_of=as_of,
        days_overdue=days,
        nominal_amount=nominal,
        fee_amount=fee,
        interest_amount=interest,
        updated_amount=money(nominal + fee + interest),
        terms=terms,
    )


def charge_late_breakdown(db: Session, charge: RentCharge, *, as_of: date | None = None) -> LateChargeBreakdown:
    effective_date = as_of or date.today()
    if charge.status == "paid" and charge.paid_at is not None:
        effective_date = charge.paid_at.date()
    breakdown = calculate_late_charges(
        nominal_amount=charge.gross_amount,
        due_date=charge.due_date,
        as_of=effective_date,
        terms=charge_late_payment_terms(db, charge),
    )
    if charge.status == "cancelled":
        return LateChargeBreakdown(effective_date, 0, money(charge.gross_amount), ZERO, ZERO, money(charge.gross_amount), breakdown.terms)
    return breakdown


def amount_due(db: Session, charge: RentCharge, *, as_of: date | None = None) -> Decimal:
    return charge_late_breakdown(db, charge, as_of=as_of).updated_amount


def record_payment_with_late_charges(
    db: Session,
    *,
    charge: RentCharge,
    paid_amount: Decimal,
    paid_at: datetime | None,
    payment_method: str,
    payment_reference: str | None,
    notes: str | None,
):
    # Import local evita ciclo: service também é usado pelos helpers de mora.
    from app.domains.finance.service import calculate_settlement

    if charge.status in {"paid", "cancelled"}:
        raise ValueError("Esta cobrança não está disponível para recebimento.")
    paid_at = paid_at or datetime.now(timezone.utc)
    breakdown = charge_late_breakdown(db, charge, as_of=paid_at.date())
    received = money(paid_amount)
    if received != breakdown.updated_amount:
        raise ValueError(
            "Pagamento parcial não é permitido. "
            f"O valor integral atualizado para {paid_at.date().strftime('%d/%m/%Y')} é R$ {breakdown.updated_amount:.2f}."
        )

    charge.status = "paid"
    charge.paid_amount = received
    charge.paid_at = paid_at
    charge.payment_method = payment_method
    charge.payment_reference = (payment_reference or "").strip() or None
    charge.payment_notes = (notes or "").strip() or None
    snapshot = dict(charge.admin_terms_snapshot or {})
    snapshot["late_payment_settlement"] = breakdown.as_dict()
    charge.admin_terms_snapshot = snapshot

    settlement = calculate_settlement(db, charge, paid_at)
    surcharge = money(breakdown.fee_amount + breakdown.interest_amount)
    if surcharge <= ZERO:
        return settlement

    settlement.owner_entitlement_amount = money(settlement.owner_entitlement_amount + surcharge)
    # calculate_settlement adiciona os repasses diretamente à sessão. Consultar
    # pelo settlement_id após o flush evita depender de o relationship já estar
    # materializado no identity map nesta mesma transação.
    db.flush()
    repasses = db.scalars(
        select(OwnerRepasse)
        .where(OwnerRepasse.settlement_id == settlement.id)
        .order_by(OwnerRepasse.owner_name, OwnerRepasse.id)
    ).all()
    if not repasses:
        return settlement

    allocated = ZERO
    for index, repasse in enumerate(repasses):
        if index == len(repasses) - 1:
            extra = money(surcharge - allocated)
        else:
            extra = money(surcharge * Decimal(str(repasse.ownership_percent)) / Decimal("100"))
            allocated += extra
        repasse.amount = money(repasse.amount + extra)
        if repasse.amount > ZERO and repasse.status == "settled_zero":
            repasse.status = "pending"
    db.flush()
    return settlement


def _apply_new_contract_defaults(session: Session, contract: LeaseContract) -> None:
    rules = dict(contract.rules_snapshot or {})
    if isinstance(rules.get("late_payment"), dict):
        return
    with session.no_autoflush:
        terms = organization_late_payment_terms(session, contract.organization_id)
    rules["late_payment"] = terms.as_snapshot()
    contract.rules_snapshot = rules


def _preserve_existing_contract_terms(contract: LeaseContract) -> None:
    current = dict(contract.rules_snapshot or {})
    if isinstance(current.get("late_payment"), dict):
        return
    history = inspect(contract).attrs.rules_snapshot.history
    previous = next((dict(value or {}) for value in history.deleted if isinstance(value, dict)), {})
    if isinstance(previous.get("late_payment"), dict):
        current["late_payment"] = dict(previous["late_payment"])
    else:
        # Contrato antigo sem cláusula: mora zero, nunca o padrão atual.
        current["late_payment"] = _normalized_terms(None).as_snapshot()
    contract.rules_snapshot = current


def _preserve_version_terms(session: Session, version: LeaseContractVersion) -> None:
    snapshot = dict(version.snapshot or {})
    rules = dict(snapshot.get("rules") or {})
    if isinstance(rules.get("late_payment"), dict):
        return
    with session.no_autoflush:
        contract = session.get(LeaseContract, version.contract_id)
    if contract is None:
        return
    current_terms = contract_late_payment_terms(contract).as_snapshot()
    rules["late_payment"] = current_terms
    snapshot["rules"] = rules
    version.snapshot = snapshot


_INSTALLED = False


def install_late_payment_contract_rule() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(Session, "before_flush")
    def _late_payment_before_flush(session: Session, flush_context, instances) -> None:  # noqa: ARG001
        # Primeiro estabiliza o contrato; depois corrige eventuais snapshots de
        # versão criados antes deste before_flush.
        for obj in list(session.new):
            if isinstance(obj, LeaseContract):
                _apply_new_contract_defaults(session, obj)
        for obj in list(session.dirty):
            if isinstance(obj, LeaseContract) and obj not in session.new:
                _preserve_existing_contract_terms(obj)
        for obj in list(session.new):
            if isinstance(obj, LeaseContractVersion):
                _preserve_version_terms(session, obj)

    _INSTALLED = True
