import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Identity, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgendaDepartment(Base):
    __tablename__ = "agenda_departments"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_agenda_departments_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgendaUserProfile(Base):
    __tablename__ = "agenda_user_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_agenda_user_profiles_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_departments.id", ondelete="SET NULL"), index=True)
    access_level: Mapped[str] = mapped_column(String(20), nullable=False, default="collaborator", index=True)
    work_start: Mapped[str] = mapped_column(String(5), nullable=False, default="08:30")
    work_end: Mapped[str] = mapped_column(String(5), nullable=False, default="18:00")
    lunch_start: Mapped[str | None] = mapped_column(String(5), default="12:00")
    lunch_end: Mapped[str | None] = mapped_column(String(5), default="13:00")
    work_days: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=lambda: [0, 1, 2, 3, 4])
    buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    default_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="America/Sao_Paulo")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgendaDelegation(Base):
    __tablename__ = "agenda_delegations"
    __table_args__ = (UniqueConstraint("owner_user_id", "delegate_user_id", name="uq_agenda_delegations_owner_delegate"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    delegate_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    can_view_availability: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_view_details: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_create: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_reschedule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgendaTask(Base):
    __tablename__ = "agenda_tasks"
    __table_args__ = (
        UniqueConstraint("organization_id", "source_type", "source_id", "original_scheduled_at", "reschedule_sequence", name="uq_agenda_tasks_system_occurrence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="task", index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    privacy: Mapped[str] = mapped_column(String(20), nullable=False, default="normal", index=True)
    location: Mapped[str | None] = mapped_column(String(300))
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"), index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_departments.id", ondelete="SET NULL"), index=True)
    source_module: Mapped[str | None] = mapped_column(String(60), index=True)
    source_type: Mapped[str | None] = mapped_column(String(80), index=True)
    source_id: Mapped[str | None] = mapped_column(String(180), index=True)
    automatic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    mandatory_action: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    completion_source: Mapped[str] = mapped_column(String(20), nullable=False, default="agenda")
    original_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    original_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_tasks.id", ondelete="SET NULL"), index=True)
    previous_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_tasks.id", ondelete="SET NULL"), index=True)
    reschedule_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missed_justification: Mapped[str | None] = mapped_column(Text)
    missed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    immutable_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recurrence_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    recurrence_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recurrence_rule: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgendaMeetingRequest(Base):
    __tablename__ = "agenda_meeting_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    organizer_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    privacy: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    selected_option_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgendaMeetingParticipant(Base):
    __tablename__ = "agenda_meeting_participants"
    __table_args__ = (UniqueConstraint("meeting_request_id", "user_id", name="uq_agenda_meeting_participant_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agenda_meeting_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgendaMeetingOption(Base):
    __tablename__ = "agenda_meeting_options"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agenda_meeting_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    proposed_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgendaMeetingVote(Base):
    __tablename__ = "agenda_meeting_votes"
    __table_args__ = (UniqueConstraint("meeting_option_id", "user_id", name="uq_agenda_meeting_vote_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_option_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agenda_meeting_options.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgendaDailyBriefing(Base):
    __tablename__ = "agenda_daily_briefings"
    __table_args__ = (UniqueConstraint("user_id", "briefing_date", name="uq_agenda_daily_briefing_user_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    briefing_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
