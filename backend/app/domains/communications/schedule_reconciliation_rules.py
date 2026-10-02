from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.core import database
from app.domains.communications.models import CommunicationMessage
from app.domains.communications.operational_event_rules import (
    _actor_from_inspection,
    _actor_from_maintenance,
    _as_utc,
    _inspection_suggestions,
    _maintenance_suggestions,
)
from app.domains.communications.service import add_event, ensure_default_templates
from app.domains.inspections.models import Inspection
from app.domains.maintenance.models import MaintenanceRequest


logger = logging.getLogger(__name__)
_SESSION_KEY = "operational_schedule_reconciliation_events"
_INSTALLED = False


def _remember(session: Session, payload: dict) -> None:
    rows = session.info.setdefault(_SESSION_KEY, [])
    signature = (payload.get("kind"), payload.get("source_id"), payload.get("event"), payload.get("event_at"))
    if any((row.get("kind"), row.get("source_id"), row.get("event"), row.get("event_at")) == signature for row in rows):
        return
    rows.append(payload)


def _collect(session: Session, flush_context, instances) -> None:
    for item in list(session.dirty):
        if isinstance(item, Inspection):
            state = inspect(item)
            scheduled_changed = state.attrs.scheduled_at.history.has_changes()
            cancelled_changed = state.attrs.status.history.has_changes() and item.status == "cancelled"
            if not scheduled_changed and not cancelled_changed:
                continue
            if item.id is None:
                continue
            _remember(
                session,
                {
                    "kind": "inspection",
                    "organization_id": str(item.organization_id),
                    "source_id": str(item.id),
                    "event": "cancelled" if item.status == "cancelled" else "scheduled",
                    "event_at": _as_utc(item.scheduled_at).isoformat() if item.scheduled_at is not None and item.status != "cancelled" else None,
                    "user_id": str(_actor_from_inspection(session, item) or ""),
                },
            )
            continue

        if not isinstance(item, MaintenanceRequest):
            continue
        state = inspect(item)
        status_changed = state.attrs.status.history.has_changes()
        schedule_changed = state.attrs.scheduled_at.history.has_changes()
        if not status_changed and not (schedule_changed and item.status == "scheduled"):
            continue
        if item.id is None:
            continue
        event_at = {
            "scheduled": item.scheduled_at,
            "in_progress": item.started_at,
            "completed": item.completed_at,
            "cancelled": item.cancelled_at,
        }.get(item.status)
        _remember(
            session,
            {
                "kind": "maintenance",
                "organization_id": str(item.organization_id),
                "source_id": str(item.id),
                "event": item.status,
                "event_at": _as_utc(event_at).isoformat() if event_at is not None else None,
                "user_id": str(_actor_from_maintenance(item) or ""),
            },
        )


def _supersede(
    db: Session,
    *,
    organization_id: uuid.UUID,
    source_module: str,
    source_type: str,
    source_id: str,
    category: str,
    keep_prefix: str | None,
    user_id: uuid.UUID | None,
    reason: str,
) -> int:
    rows = db.scalars(
        select(CommunicationMessage).where(
            CommunicationMessage.organization_id == organization_id,
            CommunicationMessage.origin == "suggestion",
            CommunicationMessage.source_module == source_module,
            CommunicationMessage.source_type == source_type,
            CommunicationMessage.source_id == source_id,
            CommunicationMessage.category == category,
            CommunicationMessage.status.in_(("pending", "failed")),
        )
    ).all()
    changed = 0
    now = datetime.now(timezone.utc)
    for message in rows:
        if keep_prefix and str(message.dedupe_key or "").startswith(keep_prefix):
            continue
        message.status = "cancelled"
        message.cancelled_at = now
        add_event(
            db,
            message,
            "superseded",
            user_id=user_id,
            data={"reason": reason, "replacement_prefix": keep_prefix},
        )
        changed += 1
    return changed


def _publish(session: Session) -> None:
    rows = list(session.info.pop(_SESSION_KEY, []))
    if not rows or database.SessionLocal is None:
        return
    try:
        with database.SessionLocal() as db:
            for payload in rows:
                organization_id = uuid.UUID(payload["organization_id"])
                source_id = str(payload["source_id"])
                user_id = uuid.UUID(payload["user_id"]) if payload.get("user_id") else None
                ensure_default_templates(db, organization_id, user_id)

                if payload["kind"] == "inspection":
                    event_at_raw = payload.get("event_at")
                    keep_prefix = None
                    if event_at_raw and payload.get("event") == "scheduled":
                        event_at = datetime.fromisoformat(event_at_raw)
                        current_payload = {
                            "kind": "inspection_schedule",
                            "organization_id": str(organization_id),
                            "source_id": source_id,
                            "event": "scheduled",
                            "event_at": _as_utc(event_at).isoformat(),
                            "user_id": str(user_id or ""),
                        }
                        _inspection_suggestions(db, current_payload)
                        keep_prefix = f"inspection_schedule:{source_id}:{_as_utc(event_at).isoformat()}:"
                    _supersede(
                        db,
                        organization_id=organization_id,
                        source_module="inspections",
                        source_type="inspection",
                        source_id=source_id,
                        category="inspection_schedule",
                        keep_prefix=keep_prefix,
                        user_id=user_id,
                        reason="Agendamento da vistoria alterado ou cancelado na origem.",
                    )
                    continue

                event_name = str(payload.get("event") or "")
                event_at_raw = payload.get("event_at")
                keep_prefix = None
                if event_name in {"scheduled", "in_progress", "completed", "cancelled"} and event_at_raw:
                    event_at = datetime.fromisoformat(event_at_raw)
                    current_payload = {
                        "kind": "maintenance_update",
                        "organization_id": str(organization_id),
                        "source_id": source_id,
                        "event": event_name,
                        "event_at": _as_utc(event_at).isoformat(),
                        "user_id": str(user_id or ""),
                    }
                    _maintenance_suggestions(db, current_payload)
                    keep_prefix = f"maintenance_update:{source_id}:{event_name}:{_as_utc(event_at).isoformat()}:"
                _supersede(
                    db,
                    organization_id=organization_id,
                    source_module="maintenance",
                    source_type="maintenance_request",
                    source_id=source_id,
                    category="maintenance_update",
                    keep_prefix=keep_prefix,
                    user_id=user_id,
                    reason="A situação ou o agendamento da manutenção mudou na origem.",
                )
            db.commit()
    except Exception:
        logger.exception("Falha ao reconciliar sugestões obsoletas de agendamento.")


def _discard(session: Session) -> None:
    session.info.pop(_SESSION_KEY, None)


def install_schedule_reconciliation_rules() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    event.listen(Session, "before_flush", _collect)
    event.listen(Session, "after_commit", _publish)
    event.listen(Session, "after_rollback", _discard)
    _INSTALLED = True
