from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.leases.models import LeaseContract, LeaseContractVersion
from app.domains.leases.schemas import (
    LeaseContractCreate,
    LeaseContractResponse,
    LeaseContractUpdate,
    LeaseContractVersionResponse,
    LeaseContractWorkflow,
)
from app.domains.portfolio.models import Person, Property, PropertyOwner

router = APIRouter(tags=["leases"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _property(db: Session, organization_id: UUID, property_id: UUID) -> Property:
    item = db.scalar(
        select(Property)
        .options(selectinload(Property.owners).selectinload(PropertyOwner.person))
        .where(Property.id == property_id, Property.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Imóvel não encontrado.")
    if not item.owners:
        raise HTTPException(status_code=422, detail="Vincule proprietário(s) ao imóvel antes de criar a locação.")
    total = sum((owner.ownership_percent for owner in item.owners), Decimal("0"))
    if total != Decimal("100"):
        raise HTTPException(status_code=422, detail="A participação dos proprietários deve totalizar 100%.")
    return item


def _tenants(db: Session, organization_id: UUID, tenant_ids: list[UUID]) -> list[Person]:
    unique_ids = list(dict.fromkeys(tenant_ids))
    items = db.scalars(
        select(Person).where(Person.organization_id == organization_id, Person.id.in_(unique_ids), Person.is_active.is_(True))
    ).all()
    by_id = {item.id: item for item in items}
    missing = [tenant_id for tenant_id in unique_ids if tenant_id not in by_id]
    if missing:
        raise HTTPException(status_code=422, detail="Um ou mais locatários não foram encontrados ou estão inativos.")
    return [by_id[tenant_id] for tenant_id in unique_ids]


def _property_snapshot(item: Property) -> dict:
    return {
        "property_id": str(item.id),
        "code": f"{item.internal_number:06d}",
        "property_type": item.property_type,
        "purpose": item.purpose,
        "address": dict(item.address or {}),
        "rent_amount": str(item.rent_amount) if item.rent_amount is not None else None,
    }


def _owner_snapshot(item: Property) -> list[dict]:
    return [
        {
            "person_id": str(owner.person_id),
            "name": owner.person.name,
            "document_number": owner.person.document_number,
            "email": owner.person.email,
            "phone": owner.person.phone,
            "ownership_percent": str(owner.ownership_percent),
        }
        for owner in item.owners
    ]


def _tenant_snapshot(items: list[Person]) -> list[dict]:
    return [
        {
            "person_id": str(item.id),
            "name": item.name,
            "document_number": item.document_number,
            "email": item.email,
            "phone": item.phone,
        }
        for item in items
    ]


def _rules(payload: LeaseContractCreate | LeaseContractUpdate) -> dict:
    return payload.model_dump(mode="json", exclude={"property_id", "tenant_ids", "change_summary"})


def _apply(item: LeaseContract, payload: LeaseContractCreate | LeaseContractUpdate, tenants: list[Person]) -> None:
    item.rent_amount = payload.rent_amount
    item.due_day = payload.due_day
    item.adjustment_index = payload.adjustment_index
    item.adjustment_period_months = payload.adjustment_period_months
    item.adjustment_base_date = payload.adjustment_base_date
    item.next_adjustment_date = payload.next_adjustment_date
    item.term_months = payload.term_months
    item.start_date = payload.start_date
    item.end_date = payload.end_date
    item.termination_fine_months = payload.termination_fine_months
    item.inspection_contest_days = payload.inspection_contest_days
    item.guarantee_type = payload.guarantee_type
    item.guarantee_details = dict(payload.guarantee_details or {})
    item.tenant_snapshot = _tenant_snapshot(tenants)
    item.rules_snapshot = _rules(payload)
    item.notes = (payload.notes or "").strip() or None


def _snapshot(item: LeaseContract) -> dict:
    return {
        "property": item.property_snapshot,
        "owners": item.owner_snapshot,
        "tenants": item.tenant_snapshot,
        "rules": item.rules_snapshot,
    }


def _response(item: LeaseContract) -> LeaseContractResponse:
    property_snapshot = item.property_snapshot or {}
    return LeaseContractResponse(
        id=item.id,
        internal_number=item.internal_number,
        code=f"LOC-{item.internal_number:06d}",
        property_id=item.property_id,
        property_code=str(property_snapshot.get("code") or "—"),
        property_address=dict(property_snapshot.get("address") or {}),
        owners=list(item.owner_snapshot or []),
        tenants=list(item.tenant_snapshot or []),
        status=item.status,
        rent_amount=item.rent_amount,
        due_day=item.due_day,
        adjustment_index=item.adjustment_index,
        adjustment_period_months=item.adjustment_period_months,
        adjustment_base_date=item.adjustment_base_date,
        next_adjustment_date=item.next_adjustment_date,
        term_months=item.term_months,
        start_date=item.start_date,
        end_date=item.end_date,
        termination_fine_months=item.termination_fine_months,
        inspection_contest_days=item.inspection_contest_days,
        guarantee_type=item.guarantee_type,
        guarantee_details=dict(item.guarantee_details or {}),
        notes=item.notes,
        current_version=item.current_version,
        approved_at=item.approved_at,
        versions=[LeaseContractVersionResponse(version_number=v.version_number, change_summary=v.change_summary, created_at=v.created_at) for v in item.versions],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _load(db: Session, organization_id: UUID, contract_id: UUID) -> LeaseContract:
    item = db.scalar(
        select(LeaseContract)
        .options(selectinload(LeaseContract.versions))
        .where(LeaseContract.id == contract_id, LeaseContract.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Contrato de locação não encontrado.")
    return item


def _audit(db: Session, request: Request, context: UserContext, item: LeaseContract, action: str, *, before: dict | None = None, after: dict | None = None, reason: str | None = None) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="contracts",
        entity_type="lease_contract",
        entity_id=str(item.id),
        before_data=before,
        after_data=after,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.get("/lease-contracts", response_model=list[LeaseContractResponse])
def list_lease_contracts(
    contract_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> list[LeaseContractResponse]:
    stmt = (
        select(LeaseContract)
        .options(selectinload(LeaseContract.versions))
        .where(LeaseContract.organization_id == context.user.organization_id)
        .order_by(LeaseContract.internal_number.desc())
        .limit(300)
    )
    if contract_status:
        stmt = stmt.where(LeaseContract.status == contract_status)
    return [_response(item) for item in db.scalars(stmt).unique().all()]


@router.post("/lease-contracts", response_model=LeaseContractResponse, status_code=status.HTTP_201_CREATED)
def create_lease_contract(
    payload: LeaseContractCreate,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.create")),
    db: Session = Depends(get_db),
) -> LeaseContractResponse:
    property_item = _property(db, context.user.organization_id, payload.property_id)
    existing = db.scalar(
        select(LeaseContract.id).where(
            LeaseContract.organization_id == context.user.organization_id,
            LeaseContract.property_id == payload.property_id,
            LeaseContract.status.not_in(("cancelled",)),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Este imóvel já possui contrato de locação em andamento ou vigente.")
    tenant_items = _tenants(db, context.user.organization_id, payload.tenant_ids)
    item = LeaseContract(
        organization_id=context.user.organization_id,
        property_id=property_item.id,
        status="draft",
        property_snapshot=_property_snapshot(property_item),
        owner_snapshot=_owner_snapshot(property_item),
        current_version=1,
        created_by_user_id=context.user.id,
    )
    _apply(item, payload, tenant_items)
    db.add(item)
    db.flush()
    db.add(LeaseContractVersion(contract_id=item.id, version_number=1, snapshot=_snapshot(item), change_summary="Versão inicial", created_by_user_id=context.user.id))
    _audit(db, request, context, item, "contracts.lease.created", after={"code": f"LOC-{item.internal_number:06d}", "property_id": str(item.property_id), "adjustment_index": item.adjustment_index})
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.put("/lease-contracts/{contract_id}", response_model=LeaseContractResponse)
def update_lease_contract(
    contract_id: UUID,
    payload: LeaseContractUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> LeaseContractResponse:
    item = _load(db, context.user.organization_id, contract_id)
    if item.status not in {"draft", "review"}:
        raise HTTPException(status_code=409, detail="Somente locações em rascunho ou revisão podem gerar nova versão.")
    tenant_items = _tenants(db, context.user.organization_id, payload.tenant_ids)
    before = {"version": item.current_version, "status": item.status, "rules": item.rules_snapshot, "tenants": item.tenant_snapshot}
    _apply(item, payload, tenant_items)
    item.current_version += 1
    item.status = "draft"
    item.approved_at = None
    item.approved_by_user_id = None
    db.add(LeaseContractVersion(contract_id=item.id, version_number=item.current_version, snapshot=_snapshot(item), change_summary=payload.change_summary.strip(), created_by_user_id=context.user.id))
    _audit(db, request, context, item, "contracts.lease.version_created", before=before, after={"version": item.current_version, "status": item.status, "rules": item.rules_snapshot, "tenants": item.tenant_snapshot}, reason=payload.change_summary.strip())
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.post("/lease-contracts/{contract_id}/workflow", response_model=LeaseContractResponse)
def lease_contract_workflow(
    contract_id: UUID,
    payload: LeaseContractWorkflow,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> LeaseContractResponse:
    item = _load(db, context.user.organization_id, contract_id)
    before = {"status": item.status}
    if payload.action == "submit_review":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.edit")
        if item.status != "draft":
            raise HTTPException(status_code=409, detail="Somente rascunhos podem ir para revisão.")
        item.status = "review"
    elif payload.action == "approve":
        if not context.has("contracts.approve"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.approve")
        if item.status != "review":
            raise HTTPException(status_code=409, detail="Somente contratos em revisão podem ser aprovados.")
        item.status = "approved"
        item.approved_at = datetime.now(timezone.utc)
        item.approved_by_user_id = context.user.id
    elif payload.action == "return_draft":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.edit")
        if item.status not in {"review", "approved"}:
            raise HTTPException(status_code=409, detail="Este contrato não pode voltar para rascunho neste estado.")
        item.status = "draft"
        item.approved_at = None
        item.approved_by_user_id = None
    elif payload.action == "cancel":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.edit")
        if item.status in {"signed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Este contrato não pode ser cancelado por este fluxo.")
        if not (payload.reason or "").strip():
            raise HTTPException(status_code=422, detail="Informe o motivo do cancelamento.")
        item.status = "cancelled"
    else:
        raise HTTPException(status_code=422, detail="Ação inválida.")
    _audit(db, request, context, item, f"contracts.lease.{payload.action}", before=before, after={"status": item.status}, reason=(payload.reason or "").strip() or None)
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))
