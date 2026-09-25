from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgendaTaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=5000)
    kind: str = Field(default="task", pattern="^(task|appointment|meeting|visit)$")
    starts_at: datetime
    ends_at: datetime | None = None
    due_at: datetime | None = None
    all_day: bool = False
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    privacy: str = Field(default="normal", pattern="^(normal|private)$")
    location: str | None = Field(default=None, max_length=300)
    assigned_user_id: UUID | None = None
    recurrence: str = Field(default="none", pattern="^(none|daily|weekly|monthly)$")
    recurrence_until: date | None = None
    allow_conflict: bool = False

    @model_validator(mode="after")
    def validate_times(self):
        if self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("O término deve ser posterior ao início.")
        if self.due_at and self.due_at < self.starts_at:
            raise ValueError("O prazo final não pode ser anterior ao início.")
        return self


class AgendaTaskUpdate(AgendaTaskCreate):
    recurrence: str = "none"
    recurrence_until: date | None = None


class AgendaTaskStatus(BaseModel):
    status: str = Field(pattern="^(pending|confirmed|completed|cancelled|no_show)$")


class AgendaMissJustification(BaseModel):
    justification: str = Field(min_length=3, max_length=3000)


class AgendaTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    title: str
    description: str | None
    kind: str
    starts_at: datetime
    ends_at: datetime | None
    due_at: datetime | None
    all_day: bool
    priority: str
    status: str
    privacy: str
    location: str | None
    assigned_user_id: UUID | None
    assigned_user_name: str | None
    department_id: UUID | None
    department_name: str | None
    source_module: str | None
    source_type: str | None
    source_id: str | None
    automatic: bool
    mandatory_action: bool
    original_scheduled_at: datetime | None
    reschedule_sequence: int
    missed_justification: str | None
    immutable_history: bool
    recurrence_group_id: UUID | None
    recurrence_sequence: int
    created_at: datetime
    updated_at: datetime


class AgendaDepartmentResponse(BaseModel):
    id: UUID
    name: str


class AgendaDepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class AgendaUserProfileUpdate(BaseModel):
    department_id: UUID | None = None
    access_level: str = Field(pattern="^(collaborator|manager|director|admin)$")


class AgendaMyAvailabilityUpdate(BaseModel):
    work_start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    work_end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    lunch_start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    lunch_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    work_days: list[int] = Field(min_length=1, max_length=7)
    buffer_minutes: int = Field(ge=0, le=120)
    default_duration_minutes: int = Field(ge=15, le=480)
    timezone: str = Field(default="America/Sao_Paulo", min_length=3, max_length=60)


class AgendaDirectoryUser(BaseModel):
    id: UUID
    name: str
    email: str
    department_id: UUID | None
    department_name: str | None
    access_level: str
    can_view_calendar: bool = False
    can_view_details: bool = False
    can_create: bool = False
    can_reschedule: bool = False
    access_reason: str | None = None


class AgendaContextResponse(BaseModel):
    current_user_id: UUID
    current_user_name: str
    access_level: str
    department_id: UUID | None
    department_name: str | None
    work_start: str
    work_end: str
    lunch_start: str | None
    lunch_end: str | None
    work_days: list[int]
    buffer_minutes: int
    default_duration_minutes: int
    timezone: str
    departments: list[AgendaDepartmentResponse]
    directory: list[AgendaDirectoryUser]


class AgendaDelegationWrite(BaseModel):
    delegate_user_id: UUID
    can_view_availability: bool = True
    can_view_details: bool = False
    can_create: bool = False
    can_reschedule: bool = False


class AgendaDelegationResponse(BaseModel):
    id: UUID
    owner_user_id: UUID
    owner_name: str
    delegate_user_id: UUID
    delegate_name: str
    can_view_availability: bool
    can_view_details: bool
    can_create: bool
    can_reschedule: bool


class AgendaEventResponse(BaseModel):
    id: str
    event_type: str
    title: str
    description: str | None = None
    start_at: datetime
    end_at: datetime | None = None
    all_day: bool = False
    priority: str = "normal"
    status: str = "pending"
    module: str
    source_id: str | None = None
    source_code: str | None = None
    responsible_name: str | None = None
    owner_user_id: UUID | None = None
    department_id: UUID | None = None
    department_name: str | None = None
    property_code: str | None = None
    amount: float | None = None
    automatic: bool = True
    mandatory_action: bool = False
    task_id: UUID | None = None
    privacy: str = "normal"
    masked: bool = False
    needs_justification: bool = False
    original_scheduled_at: datetime | None = None
    reschedule_sequence: int = 0
    missed_justification: str | None = None
    location: str | None = None


class AgendaEventsResponse(BaseModel):
    start_date: str
    end_date: str
    events: list[AgendaEventResponse]


class AvailabilityRequest(BaseModel):
    user_ids: list[UUID] = Field(min_length=1, max_length=50)
    starts_at: datetime
    ends_at: datetime
    exclude_task_id: UUID | None = None


class AvailabilityUserResult(BaseModel):
    user_id: UUID
    user_name: str
    available: bool
    reason: str | None = None
    next_available_at: datetime | None = None


class AvailabilityResponse(BaseModel):
    all_available: bool
    users: list[AvailabilityUserResult]


class FindTimeRequest(BaseModel):
    user_ids: list[UUID] = Field(min_length=1, max_length=50)
    duration_minutes: int = Field(ge=15, le=480)
    start_date: date
    end_date: date
    limit: int = Field(default=12, ge=1, le=50)


class FindTimeOption(BaseModel):
    starts_at: datetime
    ends_at: datetime


class MeetingOptionInput(BaseModel):
    starts_at: datetime


class MeetingRequestCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=5000)
    participant_user_ids: list[UUID] = Field(min_length=1, max_length=50)
    duration_minutes: int = Field(default=60, ge=15, le=480)
    privacy: str = Field(default="normal", pattern="^(normal|private)$")
    options: list[MeetingOptionInput] = Field(default_factory=list, max_length=100)


class MeetingOptionsAdd(BaseModel):
    options: list[MeetingOptionInput] = Field(min_length=1, max_length=100)


class MeetingVoteRequest(BaseModel):
    decision: str = Field(pattern="^(accepted|rejected)$")


class MeetingDeclineRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class TodaySummaryResponse(BaseModel):
    date: str
    show_popup: bool
    events: list[AgendaEventResponse]
    pending_justifications: list[AgendaTaskResponse]
    pending_invites: int


class ReminderResponse(BaseModel):
    event: AgendaEventResponse
    minutes_until: int


class DashboardEventResponse(BaseModel):
    id: str
    title: str
    start_at: datetime
    event_type: str
    module: str
    priority: str


class DashboardOverviewResponse(BaseModel):
    administered_properties: int
    available_properties: int
    active_leases: int
    contracts_expiring_120: int
    open_maintenance: int
    overdue_amount: float
    pending_repasses_amount: float
    tasks_today: int
    overdue_tasks: int
    events_today: list[DashboardEventResponse]
    open_captures: int = 0
    approved_captures: int = 0
    properties_without_administration: int = 0
    properties_with_administration: int = 0
    managed_properties: int = 0
    contracts_awaiting_signature: int = 0
    contracts_in_review: int = 0
    recent_captures: list[dict] = Field(default_factory=list)
