import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.contracts.models import AdministrationContract
from app.domains.finance.models import FinancialSettlement, OwnerRepasse, RentCharge
from app.domains.foundation.defaults import OPERATIONAL_DEFAULTS
from app.domains.foundation.models import OrganizationSettings
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Property

CENT = Decimal("0.01")


def money(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def month_start(value: date) -> date:
    return value.replace(day=1)


def month_end(value: date) -> date:
    start = month_start(value)
    return start.replace(day=calendar.monthrange(start.year, start.month)[1])


def due_date_for(competence: date, due_day: int) -> date:
    competence = month_start(competence)
    last = calendar.monthrange(competence.year, competence.month)[1]
    return competence.replace(day=max(1, min(due_day, last)))


def business_days_after(value: date, days: int) -> date:
    current = value
    remaining = max(0, days)
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def months_since(start: date, competence: date) -> int:
    return (competence.year - start.year) * 12 + competence.month - start.month


def operational_defaults(db: Session, organization_id: UUID) -> dict:
    row = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    return {**OPERATIONAL_DEFAULTS, **(dict(row.operational_defaults or {}) if row else {})}


def administration_terms(db: Session, organization_id: UUID, property_id: UUID) -> dict:
    contracts = db.scalars(
        select(AdministrationContract)
        .where(
            AdministrationContract.organization_id == organization_id,
            AdministrationContract.property_id == property_id,
            AdministrationContract.status != "cancelled",
        )
        .order_by(AdministrationContract.created_at.desc())
    ).all()
    selected = next((item for item in contracts if item.status == "signed"), contracts[0] if contracts else None)
    defaults = operational_defaults(db, organization_id)
    if selected is None:
        return {
            "administration_contract_id": None,
            "source": "operational_defaults",
            "admin_fee_type": "percent",
            "admin_fee_percent": str(defaults.get("default_admin_fee_percent", 10)),
            "admin_fee_amount": None,
            "intermediation_percent": "0",
            "intermediation_installments": 1,
            "owner_repasse_business_days": int(defaults.get("owner_repasse_business_days", 2)),
            "condo_operational_payer": "tenant",
            "iptu_operational_payer": "tenant",
            "delinquency_critical_day": int(defaults.get("delinquency_critical_day", 5)),
        }
    return {
        "administration_contract_id": str(selected.id),
        "administration_contract_code": f"ADM-{selected.internal_number:06d}",
        "source": "administration_contract",
        "status": selected.status,
        "admin_fee_type": selected.admin_fee_type,
        "admin_fee_percent": str(selected.admin_fee_percent) if selected.admin_fee_percent is not None else None,
        "admin_fee_amount": str(selected.admin_fee_amount) if selected.admin_fee_amount is not None else None,
        "intermediation_percent": str(selected.intermediation_percent),
        "intermediation_installments": selected.intermediation_installments,
        "owner_repasse_business_days": selected.owner_repasse_business_days,
        "condo_operational_payer": selected.condo_operational_payer,
        "iptu_operational_payer": selected.iptu_operational_payer,
        "delinquency_critical_day": int(defaults.get("delinquency_critical_day", 5)),
    }


def configured_monthly_charge_rules(lease: LeaseContract) -> list[dict]:
    rules = dict(lease.rules_snapshot or {})
    raw = rules.get("monthly_charges") or []
    return [dict(item) for item in raw if isinstance(item, dict)]


def suggested_monthly_charge_rules(property_item: Property, terms: dict) -> list[dict]:
    iptu = money(property_item.iptu_amount)
    condo = money(property_item.condo_amount)
    return [
        {
            "key": "iptu",
            "kind": "iptu",
            "label": "IPTU",
            "amount": str(iptu),
            "active": iptu > 0,
            "payer": "tenant",
            "beneficiary": "owner",
            "start_date": None,
            "end_date": None,
        },
        {
            "key": "condo",
            "kind": "condo",
            "label": "Condomínio",
            "amount": str(condo),
            "active": condo > 0,
            "payer": "tenant",
            "beneficiary": "third_party",
            "start_date": None,
            "end_date": None,
        },
        {
            "key": "guarantee_insurance",
            "kind": "guarantee_insurance",
            "label": "Seguro fiança",
            "amount": "0.00",
            "active": False,
            "payer": "tenant",
            "beneficiary": "third_party",
            "start_date": None,
            "end_date": None,
        },
        {
            "key": "fire_insurance",
            "kind": "fire_insurance",
            "label": "Seguro incêndio",
            "amount": "0.00",
            "active": False,
            "payer": "tenant",
            "beneficiary": "third_party",
            "start_date": None,
            "end_date": None,
        },
    ]


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _rule_applies(rule: dict, competence: date) -> bool:
    if not bool(rule.get("active", True)) or money(rule.get("amount")) <= 0:
        return False
    start = _parse_date(rule.get("start_date"))
    end = _parse_date(rule.get("end_date"))
    period_start = month_start(competence)
    period_end = month_end(competence)
    if start and start > period_end:
        return False
    if end and end < period_start:
        return False
    return True


def charge_items(lease: LeaseContract, property_item: Property, terms: dict, competence: date) -> list[dict]:
    items: list[dict] = [
        {
            "key": "rent",
            "kind": "rent",
            "label": "Aluguel",
            "amount": str(money(lease.rent_amount)),
            "payer": "tenant",
            "beneficiary": "owner",
            "source": "lease_contract",
        }
    ]
    configured = configured_monthly_charge_rules(lease)
    if configured:
        for rule in configured:
            if rule.get("payer", "tenant") != "tenant" or not _rule_applies(rule, competence):
                continue
            beneficiary = str(rule.get("beneficiary") or "third_party")
            if beneficiary not in {"owner", "agency", "third_party"}:
                beneficiary = "third_party"
            items.append(
                {
                    "key": str(rule.get("key") or "other"),
                    "kind": str(rule.get("kind") or "other"),
                    "label": str(rule.get("label") or "Encargo mensal"),
                    "amount": str(money(rule.get("amount"))),
                    "payer": "tenant",
                    "beneficiary": beneficiary,
                    "source": "lease_monthly_rule",
                }
            )
        return items

    # Compatibilidade com contratos assinados antes da composição mensal versionada.
    if terms.get("iptu_operational_payer") == "tenant" and property_item.iptu_amount:
        items.append({"key": "iptu", "kind": "iptu", "label": "IPTU", "amount": str(money(property_item.iptu_amount)), "payer": "tenant", "beneficiary": "owner", "source": "legacy_property"})
    if terms.get("condo_operational_payer") == "agency" and property_item.condo_amount:
        items.append({"key": "condo", "kind": "condo", "label": "Condomínio", "amount": str(money(property_item.condo_amount)), "payer": "tenant", "beneficiary": "agency", "source": "legacy_property"})
    return items


def refresh_overdue(db: Session, organization_id: UUID, *, today: date | None = None) -> bool:
    today = today or date.today()
    changed = False
    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.status.in_(("generated", "sent", "overdue")),
        )
    ).all()
    for charge in charges:
        next_status = "overdue" if charge.due_date < today else ("sent" if charge.sent_at else "generated")
        if charge.status != next_status:
            charge.status = next_status
            changed = True
    return changed


