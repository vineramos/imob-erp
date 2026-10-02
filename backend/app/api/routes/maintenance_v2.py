from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.models import MaintenanceFinancialEntry
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.leases.models import LeaseContract
from app.domains.leases.pdf import lease_contract_code
from app.domains.maintenance.models import MaintenancePartner, MaintenanceRequest
from app.domains.maintenance.pdf import build_maintenance_quote_pdf
from app.domains.maintenance.schemas_v2 import MaintenanceEditRequest, MaintenanceOpenRequest, MaintenanceQuoteV2Create, MaintenanceServiceInput, MaintenanceV2Response, MaintenanceWorkflowV2
from app.domains.portfolio.models import Person, Property
from app.integrations.document_storage import DocumentStorageError, get_document_storage

router = APIRouter(tags=["maintenance-v2"])
CENT = Decimal("0.01")
TERMINAL = {"completed", "cancelled"}
QUOTE_LOCKED = {"approved", "scheduled", "in_progress", "completed", "cancelled"}


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def maintenance_code(item: MaintenanceRequest) -> str:
    return f"MAN-{item.internal_number:06d}"


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def _meta(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(db: Session, request: Request, context: UserContext, item: MaintenanceRequest, action: str, *, before=None, after=None, reason=None) -> None:
    ip, agent = _meta(request)
    write_audit(db, context=context, action=action, module="maintenance", entity_type="maintenance_request", entity_id=str(item.id), before_data=before, after_data=after, reason=reason, ip_address=ip, user_agent=agent)


def _history(item: MaintenanceRequest, context: UserContext, event: str, detail: str | None = None) -> None:
    item.history = [*list(item.history or []), {"event": event, "detail": detail, "at": datetime.now(timezone.utc).isoformat(), "user_id": str(context.user.id)}]


def _load(db: Session, org: UUID, item_id: UUID) -> MaintenanceRequest:
    item = db.scalar(select(MaintenanceRequest).where(MaintenanceRequest.id == item_id, MaintenanceRequest.organization_id == org))
    if item is None:
        raise HTTPException(404, "Chamado de manutenção não encontrado.")
    return item


def _property(db: Session, org: UUID, property_id: UUID) -> Property:
    item = db.scalar(select(Property).where(Property.id == property_id, Property.organization_id == org))
    if item is None:
        raise HTTPException(404, "Imóvel não encontrado.")
    return item


def _person(db: Session, org: UUID, person_id: UUID | None) -> Person | None:
    if person_id is None:
        return None
    item = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == org, Person.is_active.is_(True)))
    if item is None:
        raise HTTPException(422, "Solicitante inválido.")
    return item


def _lease(db: Session, org: UUID, lease_id: UUID | None, property_id: UUID) -> LeaseContract | None:
    if lease_id is None:
        return None
    item = db.scalar(select(LeaseContract).where(LeaseContract.id == lease_id, LeaseContract.organization_id == org))
    if item is None or item.property_id != property_id:
        raise HTTPException(422, "Contrato de locação não pertence ao imóvel informado.")
    return item


def _partner(db: Session, org: UUID, partner_id: UUID) -> MaintenancePartner:
    item = db.scalar(select(MaintenancePartner).where(MaintenancePartner.id == partner_id, MaintenancePartner.organization_id == org, MaintenancePartner.is_active.is_(True)))
    if item is None:
        raise HTTPException(422, "Parceiro terceirizado não encontrado ou inativo.")
    return item


def _partner_snapshot(item: MaintenancePartner) -> dict:
    return {"id": str(item.id), "code": f"PAR-{item.internal_number:06d}", "name": item.name, "legal_name": item.legal_name, "document_number": item.document_number, "contact_name": item.contact_name, "email": item.email, "phone": item.phone, "whatsapp": item.whatsapp, "address": deepcopy(item.address or {}), "specialties": deepcopy(item.specialties or []), "pix_key": item.pix_key, "bank_details": deepcopy(item.bank_details or {}), "logo_storage_reference": item.logo_storage_reference, "logo_content_type": item.logo_content_type}


def _selected(item: MaintenanceRequest) -> dict | None:
    return next((dict(q) for q in list(item.quotes or []) if q.get("id") == item.selected_quote_id), None) if item.selected_quote_id else None


