from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.finance.advanced_models import (
    BillingBatch,
    BillingItem,
    CommissionEntry,
    CommissionRule,
    DelinquencyCase,
)
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import FinancialSettlement, MaintenanceFinancialEntry, OwnerRepasse, RentCharge
from app.domains.finance.service import generate_charges, money, months_since, refresh_overdue
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person

ZERO = Decimal("0.00")


def month_start(value: date) -> date:
    return value.replace(day=1)


def ensure_billing_batch(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    competence: date,
) -> tuple[BillingBatch, int, int, int]:
    competence = month_start(competence)
    created, skipped_existing, skipped_ineligible = generate_charges(
        db,
        organization_id=organization_id,
        user_id=user_id,
        competence=competence,
    )
    batch = db.scalar(
        select(BillingBatch).where(
            BillingBatch.organization_id == organization_id,
            BillingBatch.competence == competence,
        )
    )
    if batch is None:
        batch = BillingBatch(
            organization_id=organization_id,
            competence=competence,
            status="generated",
            provider="manual",
            created_by_user_id=user_id,
        )
        db.add(batch)
        db.flush()

    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.competence == competence,
            RentCharge.status != "cancelled",
        ).order_by(RentCharge.internal_number)
    ).all()
    existing_charge_ids = set(
        db.scalars(select(BillingItem.charge_id).where(BillingItem.billing_batch_id == batch.id)).all()
    )
    for charge in charges:
        if charge.id in existing_charge_ids:
            continue
        db.add(BillingItem(
            organization_id=organization_id,
            billing_batch_id=batch.id,
            charge_id=charge.id,
            provider="manual",
        ))
    db.flush()
    refresh_billing_batch_counters(db, batch)
    return batch, len(created), skipped_existing, skipped_ineligible


def refresh_billing_batch_counters(db: Session, batch: BillingBatch) -> None:
    items = db.scalars(select(BillingItem).where(BillingItem.billing_batch_id == batch.id)).all()
    batch.generated_count = len(items)
    batch.issued_count = sum(1 for item in items if item.issued_at is not None)
    batch.sent_count = sum(1 for item in items if item.sent_at is not None)
    batch.confirmed_count = sum(1 for item in items if str(item.provider_status or "").upper() in {"RECEBIDO", "MARCADO_RECEBIDO"})
    batch.error_count = sum(1 for item in items if item.last_error)
    if batch.generated_count and batch.confirmed_count == batch.generated_count:
        batch.status = "completed"
        batch.completed_at = batch.completed_at or datetime.now(timezone.utc)
    elif batch.sent_count:
        batch.status = "sent" if batch.sent_count == batch.generated_count else "partial"
    elif batch.issued_count:
        batch.status = "issued" if batch.issued_count == batch.generated_count else "partial"
    else:
        batch.status = "generated"


def refresh_delinquency_cases(
    db: Session,
    *,
    organization_id: UUID,
    today: date | None = None,
) -> list[DelinquencyCase]:
    today = today or date.today()
    refresh_overdue(db, organization_id, today=today)
    charges = db.scalars(
        select(RentCharge).where(RentCharge.organization_id == organization_id)
    ).all()
    charge_by_id = {item.id: item for item in charges}
    existing = {
        item.charge_id: item
        for item in db.scalars(
            select(DelinquencyCase).where(DelinquencyCase.organization_id == organization_id)
        ).all()
    }
    now = datetime.now(timezone.utc)
    for charge in charges:
        case = existing.get(charge.id)
        if charge.status == "overdue":
            critical_days = max(1, int((charge.admin_terms_snapshot or {}).get("delinquency_critical_day") or 5))
            days = max(0, (today - charge.due_date).days)
            if case is None:
                case = DelinquencyCase(
                    organization_id=organization_id,
                    charge_id=charge.id,
                    property_id=charge.property_id,
                    lease_contract_id=charge.lease_contract_id,
                    status="open",
                    critical_after_days=critical_days,
                    opened_at=now,
                    action_log=[{
                        "at": now.isoformat(),
                        "action": "opened",
                        "detail": "Caso aberto automaticamente após vencimento.",
                    }],
                )
                db.add(case)
                existing[charge.id] = case
            else:
                case.critical_after_days = critical_days
                if case.status == "resolved":
                    case.status = "open"
                    case.resolved_at = None
            if days >= critical_days and case.critical_at is None:
                case.critical_at = now
                case.action_log = [
                    *list(case.action_log or []),
                    {
                        "at": now.isoformat(),
                        "action": "critical",
                        "detail": f"Atraso atingiu {days} dia(s); limite crítico configurado em {critical_days}.",
                    },
                ]
        elif case is not None and case.status != "resolved":
            case.status = "resolved"
            case.resolved_at = now
            case.action_log = [
                *list(case.action_log or []),
                {
                    "at": now.isoformat(),
                    "action": "resolved",
                    "detail": f"Caso encerrado automaticamente porque a cobrança está {charge.status}.",
                },
            ]
    db.flush()
    result = list(existing.values())
    result.sort(key=lambda item: (charge_by_id.get(item.charge_id).due_date if charge_by_id.get(item.charge_id) else today, item.opened_at))
    return result


