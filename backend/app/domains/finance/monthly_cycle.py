from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.domains.communications.models import CommunicationMessage
from app.domains.finance.bank_control_models import BankDailyClose
from app.domains.finance.bank_models import BankAccount, BankReconciliationExceptionRecord, BankTransaction
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import FinancialSettlement, OwnerRepasse, RentCharge
from app.domains.finance.monthly_cycle_schemas import (
    MonthlyClosingReadiness,
    MonthlyCycleAction,
    MonthlyCycleResponse,
    MonthlyCycleStep,
)
from app.domains.finance.service import charge_item_agency_retention, money
from app.domains.leases.models import LeaseContract


CLOSED_TITLE_STATUSES = {"settled", "settled_zero", "cancelled", "paid"}
CLOSED_REPASSE_STATUSES = {"paid", "settled_zero", "cancelled"}
OPEN_CHARGE_STATUSES = {"generated", "sent", "overdue"}
PENDING_COMMUNICATION_STATUSES = {"draft", "pending", "sending"}


def month_start(value: date) -> date:
    return value.replace(day=1)


def month_end(value: date) -> date:
    value = month_start(value)
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def _sum(values) -> Decimal:
    return money(sum((money(value) for value in values), Decimal("0.00")))


def _step(
    *,
    key: str,
    title: str,
    state: str,
    summary: str,
    detail: str,
    count: int = 0,
    pending_count: int = 0,
    amount: Decimal = Decimal("0.00"),
    pending_amount: Decimal = Decimal("0.00"),
    action_label: str | None = None,
    action_target: str | None = None,
) -> MonthlyCycleStep:
    return MonthlyCycleStep(
        key=key,
        title=title,
        state=state,
        summary=summary,
        detail=detail,
        count=count,
        pending_count=pending_count,
        amount=money(amount),
        pending_amount=money(pending_amount),
        action_label=action_label,
        action_target=action_target,
    )


