from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.core import database
from app.domains.communications.models import CommunicationMessage, CommunicationTemplate
from app.domains.communications.service import _create_suggestion, _person_from_snapshot, money
from app.domains.finance.core_models import FinancialTitle
from app.domains.foundation.models import Organization
from app.domains.lease_lifecycle.models import LeaseLifecycleCase
from app.domains.leases.models import LeaseContract


logger = logging.getLogger(__name__)
_SESSION_EVENTS_KEY = "lease_exit_communication_events"
_INSTALLED = False
_FINANCIAL_EXIT_ORIGINS = frozenset({"lease_exit_adjustment", "lease_termination_fine"})
_FINANCIAL_CLOSED_STATUSES = frozenset({"paid", "settled", "settled_zero", "cancelled"})

LEASE_EXIT_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "key": "lease_exit_requested",
        "name": "Desocupação solicitada",
        "subject": "Desocupação do contrato {{lease_code}} · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nFoi registrado o início do processo de desocupação do contrato {{lease_code}}, com data efetiva prevista para {{reference_date}}. A equipe acompanhará vistoria, entrega de chaves e acerto final antes do encerramento.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "lease_exit_keys_returned",
        "name": "Chaves devolvidas",
        "subject": "Devolução de chaves · {{lease_code}} · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nA devolução das chaves do contrato {{lease_code}} foi registrada. O processo segue agora para conferência do acerto financeiro final antes do encerramento definitivo.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "lease_exit_financial_pending",
        "name": "Pendência do acerto final",
        "subject": "Acerto final do contrato {{lease_code}} · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nFoi registrada uma pendência no acerto final do contrato {{lease_code}}: {{description}}, no valor de {{amount}}, com vencimento em {{due_date}}. Esta comunicação deve ser revisada pela equipe antes do envio.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "lease_exit_financial_resolved",
        "name": "Atualização do acerto final",
        "subject": "Atualização do acerto final · {{lease_code}} · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nA pendência \"{{description}}\", vinculada ao acerto final do contrato {{lease_code}}, não está mais em aberto. A equipe continuará a conferência dos demais requisitos para encerramento da locação.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "lease_exit_closed",
        "name": "Locação encerrada",
        "subject": "Encerramento do contrato {{lease_code}} · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nO processo de desocupação do contrato {{lease_code}} foi concluído no ERP após a vistoria final, devolução das chaves e conferências obrigatórias do acerto. Consulte a equipe caso precise de documentos ou esclarecimentos adicionais.\n\nAtenciosamente,\n{{organization_name}}",
    },
    {
        "key": "lease_exit_cancelled",
        "name": "Desocupação cancelada",
        "subject": "Desocupação cancelada · {{lease_code}} · {{organization_name}}",
        "body": "Olá, {{recipient_name}}.\n\nO processo de desocupação vinculado ao contrato {{lease_code}} foi cancelado no ERP. A locação permanece sujeita ao estado atual do contrato e às orientações da equipe.\n\nAtenciosamente,\n{{organization_name}}",
    },
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ensure_templates(db: Session, organization_id, user_id=None) -> None:
    keys = tuple(definition["key"] for definition in LEASE_EXIT_TEMPLATES)
    existing = set(
        db.scalars(
            select(CommunicationTemplate.key).where(
                CommunicationTemplate.organization_id == organization_id,
                CommunicationTemplate.channel == "email",
                CommunicationTemplate.key.in_(keys),
            )
        ).all()
    )
    changed = False
    for definition in LEASE_EXIT_TEMPLATES:
        if definition["key"] in existing:
            continue
        db.add(
            CommunicationTemplate(
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
        )
        changed = True
    if changed:
        db.flush()


def _remember(session: Session, payload: dict) -> None:
    rows = session.info.setdefault(_SESSION_EVENTS_KEY, [])
    signature = (payload.get("kind"), payload.get("source_id"), payload.get("event"))
    if any((row.get("kind"), row.get("source_id"), row.get("event")) == signature for row in rows):
        return
    rows.append(payload)


def _financial_origin(item: FinancialTitle) -> str | None:
    origin = str((item.source_snapshot or {}).get("origin") or "").strip()
    return origin if origin in _FINANCIAL_EXIT_ORIGINS else None


def _collect_events(session: Session, flush_context, instances) -> None:
    for item in list(session.new) + list(session.dirty):
        if isinstance(item, LeaseLifecycleCase):
            if item.process_type != "termination":
                continue
            state = inspect(item)
            status_changed = item in session.new or state.attrs.status.history.has_changes()
            keys_changed = state.attrs.keys_returned_at.history.has_changes()
            event_name = None
            event_at = None
            if keys_changed and item.keys_returned_at is not None:
                event_name = "keys_returned"
                event_at = item.keys_returned_at
            elif status_changed and item.status == "termination_requested":
                event_name = "requested"
                event_at = item.requested_at or datetime.now(timezone.utc)
            elif status_changed and item.status == "closed":
                event_name = "closed"
                event_at = item.closed_at or datetime.now(timezone.utc)
            elif status_changed and item.status == "cancelled":
                event_name = "cancelled"
                event_at = datetime.now(timezone.utc)
            if event_name is None:
                continue
            if item.id is None:
                item.id = uuid.uuid4()
            _remember(
                session,
                {
                    "kind": "lifecycle",
                    "organization_id": str(item.organization_id),
                    "source_id": str(item.id),
                    "event": event_name,
                    "event_at": _as_utc(event_at).isoformat(),
                    "user_id": str(item.closed_by_user_id or item.created_by_user_id or ""),
                },
            )
            continue

        if not isinstance(item, FinancialTitle) or _financial_origin(item) is None:
            continue
        state = inspect(item)
        if item not in session.new and not state.attrs.status.history.has_changes():
            continue
        if item.id is None:
            item.id = uuid.uuid4()
        if item.status in _FINANCIAL_CLOSED_STATUSES:
            event_name = "resolved"
            event_at = item.settled_at or datetime.now(timezone.utc)
        elif item.status == "pending":
            event_name = "pending"
            event_at = item.created_at or datetime.now(timezone.utc)
        else:
            continue
        _remember(
            session,
            {
                "kind": "financial",
                "organization_id": str(item.organization_id),
                "source_id": str(item.id),
                "event": event_name,
                "event_at": _as_utc(event_at).isoformat(),
                "user_id": str(item.created_by_user_id or ""),
            },
        )


def _recipient_token(recipient: tuple) -> str:
    raw = str(recipient[0] or recipient[2] or recipient[3] or recipient[1]).strip().lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _lease_parties(db: Session, lease: LeaseContract, *, include_owners: bool = True) -> list[tuple[tuple, str]]:
    targets: dict[str, tuple[tuple, str]] = {}
    pairs = [("tenant", list(lease.tenant_snapshot or []))]
    if include_owners:
        pairs.append(("owner", list(lease.owner_snapshot or [])))
    for role, rows in pairs:
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            recipient = _person_from_snapshot(db, lease.organization_id, entry)
            targets.setdefault(_recipient_token(recipient), (recipient, role))
    return list(targets.values())


def _append_detail(message: CommunicationMessage, detail: str) -> None:
    message.body = f"{message.body.rstrip()}\n\nDados do evento no ERP: {detail}"


def _event_payload(*, kind: str, organization_id, source_id, event_name: str, event_at: datetime, user_id) -> dict:
    return {
        "kind": kind,
        "organization_id": str(organization_id),
        "source_id": str(source_id),
        "event": event_name,
        "event_at": _as_utc(event_at).isoformat(),
        "user_id": str(user_id or ""),
    }


def _lifecycle_suggestions(db: Session, payload: dict) -> list[CommunicationMessage]:
    try:
        organization_id = uuid.UUID(payload["organization_id"])
        source_id = uuid.UUID(payload["source_id"])
        event_name = str(payload["event"])
        event_at = datetime.fromisoformat(payload["event_at"])
        user_id = uuid.UUID(payload["user_id"]) if payload.get("user_id") else None
    except (KeyError, TypeError, ValueError):
        return []
    case = db.get(LeaseLifecycleCase, source_id)
    if case is None or case.organization_id != organization_id or case.process_type != "termination":
        return []
    lease = db.get(LeaseContract, case.lease_contract_id)
    if lease is None or lease.organization_id != organization_id:
        return []
    template_key = {
        "requested": "lease_exit_requested",
        "keys_returned": "lease_exit_keys_returned",
        "closed": "lease_exit_closed",
        "cancelled": "lease_exit_cancelled",
    }.get(event_name)
    if template_key is None:
        return []
    organization = db.get(Organization, organization_id)
    organization_name = organization.display_name if organization else "Imobiliária"
    lease_code = f"LOC-{lease.internal_number:06d}"
    reference_date = case.effective_date.strftime("%d/%m/%Y") if case.effective_date else "—"
    cycle_token = _as_utc(case.requested_at).isoformat()
    detail = {
        "requested": f"CIC-{case.internal_number:06d} · contrato {lease_code} · desocupação prevista para {reference_date}.",
        "keys_returned": f"CIC-{case.internal_number:06d} · contrato {lease_code} · chaves devolvidas em {_as_utc(event_at).strftime('%d/%m/%Y às %H:%M')} UTC; acerto final em conferência.",
        "closed": f"CIC-{case.internal_number:06d} · contrato {lease_code} · encerramento concluído em {_as_utc(event_at).strftime('%d/%m/%Y às %H:%M')} UTC.",
        "cancelled": f"CIC-{case.internal_number:06d} · contrato {lease_code} · processo de desocupação cancelado.",
    }[event_name]
    created: list[CommunicationMessage] = []
    for recipient, role in _lease_parties(db, lease):
        token = _recipient_token(recipient)
        message = _create_suggestion(
            db,
            organization_id=organization_id,
            user_id=user_id,
            template_key=template_key,
            recipient=recipient,
            recipient_role=role,
            context={
                "organization_name": organization_name,
                "lease_code": lease_code,
                "reference_date": reference_date,
            },
            source_module="contracts",
            source_type="lease_lifecycle_case",
            source_id=str(case.id),
            dedupe_key=f"{template_key}:{case.id}:{cycle_token}:{token}",
        )
        if message is None:
            continue
        _append_detail(message, detail)
        created.append(message)
    return created


def _financial_status_label(status: str) -> str:
    return {
        "paid": "quitada",
        "settled": "quitada",
        "settled_zero": "encerrada sem saldo",
        "cancelled": "cancelada",
    }.get(status, status)


def _financial_suggestions(db: Session, payload: dict) -> list[CommunicationMessage]:
    try:
        organization_id = uuid.UUID(payload["organization_id"])
        source_id = uuid.UUID(payload["source_id"])
        event_name = str(payload["event"])
        user_id = uuid.UUID(payload["user_id"]) if payload.get("user_id") else None
    except (KeyError, TypeError, ValueError):
        return []
    title = db.get(FinancialTitle, source_id)
    if title is None or title.organization_id != organization_id or _financial_origin(title) is None:
        return []
    if title.lease_contract_id is None:
        return []
    lease = db.get(LeaseContract, title.lease_contract_id)
    if lease is None or lease.organization_id != organization_id:
        return []
    template_key = "lease_exit_financial_resolved" if event_name == "resolved" else "lease_exit_financial_pending"
    organization = db.get(Organization, organization_id)
    organization_name = organization.display_name if organization else "Imobiliária"
    lease_code = f"LOC-{lease.internal_number:06d}"
    context = {
        "organization_name": organization_name,
        "lease_code": lease_code,
        "description": title.description,
        "amount": money(title.amount),
        "due_date": title.due_date.strftime("%d/%m/%Y"),
    }
    beneficiary = str((title.source_snapshot or {}).get("beneficiary") or "").strip()
    targets = _lease_parties(db, lease, include_owners=beneficiary == "owner")
    detail = (
        f"FIN-{title.internal_number:06d} · {title.description} · {money(title.amount)} · "
        + (
            f"vencimento {title.due_date.strftime('%d/%m/%Y')}."
            if event_name == "pending"
            else f"situação: {_financial_status_label(title.status)}."
        )
    )
    created: list[CommunicationMessage] = []
    for recipient, role in targets:
        token = _recipient_token(recipient)
        message = _create_suggestion(
            db,
            organization_id=organization_id,
            user_id=user_id,
            template_key=template_key,
            recipient=recipient,
            recipient_role=role,
            context=context,
            source_module="finance",
            source_type="financial_title",
            source_id=str(title.id),
            dedupe_key=f"{template_key}:{title.id}:{token}",
        )
        if message is None:
            continue
        _append_detail(message, detail)
        created.append(message)
    return created


def _refresh_current_suggestions(db: Session, *, organization_id, user_id) -> list[CommunicationMessage]:
    now = datetime.now(timezone.utc)
    created: list[CommunicationMessage] = []
    _ensure_templates(db, organization_id, user_id)

    cases = db.scalars(
        select(LeaseLifecycleCase).where(
            LeaseLifecycleCase.organization_id == organization_id,
            LeaseLifecycleCase.process_type == "termination",
            LeaseLifecycleCase.requested_at >= now - timedelta(days=120),
        )
    ).all()
    for case in cases:
        created.extend(
            _lifecycle_suggestions(
                db,
                _event_payload(
                    kind="lifecycle",
                    organization_id=organization_id,
                    source_id=case.id,
                    event_name="requested",
                    event_at=case.requested_at,
                    user_id=user_id,
                ),
            )
        )
        if case.keys_returned_at is not None and _as_utc(case.keys_returned_at) >= now - timedelta(days=30):
            created.extend(
                _lifecycle_suggestions(
                    db,
                    _event_payload(
                        kind="lifecycle",
                        organization_id=organization_id,
                        source_id=case.id,
                        event_name="keys_returned",
                        event_at=case.keys_returned_at,
                        user_id=user_id,
                    ),
                )
            )
        if case.status == "closed" and case.closed_at is not None and _as_utc(case.closed_at) >= now - timedelta(days=7):
            created.extend(
                _lifecycle_suggestions(
                    db,
                    _event_payload(
                        kind="lifecycle",
                        organization_id=organization_id,
                        source_id=case.id,
                        event_name="closed",
                        event_at=case.closed_at,
                        user_id=user_id,
                    ),
                )
            )
        elif case.status == "cancelled" and _as_utc(case.updated_at) >= now - timedelta(days=7):
            created.extend(
                _lifecycle_suggestions(
                    db,
                    _event_payload(
                        kind="lifecycle",
                        organization_id=organization_id,
                        source_id=case.id,
                        event_name="cancelled",
                        event_at=case.updated_at,
                        user_id=user_id,
                    ),
                )
            )

    titles = db.scalars(
        select(FinancialTitle).where(
            FinancialTitle.organization_id == organization_id,
            FinancialTitle.lease_contract_id.is_not(None),
            FinancialTitle.created_at >= now - timedelta(days=120),
        )
    ).all()
    for title in titles:
        if _financial_origin(title) is None:
            continue
        if title.status in _FINANCIAL_CLOSED_STATUSES:
            event_at = title.settled_at or title.updated_at
            if _as_utc(event_at) < now - timedelta(days=7):
                continue
            event_name = "resolved"
        elif title.status == "pending":
            event_at = title.created_at
            event_name = "pending"
        else:
            continue
        created.extend(
            _financial_suggestions(
                db,
                _event_payload(
                    kind="financial",
                    organization_id=organization_id,
                    source_id=title.id,
                    event_name=event_name,
                    event_at=event_at,
                    user_id=user_id,
                ),
            )
        )
    return created


def _publish_events(session: Session) -> None:
    rows = list(session.info.pop(_SESSION_EVENTS_KEY, []))
    if not rows or database.SessionLocal is None:
        return
    try:
        with database.SessionLocal() as db:
            initialized: set[uuid.UUID] = set()
            for payload in rows:
                organization_id = uuid.UUID(payload["organization_id"])
                user_id = uuid.UUID(payload["user_id"]) if payload.get("user_id") else None
                if organization_id not in initialized:
                    _ensure_templates(db, organization_id, user_id)
                    initialized.add(organization_id)
                if payload.get("kind") == "lifecycle":
                    _lifecycle_suggestions(db, payload)
                elif payload.get("kind") == "financial":
                    _financial_suggestions(db, payload)
            db.commit()
    except Exception:
        logger.exception("Falha ao criar sugestões de comunicação da desocupação após commit da origem.")


def _discard_events(session: Session) -> None:
    session.info.pop(_SESSION_EVENTS_KEY, None)


def _install_refresh_wrapper() -> None:
    from app.api.routes import communications as communication_routes

    current = communication_routes.refresh_suggestions
    if getattr(current, "_lease_exit_refresh_installed", False):
        return

    def refresh_suggestions(
        db: Session,
        *,
        organization_id,
        user_id,
        include_overdue_charges: bool = True,
        include_contracts: bool = True,
        include_owner_repasses: bool = True,
        today=None,
    ) -> list[CommunicationMessage]:
        created = list(
            current(
                db,
                organization_id=organization_id,
                user_id=user_id,
                include_overdue_charges=include_overdue_charges,
                include_contracts=include_contracts,
                include_owner_repasses=include_owner_repasses,
                today=today,
            )
        )
        created.extend(_refresh_current_suggestions(db, organization_id=organization_id, user_id=user_id))
        return created

    setattr(refresh_suggestions, "_lease_exit_refresh_installed", True)
    communication_routes.refresh_suggestions = refresh_suggestions


def install_lease_exit_communication_rules() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    event.listen(Session, "before_flush", _collect_events)
    event.listen(Session, "after_commit", _publish_events)
    event.listen(Session, "after_rollback", _discard_events)
    _install_refresh_wrapper()
    _INSTALLED = True
