from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domains.finance.late_charges import charge_late_breakdown, money
from app.domains.finance.models import RentCharge


@dataclass(frozen=True)
class ChargeFinancialView:
    nominal_amount: Decimal
    payable_amount: Decimal
    late_fee_amount: Decimal
    late_interest_amount: Decimal
    days_overdue: int
    as_of: date


def charge_financial_view(
    db: Session,
    charge: RentCharge,
    *,
    as_of: date | None = None,
) -> ChargeFinancialView:
    """Uma única leitura do valor econômico da cobrança.

    O principal armazenado permanece imutável em ``gross_amount``. Para cobranças
    em aberto, ``payable_amount`` é principal + multa + juros na data informada.
    Para recebidas, o valor efetivamente pago é preservado. Canceladas não
    carregam mora.
    """
    breakdown = charge_late_breakdown(db, charge, as_of=as_of)
    if charge.status == "paid":
        payable = money(charge.paid_amount if charge.paid_amount is not None else breakdown.updated_amount)
    elif charge.status == "cancelled":
        payable = money(charge.gross_amount)
    else:
        payable = money(breakdown.updated_amount)
    return ChargeFinancialView(
        nominal_amount=money(charge.gross_amount),
        payable_amount=payable,
        late_fee_amount=money(breakdown.fee_amount),
        late_interest_amount=money(breakdown.interest_amount),
        days_overdue=breakdown.days_overdue,
        as_of=breakdown.as_of,
    )
