from typing import Literal

from pydantic import BaseModel


class DimobValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    scope: str
    reference: str | None = None
    message: str


class DimobValidationResponse(BaseModel):
    year: int
    status: Literal["no_operations", "attention_required", "ready_for_review"]
    operation_count: int
    lease_count: int
    owner_count: int
    tenant_count: int
    error_count: int
    warning_count: int
    official_layout_export_available: bool = False
    issues: list[DimobValidationIssue]
    note: str
