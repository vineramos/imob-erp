import hashlib
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization
from app.domains.inspections.models import Inspection, InspectionVersion, KeyHandover
from app.domains.inspections.pdf import build_inspection_pdf, inspection_code
from app.domains.inspections.schemas import (
    InspectionContestationCreate, InspectionContestationResolve, InspectionCreate, InspectionResponse,
    InspectionUpdate, InspectionVersionResponse, InspectionWorkflow, KeyHandoverCreate, KeyHandoverResponse,
)
from app.domains.leases.models import LeaseContract
from app.domains.leases.pdf import lease_contract_code
from app.integrations.document_storage import DocumentStorageError, get_document_storage

router = APIRouter(tags=["inspections"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, item: Inspection, action: str, *, before=None, after=None, reason=None) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db, context=context, action=action, module="inspections", entity_type="inspection", entity_id=str(item.id),
        before_data=before, after_data=after, reason=reason, ip_address=ip_address, user_agent=user_agent,
    )


def _organization(db: Session, organization_id: UUID) -> Organization:
    item = db.get(Organization, organization_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Organização não encontrada.")
    return item


def _lease(db: Session, organization_id: UUID, lease_id: UUID) -> LeaseContract:
    item = db.scalar(select(LeaseContract).where(LeaseContract.id == lease_id, LeaseContract.organization_id == organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Contrato de locação não encontrado.")
    return item


def _lease_snapshot(lease: LeaseContract) -> dict:
    return {
        "lease_code": lease_contract_code(lease),
        "property": deepcopy(lease.property_snapshot or {}),
        "owners": deepcopy(lease.owner_snapshot or []),
        "tenants": deepcopy(lease.tenant_snapshot or []),
        "inspection_contest_days": lease.inspection_contest_days,
        "signed_at": lease.signed_at.isoformat() if lease.signed_at else None,
        "final_document_hash": lease.final_document_hash,
    }


def _snapshot(item: Inspection) -> dict:
    return {
        "status": item.status,
        "lease": deepcopy(item.lease_snapshot or {}),
        "environments": deepcopy(item.environments or []),
        "contestations": deepcopy(item.contestations or []),
        "inspector_name": item.inspector_name,
        "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
        "performed_at": item.performed_at.isoformat() if item.performed_at else None,
        "contest_deadline": item.contest_deadline.isoformat() if item.contest_deadline else None,
        "notes": item.notes,
    }


def _version(db: Session, item: Inspection, context: UserContext, summary: str) -> None:
    db.add(InspectionVersion(
        inspection_id=item.id, version_number=item.current_version, snapshot=_snapshot(item),
        change_summary=summary, created_by_user_id=context.user.id,
    ))


def _handover_response(item: KeyHandover | None) -> KeyHandoverResponse | None:
    if item is None:
        return None
    return KeyHandoverResponse(
        id=item.id, handed_over_at=item.handed_over_at, recipient_name=item.recipient_name,
        recipient_document=item.recipient_document, keys=list(item.keys or []), meter_readings=dict(item.meter_readings or {}),
        notes=item.notes, created_at=item.created_at,
    )


def _response(item: Inspection) -> InspectionResponse:
    lease = dict(item.lease_snapshot or {})
    prop = dict(lease.get("property") or {})
    return InspectionResponse(
        id=item.id, internal_number=item.internal_number, code=inspection_code(item), inspection_type=item.inspection_type,
        status=item.status, lease_contract_id=item.lease_contract_id, lease_code=str(lease.get("lease_code") or "—"),
        property_id=item.property_id, property_code=str(prop.get("code") or "—"), property_address=dict(prop.get("address") or {}),
        tenants=list(lease.get("tenants") or []), environments=list(item.environments or []), contestations=list(item.contestations or []),
        inspector_name=item.inspector_name, scheduled_at=item.scheduled_at, performed_at=item.performed_at,
        contest_deadline=item.contest_deadline, finalized_at=item.finalized_at, notes=item.notes, current_version=item.current_version,
        report_reference=item.report_reference, report_hash=item.report_hash, report_version=item.report_version,
        key_handover=_handover_response(item.key_handover),
        versions=[InspectionVersionResponse(version_number=v.version_number, change_summary=v.change_summary, created_at=v.created_at) for v in item.versions],
        created_at=item.created_at, updated_at=item.updated_at,
    )


def _load(db: Session, organization_id: UUID, inspection_id: UUID) -> Inspection:
    item = db.scalar(
        select(Inspection)
        .options(selectinload(Inspection.versions), selectinload(Inspection.key_handover))
        .execution_options(populate_existing=True)
        .where(Inspection.id == inspection_id, Inspection.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Vistoria não encontrada.")
    return item


def _pdf(db: Session, item: Inspection) -> tuple[bytes, str]:
    content = build_inspection_pdf(inspection=item, organization=_organization(db, item.organization_id))
    return content, hashlib.sha256(content).hexdigest()


def _archive_report(db: Session, item: Inspection, content: bytes, digest: str) -> None:
    storage = get_document_storage()
    item.report_hash = digest
    item.report_version = item.current_version
    item.report_reference = None
    if not storage.configured:
        return
    object_name = storage.inspection_object_name(
        organization_id=str(item.organization_id), inspection_code=inspection_code(item),
        filename=f"{inspection_code(item)}-v{item.current_version}.pdf",
    )
    item.report_reference = storage.upload_bytes(object_name=object_name, content=content, content_type="application/pdf")


@router.get("/inspections", response_model=list[InspectionResponse])
def list_inspections(
    context: UserContext = Depends(require_permission("inspections.view")), db: Session = Depends(get_db),
) -> list[InspectionResponse]:
    items = db.scalars(
        select(Inspection).options(selectinload(Inspection.versions), selectinload(Inspection.key_handover))
        .where(Inspection.organization_id == context.user.organization_id)
        .order_by(Inspection.internal_number.desc()).limit(300)
    ).unique().all()
    return [_response(item) for item in items]


@router.post("/inspections", response_model=InspectionResponse, status_code=status.HTTP_201_CREATED)
def create_inspection(
    payload: InspectionCreate, request: Request,
    context: UserContext = Depends(require_permission("inspections.manage")), db: Session = Depends(get_db),
) -> InspectionResponse:
    lease = _lease(db, context.user.organization_id, payload.lease_contract_id)
    if lease.status != "signed" or lease.archive_status != "archived" or not lease.final_document_hash:
        raise HTTPException(status_code=409, detail="A vistoria inicial só pode ser aberta após o contrato assinado estar arquivado no ERP.")
    existing = db.scalar(select(Inspection.id).where(Inspection.lease_contract_id == lease.id, Inspection.inspection_type == "initial"))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Este contrato já possui vistoria inicial.")
    item = Inspection(
        organization_id=context.user.organization_id, lease_contract_id=lease.id, property_id=lease.property_id,
        inspection_type="initial", status="draft", lease_snapshot=_lease_snapshot(lease),
        environments=[environment.model_dump(mode="json") for environment in payload.environments], contestations=[],
        inspector_name=(payload.inspector_name or "").strip() or None, scheduled_at=payload.scheduled_at,
        notes=(payload.notes or "").strip() or None, current_version=1, created_by_user_id=context.user.id,
    )
    db.add(item); db.flush(); _version(db, item, context, "Vistoria inicial criada")
    _audit(db, request, context, item, "inspections.created", after={"lease_contract_id": str(lease.id), "version": 1})
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.put("/inspections/{inspection_id}", response_model=InspectionResponse)
def update_inspection(
    inspection_id: UUID, payload: InspectionUpdate, request: Request,
    context: UserContext = Depends(require_permission("inspections.manage")), db: Session = Depends(get_db),
) -> InspectionResponse:
    item = _load(db, context.user.organization_id, inspection_id)
    if item.status != "draft":
        raise HTTPException(status_code=409, detail="Somente vistoria em rascunho pode ser editada diretamente.")
    before = {"version": item.current_version, "environments": item.environments}
    item.environments = [environment.model_dump(mode="json") for environment in payload.environments]
    item.inspector_name = (payload.inspector_name or "").strip() or None
    item.scheduled_at = payload.scheduled_at
    item.notes = (payload.notes or "").strip() or None
    item.current_version += 1
    item.report_reference = None; item.report_hash = None; item.report_version = None
    _version(db, item, context, payload.change_summary.strip())
    _audit(db, request, context, item, "inspections.version_created", before=before, after={"version": item.current_version}, reason=payload.change_summary.strip())
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.post("/inspections/{inspection_id}/workflow", response_model=InspectionResponse)
def inspection_workflow(
    inspection_id: UUID, payload: InspectionWorkflow, request: Request,
    context: UserContext = Depends(require_permission("inspections.manage")), db: Session = Depends(get_db),
) -> InspectionResponse:
    item = _load(db, context.user.organization_id, inspection_id)
    before = {"status": item.status, "version": item.current_version}
    now = datetime.now(timezone.utc)
    if payload.action == "complete":
        if item.status != "draft": raise HTTPException(status_code=409, detail="Apenas rascunhos podem ser concluídos.")
        item.status = "ready"; item.performed_at = now
        content, digest = _pdf(db, item)
        try: _archive_report(db, item, content, digest)
        except DocumentStorageError as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc
    elif payload.action == "return_draft":
        if item.status != "ready" or item.key_handover is not None:
            raise HTTPException(status_code=409, detail="Só é possível retornar para rascunho antes da entrega de chaves.")
        item.status = "draft"; item.performed_at = None; item.report_reference = None; item.report_hash = None; item.report_version = None
    elif payload.action == "finalize":
        if item.status != "ready" or item.key_handover is None:
            raise HTTPException(status_code=409, detail="Finalize após a entrega de chaves e sem contestação pendente.")
        if any(not entry.get("resolved_at") for entry in list(item.contestations or [])):
            raise HTTPException(status_code=409, detail="Existem contestações pendentes de resolução.")
        item.status = "finalized"; item.finalized_at = now; item.finalized_by_user_id = context.user.id
    elif payload.action == "cancel":
        if item.key_handover is not None: raise HTTPException(status_code=409, detail="Vistoria com chaves entregues não pode ser cancelada.")
        if not (payload.reason or "").strip(): raise HTTPException(status_code=422, detail="Informe o motivo do cancelamento.")
        item.status = "cancelled"
    else:
        raise HTTPException(status_code=422, detail="Ação inválida.")
    _audit(db, request, context, item, f"inspections.{payload.action}", before=before, after={"status": item.status, "report_hash": item.report_hash}, reason=payload.reason)
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.post("/inspections/{inspection_id}/contestations", response_model=InspectionResponse)
def create_contestation(
    inspection_id: UUID, payload: InspectionContestationCreate, request: Request,
    context: UserContext = Depends(require_permission("inspections.manage")), db: Session = Depends(get_db),
) -> InspectionResponse:
    item = _load(db, context.user.organization_id, inspection_id)
    if item.status not in {"ready", "contested"} or item.key_handover is None:
        raise HTTPException(status_code=409, detail="A contestação só pode ser registrada após a entrega de chaves.")
    now = datetime.now(timezone.utc)
    if item.contest_deadline and now > item.contest_deadline:
        raise HTTPException(status_code=409, detail="O prazo de contestação da vistoria encerrou.")
    environments = {environment.get("key"): environment for environment in list(item.environments or [])}
    environment = environments.get(payload.environment_key)
    if environment is None or not any(entry.get("key") == payload.item_key for entry in list(environment.get("items") or [])):
        raise HTTPException(status_code=422, detail="Ambiente ou item da contestação não foi encontrado.")
    entry = {
        "id": str(uuid.uuid4()), "environment_key": payload.environment_key, "item_key": payload.item_key,
        "description": payload.description.strip(), "created_at": now.isoformat(), "created_by_user_id": str(context.user.id),
        "resolution": None, "resolved_at": None,
    }
    item.contestations = [*list(item.contestations or []), entry]
    item.status = "contested"; item.current_version += 1; _version(db, item, context, "Contestação registrada")
    _audit(db, request, context, item, "inspections.contestation_created", after={"contestation_id": entry["id"], "version": item.current_version})
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.post("/inspections/{inspection_id}/contestations/resolve", response_model=InspectionResponse)
def resolve_contestation(
    inspection_id: UUID, payload: InspectionContestationResolve, request: Request,
    context: UserContext = Depends(require_permission("inspections.manage")), db: Session = Depends(get_db),
) -> InspectionResponse:
    item = _load(db, context.user.organization_id, inspection_id)
    if item.status != "contested": raise HTTPException(status_code=409, detail="A vistoria não possui contestação pendente.")
    entries = deepcopy(list(item.contestations or [])); found = False; now = datetime.now(timezone.utc)
    for entry in entries:
        if entry.get("id") == payload.contestation_id and not entry.get("resolved_at"):
            entry["resolution"] = payload.resolution.strip(); entry["resolved_at"] = now.isoformat(); entry["resolved_by_user_id"] = str(context.user.id); found = True; break
    if not found: raise HTTPException(status_code=404, detail="Contestação pendente não encontrada.")
    item.contestations = entries
    if payload.environments is not None: item.environments = [environment.model_dump(mode="json") for environment in payload.environments]
    item.current_version += 1
    if not any(not entry.get("resolved_at") for entry in entries): item.status = "ready"
    content, digest = _pdf(db, item)
    try: _archive_report(db, item, content, digest)
    except DocumentStorageError as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc
    _version(db, item, context, payload.change_summary.strip())
    _audit(db, request, context, item, "inspections.contestation_resolved", after={"contestation_id": payload.contestation_id, "version": item.current_version, "status": item.status}, reason=payload.resolution.strip())
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.post("/inspections/{inspection_id}/keys", response_model=InspectionResponse, status_code=status.HTTP_201_CREATED)
def handover_keys(
    inspection_id: UUID, payload: KeyHandoverCreate, request: Request,
    context: UserContext = Depends(require_permission("inspections.manage")), db: Session = Depends(get_db),
) -> InspectionResponse:
    item = _load(db, context.user.organization_id, inspection_id)
    if item.inspection_type != "initial" or item.status not in {"ready", "finalized"} or not item.report_hash:
        raise HTTPException(status_code=409, detail="Conclua a vistoria inicial e gere o hash do laudo antes de entregar as chaves.")
    if item.key_handover is not None: raise HTTPException(status_code=409, detail="As chaves deste contrato já foram entregues.")
    lease = _lease(db, context.user.organization_id, item.lease_contract_id)
    if lease.status != "signed" or lease.archive_status != "archived" or not lease.final_document_hash:
        raise HTTPException(status_code=409, detail="Contrato assinado e PDF final arquivado são obrigatórios para a entrega de chaves.")
    handover = KeyHandover(
        organization_id=context.user.organization_id, lease_contract_id=lease.id, property_id=item.property_id, inspection_id=item.id,
        handed_over_at=payload.handed_over_at, recipient_name=payload.recipient_name.strip(), recipient_document=(payload.recipient_document or "").strip() or None,
        keys=[entry.model_dump(mode="json") for entry in payload.keys], meter_readings=dict(payload.meter_readings or {}),
        notes=(payload.notes or "").strip() or None, created_by_user_id=context.user.id,
    )
    db.add(handover)
    item.contest_deadline = payload.handed_over_at + timedelta(days=lease.inspection_contest_days)
    _audit(db, request, context, item, "inspections.keys_handed_over", after={"recipient": handover.recipient_name, "contest_deadline": item.contest_deadline.isoformat()})
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.get("/inspections/{inspection_id}/document/pdf")
def preview_report(
    inspection_id: UUID, context: UserContext = Depends(require_permission("inspections.view")), db: Session = Depends(get_db),
) -> Response:
    item = _load(db, context.user.organization_id, inspection_id); content, _ = _pdf(db, item)
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{inspection_code(item)}-v{item.current_version}.pdf"'})


@router.get("/inspections/{inspection_id}/document/stored")
def stored_report(
    inspection_id: UUID, context: UserContext = Depends(require_permission("inspections.view")), db: Session = Depends(get_db),
) -> Response:
    item = _load(db, context.user.organization_id, inspection_id)
    if not item.report_reference: raise HTTPException(status_code=404, detail="Laudo ainda não está arquivado no storage.")
    try: content = get_document_storage().download_bytes(item.report_reference)
    except DocumentStorageError as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{inspection_code(item)}-v{item.report_version or item.current_version}.pdf"'})


@router.post("/inspections/{inspection_id}/photos", response_model=InspectionResponse)
async def upload_photo(
    inspection_id: UUID, environment_key: str = Form(...), item_key: str = Form(...), file: UploadFile = File(...),
    request: Request = None, context: UserContext = Depends(require_permission("inspections.manage")), db: Session = Depends(get_db),
) -> InspectionResponse:
    item = _load(db, context.user.organization_id, inspection_id)
    if item.status not in {"draft", "contested"}: raise HTTPException(status_code=409, detail="Fotos só podem ser anexadas em rascunho ou durante tratamento de contestação.")
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed: raise HTTPException(status_code=415, detail="Use imagem JPG, PNG ou WEBP.")
    content = await file.read()
    if len(content) > 12 * 1024 * 1024: raise HTTPException(status_code=413, detail="A foto deve ter no máximo 12 MB.")
    storage = get_document_storage()
    if not storage.configured: raise HTTPException(status_code=409, detail="Configure o storage de documentos antes de anexar fotos de vistoria.")
    photo_id = str(uuid.uuid4()); filename = (file.filename or "foto").replace("/", "-")
    object_name = storage.inspection_object_name(organization_id=str(item.organization_id), inspection_code=inspection_code(item), filename=f"photos/{photo_id}-{filename}")
    try: reference = storage.upload_bytes(object_name=object_name, content=content, content_type=file.content_type or "application/octet-stream")
    except DocumentStorageError as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc
    environments = deepcopy(list(item.environments or [])); target = None
    for environment in environments:
        if environment.get("key") != environment_key: continue
        for entry in list(environment.get("items") or []):
            if entry.get("key") == item_key: target = entry; break
    if target is None: raise HTTPException(status_code=422, detail="Ambiente ou item não encontrado.")
    target["photos"] = [*list(target.get("photos") or []), {"id": photo_id, "filename": filename, "content_type": file.content_type, "reference": reference, "uploaded_at": datetime.now(timezone.utc).isoformat()}]
    item.environments = environments
    if request is not None: _audit(db, request, context, item, "inspections.photo_uploaded", after={"photo_id": photo_id, "environment_key": environment_key, "item_key": item_key})
    db.commit()
    return _response(_load(db, context.user.organization_id, item.id))


@router.get("/inspections/{inspection_id}/photos/{photo_id}")
def download_photo(
    inspection_id: UUID, photo_id: str, context: UserContext = Depends(require_permission("inspections.view")), db: Session = Depends(get_db),
) -> Response:
    item = _load(db, context.user.organization_id, inspection_id)
    meta = None
    for environment in list(item.environments or []):
        for entry in list(environment.get("items") or []):
            for photo in list(entry.get("photos") or []):
                if photo.get("id") == photo_id: meta = photo; break
    if meta is None: raise HTTPException(status_code=404, detail="Foto não encontrada.")
    try: content = get_document_storage().download_bytes(str(meta.get("reference") or ""))
    except DocumentStorageError as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=content, media_type=str(meta.get("content_type") or "application/octet-stream"))