def _totals(item: MaintenanceRequest) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    quote = _selected(item)
    if not quote:
        return None, None, None
    partner = money(quote.get("partner_cost_total") or quote.get("amount"))
    client = money(quote.get("client_price_total") if quote.get("client_price_total") is not None else partner)
    return partner, client, money(client - partner)


def _finance_status(db: Session, item: MaintenanceRequest) -> str | None:
    rows = db.scalars(select(MaintenanceFinancialEntry).where(MaintenanceFinancialEntry.maintenance_request_id == item.id)).all()
    if not rows:
        return None
    values = {row.status for row in rows}
    if values <= {"settled", "cancelled"}:
        return "settled"
    return "partial" if "partial" in values else "pending"


def _response(db: Session, item: MaintenanceRequest) -> MaintenanceV2Response:
    prop = db.get(Property, item.property_id)
    lease = db.get(LeaseContract, item.lease_contract_id) if item.lease_contract_id else None
    requester = db.get(Person, item.requester_person_id) if item.requester_person_id else None
    partner, client, margin = _totals(item)
    return MaintenanceV2Response(id=item.id, internal_number=item.internal_number, code=maintenance_code(item), property_id=item.property_id, property_code=f"{prop.internal_number:06d}" if prop else "—", property_title=(prop.public_title or f"Imóvel {prop.internal_number:06d}") if prop else "Imóvel", property_address=dict(prop.address or {}) if prop else {}, lease_contract_id=item.lease_contract_id, lease_code=lease_contract_code(lease) if lease else None, requester_person_id=item.requester_person_id, requester_name=requester.name if requester else None, title=item.title, category=item.category, priority=item.priority, status=item.status, description=item.description, responsibility=item.responsibility, services=deepcopy(item.services or []), selected_quote_id=item.selected_quote_id, quotes=deepcopy(item.quotes or []), history=deepcopy(item.history or []), partner_cost_total=partner, client_charge_total=client, margin_total=margin, finance_status=_finance_status(db, item), reported_at=item.reported_at, scheduled_at=item.scheduled_at, started_at=item.started_at, completed_at=item.completed_at, approved_at=item.approved_at, cancelled_at=item.cancelled_at, cancellation_reason=item.cancellation_reason, notes=item.notes, created_at=item.created_at, updated_at=item.updated_at)


def _apply(db: Session, org: UUID, item: MaintenanceRequest, payload: MaintenanceOpenRequest | MaintenanceEditRequest) -> None:
    _property(db, org, payload.property_id); _lease(db, org, payload.lease_contract_id, payload.property_id); _person(db, org, payload.requester_person_id)
    item.property_id = payload.property_id; item.lease_contract_id = payload.lease_contract_id; item.requester_person_id = payload.requester_person_id
    item.title = payload.title.strip(); item.category = payload.category; item.priority = payload.priority; item.description = payload.description.strip(); item.notes = _clean(payload.notes)
    if isinstance(payload, MaintenanceEditRequest):
        item.responsibility = payload.responsibility


