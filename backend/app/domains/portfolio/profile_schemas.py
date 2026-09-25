from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MaritalStatus = Literal["single", "married", "stable_union", "divorced", "widowed", "separated", "other"]


class PersonProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secondary_phone: str | None = Field(default=None, max_length=40)

    identity_number: str | None = Field(default=None, max_length=40)
    identity_issuer: str | None = Field(default=None, max_length=40)
    birth_date: date | None = None
    nationality: str | None = Field(default=None, max_length=80)
    marital_status: MaritalStatus | None = None
    occupation: str | None = Field(default=None, max_length=120)

    trade_name: str | None = Field(default=None, max_length=180)
    state_registration: str | None = Field(default=None, max_length=40)
    municipal_registration: str | None = Field(default=None, max_length=40)


class PersonProfileResponse(PersonProfileUpdate):
    id: UUID
    person_id: UUID
    created_at: datetime
    updated_at: datetime
