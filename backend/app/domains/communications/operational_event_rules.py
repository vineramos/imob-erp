from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.core import database
from app.domains.communications.models import CommunicationMessage
from app.domains.communications.service import _create_suggestion, _person_from_snapshot, ensure_default_templates
from app.domains.foundation.models import Organization
from app.domains.inspections.models import Inspection, InspectionVersion
from app.domains.inspections.pdf import inspection_code
from app.domains.leases.models import LeaseContract
from app.domains.maintenance.models import MaintenanceRequest
from app.domains.portfolio.models import Person


logger = logging.getLogger(__name__)
LOCAL_ZONE = ZoneInfo("America/Sao_Paulo")
_SESSION_EVENTS_KEY = "operational_communication_events"
_INSTALLED = False


def _actor_from_inspection(session: Session, item: Inspection):
    for candidate in session.new:
        if isinstance(candidate, InspectionVersion) and candidate.inspection_id == item.id:
            return candidate.created_by_user_id
    return item.created_by_user_id


def _actor_from_maintenance(item: MaintenanceRequest):
    history = list(item.history or [])
    raw = history[-1].get("user_id") if history and isinstance(history[-1], dict) else None
    if raw:
        try:
            return uuid.UUID(str(raw))
        except (TypeError, ValueError):
            pass
    return item.completed_by_user_id or item.approved_by_user_id or item.created_by_user_id


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _remember(session: Session, payload: dict) -> None:
    rows = session.info.setdefault(_SESSION_EVENTS_KEY, [])
    signature = (payload.get("kind"), payload.get("source_id"), payload.get("event"), payload.get("event_at"))
    if any((row.get("kind"), row.get("source_id"), row.get("event"), row.get("event_at")) == signature for row in rows):
        return
    rows.append(payload)


def _collect_operational_events(session: Session, flush_context, instances) -> None:
    for item in list(session.new) + list(session.dirty):
        if isinstance(item, Inspection):
            state = inspect(item)
            scheduled_history = state.attrs.scheduled_at.history
            scheduled_changed = item in session.new or scheduled_history.has_changes()
            if not scheduled_changed or item.scheduled_at is None or item.status == "cancelled":
                continue
            if item.id is None:
                item.id = uuid.uuid4()
            _remember(
                session,
                {
                    "kind": "inspection_schedule",
                    "organization_id": str(item.organization_id),
                    "source_id": str(item.id),
                    "event": "scheduled",
                    "event_at": _as_utc(item.scheduled_at).isoformat(),
                    "user_id": str(_actor_from_inspection(session, item) or ""),
                },
            )
            continue

        if not isinstance(item, MaintenanceRequest):
            continue
        state = inspect(item)
        status_history = state.attrs.status.history
        if item not in session.new and not status_history.has_changes():
            continue
        if item.status not in {"scheduled", "in_progress", "completed", "cancelled"}:
            continue
        event_at = {
            "scheduled": item.scheduled_at,
            "in_progress": item.started_at,
            "completed": item.completed_at,
            "cancelled": item.cancelled_at,
        }.get(item.status) or datetime.now(timezone.utc)
        if item.id is None:
            item.id = uuid.uuid4()
        _remember(
            session,
            {
                "kind": "maintenance_update",
                "organization_id": str(item.organization_id),
                "source_id": str(item.id),
                "event": item.status,
                "event_at": _as_utc(event_at).isoformat(),
                "user_id": str(_actor_from_maintenance(item) or ""),
            },
        )


def _local_datetime(value: datetime) -> str:
    return _as_utc(value).astimezone(LOCAL_ZONE).strftime("%d/%m/%Y às %H:%M")


def _recipient_token(recipient: tuple) -> str:
    raw = str(recipient[0] or recipient[2] or recipient[3] or recipient[1]).strip().lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _append_safe_event_detail(message: CommunicationMessage, detail: str) -> None:
    message.body = f"{message.body.rstrip()}\n\nDados do evento no ERP: {detail}"


