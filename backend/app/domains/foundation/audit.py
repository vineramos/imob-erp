from typing import Any

from sqlalchemy.orm import Session

from app.domains.foundation.access import UserContext
from app.domains.foundation.models import AuditLog


def write_audit(
    db: Session,
    *,
    context: UserContext,
    action: str,
    module: str,
    entity_type: str,
    entity_id: str | None = None,
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    event = AuditLog(
        organization_id=context.user.organization_id,
        actor_user_id=context.user.id,
        action=action,
        module=module,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=before_data,
        after_data=after_data,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(event)
    return event