def _financial_entries(db: Session, item: MaintenanceRequest, context: UserContext) -> None:
    quote = _selected(item)
    if not quote:
        raise HTTPException(409, "Selecione e aprove um orçamento antes de concluir a manutenção.")
    partner_total = money(quote.get("partner_cost_total") or quote.get("amount")); client_total = money(quote.get("client_price_total") if quote.get("client_price_total") is not None else partner_total)
    margin = money(client_total - partner_total) if item.responsibility != "agency" else money(-partner_total)
    partner_data = dict(quote.get("partner_snapshot") or {}); partner_id = UUID(str(quote["partner_id"])) if quote.get("partner_id") else None
    snapshot = {"maintenance_code": maintenance_code(item), "quote_code": quote.get("quote_code"), "quote_id": quote.get("id"), "items": deepcopy(quote.get("items") or []), "partner_cost_total": str(partner_total), "client_price_total": str(client_total), "margin_total": str(margin)}
    payable = db.scalar(select(MaintenanceFinancialEntry).where(MaintenanceFinancialEntry.maintenance_request_id == item.id, MaintenanceFinancialEntry.direction == "payable"))
    if payable is None:
        db.add(MaintenanceFinancialEntry(organization_id=item.organization_id, maintenance_request_id=item.id, property_id=item.property_id, lease_contract_id=item.lease_contract_id, direction="payable", counterparty_type="partner", counterparty_id=partner_id, counterparty_name=str(partner_data.get("name") or quote.get("supplier_name") or "Parceiro"), responsibility="partner", collection_method="partner_payment", amount=partner_total, settled_amount=Decimal("0.00"), margin_amount=margin, status="pending", due_date=date.today(), source_snapshot=snapshot, created_by_user_id=context.user.id))
    elif payable.status not in {"settled", "partial"}:
        payable.counterparty_id = partner_id; payable.counterparty_name = str(partner_data.get("name") or quote.get("supplier_name") or "Parceiro"); payable.amount = partner_total; payable.margin_amount = margin; payable.status = "pending"; payable.source_snapshot = snapshot
    receivable = db.scalar(select(MaintenanceFinancialEntry).where(MaintenanceFinancialEntry.maintenance_request_id == item.id, MaintenanceFinancialEntry.direction == "receivable"))
    if item.responsibility in {"owner", "tenant"} and client_total > 0:
        method = "owner_repasse_deduction" if item.responsibility == "owner" else "tenant_reimbursement"; name = "Proprietário(s)" if item.responsibility == "owner" else "Locatário(s)"
        if receivable is None:
            db.add(MaintenanceFinancialEntry(organization_id=item.organization_id, maintenance_request_id=item.id, property_id=item.property_id, lease_contract_id=item.lease_contract_id, direction="receivable", counterparty_type=item.responsibility, counterparty_name=name, responsibility=item.responsibility, collection_method=method, amount=client_total, settled_amount=Decimal("0.00"), margin_amount=margin, status="pending", due_date=date.today(), source_snapshot=snapshot, created_by_user_id=context.user.id))
        elif receivable.status not in {"settled", "partial"}:
            receivable.counterparty_type = item.responsibility; receivable.counterparty_name = name; receivable.responsibility = item.responsibility; receivable.collection_method = method; receivable.amount = client_total; receivable.margin_amount = margin; receivable.status = "pending"; receivable.source_snapshot = snapshot
    elif receivable is not None and receivable.status not in {"settled", "partial"}:
        receivable.status = "cancelled"; receivable.notes = "A imobiliária assumiu o custo; não há cobrança externa."


@router.get("/maintenance-v2", response_model=list[MaintenanceV2Response])
def list_v2(property_id: UUID | None = None, context: UserContext = Depends(require_permission("maintenance.view")), db: Session = Depends(get_db)) -> list[MaintenanceV2Response]:
    stmt = select(MaintenanceRequest).where(MaintenanceRequest.organization_id == context.user.organization_id)
    if property_id: stmt = stmt.where(MaintenanceRequest.property_id == property_id)
    return [_response(db, item) for item in db.scalars(stmt.order_by(MaintenanceRequest.internal_number.desc()).limit(300)).all()]