def _inspection_suggestions(db: Session, payload: dict) -> list[CommunicationMessage]:
    try:
        organization_id = uuid.UUID(payload["organization_id"])
        source_id = uuid.UUID(payload["source_id"])
        event_at = datetime.fromisoformat(payload["event_at"])
        user_id = uuid.UUID(payload["user_id"]) if payload.get("user_id") else None
    except (KeyError, TypeError, ValueError):
        return []
    item = db.get(Inspection, source_id)
    if item is None or item.organization_id != organization_id or item.status == "cancelled":
        return []
    organization = db.get(Organization, organization_id)
    organization_name = organization.display_name if organization else "Imobiliária"
    lease_snapshot = dict(item.lease_snapshot or {})
    tenants = [entry for entry in list(lease_snapshot.get("tenants") or []) if isinstance(entry, dict)]
    created: list[CommunicationMessage] = []
    for entry in tenants:
        recipient = _person_from_snapshot(db, organization_id, entry)
        token = _recipient_token(recipient)
        message = _create_suggestion(
            db,
            organization_id=organization_id,
            user_id=user_id,
            template_key="inspection_schedule",
            recipient=recipient,
            recipient_role="tenant",
            context={"organization_name": organization_name},
            source_module="inspections",
            source_type="inspection",
            source_id=str(item.id),
            dedupe_key=f"inspection_schedule:{item.id}:{_as_utc(event_at).isoformat()}:{token}",
        )
        if message is None:
            continue
        lease_code = str(lease_snapshot.get("lease_code") or "—")
        _append_safe_event_detail(
            message,
            f"{inspection_code(item)} · contrato {lease_code} · agendada para {_local_datetime(event_at)}.",
        )
        created.append(message)
    return created


def _maintenance_targets(db: Session, item: MaintenanceRequest) -> list[tuple[tuple, str]]:
    organization_id = item.organization_id
    targets: dict[str, tuple[tuple, str]] = {}
    lease = db.get(LeaseContract, item.lease_contract_id) if item.lease_contract_id else None

    if lease is not None and lease.organization_id == organization_id:
        for entry in [row for row in list(lease.tenant_snapshot or []) if isinstance(row, dict)]:
            recipient = _person_from_snapshot(db, organization_id, entry)
            targets[_recipient_token(recipient)] = (recipient, "tenant")
        if item.responsibility == "owner":
            for entry in [row for row in list(lease.owner_snapshot or []) if isinstance(row, dict)]:
                recipient = _person_from_snapshot(db, organization_id, entry)
                targets[_recipient_token(recipient)] = (recipient, "owner")

    if item.requester_person_id:
        requester = db.get(Person, item.requester_person_id)
        if requester is not None and requester.organization_id == organization_id:
            recipient = (requester.id, requester.name, requester.email, requester.phone)
            token = _recipient_token(recipient)
            targets.setdefault(token, (recipient, "other"))

    return list(targets.values())


def _maintenance_event_detail(item: MaintenanceRequest, event_name: str, event_at: datetime) -> str:
    code = f"MAN-{item.internal_number:06d}"
    title = item.title.strip()
    moment = _local_datetime(event_at)
    if event_name == "scheduled":
        return f"{code} · {title} · serviço agendado para {moment}."
    if event_name == "in_progress":
        return f"{code} · {title} · execução iniciada em {moment}."
    if event_name == "completed":
        return f"{code} · {title} · manutenção concluída em {moment}."
    return f"{code} · {title} · chamado cancelado em {moment}."


def _maintenance_suggestions(db: Session, payload: dict) -> list[CommunicationMessage]:
    try:
        organization_id = uuid.UUID(payload["organization_id"])
        source_id = uuid.UUID(payload["source_id"])
        event_name = str(payload["event"])
        event_at = datetime.fromisoformat(payload["event_at"])
        user_id = uuid.UUID(payload["user_id"]) if payload.get("user_id") else None
    except (KeyError, TypeError, ValueError):
        return []
    item = db.get(MaintenanceRequest, source_id)
    if item is None or item.organization_id != organization_id:
        return []
    organization = db.get(Organization, organization_id)
    organization_name = organization.display_name if organization else "Imobiliária"
    detail = _maintenance_event_detail(item, event_name, event_at)
    created: list[CommunicationMessage] = []
    for recipient, role in _maintenance_targets(db, item):
        token = _recipient_token(recipient)
        message = _create_suggestion(
            db,
            organization_id=organization_id,
            user_id=user_id,
            template_key="maintenance_update",
            recipient=recipient,
            recipient_role=role,
            context={"organization_name": organization_name},
            source_module="maintenance",
            source_type="maintenance_request",
            source_id=str(item.id),
            dedupe_key=f"maintenance_update:{item.id}:{event_name}:{_as_utc(event_at).isoformat()}:{token}",
        )
        if message is None:
            continue
        _append_safe_event_detail(message, detail)
        created.append(message)
    return created


