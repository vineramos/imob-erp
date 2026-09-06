from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.communications.models import (
    CommunicationEvent,
    CommunicationMessage,
    CommunicationPreference,
    CommunicationTemplate,
)
from app.domains.finance.models import OwnerRepasse, RentCharge
from app.domains.foundation.models import Organization
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person


DEFAULT_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "key": "rent_overdue",
        "name": "Cobrança em atraso",
        "subject": "Cobrança {{charge_code}} em atraso · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nIdentificamos que a cobrança {{charge_code}}, com vencimento em {{due_date}}, permanece em aberto no valor de {{amount}}.\n\nVocê pode consultar os dados atualizados da cobrança no Portal do Cliente. Caso o pagamento já tenha sido realizado, desconsidere esta mensagem e encaminhe o comprovante para conferência.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "lease_adjustment",
        "name": "Reajuste de locação",
        "subject": "Reajuste do contrato {{lease_code}} · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nO contrato {{lease_code}} possui reajuste previsto para {{reference_date}}, conforme índice {{adjustment_index}}. A atualização será processada pela imobiliária após a disponibilidade do índice aplicável.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "lease_expiry",
        "name": "Contrato próximo do término",
        "subject": "Contrato {{lease_code}} próximo do término · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nO contrato {{lease_code}} tem término previsto para {{reference_date}}. Estamos iniciando o acompanhamento para definir renovação ou encerramento da locação com antecedência.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "lease_signed",
        "name": "Contrato assinado",
        "subject": "Contrato {{lease_code}} assinado · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nO contrato {{lease_code}} foi assinado e registrado no ERP. O documento final e os próximos passos da locação permanecem disponíveis conforme o seu perfil de acesso.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "owner_repasse_paid",
        "name": "Repasse realizado ao proprietário",
        "subject": "Repasse da competência {{competence}} · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nO repasse referente à competência {{competence}} foi registrado como pago no valor de {{amount}}. A prestação de contas correspondente pode ser consultada no Portal do Cliente.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "owner_repasse_overdue",
        "name": "Repasse pendente",
        "subject": "Acompanhamento de repasse · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nO repasse no valor de {{amount}}, previsto para {{due_date}}, permanece em processamento interno. Esta comunicação deve ser revisada pela equipe antes do envio.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "inspection_schedule",
        "name": "Agendamento de vistoria",
        "subject": "Vistoria agendada · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nHá uma vistoria vinculada ao seu contrato. Confira data, horário e orientações no Portal do Cliente ou com a equipe responsável.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "maintenance_update",
        "name": "Atualização de manutenção",
        "subject": "Atualização de manutenção · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nHá uma atualização em um chamado de manutenção relacionado ao imóvel. Consulte o Portal do Cliente para acompanhar as informações disponíveis ao seu perfil.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "manual",
        "name": "Comunicação livre",
        "subject": "{{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\n\n\nAtenciosamente,\n{{organization_name}}",
    },
)

TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def money(value: Any) -> str:
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    rendered = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {rendered}"


def br_date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d/%m/%Y")


def render_template(value: str, context: dict[str, Any]) -> str:
    """Substituição deliberadamente simples: sem eval, filtros ou acesso a atributos."""
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(context.get(key, match.group(0)))
    return TOKEN_RE.sub(replace, value)


def ensure_default_templates(db: Session, organization_id: UUID, user_id: UUID | None = None) -> list[CommunicationTemplate]:
    rows = db.scalars(
        select(CommunicationTemplate).where(
            CommunicationTemplate.organization_id == organization_id,
            CommunicationTemplate.channel == "email",
        )
    ).all()
    existing = {row.key: row for row in rows}
    changed = False
    for definition in DEFAULT_TEMPLATES:
        if definition["key"] in existing:
            continue
        row = CommunicationTemplate(
            organization_id=organization_id,
            key=definition["key"],
            channel="email",
            name=definition["name"],
            subject_template=definition["subject"],
            body_template=definition["body"],
            is_active=True,
            is_system_default=True,
            updated_by_user_id=user_id,
        )
        db.add(row)
        existing[row.key] = row
        changed = True
    if changed:
        db.flush()
    return sorted(existing.values(), key=lambda row: row.name.lower())


