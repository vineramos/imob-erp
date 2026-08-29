import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.contracts.models import AdministrationContract, AdministrationContractVersion
from app.domains.contracts.pdf import build_administration_contract_pdf, contract_code
from app.domains.contracts.schemas import (
    AdministrationContractCreate,
    AdministrationContractResponse,
    AdministrationContractUpdate,
    AdministrationContractVersionResponse,
    AdministrationContractWorkflow,
    ContractDocumentResponse,
)
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization, OrganizationSettings
from app.domains.portfolio.models import Property, PropertyOwner
from app.integrations.document_storage import DocumentStorageError, get_document_storage
from app.integrations.signature import SignatureProviderError, get_signature_provider

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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Vincule ao menos um proprietário ao imóvel antes de criar o contrato de administração.")
    total = sum((owner.ownership_percent for owner in item.owners), Decimal("0"))
    if total != Decimal("100"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A participação dos proprietários do imóvel deve totalizar 100%.")
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
            "email": owner.person.email,
            "phone": owner.person.phone,
            "ownership_percent": str(owner.ownership_percent),
        }
        for owner in item.owners
    ]


def _default_signers_from_owners(item: Property) -> list[dict]:
    return [
        {
            "role": "owner",
            "name": owner.person.name,
            "email": owner.person.email,
            "document_number": owner.person.document_number,
            "phone": owner.person.phone,
            "sign_order": 1,
            "communication": "email",
        }
        for owner in item.owners
        if owner.person.email
    ]


def _rules_from_payload(payload: AdministrationContractCreate | AdministrationContractUpdate) -> dict:
    return payload.model_dump(mode="json", exclude={"property_id", "change_summary", "signers"})


def _signers_from_payload(payload: AdministrationContractCreate | AdministrationContractUpdate) -> list[dict]:
    return [signer.model_dump(mode="json") for signer in payload.signers]


def _clear_signature_artifacts(contract: AdministrationContract) -> None:
    contract.generated_document_reference = None
    contract.generated_document_hash = None
    contract.generated_document_version = None
    contract.signing_envelope_id = None
    contract.signing_document_id = None
    contract.signing_metadata = {}
    contract.signing_status = "not_prepared"
    contract.archive_status = "not_started"
    contract.archived_document_reference = None
    contract.final_document_hash = None
    contract.archived_at = None
    contract.signed_at = None


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
    contract.signers_snapshot = _signers_from_payload(payload)


def _version_snapshot(contract: AdministrationContract) -> dict:
    return {
        "property": contract.property_snapshot,
        "owners": contract.owner_snapshot,
        "rules": contract.rules_snapshot,
        "signers": contract.signers_snapshot,
    }


