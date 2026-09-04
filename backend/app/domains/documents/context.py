from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domains.contracts.models import AdministrationContract
from app.domains.documents.schemas import DocumentCatalogItem
from app.domains.documents.service import ENTITY_TYPES, catalog, resolve_entity_label
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest


def _snapshot_has_person(snapshot: object, person_id: UUID) -> bool:
    target = str(person_id)
    if not isinstance(snapshot, list):
        return False
    return any(isinstance(row, dict) and str(row.get("person_id") or "") == target for row in snapshot)


def _context_refs(db: Session, *, organization_id: UUID, entity_type: str, entity_id: UUID) -> set[tuple[str, UUID]]:
    if entity_type not in ENTITY_TYPES:
        return set()
    if resolve_entity_label(db, organization_id=organization_id, entity_type=entity_type, entity_id=entity_id) is None:
        return set()

    refs: set[tuple[str, UUID]] = {(entity_type, entity_id)}

    if entity_type == "property":
        administration = db.scalars(
            select(AdministrationContract.id).where(
                AdministrationContract.organization_id == organization_id,
                AdministrationContract.property_id == entity_id,
            )
        ).all()
        leases = db.scalars(
            select(LeaseContract.id).where(
                LeaseContract.organization_id == organization_id,
                LeaseContract.property_id == entity_id,
            )
        ).all()
        inspections = db.scalars(
            select(Inspection.id).where(
                Inspection.organization_id == organization_id,
                Inspection.property_id == entity_id,
            )
        ).all()
        maintenance = db.scalars(
            select(MaintenanceRequest.id).where(
                MaintenanceRequest.organization_id == organization_id,
                MaintenanceRequest.property_id == entity_id,
            )
        ).all()
        refs.update(("administration_contract", value) for value in administration)
        refs.update(("lease_contract", value) for value in leases)
        refs.update(("inspection", value) for value in inspections)
        refs.update(("maintenance", value) for value in maintenance)

    elif entity_type == "lease_contract":
        inspections = db.scalars(
            select(Inspection.id).where(
                Inspection.organization_id == organization_id,
                Inspection.lease_contract_id == entity_id,
            )
        ).all()
        maintenance = db.scalars(
            select(MaintenanceRequest.id).where(
                MaintenanceRequest.organization_id == organization_id,
                MaintenanceRequest.lease_contract_id == entity_id,
            )
        ).all()
        refs.update(("inspection", value) for value in inspections)
        refs.update(("maintenance", value) for value in maintenance)

    elif entity_type == "person":
        administration = db.scalars(
            select(AdministrationContract).where(AdministrationContract.organization_id == organization_id)
        ).all()
        leases = db.scalars(
            select(LeaseContract).where(LeaseContract.organization_id == organization_id)
        ).all()
        maintenance = db.scalars(
            select(MaintenanceRequest.id).where(
                MaintenanceRequest.organization_id == organization_id,
                or_(
                    MaintenanceRequest.requester_person_id == entity_id,
                    MaintenanceRequest.supplier_person_id == entity_id,
                ),
            )
        ).all()
        refs.update(
            ("administration_contract", item.id)
            for item in administration
            if _snapshot_has_person(item.owner_snapshot, entity_id)
        )
        refs.update(
            ("lease_contract", item.id)
            for item in leases
            if _snapshot_has_person(item.owner_snapshot, entity_id) or _snapshot_has_person(item.tenant_snapshot, entity_id)
        )
        refs.update(("maintenance", value) for value in maintenance)

    return refs


def context_catalog(
    db: Session,
    *,
    organization_id: UUID,
    entity_type: str,
    entity_id: UUID,
) -> list[DocumentCatalogItem] | None:
    refs = _context_refs(
        db,
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    if not refs:
        return None

    rows = catalog(db, organization_id=organization_id)
    filtered = [
        row
        for row in rows
        if row.entity_type and row.entity_id and (row.entity_type, row.entity_id) in refs
    ]
    filtered.sort(key=lambda row: row.updated_at or row.created_at, reverse=True)
    return filtered
