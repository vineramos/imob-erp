from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domains.finance.advanced_models import BillingItem
from app.domains.finance.advanced_service import generate_commissions_for_charge
from app.domains.finance.models import FinancialSettlement, RentCharge
from app.domains.finance.service import record_payment


def settle_confirmed_billing_item(
    db: Session,
    item: BillingItem,
    *,
    paid_at: datetime | None = None,
) -> FinancialSettlement | None:
    """Baixa uma cobrança confirmada pelo provedor no fluxo financeiro real.

    A operação é idempotente: webhooks repetidos ou sincronizações posteriores
    não recriam settlement, repasses ou comissões.
    """
    charge = db.get(RentCharge, item.charge_id)
    if charge is None or charge.status == "cancelled":
        return None

    paid_at = paid_at or item.confirmed_at or datetime.now(timezone.utc)
    if charge.status == "paid":
        settlement = charge.settlement or db.query(FinancialSettlement).filter(
            FinancialSettlement.charge_id == charge.id
        ).one_or_none()
        if settlement is not None:
            generate_commissions_for_charge(db, charge=charge, settlement=settlement)
        return settlement

    settlement = record_payment(
        db,
        charge=charge,
        paid_amount=charge.gross_amount,
        paid_at=paid_at,
        payment_method="inter_boleto_pix",
        payment_reference=f"INTER:{item.provider_charge_id or item.id}",
        notes="Recebimento confirmado automaticamente pelo Banco Inter.",
    )
    generate_commissions_for_charge(db, charge=charge, settlement=settlement)
    return settlement