def _contract_response(contract: AdministrationContract) -> AdministrationContractResponse:
    property_snapshot = contract.property_snapshot or {}
    return AdministrationContractResponse(
        id=contract.id,
        internal_number=contract.internal_number,
        code=contract_code(contract),
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
        signers=list(contract.signers_snapshot or []),
        current_version=contract.current_version,
        generated_document_reference=contract.generated_document_reference,
        generated_document_hash=contract.generated_document_hash,
        generated_document_version=contract.generated_document_version,
        signing_provider=contract.signing_provider,
        signing_status=contract.signing_status,
        signing_envelope_id=contract.signing_envelope_id,
        signing_document_id=contract.signing_document_id,
        approved_at=contract.approved_at,
        signed_at=contract.signed_at,
        archive_status=contract.archive_status,
        archived_document_reference=contract.archived_document_reference,
        final_document_hash=contract.final_document_hash,
        archived_at=contract.archived_at,
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
        .where(AdministrationContract.id == contract_id, AdministrationContract.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato de administração não encontrado.")
    return item


def _organization(db: Session, organization_id: UUID) -> Organization:
    item = db.get(Organization, organization_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organização não encontrada.")
    return item


def _signature_provider_key(db: Session, organization_id: UUID) -> str:
    settings = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    integrations = (settings.integrations if settings else {}) or {}
    return str(integrations.get("signature_provider") or "clicksign")


def _pdf_for_current_version(db: Session, item: AdministrationContract) -> tuple[bytes, str]:
    pdf = build_administration_contract_pdf(contract=item, organization=_organization(db, item.organization_id))
    return pdf, hashlib.sha256(pdf).hexdigest()


def _audit(db: Session, request: Request, context: UserContext, item: AdministrationContract, action: str, *, before: dict | None = None, after: dict | None = None, reason: str | None = None) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="contracts",
        entity_type="administration_contract",
        entity_id=str(item.id),
        before_data=before,
        after_data=after,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este imóvel já possui um contrato de administração em andamento ou vigente.")
    item = AdministrationContract(
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
    _apply_terms(item, payload)
    if not item.signers_snapshot:
        item.signers_snapshot = _default_signers_from_owners(property_item)
    db.add(item)
    db.flush()
    db.add(AdministrationContractVersion(contract_id=item.id, version_number=1, snapshot=_version_snapshot(item), change_summary="Versão inicial", created_by_user_id=context.user.id))
    _audit(db, request, context, item, "contracts.administration.created", after={"code": contract_code(item), "property_id": str(item.property_id), "status": item.status})
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Somente contratos em rascunho ou revisão podem gerar uma nova versão.")
    before = {"status": item.status, "current_version": item.current_version, "rules": item.rules_snapshot, "signers": item.signers_snapshot}
    _apply_terms(item, payload)
    item.current_version += 1
    item.status = "draft"
    item.approved_at = None
    item.approved_by_user_id = None
    _clear_signature_artifacts(item)
    db.add(AdministrationContractVersion(contract_id=item.id, version_number=item.current_version, snapshot=_version_snapshot(item), change_summary=payload.change_summary.strip(), created_by_user_id=context.user.id))
    _audit(db, request, context, item, "contracts.administration.version_created", before=before, after={"status": item.status, "current_version": item.current_version, "rules": item.rules_snapshot, "signers": item.signers_snapshot}, reason=payload.change_summary.strip())
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
    before = {"status": item.status, "signing_status": item.signing_status, "signing_provider": item.signing_provider}
    action = payload.action
    if action == "submit_review":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.edit")
        if item.status != "draft":
            raise HTTPException(status_code=409, detail="Somente rascunhos podem ser enviados para revisão.")
        item.status = "review"
    elif action == "approve":
        if not context.has("contracts.approve"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.approve")
        if item.status != "review":
            raise HTTPException(status_code=409, detail="Somente contratos em revisão podem ser aprovados.")
        item.status = "approved"
        item.approved_at = datetime.now(timezone.utc)
        item.approved_by_user_id = context.user.id
    elif action == "prepare_signature":
        if not context.has("contracts.send_signature"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.send_signature")
        if item.status != "approved":
            raise HTTPException(status_code=409, detail="O contrato precisa estar aprovado antes da assinatura.")
        if not item.signers_snapshot:
            raise HTTPException(status_code=422, detail="Inclua ao menos um signatário antes de preparar a assinatura.")
        provider = _signature_provider_key(db, context.user.organization_id)
        if provider == "none":
            raise HTTPException(status_code=422, detail="Configure um provedor de assinatura antes de continuar.")
        item.signing_provider = provider
        item.status = "pending_signature"
        item.signing_status = "ready_for_document"
    elif action == "return_draft":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.edit")
        if item.status not in {"review", "approved", "pending_signature"}:
            raise HTTPException(status_code=409, detail="Este contrato não pode retornar para rascunho neste estado.")
        item.status = "draft"
        item.approved_at = None
        item.approved_by_user_id = None
        _clear_signature_artifacts(item)
    elif action == "cancel":
        if not context.has("contracts.edit"):
            raise HTTPException(status_code=403, detail="Permissão necessária: contracts.edit")
        if item.status in {"signed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Este contrato não pode ser cancelado por este fluxo.")
        if not (payload.reason or "").strip():
            raise HTTPException(status_code=422, detail="Informe o motivo do cancelamento.")
        item.status = "cancelled"
    else:
        raise HTTPException(status_code=422, detail="Ação de contrato inválida.")
    _audit(db, request, context, item, f"contracts.administration.{action}", before=before, after={"status": item.status, "signing_status": item.signing_status, "signing_provider": item.signing_provider}, reason=(payload.reason or "").strip() or None)
    db.commit()
    return _contract_response(_load_contract(db, context.user.organization_id, item.id))


@router.get("/administration-contracts/{contract_id}/document/pdf")
def preview_contract_pdf(
    contract_id: UUID,
    context: UserContext = Depends(require_permission("contracts.view")),
    db: Session = Depends(get_db),
) -> Response:
    item = _load_contract(db, context.user.organization_id, contract_id)
    pdf, _ = _pdf_for_current_version(db, item)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{contract_code(item)}-v{item.current_version}.pdf"'})


@router.post("/administration-contracts/{contract_id}/document", response_model=ContractDocumentResponse)
def generate_contract_document(
    contract_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.send_signature")),
    db: Session = Depends(get_db),
) -> ContractDocumentResponse:
    item = _load_contract(db, context.user.organization_id, contract_id)
    if item.status not in {"approved", "pending_signature"}:
        raise HTTPException(status_code=409, detail="Aprove o contrato antes de gerar o PDF de assinatura.")
    pdf, digest = _pdf_for_current_version(db, item)
    storage = get_document_storage()
    reference = None
    if storage.configured:
        try:
            object_name = storage.object_name(organization_id=str(item.organization_id), contract_code=contract_code(item), filename=f"{contract_code(item)}-v{item.current_version}-original.pdf")
            reference = storage.upload_bytes(object_name=object_name, content=pdf, content_type="application/pdf")
        except DocumentStorageError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    item.generated_document_reference = reference
    item.generated_document_hash = digest
    item.generated_document_version = item.current_version
    if item.status == "pending_signature":
        item.signing_status = "document_ready"
    _audit(db, request, context, item, "contracts.administration.document_generated", after={"version": item.current_version, "hash": digest, "reference": reference})
    db.commit()
    return ContractDocumentResponse(contract_id=item.id, code=contract_code(item), version=item.current_version, hash_sha256=digest, reference=reference, storage_configured=storage.configured, message="PDF versionado gerado e hash SHA-256 registrado." if reference else "PDF versionado gerado e hash registrado; storage ainda não configurado.")


@router.post("/administration-contracts/{contract_id}/signature/send", response_model=AdministrationContractResponse)
def send_contract_to_signature(
    contract_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.send_signature")),
    db: Session = Depends(get_db),
) -> AdministrationContractResponse:
    item = _load_contract(db, context.user.organization_id, contract_id)
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
        envelope_id = item.signing_envelope_id or provider.create_empty_envelope(f"{contract_code(item)} · Contrato de Administração")
        item.signing_envelope_id = envelope_id
        document_id = item.signing_document_id or provider.upload_pdf(envelope_id, filename=f"{contract_code(item)}-v{item.current_version}.pdf", content=pdf, metadata={"contract_id": str(item.id), "contract_code": contract_code(item), "version": item.current_version, "sha256": digest})
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
                provider.create_signature_requirements(envelope_id, document_id=document_id, signer_id=signer_id, role=str(signer.get("role") or "owner"))
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
    _audit(db, request, context, item, "contracts.administration.signature_sent", after={"provider": item.signing_provider, "envelope_id": item.signing_envelope_id, "document_id": item.signing_document_id, "hash": digest})
    db.commit()
    return _contract_response(_load_contract(db, context.user.organization_id, item.id))


@router.post("/administration-contracts/{contract_id}/signature/archive", response_model=AdministrationContractResponse)
def archive_signed_contract(
    contract_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("contracts.send_signature")),
    db: Session = Depends(get_db),
) -> AdministrationContractResponse:
    item = _load_contract(db, context.user.organization_id, contract_id)
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
        object_name = storage.object_name(organization_id=str(item.organization_id), contract_code=contract_code(item), filename=f"{contract_code(item)}-v{item.current_version}-ASSINADO.pdf")
        reference = storage.upload_bytes(object_name=object_name, content=final_pdf, content_type="application/pdf")
    except (SignatureProviderError, DocumentStorageError) as exc:
        item.archive_status = "archive_failed"
        item.signing_status = "archive_failed"
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    item.archived_document_reference = reference
    item.final_document_hash = final_hash
    item.archived_at = datetime.now(timezone.utc)
    item.signed_at = item.archived_at
    item.archive_status = "archived"
    item.signing_status = "signed_archived"
    item.status = "signed"
    _audit(db, request, context, item, "contracts.administration.signed_archived", after={"reference": reference, "hash": final_hash, "signed_at": item.signed_at.isoformat()})
    db.commit()
    return _contract_response(_load_contract(db, context.user.organization_id, item.id))
