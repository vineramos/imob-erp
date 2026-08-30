import uuid
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.leases.models import LeaseContract
from app.domains.leases.pdf import lease_contract_code
from app.domains.maintenance.models import MaintenancePartner, MaintenanceRequest
from app.domains.maintenance.pdf import build_maintenance_quote_pdf
from app.domains.maintenance.schemas import MaintenanceCreate, MaintenancePartnerCreate, MaintenancePartnerResponse, MaintenancePartnerUpdate, MaintenanceQuoteCreate, MaintenanceResponse, MaintenanceUpdate, MaintenanceWorkflow
from app.domains.portfolio.models import Person, Property
from app.integrations.document_storage import DocumentStorageError, get_document_storage

router = APIRouter(tags=["maintenance"])
TERMINAL = {"completed", "cancelled"}
ALLOWED_LOGO_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_LOGO_SIZE = 4 * 1024 * 1024


def maintenance_code(item: MaintenanceRequest) -> str:
    return f"MAN-{item.internal_number:06d}"


def partner_code(item: MaintenancePartner) -> str:
    return f"PAR-{item.internal_number:06d}"


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, item: MaintenanceRequest, action: str, *, before=None, after=None, reason=None) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(db, context=context, action=action, module="maintenance", entity_type="maintenance_request", entity_id=str(item.id), before_data=before, after_data=after, reason=reason, ip_address=ip_address, user_agent=user_agent)


def _audit_partner(db: Session, request: Request, context: UserContext, item: MaintenancePartner, action: str, *, before=None, after=None) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(db, context=context, action=action, module="maintenance", entity_type="maintenance_partner", entity_id=str(item.id), before_data=before, after_data=after, ip_address=ip_address, user_agent=user_agent)


def _property(db: Session, organization_id: UUID, property_id: UUID) -> Property:
    item = db.scalar(select(Property).where(Property.id == property_id, Property.organization_id == organization_id))
    if item is None: raise HTTPException(status_code=404, detail="Imóvel não encontrado.")
    return item


def _person(db: Session, organization_id: UUID, person_id: UUID | None) -> Person | None:
    if person_id is None: return None
    item = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == organization_id, Person.is_active.is_(True)))
    if item is None: raise HTTPException(status_code=422, detail="Pessoa vinculada à manutenção é inválida.")
    return item


def _lease(db: Session, organization_id: UUID, lease_id: UUID | None, property_id: UUID) -> LeaseContract | None:
    if lease_id is None: return None
    item = db.scalar(select(LeaseContract).where(LeaseContract.id == lease_id, LeaseContract.organization_id == organization_id))
    if item is None or item.property_id != property_id: raise HTTPException(status_code=422, detail="Contrato de locação não pertence ao imóvel informado.")
    return item


def _load(db: Session, organization_id: UUID, item_id: UUID) -> MaintenanceRequest:
    item = db.scalar(select(MaintenanceRequest).where(MaintenanceRequest.id == item_id, MaintenanceRequest.organization_id == organization_id))
    if item is None: raise HTTPException(status_code=404, detail="Chamado de manutenção não encontrado.")
    return item


def _partner(db: Session, organization_id: UUID, partner_id: UUID, *, active_only: bool = False) -> MaintenancePartner:
    stmt = select(MaintenancePartner).where(MaintenancePartner.id == partner_id, MaintenancePartner.organization_id == organization_id)
    if active_only: stmt = stmt.where(MaintenancePartner.is_active.is_(True))
    item = db.scalar(stmt)
    if item is None: raise HTTPException(status_code=404 if not active_only else 422, detail="Parceiro terceirizado não encontrado ou inativo.")
    return item


def _event(context: UserContext, event: str, detail: str | None = None) -> dict:
    return {"event": event, "detail": detail, "at": datetime.now(timezone.utc).isoformat(), "user_id": str(context.user.id)}


def _append_history(item: MaintenanceRequest, context: UserContext, event: str, detail: str | None = None) -> None:
    item.history = [*list(item.history or []), _event(context, event, detail)]


def _money(value) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def _clean_dict(value: dict | None) -> dict:
    return {str(key): str(item).strip() for key, item in dict(value or {}).items() if str(item).strip()}