@router.post("/maintenance-v2", response_model=MaintenanceV2Response, status_code=status.HTTP_201_CREATED)
def create_v2(payload: MaintenanceOpenRequest, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceV2Response:
    item = MaintenanceRequest(organization_id=context.user.organization_id, property_id=payload.property_id, title=payload.title.strip(), description=payload.description.strip(), responsibility="owner", approval_required=True, services=[], quotes=[], history=[], created_by_user_id=context.user.id)
    _apply(db, context.user.organization_id, item, payload); db.add(item); db.flush(); _history(item, context, "Chamado aberto", item.title); _audit(db, request, context, item, "maintenance.created", after={"status": item.status, "property_id": str(item.property_id)}); db.commit(); db.refresh(item); return _response(db, item)


@router.put("/maintenance-v2/{item_id}", response_model=MaintenanceV2Response)
def update_v2(item_id: UUID, payload: MaintenanceEditRequest, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceV2Response:
    item = _load(db, context.user.organization_id, item_id)
    if item.status in TERMINAL: raise HTTPException(409, "Chamado concluído ou cancelado não pode ser editado.")
    before = {"title": item.title, "priority": item.priority, "responsibility": item.responsibility}; _apply(db, context.user.organization_id, item, payload); _history(item, context, "Chamado atualizado"); _audit(db, request, context, item, "maintenance.updated", before=before, after={"title": item.title, "priority": item.priority, "responsibility": item.responsibility}); db.commit(); db.refresh(item); return _response(db, item)


def _scope_locked(item: MaintenanceRequest) -> bool:
    return item.status in QUOTE_LOCKED or bool(item.selected_quote_id) or any(q.get("status") != "superseded" for q in list(item.quotes or []))


@router.post("/maintenance-v2/{item_id}/services", response_model=MaintenanceV2Response)
def add_service(item_id: UUID, payload: MaintenanceServiceInput, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceV2Response:
    item = _load(db, context.user.organization_id, item_id)
    if _scope_locked(item): raise HTTPException(409, "Já existem orçamentos ativos. Retorne à triagem antes de alterar o escopo.")
    service = {"id": str(uuid.uuid4()), "title": payload.title.strip(), "description": _clean(payload.description), "quantity": str(payload.quantity), "unit": payload.unit.strip(), "created_at": datetime.now(timezone.utc).isoformat(), "created_by_user_id": str(context.user.id)}
    item.services = [*list(item.services or []), service]
    if item.status == "requested": item.status = "triage"
    _history(item, context, "Serviço incluído", service["title"]); _audit(db, request, context, item, "maintenance.service_added", after={"service_id": service["id"]}); db.commit(); db.refresh(item); return _response(db, item)


@router.put("/maintenance-v2/{item_id}/services/{service_id}", response_model=MaintenanceV2Response)
def update_service(item_id: UUID, service_id: UUID, payload: MaintenanceServiceInput, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceV2Response:
    item = _load(db, context.user.organization_id, item_id)
    if _scope_locked(item): raise HTTPException(409, "O escopo não pode ser alterado depois que existem orçamentos ativos.")
    services = deepcopy(list(item.services or [])); target = next((s for s in services if s.get("id") == str(service_id)), None)
    if target is None: raise HTTPException(404, "Serviço não encontrado.")
    target.update({"title": payload.title.strip(), "description": _clean(payload.description), "quantity": str(payload.quantity), "unit": payload.unit.strip()}); item.services = services
    _history(item, context, "Serviço atualizado", target["title"]); _audit(db, request, context, item, "maintenance.service_updated", after={"service_id": str(service_id)}); db.commit(); db.refresh(item); return _response(db, item)


@router.delete("/maintenance-v2/{item_id}/services/{service_id}", response_model=MaintenanceV2Response)
def delete_service(item_id: UUID, service_id: UUID, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceV2Response:
    item = _load(db, context.user.organization_id, item_id)
    if _scope_locked(item): raise HTTPException(409, "O escopo não pode ser alterado depois que existem orçamentos ativos.")
    services = list(item.services or []); removed = next((s for s in services if s.get("id") == str(service_id)), None)
    if removed is None: raise HTTPException(404, "Serviço não encontrado.")
    item.services = [s for s in services if s.get("id") != str(service_id)]; _history(item, context, "Serviço removido", str(removed.get("title") or "")); _audit(db, request, context, item, "maintenance.service_removed", after={"service_id": str(service_id)}); db.commit(); db.refresh(item); return _response(db, item)


@router.post("/maintenance-v2/{item_id}/quotes", response_model=MaintenanceV2Response)
def create_quote(item_id: UUID, payload: MaintenanceQuoteV2Create, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceV2Response:
    item = _load(db, context.user.organization_id, item_id)
    if item.status in QUOTE_LOCKED or item.selected_quote_id: raise HTTPException(409, "O orçamento selecionado/aprovado já está congelado.")
    services = list(item.services or [])
    if not services: raise HTTPException(409, "Inclua os serviços antes de solicitar orçamentos.")
    by_id = {str(s.get("id")): s for s in services}; ids = [str(line.service_id) for line in payload.items]
    if len(ids) != len(set(ids)) or set(ids) != set(by_id): raise HTTPException(422, "Preencha custo e preço para todos os serviços, uma única vez.")
    partner = _partner(db, context.user.organization_id, payload.partner_id); rows = []; partner_total = Decimal("0"); client_total = Decimal("0")
    for line in payload.items:
        service = by_id[str(line.service_id)]; pc = money(line.partner_cost); cp = money(line.client_price); partner_total += pc; client_total += cp
        rows.append({"service_id": str(line.service_id), "title": str(service.get("title") or "Serviço"), "description": service.get("description"), "quantity": str(service.get("quantity") or "1"), "unit": str(service.get("unit") or "serviço"), "partner_cost": str(pc), "client_price": str(cp), "margin": str(money(cp - pc))})
    partner_total = money(partner_total); client_total = money(client_total)
    if partner_total <= 0: raise HTTPException(422, "O custo total do parceiro precisa ser maior que zero.")
    quote = {"id": str(uuid.uuid4()), "quote_code": f"{maintenance_code(item)}-ORC-{len(list(item.quotes or []))+1:02d}", "partner_id": str(partner.id), "partner_snapshot": _partner_snapshot(partner), "supplier_person_id": None, "supplier_name": partner.name, "amount": str(partner_total), "partner_cost_total": str(partner_total), "client_price_total": str(client_total), "margin_total": str(money(client_total-partner_total)), "items": rows, "description": f"{len(rows)} serviço(s) cotado(s)", "valid_until": payload.valid_until.isoformat() if payload.valid_until else None, "payment_terms": _clean(payload.payment_terms), "notes": _clean(payload.notes), "status": "proposed", "created_at": datetime.now(timezone.utc).isoformat()}
    item.quotes = [*list(item.quotes or []), quote]; item.status = "awaiting_quote"; _history(item, context, "Orçamento incluído", f"{partner.name} · custo R$ {partner_total} · cliente R$ {client_total}"); _audit(db, request, context, item, "maintenance.quote_added_v2", after={"quote_id": quote["id"], "partner_id": str(partner.id), "partner_cost": str(partner_total), "client_price": str(client_total)}); db.commit(); db.refresh(item); return _response(db, item)


@router.post("/maintenance-v2/{item_id}/quotes/{quote_id}/select", response_model=MaintenanceV2Response)
def select_quote(item_id: UUID, quote_id: UUID, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceV2Response:
    item = _load(db, context.user.organization_id, item_id)
    if item.status in QUOTE_LOCKED: raise HTTPException(409, "A execução já foi aprovada; o orçamento não pode mais ser trocado.")
    quotes = deepcopy(list(item.quotes or [])); selected = None
    for q in quotes:
        if q.get("id") == str(quote_id):
            if q.get("status") == "superseded": raise HTTPException(409, "Este orçamento foi substituído.")
            q["status"] = "selected"; selected = q
        elif q.get("status") in {"selected", "approved"}: q["status"] = "rejected"
    if selected is None: raise HTTPException(404, "Orçamento não encontrado.")
    item.quotes = quotes; item.selected_quote_id = str(quote_id); item.approved_cost = money(selected.get("partner_cost_total") or selected.get("amount")); item.status = "awaiting_approval"
    _history(item, context, "Orçamento selecionado", f"{selected.get('supplier_name')} · custo R$ {item.approved_cost}"); _audit(db, request, context, item, "maintenance.quote_selected_v2", after={"quote_id": str(quote_id), "partner_cost": str(item.approved_cost)}); db.commit(); db.refresh(item); return _response(db, item)


@router.get("/maintenance-v2/{item_id}/quotes/{quote_id}/pdf")
def quote_pdf(item_id: UUID, quote_id: UUID, context: UserContext = Depends(require_permission("maintenance.view")), db: Session = Depends(get_db)) -> Response:
    item = _load(db, context.user.organization_id, item_id); quote = next((deepcopy(q) for q in list(item.quotes or []) if q.get("id") == str(quote_id)), None)
    if quote is None: raise HTTPException(404, "Orçamento não encontrado.")
    if not quote.get("partner_snapshot"): raise HTTPException(422, "O orçamento precisa estar vinculado a um parceiro cadastrado.")
    prop = _property(db, context.user.organization_id, item.property_id); logo = None; ref = dict(quote.get("partner_snapshot") or {}).get("logo_storage_reference")
    if ref:
        try: logo = get_document_storage().download_bytes(str(ref))
        except DocumentStorageError: logo = None
    pdf = build_maintenance_quote_pdf(maintenance=item, property_item=prop, quote=quote, logo_bytes=logo); filename = f"{quote.get('quote_code') or maintenance_code(item)}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"})


@router.post("/maintenance-v2/{item_id}/workflow", response_model=MaintenanceV2Response)
def workflow(item_id: UUID, payload: MaintenanceWorkflowV2, request: Request, context: UserContext = Depends(require_permission("maintenance.manage")), db: Session = Depends(get_db)) -> MaintenanceV2Response:
    item = _load(db, context.user.organization_id, item_id); before = {"status": item.status}; now = datetime.now(timezone.utc); action = payload.action
    if action == "triage":
        if item.status != "requested": raise HTTPException(409, "Somente chamados novos podem entrar em triagem.")
        item.status = "triage"
    elif action == "request_quotes":
        if item.status not in {"triage", "awaiting_quote"}: raise HTTPException(409, "O chamado não está em definição de serviços/orçamentos.")
        if not item.services: raise HTTPException(409, "Inclua ao menos um serviço antes de solicitar orçamentos.")
        item.status = "awaiting_quote"
    elif action == "approve":
        if item.status != "awaiting_approval" or not item.selected_quote_id: raise HTTPException(409, "Selecione um orçamento antes de aprovar a execução.")
        quotes = deepcopy(list(item.quotes or [])); selected = next((q for q in quotes if q.get("id") == item.selected_quote_id), None)
        if selected is None: raise HTTPException(409, "O orçamento selecionado não foi encontrado.")
        selected["status"] = "approved"; item.quotes = quotes; item.approved_cost = money(selected.get("partner_cost_total") or selected.get("amount")); item.status = "approved"; item.approved_at = now; item.approved_by_user_id = context.user.id
    elif action == "schedule":
        if item.status != "approved": raise HTTPException(409, "A execução precisa estar aprovada antes do agendamento.")
        if payload.scheduled_at is None: raise HTTPException(422, "Informe a data e hora do serviço.")
        item.scheduled_at = payload.scheduled_at; item.status = "scheduled"
    elif action == "start":
        if item.status not in {"approved", "scheduled"}: raise HTTPException(409, "A manutenção ainda não está pronta para execução.")
        item.status = "in_progress"; item.started_at = now
    elif action == "complete":
        if item.status not in {"approved", "scheduled", "in_progress"}: raise HTTPException(409, "A manutenção não está em execução.")
        if item.responsibility == "pending": raise HTTPException(409, "Defina quem é responsável pelo custo antes de concluir.")
        quote = _selected(item)
        if not quote or quote.get("status") != "approved": raise HTTPException(409, "A manutenção precisa ter um orçamento aprovado.")
        item.status = "completed"; item.completed_at = now; item.completed_by_user_id = context.user.id; item.actual_cost = money(quote.get("partner_cost_total") or quote.get("amount")); _financial_entries(db, item, context)
    elif action == "cancel":
        if item.status in TERMINAL: raise HTTPException(409, "Chamado já encerrado.")
        if not (payload.reason or "").strip(): raise HTTPException(422, "Informe o motivo do cancelamento.")
        item.status = "cancelled"; item.cancelled_at = now; item.cancellation_reason = payload.reason.strip()
    elif action == "return_triage":
        if item.status not in {"awaiting_quote", "awaiting_approval", "approved", "scheduled"}: raise HTTPException(409, "Não é possível retornar este chamado para triagem.")
        item.status = "triage"; item.approved_at = None; item.approved_by_user_id = None; item.approved_cost = None; item.selected_quote_id = None; quotes = deepcopy(list(item.quotes or []))
        for q in quotes:
            if q.get("status") != "superseded": q["status"] = "superseded"
        item.quotes = quotes
    else: raise HTTPException(422, "Ação inválida.")
    labels = {"triage": "Triagem iniciada", "request_quotes": "Escopo liberado para orçamentos", "approve": "Execução aprovada", "schedule": "Serviço agendado", "start": "Execução iniciada", "complete": "Manutenção concluída e enviada ao Financeiro", "cancel": "Chamado cancelado", "return_triage": "Retornado para triagem"}
    _history(item, context, labels[action], payload.reason); _audit(db, request, context, item, f"maintenance.v2.{action}", before=before, after={"status": item.status, "responsibility": item.responsibility}, reason=payload.reason); db.commit(); db.refresh(item); return _response(db, item)
