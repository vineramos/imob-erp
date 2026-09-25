from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domains.finance.advanced_models import BillingItem
from app.domains.finance.advanced_service import generate_commissions_for_charge
from app.domains.finance.late_charges import amount_due, money, record_payment_with_late_charges
from app.domains.finance.models import FinancialSettlement, RentCharge


def _provider_received_amount(item: BillingItem) -> Decimal | None:
    data = dict(item.response_snapshot or {})
    cobranca = data.get("cobranca") if isinstance(data.get("cobranca"), dict) else data
    for key in ("valorTotalRecebido", "valorPago", "valorRecebido"):
        raw = cobranca.get(key) if isinstance(cobranca, dict) else None
        if raw not in (None, ""):
            value = money(raw)
            if value > 0:
                return value
    return None


def settle_confirmed_billing_item(
    db: Session,
    item: BillingItem,
    *,
    paid_at: datetime | None = None,
) -> FinancialSettlement | None:
    """Baixa uma cobrança confirmada pelo provedor no fluxo financeiro real.

    A operação é idempotente: webhooks repetidos ou sincronizações posteriores
    não recriam settlement, repasses ou comissões. Em cobranças vencidas, o
    valor efetivamente recebido pelo provedor prevalece; na ausência dele, o
    ERP calcula a mora contratual até a data da confirmação.
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

    received = _provider_received_amount(item) or amount_due(db, charge, as_of=paid_at.date())
    settlement = record_payment_with_late_charges(
        db,
        charge=charge,
        paid_amount=received,
        paid_at=paid_at,
        payment_method="inter_boleto_pix",
        payment_reference=f"INTER:{item.provider_charge_id or item.id}",
        notes="Recebimento confirmado automaticamente pelo Banco Inter.",
    )
    generate_commissions_for_charge(db, charge=charge, settlement=settlement)
    return settlement