def _partner_snapshot(item: MaintenancePartner) -> dict:
    return {"id": str(item.id), "code": partner_code(item), "name": item.name, "legal_name": item.legal_name, "document_number": item.document_number, "contact_name": item.contact_name, "email": item.email, "phone": item.phone, "whatsapp": item.whatsapp, "address": deepcopy(item.address or {}), "specialties": deepcopy(item.specialties or []), "pix_key": item.pix_key, "bank_details": deepcopy(item.bank_details or {}), "logo_storage_reference": item.logo_storage_reference, "logo_content_type": item.logo_content_type}


def _partner_response(item: MaintenancePartner) -> MaintenancePartnerResponse:
    return MaintenancePartnerResponse(id=item.id, internal_number=item.internal_number, code=partner_code(item), name=item.name, legal_name=item.legal_name, document_number=item.document_number, contact_name=item.contact_name, email=item.email, phone=item.phone, whatsapp=item.whatsapp, address=deepcopy(item.address or {}), specialties=deepcopy(item.specialties or []), pix_key=item.pix_key, bank_details=deepcopy(item.bank_details or {}), notes=item.notes, is_active=item.is_active, has_logo=bool(item.logo_storage_reference), logo_url=f"/maintenance/partners/{item.id}/logo" if item.logo_storage_reference else None, created_at=item.created_at, updated_at=item.updated_at)


def _apply_partner_payload(item: MaintenancePartner, payload: MaintenancePartnerCreate | MaintenancePartnerUpdate) -> None:
    item.name=payload.name.strip(); item.legal_name=_clean(payload.legal_name); item.document_number=_clean(payload.document_number); item.contact_name=_clean(payload.contact_name); item.email=_clean(payload.email); item.phone=_clean(payload.phone); item.whatsapp=_clean(payload.whatsapp); item.address=_clean_dict(payload.address); item.specialties=[str(value).strip() for value in payload.specialties if str(value).strip()]; item.pix_key=_clean(payload.pix_key); item.bank_details=_clean_dict(payload.bank_details); item.notes=_clean(payload.notes); item.is_active=payload.is_active


def _response(db: Session, item: MaintenanceRequest) -> MaintenanceResponse:
    prop=db.get(Property,item.property_id); lease=db.get(LeaseContract,item.lease_contract_id) if item.lease_contract_id else None; requester=db.get(Person,item.requester_person_id) if item.requester_person_id else None; supplier=db.get(Person,item.supplier_person_id) if item.supplier_person_id else None
    return MaintenanceResponse(id=item.id,internal_number=item.internal_number,code=maintenance_code(item),property_id=item.property_id,property_code=f"{prop.internal_number:06d}" if prop else "—",property_title=(prop.public_title or f"Imóvel {prop.internal_number:06d}") if prop else "Imóvel",property_address=dict(prop.address or {}) if prop else {},lease_contract_id=item.lease_contract_id,lease_code=lease_contract_code(lease) if lease else None,requester_person_id=item.requester_person_id,requester_name=requester.name if requester else None,supplier_person_id=item.supplier_person_id,supplier_name=supplier.name if supplier else next((q.get("supplier_name") for q in item.quotes or [] if q.get("id")==item.selected_quote_id),None),title=item.title,category=item.category,priority=item.priority,status=item.status,description=item.description,responsibility=item.responsibility,approval_required=item.approval_required,estimated_cost=item.estimated_cost,approved_cost=item.approved_cost,actual_cost=item.actual_cost,selected_quote_id=item.selected_quote_id,quotes=deepcopy(item.quotes or []),history=deepcopy(item.history or []),reported_at=item.reported_at,scheduled_at=item.scheduled_at,started_at=item.started_at,completed_at=item.completed_at,approved_at=item.approved_at,cancelled_at=item.cancelled_at,cancellation_reason=item.cancellation_reason,notes=item.notes,created_at=item.created_at,updated_at=item.updated_at)


