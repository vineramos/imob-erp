from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BankAccountSetup(Base):
    __tablename__ = "bank_account_setups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    institution_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    account_purpose: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    integration_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", index=True)
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", index=True)
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    provider_account_id: Mapped[str | None] = mapped_column(String(180))

    # Somente referências a segredos externos. Tokens, senhas e certificados nunca
    # devem ser persistidos diretamente no banco do Imob ERP.
    credential_secret_ref: Mapped[str | None] = mapped_column(String(300))
    certificate_secret_ref: Mapped[str | None] = mapped_column(String(300))
    webhook_secret_ref: Mapped[str | None] = mapped_column(String(300))
    non_secret_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    enabled_capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    status: Mapped[str] = mapped_column(String(40), nullable=False, default="manual_ready", index=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str | None] = mapped_column(String(40))
    last_test_message: Mapped[str | None] = mapped_column(Text)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
