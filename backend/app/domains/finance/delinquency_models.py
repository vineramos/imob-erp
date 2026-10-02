from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DelinquencyWorkflow(Base):
    """Estado operacional complementar de um caso de inadimplência.

    O caso base continua em ``delinquency_cases`` para preservar compatibilidade.
    Esta tabela guarda promessa de pagamento e acompanhamento da garantia sem
    misturar esses estados com o status financeiro da cobrança.
    """

    __tablename__ = "delinquency_workflows"
    __table_args__ = (
        UniqueConstraint("delinquency_case_id", name="uq_delinquency_workflows_case"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    delinquency_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("delinquency_cases.id", ondelete="CASCADE"), nullable=False, index=True)

    guarantee_type: Mapped[str] = mapped_column(String(40), nullable=False, default="none", index=True)
    guarantee_provider_name: Mapped[str | None] = mapped_column(String(180))
    guarantee_policy_number: Mapped[str | None] = mapped_column(String(180))
    guarantee_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_applicable", index=True)
    guarantee_protocol: Mapped[str | None] = mapped_column(String(180))
    claimed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    received_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    guarantee_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    guarantee_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    guarantee_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    guarantee_rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    guarantee_payment_reference: Mapped[str | None] = mapped_column(String(180))

    promise_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    promise_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    promise_status: Mapped[str | None] = mapped_column(String(30), index=True)
    promise_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promise_broken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    notes: Mapped[str | None] = mapped_column(Text)
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
