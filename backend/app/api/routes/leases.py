import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.contracts.schemas import ContractDocumentResponse
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization, OrganizationSettings
from app.domains.leases.models import LeaseContract, LeaseContractVersion
from app.domains.leases.pdf import build_lease_contract_pdf, lease_contract_code
from app.domains.leases.schemas import (
    LeaseContractCreate,
    LeaseContractResponse,
    LeaseContractUpdate,
    LeaseContractVersionResponse,
    LeaseContractWorkflow,
)
from app.domains.portfolio.models import Person, Property, PropertyOwner
from app.integrations.document_storage import DocumentStorageError, get_document_storage
from app.integrations.signature import SignatureProviderError, get_signature_provider

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


def _default_signers(owner_snapshot: list[dict], tenant_snapshot: list[dict]) -> list[dict]:
    signers: list[dict] = []
    for role, parties in (("owner", owner_snapshot), ("tenant", tenant_snapshot)):
        for party in parties:
            signers.append(
                {
                    "role": role,
                    "name": party.get("name") or "",
                    "email": party.get("email") or "",
                    "document_number": party.get("document_number"),
                    "phone": party.get("phone"),
                    "sign_order": 1,
                    "communication": "email",
                }
            )
    return signers


def _rules(payload: LeaseContractCreate | LeaseContractUpdate) -> dict:
    return payload.model_dump(mode="json", exclude={"property_id", "tenant_ids", "change_summary", "signers"})


def _clear_signature_artifacts(item: LeaseContract) -> None:
    item.generated_document_reference = None
    item.generated_document_hash = None
    item.generated_document_version = None
    item.signing_envelope_id = None
    item.signing_document_id = None
    item.signing_metadata = {}
    item.signing_status = "not_prepared"
    item.archive_status = "not_started"
    item.archived_document_reference = None
    item.final_document_hash = None
    item.archived_at = None
    item.signed_at = None


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
    item.signers_snapshot = (
        [signer.model_dump(mode="json") for signer in payload.signers]
        if payload.signers
        else _default_signers(list(item.owner_snapshot or []), list(item.tenant_snapshot or []))
    )
    item.notes = (payload.notes or "").strip() or None


def _snapshot(item: LeaseContract) -> dict:
    return {
        "property": item.property_snapshot,
        "owners": item.owner_snapshot,
        "tenants": item.tenant_snapshot,
        "rules": item.rules_snapshot,
        "signers": item.signers_snapshot,
    }


