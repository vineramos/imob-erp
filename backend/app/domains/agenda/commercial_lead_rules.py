from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.domains.portfolio.site_models import PublicSiteInquiry

logger = logging.getLogger(__name__)
_SESSION_INFO_KEY = "commercial_lead_agenda_touched"
_INSTALLED = False


CONTACT_LABELS = {
    "whatsapp": "WhatsApp",
    "phone": "telefone",
    "email": "e-mail",
}


def _completion_at(item: PublicSiteInquiry) -> datetime | None:
    if item.status == "new":
        return None
    return item.updated_at or datetime.now(timezone.utc)


def _sync_lead(db: Session, item: PublicSiteInquiry) -> None:
    if item.source != "public_site" or item.created_at is None:
        return

    from app.domains.agenda import logic

    commercial = logic.department_by_name(db, item.organization_id, "Comercial")
    contact_label = CONTACT_LABELS.get(item.preferred_contact, item.preferred_contact or "contato")
    description = (
        f"Lead recebido pelo site público para o imóvel #{item.property_code}. "
        f"Contato preferencial: {contact_label}. Revisar o interesse e registrar o primeiro atendimento no CRM."
    )
    if item.message:
        description += f" Mensagem do interessado: {item.message.strip()}"

    logic._ensure_source_chain(
        db,
        organization_id=item.organization_id,
        source_module="crm",
        source_type="site_inquiry",
        source_id=str(item.id),
        title=f"Atender lead do site · Imóvel #{item.property_code} · {item.name}",
        description=description,
        original_at=item.created_at,
        completion_at=_completion_at(item),
        assigned_user_id=item.responsible_user_id,
        department_id=commercial.id,
        kind="task",
        all_day=True,
        duration_minutes=30,
        priority="normal",
    )


def _track_touched_inquiries(session: Session, _flush_context) -> None:
    touched: set[tuple[UUID, UUID]] = set(session.info.get(_SESSION_INFO_KEY, set()))
    for item in tuple(session.new) + tuple(session.dirty):
        if not isinstance(item, PublicSiteInquiry):
            continue
        if item.organization_id is None or item.id is None or item.source != "public_site":
            continue
        touched.add((item.organization_id, item.id))
    if touched:
        session.info[_SESSION_INFO_KEY] = touched


def _sync_touched_after_commit(session: Session) -> None:
    touched = set(session.info.pop(_SESSION_INFO_KEY, set()))
    if not touched:
        return

    from app.core.database import SessionLocal

    if SessionLocal is None:
        return

    for organization_id, inquiry_id in touched:
        try:
            with SessionLocal() as db:
                item = db.scalar(
                    select(PublicSiteInquiry).where(
                        PublicSiteInquiry.id == inquiry_id,
                        PublicSiteInquiry.organization_id == organization_id,
                    )
                )
                if item is None:
                    continue
                _sync_lead(db, item)
                db.commit()
        except Exception:
            # O lead já foi confirmado na transação de origem. Uma falha aqui
            # não pode transformar um envio público válido em HTTP 500; a
            # reconciliação de sync_system_tasks recupera a tarefa depois.
            logger.exception("Falha ao sincronizar lead do site com a Agenda: %s", inquiry_id)


def _clear_touched_after_rollback(session: Session) -> None:
    session.info.pop(_SESSION_INFO_KEY, None)


def install_commercial_lead_agenda_rule() -> None:
    """Integra leads do site ao Comercial sem criar um segundo estado de CRM.

    O PublicSiteInquiry continua sendo a origem da verdade. Enquanto estiver
    como ``new``, há uma ação obrigatória na Agenda Comercial. Qualquer avanço
    real do funil encerra a pendência inicial. A sincronização acontece logo
    após o commit do lead e também é reconstruída pela reconciliação normal da
    Agenda, caso o hook pós-commit não consiga executar.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from app.domains.agenda import logic

    current = logic.sync_system_tasks

    def sync_system_tasks(
        db: Session,
        organization_id: UUID,
        *,
        lookback_days: int = 120,
        horizon_days: int = 120,
    ) -> None:
        current(db, organization_id, lookback_days=lookback_days, horizon_days=horizon_days)

        now = datetime.now(timezone.utc)
        rows = db.scalars(
            select(PublicSiteInquiry).where(
                PublicSiteInquiry.organization_id == organization_id,
                PublicSiteInquiry.source == "public_site",
                PublicSiteInquiry.created_at >= now - timedelta(days=lookback_days),
                PublicSiteInquiry.created_at <= now + timedelta(days=horizon_days),
            )
        ).all()
        for item in rows:
            _sync_lead(db, item)

    setattr(sync_system_tasks, "_commercial_lead_agenda_installed", True)
    logic.sync_system_tasks = sync_system_tasks

    event.listen(Session, "after_flush", _track_touched_inquiries)
    event.listen(Session, "after_commit", _sync_touched_after_commit)
    event.listen(Session, "after_rollback", _clear_touched_after_rollback)
    _INSTALLED = True