def generate_charges(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    competence: date,
    lease_contract_id: UUID | None = None,
) -> tuple[list[RentCharge], int, int]:
    competence = month_start(competence)
    period_end = month_end(competence)
    stmt = select(LeaseContract).where(LeaseContract.organization_id == organization_id)
    if lease_contract_id:
        stmt = stmt.where(LeaseContract.id == lease_contract_id)
    leases = db.scalars(stmt.order_by(LeaseContract.internal_number.asc())).all()
    eligible = [
        lease for lease in leases
        if lease.status == "signed"
        and lease.archive_status == "archived"
        and lease.final_document_hash
        and lease.start_date <= period_end
        and (lease.operational_end_date or lease.end_date) >= competence
    ]
    skipped_ineligible = max(0, len(leases) - len(eligible))
    if not eligible:
        return [], 0, skipped_ineligible

    existing_ids = set(db.scalars(
        select(RentCharge.lease_contract_id).where(
            RentCharge.organization_id == organization_id,
            RentCharge.competence == competence,
            RentCharge.lease_contract_id.in_([lease.id for lease in eligible]),
        )
    ).all())
    skipped_existing = len(existing_ids)
    property_ids = {lease.property_id for lease in eligible if lease.id not in existing_ids}
    properties = {
        item.id: item
        for item in db.scalars(select(Property).where(Property.organization_id == organization_id, Property.id.in_(property_ids))).all()
    }

    created: list[RentCharge] = []
    for lease in eligible:
        if lease.id in existing_ids:
            continue
        property_item = properties.get(lease.property_id)
        if property_item is None:
            skipped_ineligible += 1
            continue
        terms = administration_terms(db, organization_id, property_item.id)
        components = charge_items(lease, property_item, terms, competence)
        gross = sum((money(item["amount"]) for item in components), Decimal("0.00"))
        charge = RentCharge(
            organization_id=organization_id,
            lease_contract_id=lease.id,
            property_id=lease.property_id,
            competence=competence,
            due_date=due_date_for(competence, lease.due_day),
            status="generated",
            rent_amount=money(lease.rent_amount),
            gross_amount=money(gross),
            charge_items=components,
            tenant_snapshot=list(lease.tenant_snapshot or []),
            property_snapshot=dict(lease.property_snapshot or {}),
            owner_snapshot=list(lease.owner_snapshot or []),
            admin_terms_snapshot=terms,
            created_by_user_id=user_id,
        )
        db.add(charge)
        created.append(charge)
    db.flush()
    return created, skipped_existing, skipped_ineligible