def _apply_payload(db: Session, organization_id: UUID, item: MaintenanceRequest, payload: MaintenanceCreate | MaintenanceUpdate) -> None:
    _property(db,organization_id,payload.property_id); _lease(db,organization_id,payload.lease_contract_id,payload.property_id); _person(db,organization_id,payload.requester_person_id)
    item.property_id=payload.property_id; item.lease_contract_id=payload.lease_contract_id; item.requester_person_id=payload.requester_person_id; item.title=payload.title.strip(); item.category=payload.category; item.priority=payload.priority; item.description=payload.description.strip(); item.responsibility=payload.responsibility; item.approval_required=payload.approval_required; item.estimated_cost=payload.estimated_cost; item.scheduled_at=payload.scheduled_at; item.notes=_clean(payload.notes)


@router.get("/maintenance/partners", response_model=list[MaintenancePartnerResponse])
def list_maintenance_partners(include_inactive: bool=Query(default=False), context: UserContext=Depends(require_permission("maintenance.view")), db: Session=Depends(get_db)) -> list[MaintenancePartnerResponse]:
    stmt=select(MaintenancePartner).where(MaintenancePartner.organization_id==context.user.organization_id)
    if not include_inactive: stmt=stmt.where(MaintenancePartner.is_active.is_(True))
    return [_partner_response(item) for item in db.scalars(stmt.order_by(MaintenancePartner.name.asc())).all()]


@router.post("/maintenance/partners", response_model=MaintenancePartnerResponse, status_code=status.HTTP_201_CREATED)
def create_maintenance_partner(payload: MaintenancePartnerCreate, request: Request, context: UserContext=Depends(require_permission("maintenance.manage")), db: Session=Depends(get_db)) -> MaintenancePartnerResponse:
    item=MaintenancePartner(organization_id=context.user.organization_id,name=payload.name.strip(),created_by_user_id=context.user.id); _apply_partner_payload(item,payload); db.add(item)
    try: db.flush()
    except IntegrityError as exc: db.rollback(); raise HTTPException(status_code=409,detail="Já existe um parceiro com este CPF/CNPJ.") from exc
    _audit_partner(db,request,context,item,"maintenance.partner_created",after={"name":item.name,"document_number":item.document_number}); db.commit(); db.refresh(item); return _partner_response(item)


@router.put("/maintenance/partners/{partner_id}", response_model=MaintenancePartnerResponse)
def update_maintenance_partner(partner_id: UUID, payload: MaintenancePartnerUpdate, request: Request, context: UserContext=Depends(require_permission("maintenance.manage")), db: Session=Depends(get_db)) -> MaintenancePartnerResponse:
    item=_partner(db,context.user.organization_id,partner_id); before={"name":item.name,"document_number":item.document_number,"is_active":item.is_active}; _apply_partner_payload(item,payload)
    try: db.flush()
    except IntegrityError as exc: db.rollback(); raise HTTPException(status_code=409,detail="Já existe um parceiro com este CPF/CNPJ.") from exc
    _audit_partner(db,request,context,item,"maintenance.partner_updated",before=before,after={"name":item.name,"document_number":item.document_number,"is_active":item.is_active}); db.commit(); db.refresh(item); return _partner_response(item)


@router.post("/maintenance/partners/{partner_id}/logo", response_model=MaintenancePartnerResponse)
async def upload_maintenance_partner_logo(partner_id: UUID, request: Request, file: UploadFile=File(...), context: UserContext=Depends(require_permission("maintenance.manage")), db: Session=Depends(get_db)) -> MaintenancePartnerResponse:
    item=_partner(db,context.user.organization_id,partner_id); content_type=(file.content_type or "").lower()
    if content_type not in ALLOWED_LOGO_TYPES: raise HTTPException(status_code=422,detail="Use logo em JPG, PNG ou WEBP.")
    content=await file.read()
    if not content: raise HTTPException(status_code=422,detail="O arquivo da logo está vazio.")
    if len(content)>MAX_LOGO_SIZE: raise HTTPException(status_code=413,detail="A logo pode ter no máximo 4 MB.")
    safe_filename=Path(file.filename or "logo").name.replace("/","-").replace("\\","-"); object_name=f"imob-erp/{context.user.organization_id}/maintenance-partners/{item.id}/logos/{uuid.uuid4()}-{safe_filename}"
    try: reference=get_document_storage().upload_bytes(object_name=object_name,content=content,content_type=content_type)
    except DocumentStorageError as exc: raise HTTPException(status_code=502,detail=str(exc)) from exc
    before={"has_logo":bool(item.logo_storage_reference)}; item.logo_storage_reference=reference; item.logo_content_type=content_type; _audit_partner(db,request,context,item,"maintenance.partner_logo_updated",before=before,after={"has_logo":True}); db.commit(); db.refresh(item); return _partner_response(item)


