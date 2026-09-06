from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.documents import _content_response, _load as load_document, _system_reference
from app.api.routes.tenant_portal import PortalIdentity, require_portal_identity
from app.core.database import get_db
from app.domains.contracts.models import AdministrationContract
from app.domains.documents.context import context_catalog
from app.domains.finance.models import FinancialSettlement, OwnerRepasse, RentCharge
from app.domains.foundation.models import Organization
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.portfolio.models import Property, PropertyOwner
from app.integrations.document_storage import DocumentStorageError, get_document_storage

router = APIRouter(prefix="/owner-portal", tags=["owner-portal"])
context_router = APIRouter(prefix="/portal-context", tags=["portal-context"])
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
SAFE_DOCUMENT_TYPES = {"property", "administration_contract", "lease_contract", "inspection"}


class OwnerMaintenanceDecision(BaseModel):
    decision: str


def _money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _owner_links(db: Session, identity: PortalIdentity) -> list[PropertyOwner]:
    rows = db.scalars(
        select(PropertyOwner)
        .join(Property, Property.id == PropertyOwner.property_id)
        .where(
            PropertyOwner.person_id == identity.person.id,
            Property.organization_id == identity.account.organization_id,
        )
    ).all()
    return list(rows)


def _owner_properties(db: Session, identity: PortalIdentity) -> list[tuple[Property, PropertyOwner]]:
    links = _owner_links(db, identity)
    if not links:
        return []
    by_id = {
        item.id: item
        for item in db.scalars(
            select(Property).where(
                Property.organization_id == identity.account.organization_id,
                Property.id.in_([link.property_id for link in links]),
            )
        ).all()
    }
    result = [(by_id[link.property_id], link) for link in links if link.property_id in by_id]
    result.sort(key=lambda row: row[0].internal_number)
    return result


def _tenant_role(db: Session, identity: PortalIdentity) -> bool:
    leases = db.scalars(
        select(LeaseContract).where(LeaseContract.organization_id == identity.account.organization_id)
    ).all()
    person_id = str(identity.person.id)
    return any(
        any(
            isinstance(entry, dict) and str(entry.get("person_id") or "") == person_id
            for entry in list(lease.tenant_snapshot or [])
        )
        for lease in leases
    )


def _owner_role(db: Session, identity: PortalIdentity) -> bool:
    return bool(_owner_links(db, identity))


def _require_owner(db: Session, identity: PortalIdentity) -> list[tuple[Property, PropertyOwner]]:
    rows = _owner_properties(db, identity)
    if not rows:
        raise HTTPException(status_code=403, detail="Este acesso não possui imóveis vinculados como proprietário.")
    return rows


def _address(prop: Property) -> dict:
    return dict(prop.address or {})


def _property_payload(prop: Property, link: PropertyOwner, active_lease: LeaseContract | None) -> dict:
    return {
        "id": str(prop.id),
        "code": f"IMO-{prop.internal_number:06d}",
        "status": prop.status,
        "property_type": prop.property_type,
        "purpose": prop.purpose,
        "title": prop.public_title or f"Imóvel {prop.internal_number:06d}",
        "address": _address(prop),
        "rent_amount": float(prop.rent_amount) if prop.rent_amount is not None else None,
        "condo_amount": float(prop.condo_amount) if prop.condo_amount is not None else None,
        "iptu_amount": float(prop.iptu_amount) if prop.iptu_amount is not None else None,
        "ownership_percent": float(link.ownership_percent),
        "active_lease_id": str(active_lease.id) if active_lease else None,
        "active_lease_code": f"LOC-{active_lease.internal_number:06d}" if active_lease else None,
        "active_rent_amount": float(active_lease.rent_amount) if active_lease else None,
        "publication_enabled": prop.publication_enabled,
    }


def _tenant_names(lease: LeaseContract) -> list[str]:
    return [
        str(row.get("name") or "Locatário")
        for row in list(lease.tenant_snapshot or [])
        if isinstance(row, dict)
    ]


def _administration_payload(item: AdministrationContract) -> dict:
    return {
        "id": str(item.id),
        "code": f"ADM-{item.internal_number:06d}",
        "property_id": str(item.property_id),
        "status": item.status,
        "plan": item.plan,
        "admin_fee_type": item.admin_fee_type,
        "admin_fee_percent": float(item.admin_fee_percent) if item.admin_fee_percent is not None else None,
        "admin_fee_amount": float(item.admin_fee_amount) if item.admin_fee_amount is not None else None,
        "intermediation_percent": float(item.intermediation_percent),
        "owner_repasse_business_days": item.owner_repasse_business_days,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "signed_at": item.signed_at,
        "archive_status": item.archive_status,
    }