def calculate_settlement(db: Session, charge: RentCharge, paid_at: datetime) -> FinancialSettlement:
    if charge.settlement is not None:
        return charge.settlement
    terms = dict(charge.admin_terms_snapshot or {})
    rent = money(charge.rent_amount)
    if terms.get("admin_fee_type") == "fixed":
        admin_fee = money(terms.get("admin_fee_amount"))
    else:
        admin_fee = money(rent * Decimal(str(terms.get("admin_fee_percent") or 0)) / Decimal("100"))

    lease = db.get(LeaseContract, charge.lease_contract_id)
    lease_start = lease.start_date if lease else charge.competence
    installment_number = months_since(lease_start, charge.competence) + 1
    installments = max(1, int(terms.get("intermediation_installments") or 1))
    intermediation_percent = Decimal(str(terms.get("intermediation_percent") or 0))
    intermediation_fee = Decimal("0.00")
    if 1 <= installment_number <= installments and intermediation_percent > 0:
        intermediation_fee = money(rent * intermediation_percent / Decimal("100") / Decimal(installments))

    requested_agency_fees = admin_fee + intermediation_fee
    agency_fee_withheld = money(min(rent, requested_agency_fees))
    agency_reimbursement = sum(
        (money(item.get("amount")) for item in charge.charge_items if item.get("key") != "rent" and item.get("beneficiary") == "agency"),
        Decimal("0.00"),
    )
    owner_reimbursements = sum(
        (money(item.get("amount")) for item in charge.charge_items if item.get("key") != "rent" and item.get("beneficiary") == "owner"),
        Decimal("0.00"),
    )
    third_party = sum(
        (money(item.get("amount")) for item in charge.charge_items if item.get("beneficiary") == "third_party"),
        Decimal("0.00"),
    )
    owner_entitlement = money(max(Decimal("0.00"), rent - agency_fee_withheld) + owner_reimbursements)

    admin_contract_id = terms.get("administration_contract_id")
    settlement = FinancialSettlement(
        organization_id=charge.organization_id,
        charge_id=charge.id,
        lease_contract_id=charge.lease_contract_id,
        property_id=charge.property_id,
        administration_contract_id=UUID(admin_contract_id) if admin_contract_id else None,
        admin_fee_calculated=admin_fee,
        intermediation_fee_calculated=intermediation_fee,
        agency_fee_withheld=agency_fee_withheld,
        agency_reimbursement_amount=money(agency_reimbursement),
        owner_entitlement_amount=owner_entitlement,
        third_party_amount=money(third_party),
    )
    db.add(settlement)
    db.flush()

    owners = [owner for owner in list(charge.owner_snapshot or []) if owner.get("person_id")]
    repasse_days = int(terms.get("owner_repasse_business_days") or 0)
    repasse_due = business_days_after(paid_at.date(), repasse_days)
    allocated = Decimal("0.00")
    for index, owner in enumerate(owners):
        percent = Decimal(str(owner.get("ownership_percent") or 0))
        if index == len(owners) - 1:
            amount = money(owner_entitlement - allocated)
        else:
            amount = money(owner_entitlement * percent / Decimal("100"))
            allocated += amount
        repasse = OwnerRepasse(
            organization_id=charge.organization_id,
            settlement_id=settlement.id,
            charge_id=charge.id,
            lease_contract_id=charge.lease_contract_id,
            property_id=charge.property_id,
            owner_person_id=UUID(str(owner["person_id"])),
            owner_name=str(owner.get("name") or "Proprietário"),
            ownership_percent=percent,
            amount=amount,
            due_date=repasse_due,
            status="pending" if amount > 0 else "settled_zero",
        )
        db.add(repasse)
    db.flush()
    return settlement


def record_payment(
    db: Session,
    *,
    charge: RentCharge,
    paid_amount: Decimal,
    paid_at: datetime | None,
    payment_method: str,
    payment_reference: str | None,
    notes: str | None,
) -> FinancialSettlement:
    if charge.status in {"paid", "cancelled"}:
        raise ValueError("Esta cobrança não está disponível para recebimento.")
    paid_amount = money(paid_amount)
    if paid_amount != money(charge.gross_amount):
        raise ValueError("Pagamento parcial não é permitido. Informe exatamente o valor integral da cobrança.")
    paid_at = paid_at or datetime.now(timezone.utc)
    charge.status = "paid"
    charge.paid_amount = paid_amount
    charge.paid_at = paid_at
    charge.payment_method = payment_method
    charge.payment_reference = (payment_reference or "").strip() or None
    charge.payment_notes = (notes or "").strip() or None
    return calculate_settlement(db, charge, paid_at)