def _event_payload(*, kind: str, organization_id, source_id, event_name: str, event_at: datetime, user_id) -> dict:
    return {
        "kind": kind,
        "organization_id": str(organization_id),
        "source_id": str(source_id),
        "event": event_name,
        "event_at": _as_utc(event_at).isoformat(),
        "user_id": str(user_id or ""),
    }


def _refresh_current_operational_suggestions(
    db: Session,
    *,
    organization_id,
    user_id,
) -> list[CommunicationMessage]:
    now = datetime.now(timezone.utc)
    created: list[CommunicationMessage] = []

    inspections = db.scalars(
        select(Inspection).where(
            Inspection.organization_id == organization_id,
            Inspection.scheduled_at.is_not(None),
            Inspection.status != "cancelled",
        )
    ).all()
    for item in inspections:
        scheduled_at = item.scheduled_at
        if scheduled_at is None:
            continue
        scheduled_utc = _as_utc(scheduled_at)
        if scheduled_utc < now - timedelta(days=1) or scheduled_utc > now + timedelta(days=120):
            continue
        created.extend(
            _inspection_suggestions(
                db,
                _event_payload(
                    kind="inspection_schedule",
                    organization_id=organization_id,
                    source_id=item.id,
                    event_name="scheduled",
                    event_at=scheduled_at,
                    user_id=user_id,
                ),
            )
        )

    maintenance_rows = db.scalars(
        select(MaintenanceRequest).where(
            MaintenanceRequest.organization_id == organization_id,
            MaintenanceRequest.status.in_(("scheduled", "in_progress", "completed", "cancelled")),
        )
    ).all()
    for item in maintenance_rows:
        event_at = {
            "scheduled": item.scheduled_at,
            "in_progress": item.started_at,
            "completed": item.completed_at,
            "cancelled": item.cancelled_at,
        }.get(item.status)
        if event_at is None:
            continue
        event_utc = _as_utc(event_at)
        if item.status == "scheduled" and (event_utc < now - timedelta(days=1) or event_utc > now + timedelta(days=120)):
            continue
        if item.status in {"completed", "cancelled"} and event_utc < now - timedelta(days=7):
            continue
        created.extend(
            _maintenance_suggestions(
                db,
                _event_payload(
                    kind="maintenance_update",
                    organization_id=organization_id,
                    source_id=item.id,
                    event_name=item.status,
                    event_at=event_at,
                    user_id=user_id,
                ),
            )
        )

    return created


def _publish_operational_events(session: Session) -> None:
    rows = list(session.info.pop(_SESSION_EVENTS_KEY, []))
    if not rows or database.SessionLocal is None:
        return
    try:
        with database.SessionLocal() as db:
            for payload in rows:
                organization_id = uuid.UUID(payload["organization_id"])
                user_id = uuid.UUID(payload["user_id"]) if payload.get("user_id") else None
                ensure_default_templates(db, organization_id, user_id)
                if payload.get("kind") == "inspection_schedule":
                    _inspection_suggestions(db, payload)
                elif payload.get("kind") == "maintenance_update":
                    _maintenance_suggestions(db, payload)
            db.commit()
    except Exception:
        logger.exception("Falha ao criar sugestões operacionais de comunicação após commit da origem.")


def _discard_operational_events(session: Session) -> None:
    session.info.pop(_SESSION_EVENTS_KEY, None)


def _install_refresh_wrapper() -> None:
    from app.api.routes import communications as communication_routes

    current = communication_routes.refresh_suggestions
    if getattr(current, "_operational_refresh_installed", False):
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
        created.extend(
            _refresh_current_operational_suggestions(
                db,
                organization_id=organization_id,
                user_id=user_id,
            )
        )
        return created

    setattr(refresh_suggestions, "_operational_refresh_installed", True)
    communication_routes.refresh_suggestions = refresh_suggestions


def install_operational_communication_rules() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    event.listen(Session, "before_flush", _collect_operational_events)
    event.listen(Session, "after_commit", _publish_operational_events)
    event.listen(Session, "after_rollback", _discard_operational_events)
    _install_refresh_wrapper()
    _INSTALLED = True
