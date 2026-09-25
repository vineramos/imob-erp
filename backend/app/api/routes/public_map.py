from __future__ import annotations

import hashlib
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.routes.publication import _public_site_settings
from app.core.database import get_db
from app.domains.portfolio.map_models import PropertyMapLocation
from app.domains.portfolio.models import Property

router = APIRouter(tags=["public-map"])

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_GEOCODE_LOCK = threading.Lock()
_LAST_GEOCODE_AT = 0.0
_MIN_GEOCODE_INTERVAL_SECONDS = 1.05


class PublicMapPositionResponse(BaseModel):
    latitude: float
    longitude: float
    precision: Literal["exact", "street", "postal_code"]


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _private_address_parts(item: Property) -> dict[str, str]:
    address = item.address or {}
    return {
        "street": _clean(address.get("street")),
        "number": _clean(address.get("number")),
        "neighborhood": _clean(address.get("neighborhood")),
        "city": _clean(address.get("city")),
        "state": _clean(address.get("state")),
        "postal_code": _clean(address.get("postal_code")),
    }


def _address_fingerprint(item: Property) -> str:
    parts = _private_address_parts(item)
    canonical = "|".join(parts[key].casefold() for key in ("street", "number", "neighborhood", "city", "state", "postal_code"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _search_queries(item: Property) -> list[tuple[str, Literal["exact", "street", "postal_code"]]]:
    address = _private_address_parts(item)
    street = address["street"]
    number = address["number"]
    neighborhood = address["neighborhood"]
    city = address["city"]
    state = address["state"]
    postal_code = address["postal_code"]

    queries: list[tuple[str, Literal["exact", "street", "postal_code"]]] = []
    if street and number:
        queries.append((", ".join(part for part in (f"{street}, {number}", neighborhood, city, state, postal_code, "Brasil") if part), "exact"))
    if street:
        queries.append((", ".join(part for part in (street, neighborhood, city, state, postal_code, "Brasil") if part), "street"))
    if postal_code:
        queries.append((", ".join(part for part in (postal_code, city, state, "Brasil") if part), "postal_code"))
    return queries


def _nominatim_lookup(query: str) -> tuple[Decimal, Decimal] | None:
    global _LAST_GEOCODE_AT

    with _GEOCODE_LOCK:
        wait_seconds = _MIN_GEOCODE_INTERVAL_SECONDS - (time.monotonic() - _LAST_GEOCODE_AT)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        try:
            response = httpx.get(
                _NOMINATIM_URL,
                params={
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "br",
                    "q": query,
                },
                headers={
                    "User-Agent": "ImobERP/1.0 public-property-map",
                    "Accept-Language": "pt-BR,pt;q=0.9",
                },
                timeout=7.0,
                follow_redirects=True,
            )
            _LAST_GEOCODE_AT = time.monotonic()
            response.raise_for_status()
            rows = response.json()
        except (httpx.HTTPError, ValueError):
            _LAST_GEOCODE_AT = time.monotonic()
            return None

    if not isinstance(rows, list) or not rows:
        return None
    try:
        latitude = Decimal(str(rows[0].get("lat", "")))
        longitude = Decimal(str(rows[0].get("lon", "")))
    except (InvalidOperation, AttributeError):
        return None
    if not (Decimal("-90") <= latitude <= Decimal("90")):
        return None
    if not (Decimal("-180") <= longitude <= Decimal("180")):
        return None
    return latitude, longitude


def _geocode_property(item: Property) -> tuple[Decimal, Decimal, Literal["exact", "street", "postal_code"]] | None:
    for query, precision in _search_queries(item):
        coordinate = _nominatim_lookup(query)
        if coordinate is not None:
            return coordinate[0], coordinate[1], precision
    return None


def _response(location: PropertyMapLocation) -> PublicMapPositionResponse:
    return PublicMapPositionResponse(
        latitude=float(location.latitude),
        longitude=float(location.longitude),
        precision=location.precision,
    )


@router.get(
    "/public/sites/{organization_id}/properties/{slug}/map-position",
    response_model=PublicMapPositionResponse,
)
def public_property_map_position(
    organization_id: UUID,
    slug: str,
    db: Session = Depends(get_db),
) -> PublicMapPositionResponse:
    # Valida primeiro se o site está público. O endereço completo jamais entra
    # na resposta: ele existe apenas no servidor durante a geocodificação.
    _public_site_settings(db, organization_id)
    item = db.scalar(
        select(Property).where(
            Property.organization_id == organization_id,
            Property.public_slug == slug,
            Property.publication_enabled.is_(True),
            Property.status == "available",
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imóvel não encontrado.")

    fingerprint = _address_fingerprint(item)
    cached = db.get(PropertyMapLocation, item.id)
    if cached is not None and cached.address_fingerprint == fingerprint:
        return _response(cached)

    geocoded = _geocode_property(item)
    if geocoded is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Localização do imóvel indisponível no mapa.",
        )

    latitude, longitude, precision = geocoded
    statement = insert(PropertyMapLocation).values(
        property_id=item.id,
        organization_id=organization_id,
        address_fingerprint=fingerprint,
        latitude=latitude,
        longitude=longitude,
        precision=precision,
        source="nominatim",
    ).on_conflict_do_update(
        index_elements=[PropertyMapLocation.property_id],
        set_={
            "organization_id": organization_id,
            "address_fingerprint": fingerprint,
            "latitude": latitude,
            "longitude": longitude,
            "precision": precision,
            "source": "nominatim",
            "geocoded_at": func.now(),
            "updated_at": func.now(),
        },
    )
    db.execute(statement)
    db.commit()

    stored = db.get(PropertyMapLocation, item.id)
    if stored is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Não foi possível preparar a localização do imóvel.")
    return _response(stored)