def _commission_basis(rule: CommissionRule, charge: RentCharge, settlement: FinancialSettlement) -> Decimal:
    if rule.basis == "rent":
        return money(charge.rent_amount)
    if rule.basis == "administration_fee":
        return money(settlement.admin_fee_calculated)
    if rule.basis == "intermediation_fee":
        return money(settlement.intermediation_fee_calculated)
    return money(settlement.agency_fee_withheld)


def _commission_rule_applies(rule: CommissionRule, charge: RentCharge, settlement: FinancialSettlement) -> bool:
    if not rule.is_active:
        return False
    if rule.property_id and rule.property_id != charge.property_id:
        return False
    if rule.lease_contract_id and rule.lease_contract_id != charge.lease_contract_id:
        return False
    lease = None
    if rule.event_type == "first_rent":
        lease = charge.competence
        # O primeiro aluguel é a primeira competência do contrato.
        # A data real do contrato é carregada no chamador quando necessário.
    if rule.event_type == "intermediation" and money(settlement.intermediation_fee_calculated) <= 0:
        return False
    return True


def generate_commissions_for_charge(
    db: Session,
    *,
    charge: RentCharge,
    settlement: FinancialSettlement,
) -> list[CommissionEntry]:
    rules = db.scalars(
        select(CommissionRule)
        .where(CommissionRule.organization_id == charge.organization_id, CommissionRule.is_active.is_(True))
        .order_by(CommissionRule.priority, CommissionRule.internal_number)
    ).all()
    if not rules:
        return []
    lease = db.get(LeaseContract, charge.lease_contract_id)
    existing_rule_ids = set(db.scalars(
        select(CommissionEntry.rule_id).where(
            CommissionEntry.organization_id == charge.organization_id,
            CommissionEntry.source_type == "rent_charge",
            CommissionEntry.source_id == charge.id,
        )
    ).all())
    created: list[CommissionEntry] = []
    paid_date = (charge.paid_at or datetime.now(timezone.utc)).date()
    for rule in rules:
        if rule.id in existing_rule_ids or not _commission_rule_applies(rule, charge, settlement):
            continue
        if rule.event_type == "first_rent" and lease is not None and months_since(lease.start_date, charge.competence) != 0:
            continue
        basis = _commission_basis(rule, charge, settlement)
        if basis <= 0:
            continue
        if rule.calculation_type == "fixed":
            amount = money(rule.value)
        else:
            amount = money(basis * Decimal(str(rule.value)) / Decimal("100"))
        if amount <= 0:
            continue
        due_date = paid_date + timedelta(days=max(0, int(rule.due_days)))
        entry = CommissionEntry(
            organization_id=charge.organization_id,
            rule_id=rule.id,
            source_type="rent_charge",
            source_id=charge.id,
            source_code=f"COB-{charge.internal_number:06d}",
            charge_id=charge.id,
            lease_contract_id=charge.lease_contract_id,
            property_id=charge.property_id,
            beneficiary_type=rule.beneficiary_type,
            beneficiary_person_id=rule.beneficiary_person_id,
            beneficiary_name=rule.beneficiary_name,
            competence=charge.competence,
            basis_amount=basis,
            amount=amount,
            due_date=due_date,
            status="pending",
            notes=f"Gerada automaticamente pela regra {rule.name}.",
        )
        db.add(entry)
        db.flush()
        title = FinancialTitle(
            organization_id=charge.organization_id,
            direction="payable",
            fund_scope="operating",
            source_type="commission",
            source_id=entry.id,
            property_id=charge.property_id,
            lease_contract_id=charge.lease_contract_id,
            category="Comissões",
            description=f"Comissão {rule.name} · {entry.source_code}",
            counterparty_name=rule.beneficiary_name,
            competence=charge.competence,
            due_date=due_date,
            amount=amount,
            settled_amount=ZERO,
            status="pending",
            source_snapshot={
                "commission_entry_id": str(entry.id),
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "beneficiary_type": rule.beneficiary_type,
                "basis": rule.basis,
                "basis_amount": str(basis),
            },
        )
        db.add(title)
        db.flush()
        entry.financial_title_id = title.id
        created.append(entry)
    return created