def build_monthly_cycle(
    db: Session,
    *,
    organization_id: UUID,
    competence: date,
    today: date | None = None,
) -> MonthlyCycleResponse:
    competence = month_start(competence)
    period_end = month_end(competence)
    today = today or date.today()

    leases = db.scalars(
        select(LeaseContract)
        .where(LeaseContract.organization_id == organization_id)
        .order_by(LeaseContract.internal_number.asc())
    ).all()
    eligible = [
        lease
        for lease in leases
        if lease.status == "signed"
        and lease.archive_status == "archived"
        and lease.final_document_hash
        and lease.start_date <= period_end
        and (lease.operational_end_date or lease.end_date) >= competence
    ]
    eligible_ids = {lease.id for lease in eligible}

    charges = db.scalars(
        select(RentCharge)
        .where(
            RentCharge.organization_id == organization_id,
            RentCharge.competence == competence,
        )
        .order_by(RentCharge.internal_number.asc())
    ).all()
    charge_ids = {charge.id for charge in charges}
    charge_lease_ids = {charge.lease_contract_id for charge in charges if charge.status != "cancelled"}
    missing_charges = len(eligible_ids - charge_lease_ids)

    active_charges = [charge for charge in charges if charge.status != "cancelled"]
    open_charges = [
        charge
        for charge in active_charges
        if charge.status in OPEN_CHARGE_STATUSES and charge.paid_at is None
    ]
    overdue_charges = [
        charge
        for charge in open_charges
        if charge.status == "overdue" or charge.due_date < today
    ]
    paid_charges = [
        charge
        for charge in active_charges
        if charge.status == "paid" and charge.paid_at is not None
    ]

    settlements = db.scalars(
        select(FinancialSettlement).where(
            FinancialSettlement.organization_id == organization_id,
            FinancialSettlement.charge_id.in_(list(charge_ids)),
        )
    ).all() if charge_ids else []
    settlement_charge_ids = {item.charge_id for item in settlements}
    settlement_gap = sum(1 for charge in paid_charges if charge.id not in settlement_charge_ids)

    repasses = db.scalars(
        select(OwnerRepasse)
        .where(
            OwnerRepasse.organization_id == organization_id,
            OwnerRepasse.charge_id.in_(list(charge_ids)),
        )
        .order_by(OwnerRepasse.due_date.asc())
    ).all() if charge_ids else []
    pending_repasses = [
        item
        for item in repasses
        if item.status not in CLOSED_REPASSE_STATUSES and money(item.amount) > 0
    ]
    overdue_repasses = [item for item in pending_repasses if item.due_date < today]

    third_party_titles = db.scalars(
        select(FinancialTitle)
        .where(
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.competence == competence,
            FinancialTitle.direction == "payable",
            FinancialTitle.fund_scope == "third_party",
        )
        .order_by(FinancialTitle.due_date.asc(), FinancialTitle.internal_number.asc())
    ).all()
    pending_third_party = [
        item
        for item in third_party_titles
        if item.status not in CLOSED_TITLE_STATUSES and money(item.amount) > money(item.settled_amount)
    ]
    overdue_third_party = [item for item in pending_third_party if item.due_date < today]

    communication_conditions = []
    if charge_ids:
        communication_conditions.append(
            and_(
                CommunicationMessage.source_type == "rent_charge",
                CommunicationMessage.source_id.in_([str(item_id) for item_id in charge_ids]),
            )
        )
    if repasses:
        communication_conditions.append(
            and_(
                CommunicationMessage.source_type == "owner_repasse",
                CommunicationMessage.source_id.in_([str(item.id) for item in repasses]),
            )
        )
    communications = []
    if communication_conditions:
        communications = db.scalars(
            select(CommunicationMessage).where(
                CommunicationMessage.organization_id == organization_id,
                or_(*communication_conditions),
            )
        ).all()

    communications_pending = [item for item in communications if item.status in PENDING_COMMUNICATION_STATUSES]
    communications_sent = [item for item in communications if item.status == "sent"]
    communications_failed = [item for item in communications if item.status == "failed"]

    gross_amount = _sum(charge.gross_amount for charge in active_charges)
    received_amount = _sum(charge.paid_amount for charge in paid_charges)
    retention_amount = _sum(
        charge_item_agency_retention(component)
        for charge in paid_charges
        for component in list(charge.charge_items or [])
    )
    agency_revenue_amount = money(
        _sum(item.agency_fee_withheld + item.agency_reimbursement_amount for item in settlements)
        + retention_amount
    )
    owner_entitlement_amount = _sum(item.owner_entitlement_amount for item in settlements)
    third_party_pending_amount = _sum(
        money(item.amount) - money(item.settled_amount)
        for item in pending_third_party
    )
    owner_repasse_pending_amount = _sum(item.amount for item in pending_repasses)
    statement_owner_count = len({item.owner_person_id for item in repasses})

    if not eligible:
        contract_state = "idle"
        contract_summary = "Nenhum contrato elegível nesta competência."
    else:
        contract_state = "complete"
        contract_summary = f"{len(eligible)} contrato(s) assinado(s) e arquivado(s) estão aptos para faturamento."

    if not eligible and not charges:
        charge_state = "idle"
    elif missing_charges > 0:
        charge_state = "attention"
    else:
        charge_state = "complete"

    if not active_charges:
        receipt_state = "idle"
    elif overdue_charges:
        receipt_state = "attention"
    elif open_charges:
        receipt_state = "pending"
    else:
        receipt_state = "complete"

    if not paid_charges:
        settlement_state = "idle"
    elif settlement_gap:
        settlement_state = "attention"
    else:
        settlement_state = "complete"

    if not third_party_titles:
        third_party_state = "idle"
    elif overdue_third_party:
        third_party_state = "attention"
    elif pending_third_party:
        third_party_state = "pending"
    else:
        third_party_state = "complete"

    if not repasses:
        repasse_state = "idle"
    elif overdue_repasses:
        repasse_state = "attention"
    elif pending_repasses:
        repasse_state = "pending"
    else:
        repasse_state = "complete"

    statement_state = "complete" if statement_owner_count else "idle"

    if communications_failed:
        communication_state = "attention"
    elif communications_pending:
        communication_state = "pending"
    elif communications_sent:
        communication_state = "complete"
    else:
        communication_state = "idle"

    steps = [
        _step(
            key="contracts",
            title="Contratos elegíveis",
            state=contract_state,
            summary=contract_summary,
            detail="Somente contratos assinados, arquivados e vigentes entram na geração mensal.",
            count=len(eligible),
            pending_count=missing_charges,
            action_label="Abrir contratos",
            action_target="contracts",
        ),
        _step(
            key="charges",
            title="Cobranças da competência",
            state=charge_state,
            summary=f"{len(active_charges)} cobrança(s) ativa(s); {missing_charges} contrato(s) ainda sem cobrança.",
            detail="A cobrança preserva o valor bruto do locatário e a composição de proprietário, imobiliária e terceiros.",
            count=len(active_charges),
            pending_count=missing_charges,
            amount=gross_amount,
            action_label="Abrir cobranças",
            action_target="billing",
        ),
        _step(
            key="receipts",
            title="Recebimentos",
            state=receipt_state,
            summary=f"{len(paid_charges)} recebida(s), {len(open_charges)} em aberto e {len(overdue_charges)} em atraso.",
            detail="O ERP não aceita pagamento parcial; o recebimento integral dispara a liquidação financeira da cobrança.",
            count=len(paid_charges),
            pending_count=len(open_charges),
            amount=received_amount,
            pending_amount=_sum(charge.gross_amount for charge in open_charges),
            action_label="Abrir locações",
            action_target="rent",
        ),
        _step(
            key="settlement",
            title="Liquidação e segregação",
            state=settlement_state,
            summary=f"{len(settlements)} liquidação(ões) calculada(s); {settlement_gap} recebimento(s) sem liquidação.",
            detail="Taxas da imobiliária, direito do proprietário e obrigações de terceiros são calculados sem misturar recursos.",
            count=len(settlements),
            pending_count=settlement_gap,
            amount=agency_revenue_amount,
            pending_amount=owner_entitlement_amount,
            action_label="Ver composição",
            action_target="rent",
        ),
        _step(
            key="third_party",
            title="Obrigações de terceiros",
            state=third_party_state,
            summary=f"{len(pending_third_party)} obrigação(ões) pendente(s), sendo {len(overdue_third_party)} vencida(s).",
            detail="Valores líquidos de seguradoras e outros terceiros permanecem separados do caixa operacional.",
            count=len(third_party_titles),
            pending_count=len(pending_third_party),
            amount=_sum(item.amount for item in third_party_titles),
            pending_amount=third_party_pending_amount,
            action_label="Abrir visão financeira",
            action_target="overview",
        ),
        _step(
            key="owner_repasses",
            title="Repasses ao proprietário",
            state=repasse_state,
            summary=f"{len(pending_repasses)} repasse(s) pendente(s), sendo {len(overdue_repasses)} vencido(s).",
            detail="O repasse usa somente o direito líquido do proprietário apurado após a liquidação da cobrança.",
            count=len(repasses),
            pending_count=len(pending_repasses),
            amount=_sum(item.amount for item in repasses),
            pending_amount=owner_repasse_pending_amount,
            action_label="Abrir repasses",
            action_target="rent",
        ),
        _step(
            key="statements",
            title="Prestação de contas",
            state=statement_state,
            summary=f"{statement_owner_count} proprietário(s) com prestação de contas disponível na competência.",
            detail="A prestação consolida recebimento, taxas e repasse sem expor valores internos indevidos ao locatário.",
            count=statement_owner_count,
            action_label="Abrir prestações",
            action_target="rent",
        ),
        _step(
            key="communications",
            title="Comunicações",
            state=communication_state,
            summary=f"{len(communications_pending)} aguardando revisão, {len(communications_sent)} enviada(s) e {len(communications_failed)} com falha.",
            detail="Nenhuma mensagem é enviada automaticamente: sugestões continuam exigindo revisão e confirmação humana.",
            count=len(communications),
            pending_count=len(communications_pending) + len(communications_failed),
            action_label="Abrir comunicações",
            action_target="communications",
        ),
    ]

    next_action: MonthlyCycleAction | None = None
    if missing_charges > 0:
        next_action = MonthlyCycleAction(
            key="charges",
            title="Gerar cobranças faltantes",
            detail=f"Há {missing_charges} contrato(s) elegível(is) ainda sem cobrança nesta competência.",
            target="billing",
        )
    elif overdue_charges:
        next_action = MonthlyCycleAction(
            key="receipts",
            title="Tratar cobranças em atraso",
            detail=f"Há {len(overdue_charges)} cobrança(s) vencida(s) aguardando recebimento ou tratamento de inadimplência.",
            target="rent",
        )
    elif open_charges:
        next_action = MonthlyCycleAction(
            key="receipts",
            title="Acompanhar recebimentos",
            detail=f"Há {len(open_charges)} cobrança(s) ainda em aberto nesta competência.",
            target="rent",
        )
    elif settlement_gap:
        next_action = MonthlyCycleAction(
            key="settlement",
            title="Revisar liquidações",
            detail=f"Há {settlement_gap} recebimento(s) sem liquidação financeira calculada.",
            target="rent",
        )
    elif overdue_third_party:
        next_action = MonthlyCycleAction(
            key="third_party",
            title="Regularizar terceiros vencidos",
            detail=f"Há {len(overdue_third_party)} obrigação(ões) de terceiros vencida(s).",
            target="overview",
        )
    elif pending_third_party:
        next_action = MonthlyCycleAction(
            key="third_party",
            title="Preparar pagamentos de terceiros",
            detail=f"Há {len(pending_third_party)} obrigação(ões) de terceiros aguardando liquidação.",
            target="overview",
        )
    elif overdue_repasses:
        next_action = MonthlyCycleAction(
            key="owner_repasses",
            title="Regularizar repasses vencidos",
            detail=f"Há {len(overdue_repasses)} repasse(s) ao proprietário vencido(s).",
            target="rent",
        )
    elif pending_repasses:
        next_action = MonthlyCycleAction(
            key="owner_repasses",
            title="Executar repasses",
            detail=f"Há {len(pending_repasses)} repasse(s) aguardando pagamento.",
            target="rent",
        )
    elif communications_failed:
        next_action = MonthlyCycleAction(
            key="communications",
            title="Revisar falhas de comunicação",
            detail=f"Há {len(communications_failed)} comunicação(ões) com falha vinculada(s) à competência.",
            target="communications",
        )
    elif communications_pending:
        next_action = MonthlyCycleAction(
            key="communications",
            title="Revisar comunicações pendentes",
            detail=f"Há {len(communications_pending)} comunicação(ões) aguardando ação humana.",
            target="communications",
        )

    attention_count = (
        missing_charges
        + len(overdue_charges)
        + settlement_gap
        + len(overdue_third_party)
        + len(overdue_repasses)
        + len(communications_failed)
    )

    return MonthlyCycleResponse(
        competence=competence,
        eligible_contracts=len(eligible),
        charges_count=len(active_charges),
        missing_charges=missing_charges,
        gross_amount=gross_amount,
        open_charges=len(open_charges),
        overdue_charges=len(overdue_charges),
        paid_charges=len(paid_charges),
        received_amount=received_amount,
        settlements_count=len(settlements),
        agency_revenue_amount=agency_revenue_amount,
        owner_entitlement_amount=owner_entitlement_amount,
        third_party_pending_count=len(pending_third_party),
        third_party_pending_amount=third_party_pending_amount,
        owner_repasse_pending_count=len(pending_repasses),
        owner_repasse_pending_amount=owner_repasse_pending_amount,
        statement_owner_count=statement_owner_count,
        communications_pending_count=len(communications_pending),
        communications_sent_count=len(communications_sent),
        communications_failed_count=len(communications_failed),
        attention_count=attention_count,
        next_action=next_action,
        steps=steps,
    )



