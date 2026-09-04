from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.domains.agenda.models import AgendaTask
from app.domains.contracts.models import AdministrationContract
from app.domains.finance.models import RentCharge
from app.domains.foundation.access import UserContext, get_current_user_context
from app.domains.inspections.models import Inspection
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenancePartner, MaintenanceRequest
from app.domains.portfolio.models import Person, Property, PropertyOwner

router = APIRouter(tags=["deep-links"])


MODULE_LABELS = {
    "people": "Pessoas",
    "properties": "Imóveis",
    "contracts": "Contratos",
    "inspections": "Vistorias",
    "maintenance": "Manutenções",
    "finance": "Financeiro",
    "agenda": "Agenda / Tarefas",
}

STATUS_LABELS = {
    "active": "Ativo",
    "draft": "Rascunho",
    "available": "Disponível",
    "reserved": "Reservado",
    "leased": "Locado",
    "inactive": "Inativo",
    "review": "Em revisão",
    "approved": "Aprovado",
    "pending_signature": "Assinatura",
    "signed": "Assinado",
    "cancelled": "Cancelado",
    "ready": "Laudo concluído",
    "contested": "Contestada",
    "finalized": "Finalizada",
    "requested": "Solicitada",
    "scope_defined": "Escopo definido",
    "quoted": "Orçada",
    "awaiting_approval": "Aguardando aprovação",
    "scheduled": "Agendada",
    "in_progress": "Em execução",
    "completed": "Concluído",
    "generated": "Gerada",
    "sent": "Enviada",
    "paid": "Paga",
    "overdue": "Vencida",
    "pending": "Pendente",
    "missed": "Não cumprido",
}

VALUE_LABELS = {
    "apartment": "Apartamento",
    "house": "Casa",
    "commercial": "Comercial",
    "land": "Terreno",
    "studio": "Studio",
    "other": "Outro",
    "rent": "Locação",
    "sale": "Venda",
    "essential": "Essencial",
    "complete": "Completo",
    "custom": "Personalizado",
    "initial": "Inicial",
    "final": "Final",
    "insurance": "Seguro fiança",
    "deposit": "Caução",
    "capitalization": "Título de capitalização",
    "guarantor": "Fiador",
    "none": "Sem garantia",
    "low": "Baixa",
    "normal": "Normal",
    "high": "Alta",
    "urgent": "Urgente",
    "task": "Tarefa",
    "appointment": "Compromisso",
    "visit": "Visita",
    "meeting": "Reunião",
}