def _lease_payload(item: LeaseContract) -> dict:
    return {
        "id": str(item.id),
        "code": f"LOC-{item.internal_number:06d}",
        "property_id": str(item.property_id),
        "status": item.status,
        "tenant_names": _tenant_names(item),
        "rent_amount": float(item.rent_amount),
        "due_day": item.due_day,
        "start_date": item.start_date,
        "end_date": item.end_date,
        "operational_end_date": item.operational_end_date,
        "adjustment_index": item.adjustment_index,
        "next_adjustment_date": item.next_adjustment_date,
        "guarantee_type": item.guarantee_type,
        "signed_at": item.signed_at,
    }


def _safe_selected_quote(item: MaintenanceRequest) -> dict | None:
    if not item.selected_quote_id:
        return None
    return next(
        (dict(row) for row in list(item.quotes or []) if str(row.get("id") or "") == item.selected_quote_id),
        None,
    )


def _maintenance_payload(item: MaintenanceRequest) -> dict:
    selected = _safe_selected_quote(item)
    owner_charge = None
    if item.responsibility == "owner" and selected is not None:
        raw = selected.get("client_price_total")
        if raw is not None:
            owner_charge = float(_money(raw))
    return {
        "id": str(item.id),
        "code": f"MAN-{item.internal_number:06d}",
        "property_id": str(item.property_id),
        "lease_contract_id": str(item.lease_contract_id) if item.lease_contract_id else None,
        "title": item.title,
        "category": item.category,
        "priority": item.priority,
        "status": item.status,
        "description": item.description,
        "responsibility": item.responsibility,
        "approval_required": item.approval_required,
        "owner_charge_amount": owner_charge,
        "owner_decision_pending": bool(
            item.responsibility == "owner" and item.status == "awaiting_approval" and item.selected_quote_id
        ),
        "reported_at": item.reported_at,
        "scheduled_at": item.scheduled_at,
        "completed_at": item.completed_at,
    }


def _document_rows(db: Session, identity: PortalIdentity, properties: list[Property]) -> list[dict]:
    unique: dict[str, object] = {}
    for prop in properties:
        rows = context_catalog(
            db,
            organization_id=identity.account.organization_id,
            entity_type="property",
            entity_id=prop.id,
        ) or []
        for row in rows:
            if row.entity_type in SAFE_DOCUMENT_TYPES:
                unique[row.key] = row
    ordered = sorted(unique.values(), key=lambda row: row.updated_at or row.created_at, reverse=True)
    return [
        {
            "key": row.key,
            "title": row.title,
            "category": row.category,
            "filename": row.filename,
            "content_type": row.content_type,
            "status": row.status,
            "entity_type": row.entity_type,
            "entity_label": row.entity_label,
            "updated_at": row.updated_at,
            "download_path": f"/owner-portal/documents/{row.key}/content",
        }
        for row in ordered
    ]


def _allowed_document_keys(db: Session, identity: PortalIdentity) -> set[str]:
    props = [row[0] for row in _owner_properties(db, identity)]
    return {row["key"] for row in _document_rows(db, identity, props)}


def _repasse_payload(
    repasse: OwnerRepasse,
    charge: RentCharge | None,
    settlement: FinancialSettlement | None,
) -> dict:
    pct = _money(repasse.ownership_percent) / Decimal("100")
    rent_share = _money(charge.rent_amount if charge else 0) * pct
    admin_fee = _money(settlement.admin_fee_calculated if settlement else 0) * pct
    intermediation = _money(settlement.intermediation_fee_calculated if settlement else 0) * pct
    agency_fee = _money(settlement.agency_fee_withheld if settlement else 0) * pct
    amount = _money(repasse.amount)
    other_adjustments = (rent_share - agency_fee - amount).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "id": str(repasse.id),
        "charge_id": str(repasse.charge_id),
        "lease_contract_id": str(repasse.lease_contract_id),
        "property_id": str(repasse.property_id),
        "competence": charge.competence if charge else None,
        "rent_amount": float(charge.rent_amount) if charge else 0.0,
        "owner_rent_share": float(rent_share),
        "ownership_percent": float(repasse.ownership_percent),
        "admin_fee": float(admin_fee),
        "intermediation_fee": float(intermediation),
        "agency_fee_withheld": float(agency_fee),
        "other_adjustments": float(other_adjustments),
        "amount": float(amount),
        "due_date": repasse.due_date,
        "status": repasse.status,
        "paid_at": repasse.paid_at,
        "payment_reference": repasse.payment_reference,
    }