def add_event(
    db: Session,
    message: CommunicationMessage,
    event_type: str,
    *,
    user_id: UUID | None = None,
    data: dict[str, Any] | None = None,
) -> CommunicationEvent:
    event = CommunicationEvent(
        organization_id=message.organization_id,
        message_id=message.id,
        event_type=event_type,
        event_data=data or {},
        created_by_user_id=user_id,
    )
    db.add(event)
    return event


def preference_for(db: Session, organization_id: UUID, person_id: UUID | None) -> CommunicationPreference | None:
    if person_id is None:
        return None
    return db.scalar(
        select(CommunicationPreference).where(
            CommunicationPreference.organization_id == organization_id,
            CommunicationPreference.person_id == person_id,
        )
    )


def delivery_block_reason(db: Session, message: CommunicationMessage, *, email_configured: bool) -> str | None:
    if message.status in {"sent", "cancelled"}:
        return "Esta comunicação já foi encerrada."
    preference = preference_for(db, message.organization_id, message.person_id)
    if preference is not None:
        if not preference.transactional_enabled:
            return "A pessoa desativou comunicações transacionais neste cadastro."
        if message.channel == "email" and not preference.email_enabled:
            return "O envio por e-mail está desativado para esta pessoa."
        if message.channel == "whatsapp" and not preference.whatsapp_enabled:
            return "O canal WhatsApp está desativado para esta pessoa."
    if message.channel == "email":
        if not message.recipient_email:
            return "Destinatário sem e-mail cadastrado."
        if not email_configured:
            return "SMTP ainda não está configurado."
        return None
    if message.channel == "whatsapp":
        if not message.recipient_phone:
            return "Destinatário sem telefone cadastrado."
        return "Provider de WhatsApp ainda não está implementado."
    return "Canal de comunicação não suportado."


def _person_from_snapshot(db: Session, organization_id: UUID, entry: dict[str, Any]) -> tuple[UUID | None, str, str | None, str | None]:
    raw_id = entry.get("person_id") or entry.get("id")
    person = None
    if raw_id:
        try:
            person_id = UUID(str(raw_id))
        except (TypeError, ValueError):
            person_id = None
        if person_id:
            candidate = db.get(Person, person_id)
            if candidate is not None and candidate.organization_id == organization_id:
                person = candidate
    return (
        person.id if person else None,
        person.name if person else str(entry.get("name") or "Cliente"),
        person.email if person else (str(entry.get("email") or "").strip() or None),
        person.phone if person else (str(entry.get("phone") or "").strip() or None),
    )


def _template(db: Session, organization_id: UUID, key: str) -> CommunicationTemplate | None:
    return db.scalar(
        select(CommunicationTemplate).where(
            CommunicationTemplate.organization_id == organization_id,
            CommunicationTemplate.key == key,
            CommunicationTemplate.channel == "email",
            CommunicationTemplate.is_active.is_(True),
        )
    )


