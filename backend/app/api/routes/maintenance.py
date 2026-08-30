import uuid
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.leases.models import LeaseContract
from app.domains.leases.pdf import lease_contract_code
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.maintenance.schemas import MaintenanceCreate, MaintenanceQuoteCreate, MaintenanceResponse, MaintenanceUpdate, MaintenanceWorkflow
from app.domains.portfolio.models import Person, Property

router = APIRouter(tags=["maintenance"])
TERMINAL = {"completed", "cancelled"}


def maintenance_code(item: MaintenanceRequest) -> str:
    return f"MAN-{item.internal_number:06d}"


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, item: MaintenanceRequest, action: str, *, before=None, after=None, reason=None) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(db, context=context, action=action, module="maintenance", entity_type="maintenance_request", entity_id=str(item.id), before_data=before, after_data=after, reason=reason, ip_address=ip_address, user_agent=user_agent)


def _property(db: Session, organization_id: UUID, property_id: UUID) -> Property:
    item = db.scalar(select(Property).where(Property.id == property_id, Property.organization_id == organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Imóvel não encontrado.")
    return item


def _person(db: Session, organization_id: UUID, person_id: UUID | None) -> Person | None:
    if person_id is None:
        return None
    item = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == organization_id, Person.is_active.is_(True)))
    if item is None:
        raise HTTPException(status_code=422, detail="Pessoa vinculada à manutenção é inválida.")
    return item


def _lease(db: Session, organization_id: UUID, lease_id: UUID | None, property_id: UUID) -> LeaseContract | None:
    if lease_id is None:
        return None
    item = db.scalar(select(LeaseContract).where(LeaseContract.id == lease_id, LeaseContract.organization_id == organization_id))
    if item is None or item.property_id != property_id:
        raise HTTPException(status_code=422, detail="Contrato de locação não pertence ao imóvel informado.")
    return item


