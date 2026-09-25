from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

BankAccountType = Literal["checking", "savings", "payment"]
PixKeyType = Literal["none", "cpf_cnpj", "email", "phone", "random"]


class PersonBankDetailsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_name: str | None = Field(default=None, max_length=120)
    bank_code: str | None = Field(default=None, max_length=10)
    branch: str | None = Field(default=None, max_length=30)
    account_number: str | None = Field(default=None, max_length=40)
    account_digit: str | None = Field(default=None, max_length=10)
    account_type: BankAccountType = "checking"
    pix_key_type: PixKeyType = "none"
    pix_key: str | None = Field(default=None, max_length=180)
    account_holder_name: str | None = Field(default=None, max_length=180)
    account_holder_document: str | None = Field(default=None, max_length=24)


class PersonBankDetailsResponse(PersonBankDetailsUpdate):
    id: UUID
    person_id: UUID
    created_at: datetime
    updated_at: datetime
