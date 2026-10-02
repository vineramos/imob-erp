"""repair first-rent intermediation settlements and owner repasses

Revision ID: 0053_repair_first_intermediation
Revises: 0052_company_representative
"""
from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from alembic import op
from sqlalchemy import text

revision = "0053_repair_first_intermediation"
down_revision = "0052_company_representative"
branch_labels = None
depends_on = None

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(text("""
        select
            fs.id as settlement_id,
            fs.organization_id,
            fs.charge_id,
            fs.lease_contract_id,
            fs.property_id,
            rc.rent_amount,
            rc.charge_items,
            rc.admin_terms_snapshot,
            rc.paid_at,
            (
                select min(or2.due_date)
                from owner_repasses or2
                where or2.settlement_id = fs.id
            ) as existing_due_date
        from financial_settlements fs
        join rent_charges rc on rc.id = fs.charge_id
        where fs.intermediation_fee_calculated = 0
          and coalesce((rc.admin_terms_snapshot->>'intermediation_percent')::numeric, 0) > 0
          and coalesce((rc.admin_terms_snapshot->>'intermediation_installments')::int, 1) = 1
          and rc.status = 'paid'
          and not exists (
              select 1
              from rent_charges prior
              where prior.lease_contract_id = rc.lease_contract_id
                and prior.status = 'paid'
                and prior.competence < rc.competence
          )
          and not exists (
              select 1
              from owner_repasses paid_repasse
              where paid_repasse.settlement_id = fs.id
                and paid_repasse.status = 'paid'
          )
    """)).mappings().all()

    for row in rows:
        terms = dict(row["admin_terms_snapshot"] or {})
        rent = money(row["rent_amount"])
        percent = Decimal(str(terms.get("intermediation_percent") or 0))
        installments = max(1, int(terms.get("intermediation_installments") or 1))
        intermediation = money(rent * percent / Decimal("100") / Decimal(installments))
        intermediation = min(rent, intermediation)

        if intermediation <= 0:
            continue

        if terms.get("admin_fee_type") == "fixed":
            admin_fee = money(terms.get("admin_fee_amount"))
        else:
            admin_fee = money(rent * Decimal(str(terms.get("admin_fee_percent") or 0)) / Decimal("100"))
        if intermediation >= rent:
            admin_fee = Decimal("0.00")

        agency_withheld = min(rent, money(intermediation + admin_fee))
        owner_reimbursements = sum(
            (
                money(item.get("amount"))
                for item in list(row["charge_items"] or [])
                if isinstance(item, dict)
                and item.get("key") != "rent"
                and item.get("beneficiary") == "owner"
            ),
            Decimal("0.00"),
        )
        owner_entitlement = money(max(Decimal("0.00"), rent - agency_withheld) + owner_reimbursements)

        owners = bind.execute(text("""
            select po.person_id, p.name, po.ownership_percent
            from property_owners po
            join persons p on p.id = po.person_id
            where po.property_id = :property_id
            order by p.name
        """), {"property_id": row["property_id"]}).mappings().all()

        if not owners:
            continue

        owner_snapshot = [
            {
                "person_id": str(owner["person_id"]),
                "name": owner["name"],
                "ownership_percent": str(owner["ownership_percent"]),
            }
            for owner in owners
        ]

        bind.execute(
            text("""
                update rent_charges
                set owner_snapshot = cast(:owner_snapshot as jsonb),
                    updated_at = now()
                where id = :charge_id
            """),
            {"owner_snapshot": __import__("json").dumps(owner_snapshot), "charge_id": row["charge_id"]},
        )

        bind.execute(
            text("""
                update financial_settlements
                set admin_fee_calculated = :admin_fee,
                    intermediation_fee_calculated = :intermediation,
                    agency_fee_withheld = :agency_withheld,
                    owner_entitlement_amount = :owner_entitlement
                where id = :settlement_id
            """),
            {
                "admin_fee": admin_fee,
                "intermediation": intermediation,
                "agency_withheld": agency_withheld,
                "owner_entitlement": owner_entitlement,
                "settlement_id": row["settlement_id"],
            },
        )

        bind.execute(text("delete from owner_repasses where settlement_id = :settlement_id"), {"settlement_id": row["settlement_id"]})

        due_date = row["existing_due_date"] or (row["paid_at"].date() if row["paid_at"] else None)
        allocated = Decimal("0.00")
        for index, owner in enumerate(owners):
            percent_owned = Decimal(str(owner["ownership_percent"]))
            if index == len(owners) - 1:
                amount = money(owner_entitlement - allocated)
            else:
                amount = money(owner_entitlement * percent_owned / Decimal("100"))
                allocated += amount
            bind.execute(
                text("""
                    insert into owner_repasses (
                        id, organization_id, settlement_id, charge_id, lease_contract_id, property_id,
                        owner_person_id, owner_name, ownership_percent, amount, due_date, status,
                        created_at, updated_at
                    ) values (
                        :id, :organization_id, :settlement_id, :charge_id, :lease_contract_id, :property_id,
                        :owner_person_id, :owner_name, :ownership_percent, :amount, :due_date, :status,
                        now(), now()
                    )
                """),
                {
                    "id": uuid.uuid4(),
                    "organization_id": row["organization_id"],
                    "settlement_id": row["settlement_id"],
                    "charge_id": row["charge_id"],
                    "lease_contract_id": row["lease_contract_id"],
                    "property_id": row["property_id"],
                    "owner_person_id": owner["person_id"],
                    "owner_name": owner["name"],
                    "ownership_percent": percent_owned,
                    "amount": amount,
                    "due_date": due_date,
                    "status": "pending" if amount > 0 else "settled_zero",
                },
            )


def downgrade() -> None:
    # Data repair: the previous inconsistent settlement cannot be reconstructed safely.
    pass
