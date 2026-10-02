from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.agenda.models import AgendaTask
from app.domains.contracts.models import AdministrationContract
from app.domains.finance.models import RentCharge
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenancePartner, MaintenanceRequest
from app.domains.portfolio.models import Person, Property

router = APIRouter(tags=["search"])


def _code(prefix: str, number: int | None) -> str:
    if number is None:
        return prefix.rstrip("-")
    return f"{prefix}{int(number):06d}"


def _address_label(address: dict[str, Any] | None) -> str:
    value = address or {}
    return ", ".join(
        str(part).strip()
        for part in (value.get("street"), value.get("number"), value.get("neighborhood"), value.get("city"))
        if str(part or "").strip()
    ) or "Endereço não informado"


def _money(value: Decimal | int | float | None) -> str:
    if value is None:
        return ""
    amount = float(value)
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _result(
    *,
    entity_id: Any,
    kind: str,
    module: str,
    code: str,
    title: str,
    subtitle: str,
    route: str,
    meta: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(entity_id),
        "kind": kind,
        "module": module,
        "code": code,
        "title": title,
        "subtitle": subtitle,
        "route": route,
        "meta": meta,
    }


def _numeric_term(value: str) -> int | None:
    digits = "".join(character for character in value if character.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


@router.get("/search")
def global_search(
    q: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(24, ge=5, le=60),
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    term = q.strip()
    if len(term) < 2:
        return {"query": term, "results": []}

    pattern = f"%{term}%"
    numeric = _numeric_term(term)
    organization_id = context.user.organization_id
    per_group = max(4, min(10, limit // 3 or 4))
    results: list[dict[str, Any]] = []

    if context.has("properties.view"):
        people_conditions = [
            Person.name.ilike(pattern),
            Person.document_number.ilike(pattern),
            Person.email.ilike(pattern),
            Person.phone.ilike(pattern),
        ]
        people = db.scalars(
            select(Person)
            .where(Person.organization_id == organization_id, or_(*people_conditions))
            .order_by(Person.name)
            .limit(per_group)
        ).all()
        for person in people:
            roles = ", ".join(sorted(role.role_key for role in person.roles if role.is_active)) or "Pessoa"
            results.append(
                _result(
                    entity_id=person.id,
                    kind="person",
                    module="people",
                    code="PESSOA",
                    title=person.name,
                    subtitle=" · ".join(part for part in (person.document_number or "", person.email or "") if part) or roles,
                    route="/app/people",
                    meta=roles,
                )
            )

        property_conditions = [
            Property.public_title.ilike(pattern),
            Property.property_type.ilike(pattern),
            Property.status.ilike(pattern),
            cast(Property.address, String).ilike(pattern),
            cast(Property.internal_number, String).ilike(pattern),
        ]
        if numeric is not None:
            property_conditions.append(Property.internal_number == numeric)
        properties = db.scalars(
            select(Property)
            .where(Property.organization_id == organization_id, or_(*property_conditions))
            .order_by(Property.internal_number.desc())
            .limit(per_group)
        ).all()
        for property_item in properties:
            code = _code("", property_item.internal_number)
            results.append(
                _result(
                    entity_id=property_item.id,
                    kind="property",
                    module="properties",
                    code=code,
                    title=property_item.public_title or f"Imóvel {code}",
                    subtitle=_address_label(property_item.address),
                    route="/app/properties",
                    meta=property_item.status,
                )
            )

    if context.has("contracts.view"):
        admin_conditions = [
            cast(AdministrationContract.internal_number, String).ilike(pattern),
            AdministrationContract.status.ilike(pattern),
            cast(AdministrationContract.property_snapshot, String).ilike(pattern),
            cast(AdministrationContract.owner_snapshot, String).ilike(pattern),
        ]
        lease_conditions = [
            cast(LeaseContract.internal_number, String).ilike(pattern),
            LeaseContract.status.ilike(pattern),
            cast(LeaseContract.property_snapshot, String).ilike(pattern),
            cast(LeaseContract.tenant_snapshot, String).ilike(pattern),
            cast(LeaseContract.owner_snapshot, String).ilike(pattern),
        ]
        if numeric is not None:
            admin_conditions.append(AdministrationContract.internal_number == numeric)
            lease_conditions.append(LeaseContract.internal_number == numeric)

        admin_contracts = db.scalars(
            select(AdministrationContract)
            .where(AdministrationContract.organization_id == organization_id, or_(*admin_conditions))
            .order_by(AdministrationContract.internal_number.desc())
            .limit(per_group)
        ).all()
        for item in admin_contracts:
            code = _code("ADM-", item.internal_number)
            snapshot = item.property_snapshot or {}
            results.append(
                _result(
                    entity_id=item.id,
                    kind="administration_contract",
                    module="contracts",
                    code=code,
                    title=f"Contrato de administração {code}",
                    subtitle=_address_label(snapshot.get("address") if isinstance(snapshot, dict) else {}),
                    route="/app/contracts",
                    meta=item.status,
                )
            )

        lease_contracts = db.scalars(
            select(LeaseContract)
            .where(LeaseContract.organization_id == organization_id, or_(*lease_conditions))
            .order_by(LeaseContract.internal_number.desc())
            .limit(per_group)
        ).all()
        for item in lease_contracts:
            code = _code("LOC-", item.internal_number)
            tenants = ", ".join(str(row.get("name") or "") for row in (item.tenant_snapshot or []) if row.get("name"))
            snapshot = item.property_snapshot or {}
            address_part = _address_label(snapshot.get("address") if isinstance(snapshot, dict) else {}) if snapshot else ""
            subtitle = " · ".join(part for part in (tenants, address_part) if part)
            results.append(
                _result(
                    entity_id=item.id,
                    kind="lease_contract",
                    module="contracts",
                    code=code,
                    title=f"Contrato de locação {code}",
                    subtitle=subtitle or f"Vencimento {item.end_date.strftime('%d/%m/%Y')}",
                    route="/app/contracts",
                    meta=item.status,
                )
            )

    if context.has("inspections.view"):
        conditions = [
            cast(Inspection.internal_number, String).ilike(pattern),
            Inspection.inspector_name.ilike(pattern),
            Inspection.status.ilike(pattern),
            Inspection.notes.ilike(pattern),
            cast(Inspection.lease_snapshot, String).ilike(pattern),
        ]
        if numeric is not None:
            conditions.append(Inspection.internal_number == numeric)
        inspections = db.scalars(
            select(Inspection)
            .where(Inspection.organization_id == organization_id, or_(*conditions))
            .order_by(Inspection.internal_number.desc())
            .limit(per_group)
        ).all()
        for item in inspections:
            code = _code("VIS-", item.internal_number)
            results.append(
                _result(
                    entity_id=item.id,
                    kind="inspection",
                    module="inspections",
                    code=code,
                    title=f"Vistoria {code}",
                    subtitle=" · ".join(part for part in (item.inspector_name or "", item.inspection_type) if part),
                    route="/app/inspections",
                    meta=item.status,
                )
            )

    if context.has("maintenance.view"):
        request_conditions = [
            cast(MaintenanceRequest.internal_number, String).ilike(pattern),
            MaintenanceRequest.title.ilike(pattern),
            MaintenanceRequest.description.ilike(pattern),
            MaintenanceRequest.status.ilike(pattern),
            MaintenanceRequest.category.ilike(pattern),
            cast(MaintenanceRequest.services, String).ilike(pattern),
            cast(MaintenanceRequest.quotes, String).ilike(pattern),
        ]
        if numeric is not None:
            request_conditions.append(MaintenanceRequest.internal_number == numeric)
        requests = db.scalars(
            select(MaintenanceRequest)
            .where(MaintenanceRequest.organization_id == organization_id, or_(*request_conditions))
            .order_by(MaintenanceRequest.internal_number.desc())
            .limit(per_group)
        ).all()
        for item in requests:
            code = _code("MAN-", item.internal_number)
            results.append(
                _result(
                    entity_id=item.id,
                    kind="maintenance",
                    module="maintenance",
                    code=code,
                    title=item.title,
                    subtitle=f"{code} · {item.category}",
                    route="/app/maintenance",
                    meta=item.status,
                )
            )

        partner_conditions = [
            MaintenancePartner.name.ilike(pattern),
            MaintenancePartner.legal_name.ilike(pattern),
            MaintenancePartner.document_number.ilike(pattern),
            MaintenancePartner.contact_name.ilike(pattern),
            MaintenancePartner.email.ilike(pattern),
            MaintenancePartner.phone.ilike(pattern),
            cast(MaintenancePartner.specialties, String).ilike(pattern),
        ]
        partners = db.scalars(
            select(MaintenancePartner)
            .where(MaintenancePartner.organization_id == organization_id, or_(*partner_conditions))
            .order_by(MaintenancePartner.name)
            .limit(max(3, per_group // 2))
        ).all()
        for item in partners:
            results.append(
                _result(
                    entity_id=item.id,
                    kind="maintenance_partner",
                    module="maintenance",
                    code=_code("PAR-", item.internal_number),
                    title=item.name,
                    subtitle=item.document_number or ", ".join(item.specialties or []) or "Parceiro terceirizado",
                    route="/app/maintenance",
                    meta="Parceiro ativo" if item.is_active else "Parceiro inativo",
                )
            )

    if context.has("finance.view"):
        charge_conditions = [
            cast(RentCharge.internal_number, String).ilike(pattern),
            RentCharge.status.ilike(pattern),
            cast(RentCharge.tenant_snapshot, String).ilike(pattern),
            cast(RentCharge.property_snapshot, String).ilike(pattern),
            RentCharge.payment_reference.ilike(pattern),
        ]
        if numeric is not None:
            charge_conditions.append(RentCharge.internal_number == numeric)
        charges = db.scalars(
            select(RentCharge)
            .where(RentCharge.organization_id == organization_id, or_(*charge_conditions))
            .order_by(RentCharge.internal_number.desc())
            .limit(per_group)
        ).all()
        for item in charges:
            code = _code("COB-", item.internal_number)
            tenant_names = ", ".join(str(row.get("name") or "") for row in (item.tenant_snapshot or []) if row.get("name"))
            results.append(
                _result(
                    entity_id=item.id,
                    kind="charge",
                    module="finance",
                    code=code,
                    title=f"Cobrança {code}",
                    subtitle=" · ".join(part for part in (tenant_names, item.competence.strftime("%m/%Y"), _money(item.gross_amount)) if part),
                    route="/app/finance",
                    meta=item.status,
                )
            )

    if context.has("agenda.view"):
        task_conditions = [AgendaTask.title.ilike(pattern), AgendaTask.description.ilike(pattern), cast(AgendaTask.internal_number, String).ilike(pattern)]
        if numeric is not None:
            task_conditions.append(AgendaTask.internal_number == numeric)
        tasks = db.scalars(
            select(AgendaTask)
            .where(
                AgendaTask.organization_id == organization_id,
                AgendaTask.assigned_user_id == context.user.id,
                or_(*task_conditions),
            )
            .order_by(AgendaTask.starts_at.desc())
            .limit(per_group)
        ).all()
        for item in tasks:
            code = _code("TAR-", item.internal_number)
            starts_at: datetime = item.starts_at
            results.append(
                _result(
                    entity_id=item.id,
                    kind="agenda_task",
                    module="agenda",
                    code=code,
                    title=item.title,
                    subtitle=f"{starts_at.astimezone().strftime('%d/%m/%Y %H:%M')} · {item.priority}",
                    route="/app/agenda",
                    meta=item.status,
                )
            )

    return {"query": term, "results": results[:limit]}