@router.delete("/maintenance/partners/{partner_id}/logo", response_model=MaintenancePartnerResponse)
def clear_maintenance_partner_logo(partner_id: UUID, request: Request, context: UserContext=Depends(require_permission("maintenance.manage")), db: Session=Depends(get_db)) -> MaintenancePartnerResponse:
    item=_partner(db,context.user.organization_id,partner_id)
    if item.logo_storage_reference:
        item.logo_storage_reference=None; item.logo_content_type=None; _audit_partner(db,request,context,item,"maintenance.partner_logo_cleared",before={"has_logo":True},after={"has_logo":False}); db.commit(); db.refresh(item)
    return _partner_response(item)


@router.get("/maintenance/partners/{partner_id}/logo")
def maintenance_partner_logo(partner_id: UUID, context: UserContext=Depends(require_permission("maintenance.view")), db: Session=Depends(get_db)) -> Response:
    item=_partner(db,context.user.organization_id,partner_id)
    if not item.logo_storage_reference: raise HTTPException(status_code=404,detail="Parceiro não possui logo cadastrada.")
    try: content=get_document_storage().download_bytes(item.logo_storage_reference)
    except DocumentStorageError as exc: raise HTTPException(status_code=502,detail=str(exc)) from exc
    return Response(content=content,media_type=item.logo_content_type or "application/octet-stream",headers={"Cache-Control":"private, max-age=3600"})


@router.get("/maintenance", response_model=list[MaintenanceResponse])
def list_maintenance(property_id: UUID|None=Query(default=None), context: UserContext=Depends(require_permission("maintenance.view")), db: Session=Depends(get_db)) -> list[MaintenanceResponse]:
    stmt=select(MaintenanceRequest).where(MaintenanceRequest.organization_id==context.user.organization_id)
    if property_id: stmt=stmt.where(MaintenanceRequest.property_id==property_id)
    return [_response(db,item) for item in db.scalars(stmt.order_by(MaintenanceRequest.internal_number.desc()).limit(300)).all()]


@router.post("/maintenance", response_model=MaintenanceResponse, status_code=status.HTTP_201_CREATED)
def create_maintenance(payload: MaintenanceCreate, request: Request, context: UserContext=Depends(require_permission("maintenance.manage")), db: Session=Depends(get_db)) -> MaintenanceResponse:
    item=MaintenanceRequest(organization_id=context.user.organization_id,property_id=payload.property_id,title=payload.title.strip(),description=payload.description.strip(),created_by_user_id=context.user.id,quotes=[],history=[]); _apply_payload(db,context.user.organization_id,item,payload); db.add(item); db.flush(); _append_history(item,context,"Chamado aberto",item.title); _audit(db,request,context,item,"maintenance.created",after={"status":item.status,"property_id":str(item.property_id),"priority":item.priority}); db.commit(); db.refresh(item); return _response(db,item)


@router.put("/maintenance/{item_id}", response_model=MaintenanceResponse)
def update_maintenance(item_id: UUID, payload: MaintenanceUpdate, request: Request, context: UserContext=Depends(require_permission("maintenance.manage")), db: Session=Depends(get_db)) -> MaintenanceResponse:
    item=_load(db,context.user.organization_id,item_id)
    if item.status in TERMINAL: raise HTTPException(status_code=409,detail="Chamado concluído ou cancelado não pode ser editado.")
    before={"status":item.status,"title":item.title,"priority":item.priority,"responsibility":item.responsibility}; _apply_payload(db,context.user.organization_id,item,payload); _append_history(item,context,"Cadastro atualizado"); _audit(db,request,context,item,"maintenance.updated",before=before,after={"status":item.status,"title":item.title,"priority":item.priority,"responsibility":item.responsibility}); db.commit(); db.refresh(item); return _response(db,item)