def _load(db: Session, organization_id: UUID, item_id: UUID) -> MaintenanceRequest:
    item = db.scalar(select(MaintenanceRequest).where(MaintenanceRequest.id == item_id, MaintenanceRequest.organization_id == organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Chamado de manutenção não encontrado.")
    return item


def _event(context: UserContext, event: str, detail: str | None = None) -> dict:
    return {"event": event, "detail": detail, "at": datetime.now(timezone.utc).isoformat(), "user_id": str(context.user.id)}


def _append_history(item: MaintenanceRequest, context: UserContext, event: str, detail: str | None = None) -> None:
    item.history = [*list(item.history or []), _event(context, event, detail)]


def _money(value) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _response(db: Session, item: MaintenanceRequest) -> MaintenanceResponse:
    prop = db.get(Property, item.property_id)
    lease = db.get(LeaseContract, item.lease_contract_id) if item.lease_contract_id else None
    requester = db.get(Person, item.requester_person_id) if item.requester_person_id else None
    supplier = db.get(Person, item.supplier_person_id) if item.supplier_person_id else None
    return MaintenanceResponse(
        id=item.id, internal_number=item.internal_number, code=maintenance_code(item), property_id=item.property_id,
        property_code=f"{prop.internal_number:06d}" if prop else "—", property_title=(prop.public_title or f"Imóvel {prop.internal_number:06d}") if prop else "Imóvel",
        property_address=dict(prop.address or {}) if prop else {}, lease_contract_id=item.lease_contract_id,
        lease_code=lease_contract_code(lease) if lease else None, requester_person_id=item.requester_person_id,
        requester_name=requester.name if requester else None, supplier_person_id=item.supplier_person_id,
        supplier_name=supplier.name if supplier else next((q.get("supplier_name") for q in item.quotes or [] if q.get("id") == item.selected_quote_id), None),
        title=item.title, category=item.category, priority=item.priority, status=item.status, description=item.description,
        responsibility=item.responsibility, approval_required=item.approval_required, estimated_cost=item.estimated_cost,
        approved_cost=item.approved_cost, actual_cost=item.actual_cost, selected_quote_id=item.selected_quote_id,
        quotes=deepcopy(item.quotes or []), history=deepcopy(item.history or []), reported_at=item.reported_at,
        scheduled_at=item.scheduled_at, started_at=item.started_at, completed_at=item.completed_at, approved_at=item.approved_at,
        cancelled_at=item.cancelled_at, cancellation_reason=item.cancellation_reason, notes=item.notes,
        created_at=item.created_at, updated_at=item.updated_at,
    )


def _apply_payload(db: Session, organization_id: UUID, item: MaintenanceRequest, payload: MaintenanceCreate | MaintenanceUpdate) -> None:
    _property(db, organization_id, payload.property_id)
    _lease(db, organization_id, payload.lease_contract_id, payload.property_id)
    _person(db, organization_id, payload.requester_person_id)
    item.property_id = payload.property_id; item.lease_contract_id = payload.lease_contract_id; item.requester_person_id = payload.requester_person_id
    item.title = payload.title.strip(); item.category = payload.category; item.priority = payload.priority; item.description = payload.description.strip()
    item.responsibility = payload.responsibility; item.approval_required = payload.approval_required; item.estimated_cost = payload.estimated_cost
    item.scheduled_at = payload.scheduled_at; item.notes = (payload.notes or "").strip() or None


@router.get("/maintenance", response_model=list[MaintenanceResponse])
def list_maintenance(property_id: UUID | None = Query(default=None), context: UserContext = Depends(require_permission("maintenance.view")), db: Session = Depends(get_db)) -> list[MaintenanceResponse]:
    stmt = select(MaintenanceRequest).where(MaintenanceRequest.organization_id == context.user.organization_id)
    if property_id: stmt = stmt.where(MaintenanceRequest.property_id == property_id)
    items = db.scalars(stmt.order_by(MaintenanceRequest.internal_number.desc()).limit(300)).all()
    return [_response(db, item) for item in items]


@router.post("/maintenance", response_model=MaintenanceResponse, status_code=status.HTTP_201_CREATED)
def create_maintenance(payload: MaintenanceCreate, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceResponse:
    item = MaintenanceRequest(organization_id=context.user.organization_id, property_id=payload.property_id, title=payload.title.strip(), description=payload.description.strip(), created_by_user_id=context.user.id, quotes=[], history=[])
    _apply_payload(db, context.user.organization_id, item, payload)
    db.add(item); db.flush(); _append_history(item, context, "Chamado aberto", item.title)
    _audit(db, request, context, item, "maintenance.created", after={"status": item.status, "property_id": str(item.property_id), "priority": item.priority})
    db.commit(); db.refresh(item)
    return _response(db, item)


@router.put("/maintenance/{item_id}", response_model=MaintenanceResponse)
def update_maintenance(item_id: UUID, payload: MaintenanceUpdate, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceResponse:
    item = _load(db, context.user.organization_id, item_id)
    if item.status in TERMINAL:
        raise HTTPException(status_code=409, detail="Chamado concluído ou cancelado não pode ser editado.")
    before = {"status": item.status, "title": item.title, "priority": item.priority, "responsibility": item.responsibility}
    _apply_payload(db, context.user.organization_id, item, payload); _append_history(item, context, "Cadastro atualizado")
    _audit(db, request, context, item, "maintenance.updated", before=before, after={"status": item.status, "title": item.title, "priority": item.priority, "responsibility": item.responsibility})
    db.commit(); db.refresh(item)
    return _response(db, item)


@router.post("/maintenance/{item_id}/quotes", response_model=MaintenanceResponse)
def add_quote(item_id: UUID, payload: MaintenanceQuoteCreate, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceResponse:
    item = _load(db, context.user.organization_id, item_id)
    if item.status in TERMINAL:
        raise HTTPException(status_code=409, detail="Não é possível incluir orçamento em chamado encerrado.")
    supplier = _person(db, context.user.organization_id, payload.supplier_person_id)
    quote = {"id": str(uuid.uuid4()), "supplier_person_id": str(supplier.id) if supplier else None, "supplier_name": supplier.name if supplier else payload.supplier_name.strip(), "amount": str(payload.amount), "description": (payload.description or "").strip() or None, "valid_until": payload.valid_until.isoformat() if payload.valid_until else None, "status": "proposed", "created_at": datetime.now(timezone.utc).isoformat()}
    item.quotes = [*list(item.quotes or []), quote]
    if item.status in {"requested", "triage"}: item.status = "awaiting_quote"
    _append_history(item, context, "Orçamento incluído", f"{quote['supplier_name']} · R$ {payload.amount}")
    _audit(db, request, context, item, "maintenance.quote_added", after={"quote_id": quote["id"], "amount": str(payload.amount), "status": item.status})
    db.commit(); db.refresh(item)
    return _response(db, item)


@router.post("/maintenance/{item_id}/quotes/{quote_id}/select", response_model=MaintenanceResponse)
def select_quote(item_id: UUID, quote_id: str, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceResponse:
    item = _load(db, context.user.organization_id, item_id)
    if item.status in TERMINAL:
        raise HTTPException(status_code=409, detail="Chamado encerrado não aceita seleção de orçamento.")
    quotes = deepcopy(list(item.quotes or [])); selected = None
    for quote in quotes:
        if quote.get("id") == quote_id: quote["status"] = "selected"; selected = quote
        elif quote.get("status") == "selected": quote["status"] = "rejected"
    if selected is None: raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
    item.quotes = quotes; item.selected_quote_id = quote_id; item.approved_cost = _money(selected.get("amount"))
    item.supplier_person_id = UUID(selected["supplier_person_id"]) if selected.get("supplier_person_id") else None
    item.status = "awaiting_approval" if item.approval_required else "approved"
    if item.status == "approved": item.approved_at = datetime.now(timezone.utc); item.approved_by_user_id = context.user.id
    _append_history(item, context, "Orçamento selecionado", f"{selected.get('supplier_name')} · R$ {selected.get('amount')}")
    _audit(db, request, context, item, "maintenance.quote_selected", after={"quote_id": quote_id, "status": item.status, "approved_cost": str(item.approved_cost)})
    db.commit(); db.refresh(item)
    return _response(db, item)


@router.post("/maintenance/{item_id}/workflow", response_model=MaintenanceResponse)
def workflow(item_id: UUID, payload: MaintenanceWorkflow, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceResponse:
    item = _load(db, context.user.organization_id, item_id); before = {"status": item.status}; now = datetime.now(timezone.utc); action = payload.action
    if action == "triage":
        if item.status != "requested": raise HTTPException(status_code=409, detail="Somente chamados novos podem entrar em triagem.")
        item.status = "triage"
    elif action == "request_quotes":
        if item.status != "triage": raise HTTPException(status_code=409, detail="Solicite orçamentos após a triagem.")
        item.status = "awaiting_quote"
    elif action == "approve":
        if item.status not in {"triage", "awaiting_quote", "awaiting_approval"}: raise HTTPException(status_code=409, detail="O chamado não está em etapa de aprovação.")
        item.approved_cost = payload.approved_cost if payload.approved_cost is not None else item.approved_cost or item.estimated_cost
        item.status = "approved"; item.approved_at = now; item.approved_by_user_id = context.user.id
    elif action == "schedule":
        if item.status != "approved": raise HTTPException(status_code=409, detail="A execução precisa estar aprovada antes do agendamento.")
        item.scheduled_at = payload.scheduled_at or item.scheduled_at
        if item.scheduled_at is None: raise HTTPException(status_code=422, detail="Informe a data e hora do serviço.")
        item.status = "scheduled"
    elif action == "start":
        if item.status not in {"approved", "scheduled"}: raise HTTPException(status_code=409, detail="A manutenção ainda não está pronta para execução.")
        item.status = "in_progress"; item.started_at = now
    elif action == "complete":
        if item.status not in {"approved", "scheduled", "in_progress"}: raise HTTPException(status_code=409, detail="A manutenção não está em execução.")
        item.status = "completed"; item.completed_at = now; item.completed_by_user_id = context.user.id
        item.actual_cost = payload.actual_cost if payload.actual_cost is not None else item.approved_cost or item.estimated_cost
    elif action == "cancel":
        if item.status in TERMINAL: raise HTTPException(status_code=409, detail="Chamado já encerrado.")
        if not (payload.reason or "").strip(): raise HTTPException(status_code=422, detail="Informe o motivo do cancelamento.")
        item.status = "cancelled"; item.cancelled_at = now; item.cancellation_reason = payload.reason.strip()
    elif action == "return_triage":
        if item.status not in {"awaiting_quote", "awaiting_approval", "approved", "scheduled"}: raise HTTPException(status_code=409, detail="Não é possível retornar este chamado para triagem.")
        item.status = "triage"; item.approved_at = None; item.approved_by_user_id = None
    else:
        raise HTTPException(status_code=422, detail="Ação inválida.")
    _append_history(item, context, {"triage":"Triagem iniciada","request_quotes":"Orçamentos solicitados","approve":"Execução aprovada","schedule":"Serviço agendado","start":"Execução iniciada","complete":"Manutenção concluída","cancel":"Chamado cancelado","return_triage":"Retornado para triagem"}[action], payload.reason)
    _audit(db, request, context, item, f"maintenance.{action}", before=before, after={"status": item.status, "approved_cost": str(item.approved_cost) if item.approved_cost is not None else None, "actual_cost": str(item.actual_cost) if item.actual_cost is not None else None}, reason=payload.reason)
    db.commit(); db.refresh(item)
    return _response(db, item)
