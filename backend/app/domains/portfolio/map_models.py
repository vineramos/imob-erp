import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PropertyMapLocation(Base):
    """Coordenada interna derivada do endereço completo do imóvel.

    O endereço usado para geocodificação nunca é exposto pelo endpoint público;
    somente latitude/longitude e o nível de precisão são publicados para o mapa.
    """

    __tablename__ = "property_map_locations"

    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        primary_key=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    address_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    precision: Mapped[str] = mapped_column(String(24), nullable=False, default="exact")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="nominatim")
    geocoded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
