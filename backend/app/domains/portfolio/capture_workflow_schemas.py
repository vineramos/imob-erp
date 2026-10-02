from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.portfolio.schemas import CaptureResponse, PropertyResponse


CaptureWorkflowAction = Literal["advance", "back", "lose", "reopen", "assign"]


class CaptureWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: CaptureWorkflowAction
    responsible_user_id: UUID | None = None
    lost_reason: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=1000)


class CaptureConversionResponse(BaseModel):
    capture: CaptureResponse
    property: PropertyResponse