@router.post("/maintenance/{item_id}/quotes", response_model=MaintenanceResponse)
def add_quote(item_id: UUID, payload: MaintenanceQuoteCreate, request: Request, context: UserContext=Depends(require_permission("maintenance.manage")), db: Session=Depends(get_db)) -> MaintenanceResponse:
    item=_load(db,context.user.organization_id,item_id)
    if item.status in TERMINAL: raise HTTPException(status_code=409,detail="Não é possível incluir orçamento em chamado encerrado.")
    partner=_partner(db,context.user.organization_id,payload.partner_id,active_only=True) if payload.partner_id else None; supplier=_person(db,context.user.organization_id,payload.supplier_person_id); supplier_name=partner.name if partner else supplier.name if supplier else (payload.supplier_name or "").strip(); quote_number=len(list(item.quotes or []))+1
    quote={"id":str(uuid.uuid4()),"quote_code":f"{maintenance_code(item)}-ORC-{quote_number:02d}","partner_id":str(partner.id) if partner else None,"partner_snapshot":_partner_snapshot(partner) if partner else None,"supplier_person_id":str(supplier.id) if supplier else None,"supplier_name":supplier_name,"amount":str(payload.amount),"description":_clean(payload.description),"valid_until":payload.valid_until.isoformat() if payload.valid_until else None,"payment_terms":_clean(payload.payment_terms),"notes":_clean(payload.notes),"status":"proposed","created_at":datetime.now(timezone.utc).isoformat()}
    item.quotes=[*list(item.quotes or []),quote]
    if item.status in {"requested","triage"}: item.status="awaiting_quote"
    _append_history(item,context,"Orçamento incluído",f"{quote['supplier_name']} · R$ {payload.amount}"); _audit(db,request,context,item,"maintenance.quote_added",after={"quote_id":quote["id"],"partner_id":quote["partner_id"],"amount":str(payload.amount),"status":item.status}); db.commit(); db.refresh(item); return _response(db,item)