def _require(context: UserContext, permission: str) -> None:
    if not context.has(permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permissão necessária: {permission}")


def _code(prefix: str, number: int | None) -> str:
    return f"{prefix}{int(number):06d}" if number is not None else prefix.rstrip("-")


def _address(address: dict[str, Any] | None) -> str:
    value = address or {}
    parts = [value.get("street"), value.get("number"), value.get("neighborhood"), value.get("city"), value.get("state")]
    return ", ".join(str(part).strip() for part in parts if str(part or "").strip()) or "Endereço não informado"


def _money(value: Decimal | float | int | None) -> str:
    if value is None:
        return "—"
    formatted = f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _percent(value: Decimal | float | int | None) -> str:
    if value is None:
        return "—"
    number = float(value)
    formatted = f"{number:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{formatted}%"


def _date(value: date | datetime | None, include_time: bool = False) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M" if include_time else "%d/%m/%Y")
    return value.strftime("%d/%m/%Y")


def _label(value: Any) -> str:
    text = str(value or "").strip()
    return VALUE_LABELS.get(text, text) or "—"


def _detail(label: str, value: Any) -> dict[str, str]:
    text = str(value).strip() if value is not None else ""
    return {"label": label, "value": text or "—"}


def _record(*, kind: str, module: str, code: str, title: str, status_value: str | None, subtitle: str, details: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "kind": kind,
        "module": module,
        "module_label": MODULE_LABELS[module],
        "code": code,
        "title": title,
        "status": status_value,
        "status_label": STATUS_LABELS.get(status_value or "", status_value or ""),
        "subtitle": subtitle,
        "details": details,
        "root_route": f"/app/{module}",
    }


def _not_found() -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro não encontrado")


@router.get("/deep-links/{kind}/{entity_id}")
def resolve_deep_link(
    kind: str,
    entity_id: UUID,
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    organization_id = context.user.organization_id

    if kind == "person":
        _require(context, "properties.view")
        item = db.scalar(
            select(Person)
            .options(selectinload(Person.roles))
            .where(Person.id == entity_id, Person.organization_id == organization_id)
        )
        if item is None:
            _not_found()
        roles = ", ".join(sorted(role.role_key for role in item.roles if role.is_active)) or "Sem papel operacional"
        return _record(
            kind=kind,
            module="people",
            code="PESSOA",
            title=item.name,
            status_value="active" if item.is_active else "inactive",
            subtitle=" · ".join(part for part in (item.document_number or "", item.email or "") if part) or roles,
            details=[
                _detail("CPF/CNPJ", item.document_number),
                _detail("E-mail", item.email),
                _detail("Telefone", item.phone),
                _detail("Papéis", roles),
                _detail("Endereço", _address(item.address)),
                _detail("Cadastro", _date(item.created_at)),
            ],
        )

    if kind == "property":
        _require(context, "properties.view")
        item = db.scalar(
            select(Property)
            .options(selectinload(Property.owners).selectinload(PropertyOwner.person))
            .where(Property.id == entity_id, Property.organization_id == organization_id)
        )
        if item is None:
            _not_found()
        code = _code("", item.internal_number)
        owners = " / ".join(owner.person.name for owner in item.owners if owner.person) or "Proprietário não informado"
        return _record(
            kind=kind,
            module="properties",
            code=code,
            title=item.public_title or f"Imóvel {code}",
            status_value=item.status,
            subtitle=_address(item.address),
            details=[
                _detail("Código", code),
                _detail("Tipo", _label(item.property_type)),
                _detail("Finalidade", _label(item.purpose)),
                _detail("Proprietário(s)", owners),
                _detail("Aluguel", _money(item.rent_amount)),
                _detail("Condomínio", _money(item.condo_amount)),
                _detail("IPTU", _money(item.iptu_amount)),
                _detail("Publicação", "Publicado" if item.publication_enabled else "Não publicado"),
            ],
        )

    if kind == "administration_contract":
        _require(context, "contracts.view")
        item = db.scalar(
            select(AdministrationContract).where(
                AdministrationContract.id == entity_id,
                AdministrationContract.organization_id == organization_id,
            )
        )
        if item is None:
            _not_found()
        code = _code("ADM-", item.internal_number)
        snapshot = item.property_snapshot if isinstance(item.property_snapshot, dict) else {}
        owners = " / ".join(str(row.get("name") or "") for row in (item.owner_snapshot or []) if row.get("name"))
        return _record(
            kind=kind,
            module="contracts",
            code=code,
            title=f"Contrato de administração {code}",
            status_value=item.status,
            subtitle=_address(snapshot.get("address") if isinstance(snapshot, dict) else {}),
            details=[
                _detail("Proprietário(s)", owners),
                _detail("Plano", _label(item.plan)),
                _detail("Administração", _percent(item.admin_fee_percent) if item.admin_fee_type == "percent" else _money(item.admin_fee_amount)),
                _detail("Intermediação", _percent(item.intermediation_percent)),
                _detail("Início", _date(item.start_date)),
                _detail("Fim", _date(item.end_date)),
                _detail("Versão", item.current_version),
                _detail("Assinatura", item.signing_status.replace("_", " ")),
            ],
        )

    if kind == "lease_contract":
        _require(context, "contracts.view")
        item = db.scalar(
            select(LeaseContract).where(
                LeaseContract.id == entity_id,
                LeaseContract.organization_id == organization_id,
            )
        )
        if item is None:
            _not_found()
        code = _code("LOC-", item.internal_number)
        snapshot = item.property_snapshot if isinstance(item.property_snapshot, dict) else {}
        tenants = " / ".join(str(row.get("name") or "") for row in (item.tenant_snapshot or []) if row.get("name"))
        owners = " / ".join(str(row.get("name") or "") for row in (item.owner_snapshot or []) if row.get("name"))
        return _record(
            kind=kind,
            module="contracts",
            code=code,
            title=f"Contrato de locação {code}",
            status_value=item.status,
            subtitle=" · ".join(part for part in (tenants, _address(snapshot.get("address") if isinstance(snapshot, dict) else {})) if part),
            details=[
                _detail("Locatário(s)", tenants),
                _detail("Proprietário(s)", owners),
                _detail("Aluguel", _money(item.rent_amount)),
                _detail("Vencimento mensal", f"Dia {item.due_day}"),
                _detail("Início", _date(item.start_date)),
                _detail("Fim", _date(item.end_date)),
                _detail("Reajuste", f"{item.adjustment_index} · {_date(item.next_adjustment_date)}"),
                _detail("Garantia", _label(item.guarantee_type)),
            ],
        )

    if kind == "inspection":
        _require(context, "inspections.view")
        item = db.scalar(
            select(Inspection).where(Inspection.id == entity_id, Inspection.organization_id == organization_id)
        )
        if item is None:
            _not_found()
        code = _code("VIS-", item.internal_number)
        lease_snapshot = item.lease_snapshot if isinstance(item.lease_snapshot, dict) else {}
        return _record(
            kind=kind,
            module="inspections",
            code=code,
            title=f"Vistoria {code}",
            status_value=item.status,
            subtitle=_address(lease_snapshot.get("property_address") or lease_snapshot.get("address") or {}),
            details=[
                _detail("Tipo", _label(item.inspection_type)),
                _detail("Vistoriador", item.inspector_name),
                _detail("Agendada para", _date(item.scheduled_at, include_time=True)),
                _detail("Realizada em", _date(item.performed_at, include_time=True)),
                _detail("Prazo de contestação", _date(item.contest_deadline, include_time=True)),
                _detail("Versão", item.current_version),
                _detail("Laudo", "Gerado" if item.report_hash else "Ainda aberto"),
            ],
        )

    if kind == "maintenance":
        _require(context, "maintenance.view")
        item = db.scalar(
            select(MaintenanceRequest).where(
                MaintenanceRequest.id == entity_id,
                MaintenanceRequest.organization_id == organization_id,
            )
        )
        if item is None:
            _not_found()
        property_item = db.scalar(
            select(Property).where(Property.id == item.property_id, Property.organization_id == organization_id)
        )
        code = _code("MAN-", item.internal_number)
        property_code = _code("", property_item.internal_number) if property_item else "—"
        return _record(
            kind=kind,
            module="maintenance",
            code=code,
            title=item.title,
            status_value=item.status,
            subtitle=f"Imóvel {property_code} · {_address(property_item.address if property_item else {})}",
            details=[
                _detail("Prioridade", _label(item.priority)),
                _detail("Categoria", item.category),
                _detail("Responsabilidade", item.responsibility),
                _detail("Serviços", len(item.services or [])),
                _detail("Orçamentos", len(item.quotes or [])),
                _detail("Agendamento", _date(item.scheduled_at, include_time=True)),
                _detail("Abertura", _date(item.reported_at, include_time=True)),
                _detail("Descrição", item.description),
            ],
        )

    if kind == "maintenance_partner":
        _require(context, "maintenance.view")
        item = db.scalar(
            select(MaintenancePartner).where(
                MaintenancePartner.id == entity_id,
                MaintenancePartner.organization_id == organization_id,
            )
        )
        if item is None:
            _not_found()
        code = _code("PAR-", item.internal_number)
        return _record(
            kind=kind,
            module="maintenance",
            code=code,
            title=item.name,
            status_value="active" if item.is_active else "inactive",
            subtitle=item.legal_name or item.document_number or "Parceiro terceirizado",
            details=[
                _detail("CPF/CNPJ", item.document_number),
                _detail("Contato", item.contact_name),
                _detail("Telefone", item.phone or item.whatsapp),
                _detail("E-mail", item.email),
                _detail("Especialidades", ", ".join(item.specialties or [])),
                _detail("Chave Pix", item.pix_key),
                _detail("Endereço", _address(item.address)),
            ],
        )

    if kind == "charge":
        _require(context, "finance.view")
        item = db.scalar(
            select(RentCharge).where(RentCharge.id == entity_id, RentCharge.organization_id == organization_id)
        )
        if item is None:
            _not_found()
        code = _code("COB-", item.internal_number)
        tenants = " / ".join(str(row.get("name") or "") for row in (item.tenant_snapshot or []) if row.get("name"))
        property_snapshot = item.property_snapshot if isinstance(item.property_snapshot, dict) else {}
        return _record(
            kind=kind,
            module="finance",
            code=code,
            title=f"Cobrança {code}",
            status_value=item.status,
            subtitle=" · ".join(part for part in (tenants, item.competence.strftime("%m/%Y"), _money(item.gross_amount)) if part),
            details=[
                _detail("Locatário(s)", tenants),
                _detail("Imóvel", _address(property_snapshot.get("address") if isinstance(property_snapshot, dict) else {})),
                _detail("Competência", item.competence.strftime("%m/%Y")),
                _detail("Vencimento", _date(item.due_date)),
                _detail("Aluguel", _money(item.rent_amount)),
                _detail("Total", _money(item.gross_amount)),
                _detail("Pago em", _date(item.paid_at, include_time=True)),
                _detail("Referência", item.payment_reference),
            ],
        )

    if kind == "agenda_task":
        _require(context, "agenda.view")
        item = db.scalar(
            select(AgendaTask).where(AgendaTask.id == entity_id, AgendaTask.organization_id == organization_id)
        )
        if item is None:
            _not_found()
        is_owner = item.assigned_user_id == context.user.id
        if not is_owner and (item.privacy == "private" or not context.has("agenda.manage")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não possui acesso aos detalhes deste agendamento")
        code = _code("TAR-", item.internal_number)
        return _record(
            kind=kind,
            module="agenda",
            code=code,
            title=item.title,
            status_value=item.status,
            subtitle=f"{_date(item.starts_at, include_time=not item.all_day)} · {_label(item.priority)}",
            details=[
                _detail("Tipo", _label(item.kind)),
                _detail("Prioridade", _label(item.priority)),
                _detail("Início", _date(item.starts_at, include_time=not item.all_day)),
                _detail("Fim", _date(item.ends_at, include_time=not item.all_day)),
                _detail("Prazo", _date(item.due_at, include_time=True)),
                _detail("Local", item.location),
                _detail("Descrição", item.description),
                _detail("Origem", item.source_module),
            ],
        )

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tipo de registro não suportado")
