from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

InspectionStatus = Literal["draft", "ready", "contested", "finalized", "cancelled"]
InspectionType = Literal["initial", "final"]
ItemCondition = Literal["excellent", "good", "regular", "poor", "damaged", "not_applicable"]
InspectionWorkflowAction = Literal["complete", "return_draft", "finalize", "cancel"]


class InspectionPhoto(BaseModel):
    id: str
    filename: str
    content_type: str
    reference: str
    uploaded_at: str


class InspectionItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    condition: ItemCondition = "good"
    notes: str | None = Field(default=None, max_length=2000)
    photos: list[dict] = Field(default_factory=list, max_length=40)


class InspectionEnvironmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)
    items: list[InspectionItemPayload] = Field(min_length=1, max_length=100)


class InspectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_contract_id: UUID
    scheduled_at: datetime | None = None
    inspector_name: str | None = Field(default=None, max_length=180)
    environments: list[InspectionEnvironmentPayload] = Field(min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=4000)


class InspectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: datetime | None = None
    inspector_name: str | None = Field(default=None, max_length=180)
    environments: list[InspectionEnvironmentPayload] = Field(min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=4000)
    change_summary: str = Field(min_length=3, max_length=500)


class InspectionWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: InspectionWorkflowAction
    reason: str | None = Field(default=None, max_length=1000)


class InspectionContestationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment_key: str = Field(min_length=1, max_length=80)
    item_key: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=3, max_length=3000)


class InspectionContestationResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contestation_id: str = Field(min_length=1, max_length=80)
    resolution: str = Field(min_length=3, max_length=3000)
    change_summary: str = Field(min_length=3, max_length=500)
    environments: list[InspectionEnvironmentPayload] | None = Field(default=None, max_length=60)


class KeyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=50)
    notes: str | None = Field(default=None, max_length=500)


class KeyHandoverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handed_over_at: datetime
    recipient_name: str = Field(min_length=2, max_length=180)
    recipient_document: str | None = Field(default=None, max_length=30)
    keys: list[KeyEntry] = Field(min_length=1, max_length=30)
    meter_readings: dict = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=2000)


class KeyHandoverResponse(BaseModel):
    id: UUID
    handed_over_at: datetime
    recipient_name: str
    recipient_document: str | None = None
    keys: list[dict]
    meter_readings: dict
    notes: str | None = None
    created_at: datetime


class InspectionVersionResponse(BaseModel):
    version_number: int
    change_summary: str | None = None
    created_at: datetime


class InspectionResponse(BaseModel):
    id: UUID
    internal_number: int
    code: str
    inspection_type: InspectionType
    status: InspectionStatus
    lease_contract_id: UUID
    lease_code: str
    property_id: UUID
    property_code: str
    property_address: dict
    tenants: list[dict]
    environments: list[dict]
    contestations: list[dict]
    inspector_name: str | None = None
    scheduled_at: datetime | None = None
    performed_at: datetime | None = None
    contest_deadline: datetime | None = None
    finalized_at: datetime | None = None
    notes: str | None = None
    current_version: int
    report_reference: str | None = None
    report_hash: str | None = None
    report_version: int | None = None
    key_handover: KeyHandoverResponse | None = None
    versions: list[InspectionVersionResponse]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_report_version(self):
        if self.report_version is not None and self.report_version > self.current_version:
            raise ValueError("Versão do laudo inválida.")
        return self