def build_monthly_closing_readiness(
    db: Session,
    *,
    organization_id: UUID,
    competence: date,
) -> MonthlyClosingReadiness:
    competence = month_start(competence)
    period_end = month_end(competence)

    accounts = db.scalars(
        select(BankAccount).where(
            BankAccount.organization_id == organization_id,
            BankAccount.is_active.is_(True),
        )
    ).all()
    account_ids = [item.id for item in accounts]

    closed_account_ids = set()
    if account_ids:
        closed_account_ids = set(
            db.scalars(
                select(BankDailyClose.bank_account_id).where(
                    BankDailyClose.organization_id == organization_id,
                    BankDailyClose.bank_account_id.in_(account_ids),
                    BankDailyClose.closing_date == period_end,
                    BankDailyClose.status == "confirmed",
                )
            ).all()
        )

    period_transactions = []
    if account_ids:
        period_transactions = db.scalars(
            select(BankTransaction).where(
                BankTransaction.organization_id == organization_id,
                BankTransaction.bank_account_id.in_(account_ids),
                BankTransaction.transaction_date >= competence,
                BankTransaction.transaction_date <= period_end,
            )
        ).all()
    unreconciled = [item for item in period_transactions if item.status != "reconciled"]
    transaction_ids = [item.id for item in period_transactions]

    open_exceptions: list[BankReconciliationExceptionRecord] = []
    if transaction_ids:
        open_exceptions = db.scalars(
            select(BankReconciliationExceptionRecord).where(
                BankReconciliationExceptionRecord.organization_id == organization_id,
                BankReconciliationExceptionRecord.bank_transaction_id.in_(transaction_ids),
                BankReconciliationExceptionRecord.status.in_(("open", "ignored")),
            )
        ).all()

    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.competence == competence,
            RentCharge.status != "cancelled",
        )
    ).all()
    charge_ids = [item.id for item in charges]
    paid_charge_ids = {item.id for item in charges if item.status == "paid" and item.paid_at is not None}

    settlements = []
    if charge_ids:
        settlements = db.scalars(
            select(FinancialSettlement).where(
                FinancialSettlement.organization_id == organization_id,
                FinancialSettlement.charge_id.in_(charge_ids),
            )
        ).all()
    settlement_by_charge = {item.charge_id: item for item in settlements}
    settlement_gap = len(paid_charge_ids - set(settlement_by_charge))

    settlement_ids = [item.id for item in settlements]
    repasses = []
    if settlement_ids:
        repasses = db.scalars(
            select(OwnerRepasse).where(
                OwnerRepasse.organization_id == organization_id,
                OwnerRepasse.settlement_id.in_(settlement_ids),
            )
        ).all()
    repasses_by_settlement: dict[UUID, list[OwnerRepasse]] = {}
    for item in repasses:
        repasses_by_settlement.setdefault(item.settlement_id, []).append(item)

    integrity_issues = 0
    for settlement in settlements:
        expected = money(settlement.owner_entitlement_amount)
        actual = _sum(item.amount for item in repasses_by_settlement.get(settlement.id, []))
        if abs(expected - actual) > Decimal("0.01"):
            integrity_issues += 1

    third_party_titles = db.scalars(
        select(FinancialTitle).where(
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.competence == competence,
            FinancialTitle.direction == "payable",
            FinancialTitle.fund_scope == "third_party",
        )
    ).all()
    pending_third_party = [
        item for item in third_party_titles
        if item.status not in CLOSED_TITLE_STATUSES and money(item.amount) > money(item.settled_amount)
    ]

    pending_repasses = [
        item for item in repasses
        if item.status not in CLOSED_REPASSE_STATUSES and money(item.amount) > 0
    ]

    unclosed_accounts = max(0, len(accounts) - len(closed_account_ids))
    open_bank_exceptions = sum(1 for item in open_exceptions if item.status == "open")
    ignored_bank_exceptions = sum(1 for item in open_exceptions if item.status == "ignored")

    blockers: list[str] = []
    if unclosed_accounts:
        blockers.append(f"{unclosed_accounts} conta(s) bancária(s) sem fechamento confirmado no último dia da competência.")
    if unreconciled:
        blockers.append(f"{len(unreconciled)} movimento(s) bancário(s) da competência ainda não estão integralmente conciliados.")
    if open_bank_exceptions:
        blockers.append(f"{open_bank_exceptions} exceção(ões) bancária(s) aberta(s) exigem resolução.")
    if ignored_bank_exceptions:
        blockers.append(f"{ignored_bank_exceptions} exceção(ões) bancária(s) ignorada(s) precisam de revisão antes do fechamento.")
    if settlement_gap:
        blockers.append(f"{settlement_gap} recebimento(s) pago(s) ainda não possuem liquidação financeira.")
    if integrity_issues:
        blockers.append(f"{integrity_issues} liquidação(ões) possuem divergência entre direito do proprietário e repasses gerados.")
    if pending_third_party:
        blockers.append(f"{len(pending_third_party)} obrigação(ões) de terceiros permanecem pendentes.")
    if pending_repasses:
        blockers.append(f"{len(pending_repasses)} repasse(s) ao proprietário permanecem pendentes.")

    blocker_count = (
        unclosed_accounts
        + len(unreconciled)
        + open_bank_exceptions
        + ignored_bank_exceptions
        + settlement_gap
        + integrity_issues
        + len(pending_third_party)
        + len(pending_repasses)
    )
    return MonthlyClosingReadiness(
        competence=competence,
        period_end=period_end,
        can_close=blocker_count == 0,
        bank_accounts_count=len(accounts),
        accounts_closed_count=len(closed_account_ids),
        unclosed_accounts_count=unclosed_accounts,
        unreconciled_bank_transactions_count=len(unreconciled),
        open_bank_exceptions_count=open_bank_exceptions,
        ignored_bank_exceptions_count=ignored_bank_exceptions,
        settlement_gap_count=settlement_gap,
        settlement_integrity_issues_count=integrity_issues,
        pending_third_party_count=len(pending_third_party),
        pending_owner_repasses_count=len(pending_repasses),
        blocker_count=blocker_count,
        blockers=blockers,
    )