def sync_commission_status(db: Session, entry: CommissionEntry) -> CommissionEntry:
    if not entry.financial_title_id:
        return entry
    title = db.get(FinancialTitle, entry.financial_title_id)
    if title is None:
        return entry
    if title.status == "settled":
        entry.status = "paid"
        entry.paid_at = title.settled_at
        entry.payment_reference = title.payment_reference
    elif title.status == "cancelled":
        entry.status = "cancelled"
    elif entry.status not in {"approved", "cancelled"}:
        entry.status = "pending"
    return entry


def dre_values(
    db: Session,
    *,
    organization_id: UUID,
    start_date: date,
    end_date: date,
    regime: str,
) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {
        "administration": ZERO,
        "intermediation": ZERO,
        "maintenance_revenue": ZERO,
        "other_revenue": ZERO,
        "maintenance_cost": ZERO,
        "commissions": ZERO,
        "other_expense": ZERO,
    }

    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.status == "paid",
        )
    ).all()
    settlements = {
        item.charge_id: item
        for item in db.scalars(
            select(FinancialSettlement).where(FinancialSettlement.organization_id == organization_id)
        ).all()
    }
    for charge in charges:
        reference = charge.competence if regime == "competence" else (charge.paid_at.date() if charge.paid_at else None)
        if reference is None or reference < start_date or reference > end_date:
            continue
        settlement = settlements.get(charge.id)
        if not settlement:
            continue
        admin = money(settlement.admin_fee_calculated)
        intermediation = money(settlement.intermediation_fee_calculated)
        withheld = money(settlement.agency_fee_withheld)
        # Quando as taxas calculadas excedem o que pôde ser retido, distribuímos
        # proporcionalmente para a DRE não reconhecer receita inexistente.
        requested = admin + intermediation
        factor = (withheld / requested) if requested > 0 and withheld < requested else Decimal("1")
        values["administration"] += money(admin * factor)
        values["intermediation"] += money(intermediation * factor)

    maintenance = db.scalars(
        select(MaintenanceFinancialEntry).where(
            MaintenanceFinancialEntry.organization_id == organization_id,
            MaintenanceFinancialEntry.settled_at.is_not(None),
        )
    ).all()
    for item in maintenance:
        reference = item.created_at.date() if regime == "competence" else (item.settled_at.date() if item.settled_at else None)
        if reference is None or reference < start_date or reference > end_date:
            continue
        amount = money(item.settled_amount)
        if item.direction == "receivable" and item.collection_method != "owner_repasse_deduction":
            values["maintenance_revenue"] += amount
        elif item.direction == "payable":
            values["maintenance_cost"] += amount

    titles = db.scalars(
        select(FinancialTitle).where(
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.fund_scope == "operating",
            FinancialTitle.status == "settled",
        )
    ).all()
    for item in titles:
        reference = item.competence if regime == "competence" else (item.settled_at.date() if item.settled_at else None)
        if reference is None or reference < start_date or reference > end_date:
            continue
        amount = money(item.settled_amount)
        if item.direction == "receivable":
            values["other_revenue"] += amount
        elif item.source_type == "commission":
            values["commissions"] += amount
        else:
            values["other_expense"] += amount

    return {key: money(value) for key, value in values.items()}



