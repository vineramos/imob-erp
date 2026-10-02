from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.agenda.models import AgendaUserProfile

DEFAULT_AGENDA_TIMEZONE = "America/Sao_Paulo"


def resolve_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_AGENDA_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_AGENDA_TIMEZONE)


def profile_timezone(db: Session, organization_id: UUID, user_id: UUID | None) -> ZoneInfo:
    if user_id is None:
        return resolve_timezone(DEFAULT_AGENDA_TIMEZONE)
    name = db.scalar(
        select(AgendaUserProfile.timezone).where(
            AgendaUserProfile.organization_id == organization_id,
            AgendaUserProfile.user_id == user_id,
        )
    )
    return resolve_timezone(name)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def local_date(value: datetime, zone: ZoneInfo) -> date:
    return aware_utc(value).astimezone(zone).date()


def local_today(zone: ZoneInfo) -> date:
    return datetime.now(timezone.utc).astimezone(zone).date()


def local_day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
    return start, end


def install_event_collection_timezone_rule() -> None:
    """Faz a API da Agenda interpretar intervalos e atrasos no fuso do perfil.

    O banco permanece em UTC. Datas recebidas pela Agenda, porém, representam
    dias civis do usuário. O coletor legado montava 00:00/24:00 em UTC e também
    comparava `starts_at.date()` em UTC. Isso deslocava eventos noturnos de
    America/Sao_Paulo para o dia seguinte e podia impedir o reagendamento diário.
    """
    from app.api.routes import agenda as agenda_routes

    current = agenda_routes._collect_events
    if getattr(current, "_agenda_timezone_installed", False):
        return

    def collect_events(
        db: Session,
        context,
        start: date,
        end: date,
        *,
        mine: bool = True,
        user_id: UUID | None = None,
        department_id: UUID | None = None,
    ):
        organization_id = context.user.organization_id
        viewer_zone = profile_timezone(db, organization_id, context.user.id)

        # O coletor original ainda filtra timestamps em UTC. Ampliamos a janela
        # em um dia de cada lado e, em seguida, aplicamos o intervalo civil exato
        # do perfil. Assim nenhum evento local na borda é perdido.
        rows = current(
            db,
            context,
            start - timedelta(days=1),
            end + timedelta(days=1),
            mine=mine,
            user_id=user_id,
            department_id=department_id,
        )
        start_utc = datetime.combine(start, time.min, tzinfo=viewer_zone).astimezone(timezone.utc)
        end_utc = datetime.combine(end + timedelta(days=1), time.min, tzinfo=viewer_zone).astimezone(timezone.utc)
        today = local_today(viewer_zone)
        result = []

        for row in rows:
            row_start = aware_utc(row.start_at)
            if row.all_day:
                # Eventos de dia inteiro codificam o próprio dia civil na data.
                event_day = row.start_at.date()
                include = start <= event_day <= end
            else:
                row_end = aware_utc(row.end_at) if row.end_at else row_start + timedelta(microseconds=1)
                include = row_start < end_utc and row_end > start_utc
                event_day = row_start.astimezone(viewer_zone).date()

            if not include:
                continue

            if row.automatic and row.mandatory_action and row.status == "pending":
                row.needs_justification = event_day < today
            result.append(row)

        return result

    setattr(collect_events, "_agenda_timezone_installed", True)
    agenda_routes._collect_events = collect_events
