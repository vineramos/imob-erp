import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FinanceMonthlyClosure(Base):
    __tablename__ = "finance_monthly_closures"
    __table_args__ = (
        UniqueConstraint("organization_id", "competence", name="uq_finance_monthly_closure_org_competence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    competence: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)

    readiness_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    closing_note: Mapped[str | None] = mapped_column(Text)
    reopen_reason: Mapped[str | None] = mapped_column(Text)

    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    reopened_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class FinanceMonthlyClosureEvent(Base):
    __tablename__ = "finance_monthly_closure_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    closure_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finance_monthly_closures.id", ondelete="CASCADE"), nullable=False, index=True)
    competence: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    readiness_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