def _response(item: LeaseContract) -> LeaseContractResponse:
    property_snapshot = item.property_snapshot or {}
    return LeaseContractResponse(
        id=item.id,
        internal_number=item.internal_number,
        code=lease_contract_code(item),
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
        signers=list(item.signers_snapshot or []),
        current_version=item.current_version,
        generated_document_reference=item.generated_document_reference,
        generated_document_hash=item.generated_document_hash,
        generated_document_version=item.generated_document_version,
        signing_provider=item.signing_provider,
        signing_status=item.signing_status,
        signing_envelope_id=item.signing_envelope_id,
        signing_document_id=item.signing_document_id,
        approved_at=item.approved_at,
        signed_at=item.signed_at,
        archive_status=item.archive_status,
        archived_document_reference=item.archived_document_reference,
        final_document_hash=item.final_document_hash,
        archived_at=item.archived_at,
        versions=[
            LeaseContractVersionResponse(
                version_number=v.version_number,
                change_summary=v.change_summary,
                created_at=v.created_at,
            )
            for v in item.versions
        ],
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


def _organization(db: Session, organization_id: UUID) -> Organization:
    item = db.get(Organization, organization_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Organização não encontrada.")
    return item


def _signature_provider_key(db: Session, organization_id: UUID) -> str:
    settings = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    integrations = (settings.integrations if settings else {}) or {}
    return str(integrations.get("signature_provider") or "clicksign")


def _pdf_for_current_version(db: Session, item: LeaseContract) -> tuple[bytes, str]:
    pdf = build_lease_contract_pdf(contract=item, organization=_organization(db, item.organization_id))
    return pdf, hashlib.sha256(pdf).hexdigest()


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    item: LeaseContract,
    action: str,
    *,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> None:
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


def _activate_property_after_signature(db: Session, item: LeaseContract, user_id: UUID | None = None) -> None:
    property_item = db.scalar(
        select(Property).where(Property.id == item.property_id, Property.organization_id == item.organization_id)
    )
    if property_item is None:
        return
    property_item.status = "leased"
    property_item.publication_enabled = False
    if user_id is not None:
        property_item.publication_updated_by_user_id = user_id


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
        signing_provider=_signature_provider_key(db, context.user.organization_id),
        signing_status="not_prepared",
        signing_metadata={},
        archive_status="not_started",
        current_version=1,
        created_by_user_id=context.user.id,
    )
    _apply(item, payload, tenant_items)
    db.add(item)
    db.flush()
    db.add(
        LeaseContractVersion(
            contract_id=item.id,
            version_number=1,
            snapshot=_snapshot(item),
            change_summary="Versão inicial",
            created_by_user_id=context.user.id,
        )
    )
    _audit(
        db,
        request,
        context,
        item,
        "contracts.lease.created",
        after={"code": lease_contract_code(item), "property_id": str(item.property_id), "adjustment_index": item.adjustment_index},
    )
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
    before = {
        "version": item.current_version,
        "status": item.status,
        "rules": item.rules_snapshot,
        "tenants": item.tenant_snapshot,
        "signers": item.signers_snapshot,
    }
    _apply(item, payload, tenant_items)
    item.current_version += 1
    item.status = "draft"
    item.approved_at = None
    item.approved_by_user_id = None
    _clear_signature_artifacts(item)
    db.add(
        LeaseContractVersion(
            contract_id=item.id,
            version_number=item.current_version,
            snapshot=_snapshot(item),
            change_summary=payload.change_summary.strip(),
            created_by_user_id=context.user.id,
        )
    )
    _audit(
        db,
        request,
        context,
        item,
        "contracts.lease.version_created",
        before=before,
        after={
            "version": item.current_version,
            "status": item.status,
            "rules": item.rules_snapshot,
            "tenants": item.tenant_snapshot,
            "signers": item.signers_snapshot,
        },
        reason=payload.change_summary.strip(),
    )
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
    before = {"status": item.status, "signing_status": item.signing_status, "signing_provider": item.signing_provider}
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
    elif payload.action == "prepare_signature":
        if not context.has("contracts.send_signature"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.send_signature")
        if item.status != "approved":
            raise HTTPException(status_code=409, detail="O contrato precisa estar aprovado antes da assinatura.")
        if not item.signers_snapshot:
            item.signers_snapshot = _default_signers(list(item.owner_snapshot or []), list(item.tenant_snapshot or []))
        missing_email = [str(signer.get("name") or "signatário") for signer in item.signers_snapshot if not str(signer.get("email") or "").strip()]
        if missing_email:
            raise HTTPException(
                status_code=422,
                detail="Complete o e-mail dos signatários antes da assinatura: " + ", ".join(missing_email),
            )
        provider = _signature_provider_key(db, context.user.organization_id)
        if provider == "none":
            raise HTTPException(status_code=422, detail="Configure um provedor de assinatura antes de continuar.")
        item.signing_provider = provider
        item.status = "pending_signature"
        item.signing_status = "ready_for_document"
    elif payload.action == "return_draft":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.edit")
        if item.status not in {"review", "approved", "pending_signature"}:
            raise HTTPException(status_code=409, detail="Este contrato não pode voltar para rascunho neste estado.")
        item.status = "draft"
        item.approved_at = None
        item.approved_by_user_id = None
        _clear_signature_artifacts(item)
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
    _audit(
        db,
        request,
        context,
        item,
        f"contracts.lease.{payload.action}",
        before=before,
        after={"status": item.status, "signing_status": item.signing_status, "signing_provider": item.signing_provider},
        reason=(payload.reason or "").strip() or None,
    )
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.get("/lease-contracts/{contract_id}/document/pdf")
def preview_lease_contract_pdf(
    contract_id: UUID,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> Response:
    item = _load(db, context.user.organization_id, contract_id)
    pdf, _ = _pdf_for_current_version(db, item)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{lease_contract_code(item)}-v{item.current_version}.pdf"'},
    )


@router.post("/lease-contracts/{contract_id}/document", response_model=ContractDocumentResponse)
def generate_lease_contract_document(
    contract_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.send_signature")),
    db: Session = Depends(get_db),
) -> ContractDocumentResponse:
    item = _load(db, context.user.organization_id, contract_id)
    if item.status not in {"approved", "pending_signature"}:
        raise HTTPException(status_code=409, detail="Aprove o contrato antes de gerar o PDF de assinatura.")
    pdf, digest = _pdf_for_current_version(db, item)
    storage = get_document_storage()
    reference = None
    if storage.configured:
        try:
            object_name = storage.object_name(
                organization_id=str(item.organization_id),
                contract_code=lease_contract_code(item),
                filename=f"{lease_contract_code(item)}-v{item.current_version}-original.pdf",
            )
            reference = storage.upload_bytes(object_name=object_name, content=pdf, content_type="application/pdf")
        except DocumentStorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    item.generated_document_reference = reference
    item.generated_document_hash = digest
    item.generated_document_version = item.current_version
    if item.status == "pending_signature":
        item.signing_status = "document_ready"
    _audit(
        db,
        request,
        context,
        item,
        "contracts.lease.document_generated",
        after={"version": item.current_version, "hash": digest, "reference": reference},
    )
    db.commit()
    return ContractDocumentResponse(
        contract_id=item.id,
        code=lease_contract_code(item),
        version=item.current_version,
        hash_sha256=digest,
        reference=reference,
        storage_configured=storage.configured,
        message="PDF versionado gerado e hash SHA-256 registrado."
        if reference
        else "PDF versionado gerado e hash registrado; storage ainda não configurado.",
    )


@router.post("/lease-contracts/{contract_id}/signature/send", response_model=LeaseContractResponse)
def send_lease_contract_to_signature(
    contract_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.send_signature")),
    db: Session = Depends(get_db),
) -> LeaseContractResponse:
    item = _load(db, context.user.organization_id, contract_id)
    if item.status != "pending_signature":
        raise HTTPException(status_code=409, detail="Prepare a assinatura antes de enviar o contrato ao provider.")
    if item.generated_document_version != item.current_version or not item.generated_document_hash:
        raise HTTPException(status_code=409, detail="Gere o PDF da versão atual antes de enviar para assinatura.")
    provider = get_signature_provider(item.signing_provider)
    if provider is None or not provider.configured:
        raise HTTPException(status_code=422, detail="Credencial do provider de assinatura ainda não está configurada.")
    pdf, digest = _pdf_for_current_version(db, item)
    if digest != item.generated_document_hash:
        raise HTTPException(status_code=409, detail="O PDF atual não corresponde ao hash registrado. Gere novamente antes de enviar.")
    try:
        envelope_id = item.signing_envelope_id or provider.create_empty_envelope(
            f"{lease_contract_code(item)} · Contrato de Locação"
        )
        item.signing_envelope_id = envelope_id
        document_id = item.signing_document_id or provider.upload_pdf(
            envelope_id,
            filename=f"{lease_contract_code(item)}-v{item.current_version}.pdf",
            content=pdf,
            metadata={
                "contract_id": str(item.id),
                "contract_type": "lease",
                "contract_code": lease_contract_code(item),
                "version": item.current_version,
                "sha256": digest,
            },
        )
        item.signing_document_id = document_id
        metadata = dict(item.signing_metadata or {})
        signer_ids = dict(metadata.get("signer_ids") or {})
        for signer in item.signers_snapshot or []:
            email = str(signer.get("email") or "").strip().lower()
            if not email:
                raise SignatureProviderError("Todos os signatários precisam possuir e-mail antes do envio.")
            signer_id = signer_ids.get(email)
            if not signer_id:
                signer_id = provider.create_signer(envelope_id, signer)
                signer_ids[email] = signer_id
                provider.create_signature_requirements(
                    envelope_id,
                    document_id=document_id,
                    signer_id=signer_id,
                    role=str(signer.get("role") or "tenant"),
                )
        metadata["signer_ids"] = signer_ids
        metadata["prepared_version"] = item.current_version
        metadata["prepared_hash"] = digest
        item.signing_metadata = metadata
        provider.activate_envelope(envelope_id)
    except SignatureProviderError as exc:
        item.signing_status = "provider_setup_failed"
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    item.signing_status = "provider_running"
    _audit(
        db,
        request,
        context,
        item,
        "contracts.lease.signature_sent",
        after={
            "provider": item.signing_provider,
            "envelope_id": item.signing_envelope_id,
            "document_id": item.signing_document_id,
            "hash": digest,
        },
    )
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.post("/lease-contracts/{contract_id}/signature/archive", response_model=LeaseContractResponse)
def archive_signed_lease_contract(
    contract_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.send_signature")),
    db: Session = Depends(get_db),
) -> LeaseContractResponse:
    item = _load(db, context.user.organization_id, contract_id)
    if not item.signing_envelope_id or not item.signing_document_id:
        raise HTTPException(status_code=409, detail="Contrato ainda não possui documento enviado para assinatura.")
    if item.signing_status not in {"provider_closed_pending_archive", "archive_failed"}:
        raise HTTPException(status_code=409, detail="O provider ainda não confirmou o fechamento do documento.")
    provider = get_signature_provider(item.signing_provider)
    storage = get_document_storage()
    if provider is None or not provider.configured:
        raise HTTPException(status_code=422, detail="Provider de assinatura não está configurado.")
    if not storage.configured:
        item.archive_status = "storage_not_configured"
        db.commit()
        raise HTTPException(status_code=422, detail="Configure o bucket próprio de documentos antes de concluir a assinatura.")
    item.archive_status = "archiving"
    db.commit()
    try:
        final_pdf = provider.signed_document_bytes(item.signing_envelope_id, item.signing_document_id)
        final_hash = hashlib.sha256(final_pdf).hexdigest()
        object_name = storage.object_name(
            organization_id=str(item.organization_id),
            contract_code=lease_contract_code(item),
            filename=f"{lease_contract_code(item)}-v{item.current_version}-ASSINADO.pdf",
        )
        reference = storage.upload_bytes(object_name=object_name, content=final_pdf, content_type="application/pdf")
    except (SignatureProviderError, DocumentStorageError) as exc:
        item.archive_status = "archive_failed"
        item.signing_status = "archive_failed"
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    item.archived_document_reference = reference
    item.final_document_hash = final_hash
    item.archived_at = now
    item.signed_at = now
    item.archive_status = "archived"
    item.signing_status = "signed_archived"
    item.status = "signed"
    _activate_property_after_signature(db, item, context.user.id)
    _audit(
        db,
        request,
        context,
        item,
        "contracts.lease.signed_archived",
        after={
            "reference": reference,
            "hash": final_hash,
            "signed_at": item.signed_at.isoformat(),
            "property_status": "leased",
            "publication_enabled": False,
        },
    )
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


def _stored_pdf_response(item: LeaseContract, reference: str | None, suffix: str) -> Response:
    if not reference:
        raise HTTPException(status_code=404, detail="Documento ainda não está arquivado no storage.")
    try:
        content = get_document_storage().download_bytes(reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{lease_contract_code(item)}-v{item.current_version}-{suffix}.pdf"'},
    )


@router.get("/lease-contracts/{contract_id}/document/original")
def download_lease_original(
    contract_id: UUID,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> Response:
    item = _load(db, context.user.organization_id, contract_id)
    return _stored_pdf_response(item, item.generated_document_reference, "original")


@router.get("/lease-contracts/{contract_id}/document/final")
def download_lease_final(
    contract_id: UUID,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> Response:
    item = _load(db, context.user.organization_id, contract_id)
    return _stored_pdf_response(item, item.archived_document_reference, "ASSINADO")
