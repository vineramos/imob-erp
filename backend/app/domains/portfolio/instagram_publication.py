from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domains.portfolio.models import Property


ACTIVE_INSTAGRAM_STATES = {"ready", "published", "publishing", "failed"}


def instagram_state(item: Property) -> dict[str, Any]:
    return dict(item.instagram_publication or {})


def inactivate_instagram_publication(item: Property, *, reason: str) -> bool:
    """Move the ERP Instagram publication lifecycle to inactive.

    Meta's content publishing API does not expose a documented archive/delete
    operation for published Instagram media. When a post already has a media
    id, we keep an explicit external-removal pending flag instead of pretending
    the Instagram post was removed.
    """
    current = instagram_state(item)
    if not current:
        return False
    status = str(current.get("status") or "draft")
    if status == "inactive":
        return False

    now = datetime.now(timezone.utc).isoformat()
    media_id = str(current.get("media_id") or "").strip() or None
    current["status"] = "inactive"
    current["inactivated_at"] = now
    current["inactivation_reason"] = reason
    current["external_removal_pending"] = bool(media_id)
    current["updated_at"] = now
    item.instagram_publication = current
    return True