def _create_suggestion(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    template_key: str,
    recipient: tuple[UUID | None, str, str | None, str | None],
    recipient_role: str,
    context: dict[str, Any],
    source_module: str,
    source_type: str,
    source_id: str,
    dedupe_key: str,
    attachments: list[dict[str, Any]] | None = None,
) -> CommunicationMessage | None:
    if db.scalar(
        select(CommunicationMessage.id).where(
            CommunicationMessage.organization_id == organization_id,
            CommunicationMessage.dedupe_key == dedupe_key,
        )
    ) is not None:
        return None
    template = _template(db, organization_id, template_key)
    if template is None:
        return None
    person_id, name, email, phone = recipient
    payload = {"recipient_name": name, **context}
    now = datetime.now(timezone.utc)
    message = CommunicationMessage(
        organization_id=organization_id,
        person_id=person_id,
        recipient_name=name,
        recipient_email=email,
        recipient_phone=phone,
        recipient_role=recipient_role,
        channel="email",
        category=template_key,
        origin="suggestion",
        subject=render_template(template.subject_template, payload),
        body=render_template(template.body_template, payload),
        status="pending",
        source_module=source_module,
        source_type=source_type,
        source_id=source_id,
        dedupe_key=dedupe_key,
        attachment_manifest=attachments or [],
        suggested_at=now,
        queued_at=now,
        created_by_user_id=user_id,
    )
    db.add(message)
    db.flush()
    add_event(db, message, "suggested", user_id=user_id, data={"category": template_key, "source_id": source_id})
    return message