def finance_closing_control(
    db: Session,
    *,
    organization_id: UUID,
    start_date: date,
    end_date: date,
):
    from app.domains.finance.bank_models import BankReconciliation, BankTransaction

    issues = []
    transactions = db.scalars(
        select(BankTransaction)
        .where(
            BankTransaction.organization_id == organization_id,
            BankTransaction.transaction_date >= start_date,
            BankTransaction.transaction_date <= end_date,
        )
        .order_by(BankTransaction.transaction_date, BankTransaction.internal_number)
    ).all()

    reconciled_count = 0
    unreconciled_count = 0
    mismatch_count = 0
    invalid_target_count = 0

    def issue(severity, code, message, entity_type, entity_id, reference=None):
        issues.append({
            "severity": severity,
            "code": code,
            "message": message,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "reference": reference,
        })

    for tx in transactions:
        reconciliations = list(tx.reconciliations or [])
        total_reconciled = money(sum((money(item.amount) for item in reconciliations), ZERO))
        tx_amount = money(tx.amount)

        if tx.status in {"reconciled", "partial"} and not reconciliations:
            unreconciled_count += 1
            issue(
                "error",
                "BANK_TX_WITHOUT_ORIGIN",
                f"Movimentação bancária {tx.internal_number} está {tx.status}, mas não possui conciliação.",
                "bank_transaction",
                tx.id,
                str(tx.internal_number),
            )
        elif not reconciliations:
            unreconciled_count += 1
            issue(
                "warning",
                "BANK_TX_PENDING_RECONCILIATION",
                f"Movimentação bancária {tx.internal_number} ainda não possui origem financeira conciliada.",
                "bank_transaction",
                tx.id,
                str(tx.internal_number),
            )
        else:
            reconciled_count += 1

        if total_reconciled != tx_amount:
            mismatch_count += 1
            issue(
                "error",
                "BANK_RECONCILIATION_AMOUNT_MISMATCH",
                f"Movimentação {tx.internal_number}: banco R$ {tx_amount:.2f}, conciliação R$ {total_reconciled:.2f}.",
                "bank_transaction",
                tx.id,
                str(tx.internal_number),
            )

        expected_direction = "receivable" if tx.direction == "credit" else "payable"
        for rec in reconciliations:
            if rec.target_direction != expected_direction:
                invalid_target_count += 1
                issue(
                    "error",
                    "BANK_RECONCILIATION_DIRECTION",
                    f"Conciliação {rec.target_code} possui direção {rec.target_direction}, incompatível com movimento {tx.direction}.",
                    "bank_reconciliation",
                    rec.id,
                    rec.target_code,
                )
                continue

            target = None
            if rec.target_type == "rent":
                target = db.get(RentCharge, rec.target_id)
                valid = target is not None and target.status == "paid"
            elif rec.target_type == "owner_repasse":
                target = db.get(OwnerRepasse, rec.target_id)
                valid = target is not None and target.status == "paid"
            elif rec.target_type == "maintenance":
                target = db.get(MaintenanceFinancialEntry, rec.target_id)
                valid = target is not None and target.status == "settled"
            else:
                target = db.get(FinancialTitle, rec.target_id)
                valid = target is not None and target.status == "settled"

            if not valid:
                invalid_target_count += 1
                issue(
                    "error",
                    "BANK_RECONCILIATION_INVALID_TARGET",
                    f"Conciliação {rec.target_code} aponta para uma obrigação/recebível que não está liquidado ou não existe.",
                    "bank_reconciliation",
                    rec.id,
                    rec.target_code,
                )

    commission_entries = db.scalars(
        select(CommissionEntry).where(CommissionEntry.organization_id == organization_id)
    ).all()
    duplicate_commissions = 0
    unclassified_commissions = 0
    seen = {}
    for entry in commission_entries:
        sync_commission_status(db, entry)
        if entry.status != "paid":
            continue
        reference = entry.paid_at.date() if entry.paid_at else None
        if reference is None or reference < start_date or reference > end_date:
            continue
        key = (entry.source_type, entry.source_id, entry.rule_id)
        seen[key] = seen.get(key, 0) + 1
        title = db.get(FinancialTitle, entry.financial_title_id) if entry.financial_title_id else None
        if title is None or title.source_type != "commission":
            unclassified_commissions += 1
            issue(
                "error",
                "DRE_COMMISSION_UNCLASSIFIED",
                f"Comissão {entry.source_code} liquidada sem título financeiro classificado como comissão.",
                "commission_entry",
                entry.id,
                entry.source_code,
            )

    for key, count in seen.items():
        if count > 1:
            duplicate_commissions += count - 1
            issue(
                "error",
                "DRE_COMMISSION_DUPLICATE",
                f"Existem {count} lançamentos de comissão para a mesma origem/regra: {key[1]}.",
                "commission_entry",
                key[1],
                str(key[1]),
            )

    return {
        "bank_transactions": len(transactions),
        "bank_transactions_reconciled": reconciled_count,
        "bank_transactions_unreconciled": unreconciled_count,
        "reconciliation_amount_mismatch": mismatch_count,
        "invalid_reconciliation_targets": invalid_target_count,
        "dre_duplicate_commissions": duplicate_commissions,
        "dre_unclassified_commissions": unclassified_commissions,
        "ready_to_close": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
    }

