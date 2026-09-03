from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgendaTaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=5000)
    starts_at: datetime
    due_at: datetime | None = None
    all_day: bool = False
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    assigned_user_id: UUID | None = None
    source_module: str | None = Field(default=None, max_length=60)
    source_type: str | None = Field(default=None, max_length=80)
    source_id: str | None = Field(default=None, max_length=180)


class AgendaTaskUpdate(AgendaTaskCreate):
    pass


class AgendaTaskStatus(BaseModel):
    status: str = Field(pattern="^(pending|completed|cancelled)$")


class AgendaTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    title: str
    description: str | None
    starts_at: datetime
    due_at: datetime | None
    all_day: bool
    priority: str
    status: str
    assigned_user_id: UUID | None
    assigned_user_name: str | None
    source_module: str | None
    source_type: str | None
    source_id: str | None
    created_at: datetime
    updated_at: datetime


class AgendaUserResponse(BaseModel):
    id: UUID
    name: str
    email: str


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
    property_code: str | None = None
    amount: float | None = None
    automatic: bool = True
    task_id: UUID | None = None


class AgendaEventsResponse(BaseModel):
    start_date: str
    end_date: str
    events: list[AgendaEventResponse]


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
