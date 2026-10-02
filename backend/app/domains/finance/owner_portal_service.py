from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.finance.models import FinancialSettlement, OwnerRepasse, RentCharge
from app.domains.portfolio.models import Person

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def owner_annual_income_values(
    db: Session,
    *,
    organization_id: UUID,
    year: int,
    person_id: UUID,
) -> tuple[Person, list[dict], str]:
    """Monta o informe anual do proprietário a partir dos repasses efetivamente pagos.

    A cobrança do locatário pode ser recebida em um ano e o repasse ao proprietário
    ocorrer no seguinte. Para o Portal do Proprietário, o critério de caixa é a data
    em que o repasse foi efetivamente pago ao proprietário, não a data de recebimento
    da cobrança pela imobiliária.
    """
    person = db.scalar(
        select(Person).where(
            Person.id == person_id,
            Person.organization_id == organization_id,
            Person.is_active.is_(True),
        )
    )
    if person is None:
        raise ValueError("Pessoa não encontrada.")

    repasses = db.scalars(
        select(OwnerRepasse).where(
            OwnerRepasse.organization_id == organization_id,
            OwnerRepasse.owner_person_id == person_id,
            OwnerRepasse.status.in_(["paid", "settled"]),
            OwnerRepasse.paid_at.is_not(None),
        )
    ).all()

    lines: list[dict] = []
    for repasse in repasses:
        if repasse.paid_at is None or repasse.paid_at.year != year:
            continue
        charge = db.get(RentCharge, repasse.charge_id)
        settlement = db.get(FinancialSettlement, repasse.settlement_id)
        if charge is None or settlement is None:
            continue

        share = Decimal(str(repasse.ownership_percent or 0)) / Decimal("100")
        rent_share = money(money(charge.rent_amount) * share)
        agency_fee_share = money(money(settlement.agency_fee_withheld) * share)
        economic_entitlement = money(money(settlement.owner_entitlement_amount) * share)
        repasse_amount = money(repasse.amount)
        adjustments = money(repasse_amount - economic_entitlement)

        lines.append({
            "competence": charge.competence,
            "payment_date": repasse.paid_at.date(),
            "property_code": str((charge.property_snapshot or {}).get("code") or "—"),
            "charge_code": f"COB-{charge.internal_number:06d}",
            "rent_amount": rent_share,
            # Para proprietário, este campo representa ajustes posteriores ao
            # direito econômico: por exemplo, dedução proporcional de manutenção.
            "additional_charges": adjustments,
            "total_amount": repasse_amount,
            "administration_fee": agency_fee_share,
            "owner_net_amount": repasse_amount,
        })

    lines.sort(key=lambda row: (row["payment_date"] or date.min, row["competence"], row["charge_code"]))
    return person, lines, "percentual de propriedade do contrato · regime de caixa pelo repasse"
