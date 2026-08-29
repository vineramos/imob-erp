from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.contracts.models import AdministrationContract, AdministrationContractVersion
from app.domains.contracts.schemas import (
    AdministrationContractCreate,
    AdministrationContractResponse,
    AdministrationContractUpdate,
    AdministrationContractVersionResponse,
    AdministrationContractWorkflow,
)
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import OrganizationSettings
from app.domains.portfolio.models import Property, PropertyOwner

router = APIRouter(tags=["contracts"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _property_for_contract(db: Session, organization_id: UUID, property_id: UUID) -> Property:
    item = db.scalar(
        select(Property)
        .options(selectinload(Property.owners).selectinload(PropertyOwner.person))
        .where(Property.id == property_id, Property.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imóvel não encontrado.")
    if not item.owners:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vincule ao menos um proprietário ao imóvel antes de criar o contrato de administração.",
        )
    total = sum((owner.ownership_percent for owner in item.owners), Decimal("0"))
    if total != Decimal("100"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A participação dos proprietários do imóvel deve totalizar 100%.",
        )
    return item


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
            "ownership_percent": str(owner.ownership_percent),
        }
        for owner in item.owners
    ]


def _rules_from_payload(payload: AdministrationContractCreate | AdministrationContractUpdate) -> dict:
    return payload.model_dump(mode="json", exclude={"property_id", "change_summary"})


def _apply_terms(contract: AdministrationContract, payload: AdministrationContractCreate | AdministrationContractUpdate) -> None:
    contract.plan = payload.plan
    contract.admin_fee_type = payload.admin_fee_type
    contract.admin_fee_percent = payload.admin_fee_percent if payload.admin_fee_type == "percent" else None
    contract.admin_fee_amount = payload.admin_fee_amount if payload.admin_fee_type == "fixed" else None
    contract.intermediation_percent = payload.intermediation_percent
    contract.intermediation_installments = payload.intermediation_installments
    contract.owner_repasse_business_days = payload.owner_repasse_business_days
    contract.condo_operational_payer = payload.condo_operational_payer
    contract.iptu_operational_payer = payload.iptu_operational_payer
    contract.publication_requires_owner_approval = payload.publication_requires_owner_approval
    contract.maintenance_limit_amount = payload.maintenance_limit_amount
    contract.emergency_limit_amount = payload.emergency_limit_amount
    contract.start_date = payload.start_date
    contract.end_date = payload.end_date
    contract.notes = (payload.notes or "").strip() or None
    contract.rules_snapshot = _rules_from_payload(payload)


def _version_snapshot(contract: AdministrationContract) -> dict:
    return {
        "property": contract.property_snapshot,
        "owners": contract.owner_snapshot,
        "rules": contract.rules_snapshot,
    }


def _contract_response(contract: AdministrationContract) -> AdministrationContractResponse:
    property_snapshot = contract.property_snapshot or {}
    return AdministrationContractResponse(
        id=contract.id,
        internal_number=contract.internal_number,
        code=f"ADM-{contract.internal_number:06d}",
        property_id=contract.property_id,
        property_code=str(property_snapshot.get("code") or "—"),
        property_address=dict(property_snapshot.get("address") or {}),
        owners=list(contract.owner_snapshot or []),
        status=contract.status,
        plan=contract.plan,
        admin_fee_type=contract.admin_fee_type,
        admin_fee_percent=contract.admin_fee_percent,
        admin_fee_amount=contract.admin_fee_amount,
        intermediation_percent=contract.intermediation_percent,
        intermediation_installments=contract.intermediation_installments,
        owner_repasse_business_days=contract.owner_repasse_business_days,
        condo_operational_payer=contract.condo_operational_payer,
        iptu_operational_payer=contract.iptu_operational_payer,
        publication_requires_owner_approval=contract.publication_requires_owner_approval,
        maintenance_limit_amount=contract.maintenance_limit_amount,
        emergency_limit_amount=contract.emergency_limit_amount,
        start_date=contract.start_date,
        end_date=contract.end_date,
        notes=contract.notes,
        current_version=contract.current_version,
        signing_provider=contract.signing_provider,
        signing_status=contract.signing_status,
        signing_envelope_id=contract.signing_envelope_id,
        approved_at=contract.approved_at,
        signed_at=contract.signed_at,
        archived_document_reference=contract.archived_document_reference,
        versions=[
            AdministrationContractVersionResponse(
                version_number=version.version_number,
                change_summary=version.change_summary,
                created_by_user_id=version.created_by_user_id,
                created_at=version.created_at,
            )
            for version in contract.versions
        ],
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


def _load_contract(db: Session, organization_id: UUID, contract_id: UUID) -> AdministrationContract:
    item = db.scalar(
        select(AdministrationContract)
        .options(selectinload(AdministrationContract.versions))
        .where(
            AdministrationContract.id == contract_id,
            AdministrationContract.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato de administração não encontrado.")
    return item


def _signature_provider(db: Session, organization_id: UUID) -> str:
    settings = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    integrations = (settings.integrations if settings else {}) or {}
    return str(integrations.get("signature_provider") or "clicksign")


@router.get("/administration-contracts", response_model=list[AdministrationContractResponse])
def list_administration_contracts(
    contract_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> list[AdministrationContractResponse]:
    stmt = (
        select(AdministrationContract)
        .options(selectinload(AdministrationContract.versions))
        .where(AdministrationContract.organization_id == context.user.organization_id)
        .order_by(AdministrationContract.internal_number.desc())
        .limit(200)
    )
    if contract_status:
        stmt = stmt.where(AdministrationContract.status == contract_status)
    return [_contract_response(item) for item in db.scalars(stmt).unique().all()]


@router.post("/administration-contracts", response_model=AdministrationContractResponse, status_code=status.HTTP_201_CREATED)
def create_administration_contract(
    payload: AdministrationContractCreate,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.create")),
    db: Session = Depends(get_db),
) -> AdministrationContractResponse:
    property_item = _property_for_contract(db, context.user.organization_id, payload.property_id)
    existing = db.scalar(
        select(AdministrationContract.id).where(
            AdministrationContract.organization_id == context.user.organization_id,
            AdministrationContract.property_id == payload.property_id,
            AdministrationContract.status.not_in(("cancelled",)),
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este imóvel já possui um contrato de administração em andamento ou vigente.",
        )

    item = AdministrationContract(
        organization_id=context.user.organization_id,
        property_id=property_item.id,
        status="draft",
        property_snapshot=_property_snapshot(property_item),
        owner_snapshot=_owner_snapshot(property_item),
        signing_provider=_signature_provider(db, context.user.organization_id),
        signing_status="not_prepared",
        current_version=1,
        created_by_user_id=context.user.id,
    )
    _apply_terms(item, payload)
    db.add(item)
    db.flush()
    db.add(
        AdministrationContractVersion(
            contract_id=item.id,
            version_number=1,
            snapshot=_version_snapshot(item),
            change_summary="Versão inicial",
            created_by_user_id=context.user.id,
        )
    )

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="contracts.administration.created",
        module="contracts",
        entity_type="administration_contract",
        entity_id=str(item.id),
        after_data={"code": f"ADM-{item.internal_number:06d}", "property_id": str(item.property_id), "status": item.status},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return _contract_response(_load_contract(db, context.user.organization_id, item.id))


@router.put("/administration-contracts/{contract_id}", response_model=AdministrationContractResponse)
def update_administration_contract(
    contract_id: UUID,
    payload: AdministrationContractUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.edit")),
    db: Session = Depends(get_db),
) -> AdministrationContractResponse:
    item = _load_contract(db, context.user.organization_id, contract_id)
    if item.status not in {"draft", "review"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Somente contratos em rascunho ou revisão podem gerar uma nova versão.",
        )

    before = {"status": item.status, "current_version": item.current_version, "rules": item.rules_snapshot}
    _apply_terms(item, payload)
    item.current_version += 1
    if item.status == "review":
        item.status = "draft"
    item.approved_at = None
    item.approved_by_user_id = None
    item.signing_status = "not_prepared"
    item.signing_envelope_id = None

    db.add(
        AdministrationContractVersion(
            contract_id=item.id,
            version_number=item.current_version,
            snapshot=_version_snapshot(item),
            change_summary=payload.change_summary.strip(),
            created_by_user_id=context.user.id,
        )
    )
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="contracts.administration.version_created",
        module="contracts",
        entity_type="administration_contract",
        entity_id=str(item.id),
        before_data=before,
        after_data={"status": item.status, "current_version": item.current_version, "rules": item.rules_snapshot},
        reason=payload.change_summary.strip(),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return _contract_response(_load_contract(db, context.user.organization_id, item.id))


@router.post("/administration-contracts/{contract_id}/workflow", response_model=AdministrationContractResponse)
def administration_contract_workflow(
    contract_id: UUID,
    payload: AdministrationContractWorkflow,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> AdministrationContractResponse:
    item = _load_contract(db, context.user.organization_id, contract_id)
    before_status = item.status
    before_signing_status = item.signing_status
    before_signing_provider = item.signing_provider
    action = payload.action

    if action == "submit_review":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissão necessária: contracts.edit")
        if item.status != "draft":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Somente rascunhos podem ser enviados para revisão.")
        item.status = "review"
    elif action == "approve":
        if not context.has("contracts.approve"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissão necessária: contracts.approve")
        if item.status != "review":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Somente contratos em revisão podem ser aprovados.")
        item.status = "approved"
        item.approved_at = datetime.now(timezone.utc)
        item.approved_by_user_id = context.user.id
    elif action == "prepare_signature":
        if not context.has("contracts.send_signature"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissão necessária: contracts.send_signature")
        if item.status != "approved":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="O contrato precisa estar aprovado antes da assinatura.")
        provider = _signature_provider(db, context.user.organization_id)
        if provider == "none":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Configure um provedor de assinatura antes de continuar.")
        item.signing_provider = provider
        item.status = "pending_signature"
        item.signing_status = "ready_for_provider"
    elif action == "return_draft":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissão necessária: contracts.edit")
        if item.status not in {"review", "approved", "pending_signature"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este contrato não pode retornar para rascunho neste estado.")
        item.status = "draft"
        item.approved_at = None
        item.approved_by_user_id = None
        item.signing_status = "not_prepared"
        item.signing_envelope_id = None
    elif action == "cancel":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissão necessária: contracts.edit")
        if item.status in {"signed", "cancelled"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este contrato não pode ser cancelado por este fluxo.")
        if not (payload.reason or "").strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe o motivo do cancelamento.")
        item.status = "cancelled"
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ação de contrato inválida.")

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=f"contracts.administration.{action}",
        module="contracts",
        entity_type="administration_contract",
        entity_id=str(item.id),
        before_data={"status": before_status, "signing_status": before_signing_status, "signing_provider": before_signing_provider},
        after_data={"status": item.status, "signing_status": item.signing_status, "signing_provider": item.signing_provider},
        reason=(payload.reason or "").strip() or None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return _contract_response(_load_contract(db, context.user.organization_id, item.id))