@context_router.get("")
def portal_context(
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> dict:
    roles: list[str] = []
    if _tenant_role(db, identity):
        roles.append("tenant")
    if _owner_role(db, identity):
        roles.append("owner")
    return {
        "person_id": str(identity.person.id),
        "person_name": identity.person.name,
        "roles": roles,
    }


@router.get("/overview")
def owner_overview(
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> dict:
    owner_rows = _require_owner(db, identity)
    properties = [row[0] for row in owner_rows]
    property_ids = [item.id for item in properties]
    owner_link_by_property = {row[0].id: row[1] for row in owner_rows}

    leases = list(db.scalars(
        select(LeaseContract)
        .where(
            LeaseContract.organization_id == identity.account.organization_id,
            LeaseContract.property_id.in_(property_ids),
        )
        .order_by(LeaseContract.start_date.desc())
    ).all())
    active_by_property: dict[UUID, LeaseContract] = {}
    for lease in leases:
        if lease.status == "signed" and lease.property_id not in active_by_property:
            active_by_property[lease.property_id] = lease

    administration = list(db.scalars(
        select(AdministrationContract)
        .where(
            AdministrationContract.organization_id == identity.account.organization_id,
            AdministrationContract.property_id.in_(property_ids),
        )
        .order_by(AdministrationContract.created_at.desc())
    ).all())

    repasses = list(db.scalars(
        select(OwnerRepasse)
        .where(
            OwnerRepasse.organization_id == identity.account.organization_id,
            OwnerRepasse.owner_person_id == identity.person.id,
            OwnerRepasse.property_id.in_(property_ids),
        )
        .order_by(OwnerRepasse.due_date.desc())
        .limit(500)
    ).all())
    charge_ids = list({item.charge_id for item in repasses})
    settlement_ids = list({item.settlement_id for item in repasses})
    charges = {
        item.id: item
        for item in db.scalars(select(RentCharge).where(RentCharge.id.in_(charge_ids))).all()
    } if charge_ids else {}
    settlements = {
        item.id: item
        for item in db.scalars(select(FinancialSettlement).where(FinancialSettlement.id.in_(settlement_ids))).all()
    } if settlement_ids else {}
    repasse_rows = [_repasse_payload(item, charges.get(item.charge_id), settlements.get(item.settlement_id)) for item in repasses]

    inspections = list(db.scalars(
        select(Inspection)
        .where(
            Inspection.organization_id == identity.account.organization_id,
            Inspection.property_id.in_(property_ids),
        )
        .order_by(Inspection.created_at.desc())
    ).all())
    maintenance = list(db.scalars(
        select(MaintenanceRequest)
        .where(
            MaintenanceRequest.organization_id == identity.account.organization_id,
            MaintenanceRequest.property_id.in_(property_ids),
        )
        .order_by(MaintenanceRequest.reported_at.desc())
        .limit(200)
    ).all())

    today = date.today()
    year_paid = sum(
        _money(item.amount)
        for item in repasses
        if item.status in {"paid", "settled"} and item.paid_at and item.paid_at.year == today.year
    )
    pending_amount = sum(
        (_money(item.amount) for item in repasses if item.status not in {"paid", "settled", "settled_zero", "cancelled"}),
        ZERO,
    )
    pending_repasses = sorted(
        [item for item in repasses if item.status not in {"paid", "settled", "settled_zero", "cancelled"}],
        key=lambda row: row.due_date,
    )
    next_repasse = pending_repasses[0] if pending_repasses else None

    years = sorted(
        {charges[item.charge_id].competence.year for item in repasses if item.charge_id in charges},
        reverse=True,
    )
    annual_reports = []
    for year in years:
        rows = [
            item for item in repasses
            if item.charge_id in charges and charges[item.charge_id].competence.year == year
        ]
        annual_reports.append({
            "year": year,
            "received_amount": float(sum((_money(item.amount) for item in rows if item.status in {"paid", "settled"}), ZERO)),
            "scheduled_amount": float(sum((_money(item.amount) for item in rows), ZERO)),
            "repasses": len(rows),
            "properties": len({item.property_id for item in rows}),
        })

    organization = db.get(Organization, identity.account.organization_id)
    return {
        "person": {
            "id": str(identity.person.id),
            "name": identity.person.name,
            "email": identity.account.email,
            "document_number": identity.person.document_number,
        },
        "organization": {
            "name": organization.display_name if organization else "Imobiliária",
            "email": organization.contact_email if organization else None,
            "phone": organization.contact_phone if organization else None,
        },
        "metrics": {
            "properties": len(properties),
            "active_leases": sum(1 for item in leases if item.status == "signed"),
            "pending_repasse_amount": float(pending_amount),
            "received_this_year": float(year_paid),
            "maintenance_open": sum(1 for item in maintenance if item.status not in {"completed", "cancelled"}),
            "next_repasse_date": next_repasse.due_date if next_repasse else None,
            "next_repasse_amount": float(next_repasse.amount) if next_repasse else None,
        },
        "properties": [
            _property_payload(item, owner_link_by_property[item.id], active_by_property.get(item.id))
            for item in properties
        ],
        "administration_contracts": [_administration_payload(item) for item in administration],
        "leases": [_lease_payload(item) for item in leases],
        "repasses": repasse_rows,
        "documents": _document_rows(db, identity, properties),
        "inspections": [
            {
                "id": str(item.id),
                "code": f"VIS-{item.internal_number:06d}",
                "property_id": str(item.property_id),
                "lease_contract_id": str(item.lease_contract_id),
                "inspection_type": item.inspection_type,
                "status": item.status,
                "scheduled_at": item.scheduled_at,
                "performed_at": item.performed_at,
                "finalized_at": item.finalized_at,
                "report_available": bool(item.report_reference),
            }
            for item in inspections
        ],
        "maintenance": [_maintenance_payload(item) for item in maintenance],
        "annual_reports": annual_reports,
    }


@router.post("/maintenance/{maintenance_id}/decision")
def owner_maintenance_decision(
    maintenance_id: UUID,
    payload: OwnerMaintenanceDecision,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> dict:
    owner_rows = _require_owner(db, identity)
    property_ids = {row[0].id for row in owner_rows}
    item = db.scalar(select(MaintenanceRequest).where(
        MaintenanceRequest.id == maintenance_id,
        MaintenanceRequest.organization_id == identity.account.organization_id,
    ))
    if item is None or item.property_id not in property_ids:
        raise HTTPException(status_code=404, detail="Chamado não encontrado neste portal.")
    if item.responsibility != "owner" or item.status != "awaiting_approval" or not item.selected_quote_id:
        raise HTTPException(status_code=409, detail="Este chamado não está aguardando decisão do proprietário.")
    decision = payload.decision.strip().lower()
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=422, detail="Decisão inválida.")
    quotes = deepcopy(list(item.quotes or []))
    selected = next((row for row in quotes if str(row.get("id") or "") == item.selected_quote_id), None)
    if selected is None:
        raise HTTPException(status_code=409, detail="O orçamento selecionado não foi encontrado.")
    now = datetime.now(timezone.utc)
    history = list(item.history or [])
    if decision == "approve":
        selected["status"] = "approved"
        item.status = "approved"
        item.approved_at = now
        event = "Orçamento aprovado pelo proprietário"
    else:
        selected["status"] = "rejected"
        item.selected_quote_id = None
        item.status = "awaiting_quote"
        event = "Orçamento recusado pelo proprietário"
    history.append({
        "event": event,
        "detail": "Decisão registrada pelo Portal do Proprietário.",
        "at": now.isoformat(),
        "source": "owner_portal",
        "person_id": str(identity.person.id),
    })
    item.history = history
    item.quotes = quotes
    db.commit()
    db.refresh(item)
    return _maintenance_payload(item)


@router.get("/documents/{document_key}/content")
def owner_document_content(
    document_key: str,
    identity: PortalIdentity = Depends(require_portal_identity),
    db: Session = Depends(get_db),
) -> Response:
    if document_key not in _allowed_document_keys(db, identity):
        raise HTTPException(status_code=404, detail="Documento não encontrado neste portal.")
    parts = document_key.split(":")
    if len(parts) == 2 and parts[0] == "managed":
        document_id = UUID(parts[1])
        item = load_document(db, identity.account.organization_id, document_id)
        version = next((row for row in item.versions if row.version_number == item.current_version), None)
        if version is None:
            raise HTTPException(status_code=404, detail="Versão do documento não encontrada.")
        try:
            content = get_document_storage().download_bytes(version.storage_reference)
        except DocumentStorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _content_response(content, content_type=version.content_type, filename=version.original_filename)
    if len(parts) == 4 and parts[0] == "system":
        entity_type, entity_id_raw, variant = parts[1], parts[2], parts[3]
        if entity_type not in SAFE_DOCUMENT_TYPES:
            raise HTTPException(status_code=404, detail="Documento não encontrado neste portal.")
        reference, filename = _system_reference(
            db,
            identity.account.organization_id,
            entity_type,
            UUID(entity_id_raw),
            variant,
        )
        try:
            content = get_document_storage().download_bytes(reference)
        except DocumentStorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _content_response(content, content_type="application/pdf", filename=filename)
    raise HTTPException(status_code=422, detail="Identificador de documento inválido.")