def annual_income_values(
    db: Session,
    *,
    organization_id: UUID,
    year: int,
    party_type: str,
    person_id: UUID,
) -> tuple[Person, list[dict], str]:
    person = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == organization_id))
    if person is None:
        raise ValueError("Pessoa não encontrada.")
    lines: list[dict] = []
    allocation_method = "individual"
    if party_type == "owner":
        repasses = db.scalars(
            select(OwnerRepasse).where(
                OwnerRepasse.organization_id == organization_id,
                OwnerRepasse.owner_person_id == person_id,
            )
        ).all()
        for repasse in repasses:
            charge = db.get(RentCharge, repasse.charge_id)
            settlement = db.get(FinancialSettlement, repasse.settlement_id)
            if not charge or charge.status != "paid" or not charge.paid_at or charge.paid_at.year != year or not settlement:
                continue
            owner_share = Decimal(str(repasse.ownership_percent or 0)) / Decimal("100")
            owner_rent = money(max(ZERO, money(charge.rent_amount) - money(settlement.agency_fee_withheld)) * owner_share)
            lines.append({
                "competence": charge.competence,
                "payment_date": charge.paid_at.date(),
                "property_code": str((charge.property_snapshot or {}).get("code") or "—"),
                "charge_code": f"COB-{charge.internal_number:06d}",
                "rent_amount": owner_rent,
                "additional_charges": money(max(ZERO, repasse.amount - owner_rent)),
                "total_amount": money(repasse.amount),
                "administration_fee": money(settlement.agency_fee_withheld * owner_share),
                "owner_net_amount": money(repasse.amount),
            })
        return person, lines, "percentual de propriedade do contrato"

    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.status == "paid",
        )
    ).all()
    for charge in charges:
        if not charge.paid_at or charge.paid_at.year != year:
            continue
        tenants = [item for item in list(charge.tenant_snapshot or []) if isinstance(item, dict) and item.get("person_id")]
        matching = next((item for item in tenants if str(item.get("person_id")) == str(person_id)), None)
        if matching is None:
            continue
        explicit = matching.get("responsibility_percent") or matching.get("share_percent")
        if explicit is not None:
            share = Decimal(str(explicit)) / Decimal("100")
            method = "percentual definido no contrato"
        else:
            share = Decimal("1") / Decimal(str(max(1, len(tenants))))
            method = "divisão igual entre locatários do contrato" if len(tenants) > 1 else "locatário único"
        allocation_method = method
        rent = money(charge.rent_amount * share)
        gross = money(charge.gross_amount * share)
        lines.append({
            "competence": charge.competence,
            "payment_date": charge.paid_at.date(),
            "property_code": str((charge.property_snapshot or {}).get("code") or "—"),
            "charge_code": f"COB-{charge.internal_number:06d}",
            "rent_amount": rent,
            "additional_charges": money(max(ZERO, gross - rent)),
            "total_amount": gross,
            "administration_fee": ZERO,
            "owner_net_amount": ZERO,
        })
    return person, lines, allocation_method