@router.get("/maintenance/{item_id}/quotes/{quote_id}/pdf")
def maintenance_quote_pdf(item_id: UUID, quote_id: str, context: UserContext=Depends(require_permission("maintenance.view")), db: Session=Depends(get_db)) -> Response:
    item=_load(db,context.user.organization_id,item_id); quote=next((deepcopy(value) for value in list(item.quotes or []) if value.get("id")==quote_id),None)
    if quote is None: raise HTTPException(status_code=404,detail="Orçamento não encontrado.")
    if not quote.get("partner_snapshot"): raise HTTPException(status_code=422,detail="PDF padronizado está disponível para orçamentos emitidos por parceiros cadastrados.")
    property_item=_property(db,context.user.organization_id,item.property_id); logo_bytes=None; logo_reference=dict(quote.get("partner_snapshot") or {}).get("logo_storage_reference")
    if logo_reference:
        try: logo_bytes=get_document_storage().download_bytes(str(logo_reference))
        except DocumentStorageError: logo_bytes=None
    try: pdf=build_maintenance_quote_pdf(maintenance=item,property_item=property_item,quote=quote,logo_bytes=logo_bytes)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    filename=f"{quote.get('quote_code') or maintenance_code(item)}.pdf"; return Response(content=pdf,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{filename}"',"Cache-Control":"private, no-store"})


@router.post("/maintenance/{item_id}/quotes/{quote_id}/select", response_model=MaintenanceResponse)
def select_quote(item_id: UUID, quote_id: str, request: Request, context: UserContext=Depends(require_permission("maintenance.manage")), db: Session=Depends(get_db)) -> MaintenanceResponse:
    item=_load(db,context.user.organization_id,item_id)
    if item.status in TERMINAL: raise HTTPException(status_code=409,detail="Chamado encerrado não aceita seleção de orçamento.")
    quotes=deepcopy(list(item.quotes or [])); selected=None
    for quote in quotes:
        if quote.get("id")==quote_id: quote["status"]="selected"; selected=quote
        elif quote.get("status")=="selected": quote["status"]="rejected"
    if selected is None: raise HTTPException(status_code=404,detail="Orçamento não encontrado.")
    item.quotes=quotes; item.selected_quote_id=quote_id; item.approved_cost=_money(selected.get("amount")); item.supplier_person_id=UUID(selected["supplier_person_id"]) if selected.get("supplier_person_id") else None; item.status="awaiting_approval" if item.approval_required else "approved"
    if item.status=="approved": item.approved_at=datetime.now(timezone.utc); item.approved_by_user_id=context.user.id
    _append_history(item,context,"Orçamento selecionado",f"{selected.get('supplier_name')} · R$ {selected.get('amount')}"); _audit(db,request,context,item,"maintenance.quote_selected",after={"quote_id":quote_id,"partner_id":selected.get("partner_id"),"status":item.status,"approved_cost":str(item.approved_cost)}); db.commit(); db.refresh(item); return _response(db,item)


@router.post("/maintenance/{item_id}/workflow", response_model=MaintenanceResponse)
def workflow(item_id: UUID, payload: MaintenanceWorkflow, request: Request, context: UserContext=Depends(require_permission("maintenance.manage")), db: Session=Depends(get_db)) -> MaintenanceResponse:
    item=_load(db,context.user.organization_id,item_id); before={"status":item.status}; now=datetime.now(timezone.utc); action=payload.action
    if action=="triage":
        if item.status!="requested": raise HTTPException(status_code=409,detail="Somente chamados novos podem entrar em triagem.")
        item.status="triage"
    elif action=="request_quotes":
        if item.status!="triage": raise HTTPException(status_code=409,detail="Solicite orçamentos após a triagem.")
        item.status="awaiting_quote"
    elif action=="approve":
        if item.status not in {"triage","awaiting_quote","awaiting_approval"}: raise HTTPException(status_code=409,detail="O chamado não está em etapa de aprovação.")
        item.approved_cost=payload.approved_cost if payload.approved_cost is not None else item.approved_cost or item.estimated_cost; item.status="approved"; item.approved_at=now; item.approved_by_user_id=context.user.id
    elif action=="schedule":
        if item.status!="approved": raise HTTPException(status_code=409,detail="A execução precisa estar aprovada antes do agendamento.")
        item.scheduled_at=payload.scheduled_at or item.scheduled_at
        if item.scheduled_at is None: raise HTTPException(status_code=422,detail="Informe a data e hora do serviço.")
        item.status="scheduled"
    elif action=="start":
        if item.status not in {"approved","scheduled"}: raise HTTPException(status_code=409,detail="A manutenção ainda não está pronta para execução.")
        item.status="in_progress"; item.started_at=now
    elif action=="complete":
        if item.status not in {"approved","scheduled","in_progress"}: raise HTTPException(status_code=409,detail="A manutenção não está em execução.")
        item.status="completed"; item.completed_at=now; item.completed_by_user_id=context.user.id; item.actual_cost=payload.actual_cost if payload.actual_cost is not None else item.approved_cost or item.estimated_cost
    elif action=="cancel":
        if item.status in TERMINAL: raise HTTPException(status_code=409,detail="Chamado já encerrado.")
        if not (payload.reason or "").strip(): raise HTTPException(status_code=422,detail="Informe o motivo do cancelamento.")
        item.status="cancelled"; item.cancelled_at=now; item.cancellation_reason=payload.reason.strip()
    elif action=="return_triage":
        if item.status not in {"awaiting_quote","awaiting_approval","approved","scheduled"}: raise HTTPException(status_code=409,detail="Não é possível retornar este chamado para triagem.")
        item.status="triage"; item.approved_at=None; item.approved_by_user_id=None
    else: raise HTTPException(status_code=422,detail="Ação inválida.")
    labels={"triage":"Triagem iniciada","request_quotes":"Orçamentos solicitados","approve":"Execução aprovada","schedule":"Serviço agendado","start":"Execução iniciada","complete":"Manutenção concluída","cancel":"Chamado cancelado","return_triage":"Retornado para triagem"}; _append_history(item,context,labels[action],payload.reason); _audit(db,request,context,item,f"maintenance.{action}",before=before,after={"status":item.status,"approved_cost":str(item.approved_cost) if item.approved_cost is not None else None,"actual_cost":str(item.actual_cost) if item.actual_cost is not None else None},reason=payload.reason); db.commit(); db.refresh(item); return _response(db,item)