def refresh_suggestions(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    include_overdue_charges: bool = True,
    include_contracts: bool = True,
    include_owner_repasses: bool = True,
    today: date | None = None,
) -> list[CommunicationMessage]:
    today = today or date.today()
    organization = db.get(Organization, organization_id)
    organization_name = organization.display_name if organization else "Imobiliária"
    ensure_default_templates(db, organization_id, user_id)
    created: list[CommunicationMessage] = []

    if include_overdue_charges:
        charges = db.scalars(
            select(RentCharge).where(
                RentCharge.organization_id == organization_id,
                RentCharge.due_date < today,
                RentCharge.paid_at.is_(None),
                RentCharge.cancelled_at.is_(None),
                RentCharge.status.notin_(("paid", "cancelled")),
            )
        ).all()
        for charge in charges:
            context = {
                "organization_name": organization_name,
                "charge_code": f"COB-{charge.internal_number:06d}",
                "due_date": br_date(charge.due_date),
                "amount": money(charge.gross_amount),
                "competence": charge.competence.strftime("%m/%Y"),
            }
            for entry in list(charge.tenant_snapshot or []):
                if not isinstance(entry, dict):
                    continue
                recipient = _person_from_snapshot(db, organization_id, entry)
                discriminator = str(recipient[0] or recipient[2] or recipient[1]).lower()
                item = _create_suggestion(
                    db,
                    organization_id=organization_id,
                    user_id=user_id,
                    template_key="rent_overdue",
                    recipient=recipient,
                    recipient_role="tenant",
                    context=context,
                    source_module="finance",
                    source_type="rent_charge",
                    source_id=str(charge.id),
                    dedupe_key=f"rent_overdue:{charge.id}:{discriminator}",
                    attachments=[{"kind": "portal_reference", "label": "Cobrança e Pix/boleto no Portal do Cliente", "source_id": str(charge.id)}],
                )
                if item:
                    created.append(item)

    if include_contracts:
        leases = db.scalars(
            select(LeaseContract).where(
                LeaseContract.organization_id == organization_id,
                LeaseContract.status == "signed",
            )
        ).all()
        for lease in leases:
            lease_code = f"LOC-{lease.internal_number:06d}"
            common = {"organization_name": organization_name, "lease_code": lease_code}
            tenant_entries = [row for row in list(lease.tenant_snapshot or []) if isinstance(row, dict)]
            owner_entries = [row for row in list(lease.owner_snapshot or []) if isinstance(row, dict)]

            if lease.signed_at is not None:
                for role, entries in (("tenant", tenant_entries), ("owner", owner_entries)):
                    for entry in entries:
                        recipient = _person_from_snapshot(db, organization_id, entry)
                        discriminator = str(recipient[0] or recipient[2] or recipient[1]).lower()
                        item = _create_suggestion(
                            db,
                            organization_id=organization_id,
                            user_id=user_id,
                            template_key="lease_signed",
                            recipient=recipient,
                            recipient_role=role,
                            context=common,
                            source_module="contracts",
                            source_type="lease_contract",
                            source_id=str(lease.id),
                            dedupe_key=f"lease_signed:{lease.id}:{role}:{discriminator}",
                            attachments=[{"kind": "lease_contract_pdf", "label": f"Contrato {lease_code}", "source_id": str(lease.id)}],
                        )
                        if item:
                            created.append(item)

            adjustment_days = (lease.next_adjustment_date - today).days
            if 0 <= adjustment_days <= 30:
                context = {**common, "reference_date": br_date(lease.next_adjustment_date), "adjustment_index": lease.adjustment_index}
                for entry in tenant_entries:
                    recipient = _person_from_snapshot(db, organization_id, entry)
                    discriminator = str(recipient[0] or recipient[2] or recipient[1]).lower()
                    item = _create_suggestion(
                        db,
                        organization_id=organization_id,
                        user_id=user_id,
                        template_key="lease_adjustment",
                        recipient=recipient,
                        recipient_role="tenant",
                        context=context,
                        source_module="contracts",
                        source_type="lease_contract",
                        source_id=str(lease.id),
                        dedupe_key=f"lease_adjustment:{lease.id}:{lease.next_adjustment_date}:{discriminator}",
                    )
                    if item:
                        created.append(item)

            expiry_days = (lease.end_date - today).days
            if 0 <= expiry_days <= 120:
                bucket = "7" if expiry_days <= 7 else "30" if expiry_days <= 30 else "60" if expiry_days <= 60 else "90" if expiry_days <= 90 else "120"
                context = {**common, "reference_date": br_date(lease.end_date)}
                for role, entries in (("tenant", tenant_entries), ("owner", owner_entries)):
                    for entry in entries:
                        recipient = _person_from_snapshot(db, organization_id, entry)
                        discriminator = str(recipient[0] or recipient[2] or recipient[1]).lower()
                        item = _create_suggestion(
                            db,
                            organization_id=organization_id,
                            user_id=user_id,
                            template_key="lease_expiry",
                            recipient=recipient,
                            recipient_role=role,
                            context=context,
                            source_module="contracts",
                            source_type="lease_contract",
                            source_id=str(lease.id),
                            dedupe_key=f"lease_expiry:{lease.id}:{bucket}:{role}:{discriminator}",
                        )
                        if item:
                            created.append(item)

    if include_owner_repasses:
        repasses = db.scalars(
            select(OwnerRepasse).where(OwnerRepasse.organization_id == organization_id)
        ).all()
        for repasse in repasses:
            person = db.get(Person, repasse.owner_person_id)
            if person is None or person.organization_id != organization_id:
                continue
            recipient = (person.id, person.name, person.email, person.phone)
            charge = db.get(RentCharge, repasse.charge_id)
            competence = charge.competence.strftime("%m/%Y") if charge else "—"
            context = {
                "organization_name": organization_name,
                "recipient_name": person.name,
                "competence": competence,
                "amount": money(repasse.amount),
                "due_date": br_date(repasse.due_date),
            }
            if repasse.status == "paid" and repasse.paid_at is not None:
                key = "owner_repasse_paid"
                dedupe = f"owner_repasse_paid:{repasse.id}"
                attachments = [{"kind": "portal_reference", "label": f"Prestação de contas {competence} no Portal do Cliente", "source_id": str(repasse.id)}]
            elif repasse.status == "pending" and repasse.due_date < today:
                key = "owner_repasse_overdue"
                dedupe = f"owner_repasse_overdue:{repasse.id}"
                attachments = []
            else:
                continue
            item = _create_suggestion(
                db,
                organization_id=organization_id,
                user_id=user_id,
                template_key=key,
                recipient=recipient,
                recipient_role="owner",
                context=context,
                source_module="finance",
                source_type="owner_repasse",
                source_id=str(repasse.id),
                dedupe_key=dedupe,
                attachments=attachments,
            )
            if item:
                created.append(item)

    return created
