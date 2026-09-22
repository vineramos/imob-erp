from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class AddressPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    street: str = Field(default="", max_length=180)
    number: str = Field(default="", max_length=30)
    complement: str = Field(default="", max_length=100)
    neighborhood: str = Field(default="", max_length=120)
    city: str = Field(default="Curitiba", max_length=120)
    state: str = Field(default="PR", max_length=2)
    postal_code: str = Field(default="", max_length=12)


PersonType = Literal["individual", "company"]
PersonRoleKey = Literal["owner", "tenant", "guarantor", "broker", "supplier", "referrer"]


class PersonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_type: PersonType = "individual"
    name: str = Field(min_length=2, max_length=180)
    document_number: str | None = Field(default=None, max_length=24)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    address: AddressPayload = Field(default_factory=AddressPayload)
    notes: str | None = Field(default=None, max_length=2000)
    role_keys: list[PersonRoleKey] = Field(default_factory=list, max_length=6)


class PersonUpdate(PersonCreate):
    pass


class PersonResponse(BaseModel):
    id: UUID
    person_type: PersonType
    name: str
    document_number: str | None = None
    email: str | None = None
    phone: str | None = None
    address: dict
    notes: str | None = None
    is_active: bool
    role_keys: list[str]
    created_at: datetime


class PropertyOwnerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    ownership_percent: Decimal = Field(default=Decimal("100"), gt=0, le=100)


PropertyFeatureKey = Literal[
    "balcony", "barbecue", "air_conditioning", "planned_kitchen", "closet", "lavabo",
    "office", "laundry", "heating", "garden", "private_pool", "service_area"
]
CondominiumFeatureKey = Literal[
    "elevator", "doorman_24h", "pool", "gym", "party_room", "playground",
    "gourmet_space", "security", "bike_rack", "coworking"
]
SolarOrientation = Literal["", "north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"]


class PropertyFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property: list[PropertyFeatureKey] = Field(default_factory=list, max_length=20)
    condominium: list[CondominiumFeatureKey] = Field(default_factory=list, max_length=20)
    floor: int | None = Field(default=None, ge=0, le=300)
    total_floors: int | None = Field(default=None, ge=0, le=300)
    elevators: int | None = Field(default=None, ge=0, le=50)
    solar_orientation: SolarOrientation = ""
    year_built: int | None = Field(default=None, ge=1800, le=2200)

PropertyType = Literal["apartment", "house", "commercial", "land", "studio", "other"]
PropertyStatus = Literal["draft", "available", "reserved", "leased", "inactive"]


class PropertyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_type: PropertyType
    purpose: Literal["rent", "sale"] = "rent"
    status: PropertyStatus = "draft"
    address: AddressPayload
    rent_amount: Decimal | None = Field(default=None, ge=0)
    condo_amount: Decimal | None = Field(default=None, ge=0)
    iptu_amount: Decimal | None = Field(default=None, ge=0)
    area_m2: Decimal | None = Field(default=None, ge=0)
    bedrooms: int = Field(default=0, ge=0, le=30)
    suites: int = Field(default=0, ge=0, le=30)
    bathrooms: int = Field(default=0, ge=0, le=30)
    parking_spaces: int = Field(default=0, ge=0, le=30)
    furnished: bool = False
    pets_allowed: bool = False
    features: PropertyFeatures = Field(default_factory=PropertyFeatures)
    public_title: str | None = Field(default=None, max_length=180)
    public_description: str | None = Field(default=None, max_length=5000)
    publication_enabled: bool = False
    owners: list[PropertyOwnerPayload] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_suites_within_bedrooms(self):
        if self.suites > self.bedrooms:
            raise ValueError("O número de suítes não pode ser maior que o total de quartos.")
        return self


class PropertyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_type: PropertyType
    purpose: Literal["rent", "sale"] = "rent"
    status: PropertyStatus
    address: AddressPayload
    rent_amount: Decimal | None = Field(default=None, ge=0)
    condo_amount: Decimal | None = Field(default=None, ge=0)
    iptu_amount: Decimal | None = Field(default=None, ge=0)
    area_m2: Decimal | None = Field(default=None, ge=0)
    bedrooms: int = Field(default=0, ge=0, le=30)
    suites: int = Field(default=0, ge=0, le=30)
    bathrooms: int = Field(default=0, ge=0, le=30)
    parking_spaces: int = Field(default=0, ge=0, le=30)
    furnished: bool = False
    pets_allowed: bool = False
    features: PropertyFeatures = Field(default_factory=PropertyFeatures)
    public_title: str | None = Field(default=None, max_length=180)
    owners: list[PropertyOwnerPayload] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_suites_within_bedrooms(self):
        if self.suites > self.bedrooms:
            raise ValueError("O número de suítes não pode ser maior que o total de quartos.")
        return self


class PropertyResponse(BaseModel):
    id: UUID
    internal_number: int
    code: str
    property_type: str
    purpose: str
    status: str
    address: dict
    rent_amount: Decimal | None = None
    condo_amount: Decimal | None = None
    iptu_amount: Decimal | None = None
    area_m2: Decimal | None = None
    bedrooms: int
    suites: int
    bathrooms: int
    parking_spaces: int
    furnished: bool
    pets_allowed: bool
    features: dict
    public_title: str | None = None
    public_slug: str | None = None
    publication_enabled: bool
    published_at: datetime | None = None
    owners: list[dict]
    created_at: datetime
    updated_at: datetime


class PublicationChecklistItem(BaseModel):
    key: str
    label: str
    ok: bool
    required: bool = True
    detail: str


class PublicationReadinessResponse(BaseModel):
    property_id: UUID
    code: str
    ready: bool
    publication_enabled: bool
    public_slug: str | None = None
    checklist: list[PublicationChecklistItem]


class PublicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    reason: str | None = Field(default=None, max_length=1000)


class PublicPropertyResponse(BaseModel):
    code: str
    slug: str
    property_type: str
    purpose: str
    address: dict
    rent_amount: Decimal | None = None
    condo_amount: Decimal | None = None
    iptu_amount: Decimal | None = None
    area_m2: Decimal | None = None
    bedrooms: int
    suites: int
    bathrooms: int
    parking_spaces: int
    furnished: bool
    pets_allowed: bool
    features: dict
    title: str
    description: str
    published_at: datetime | None = None


CaptureStatus = Literal["new", "negotiation", "documents", "inspection", "approved", "available", "lost"]
CaptureSource = Literal["direct", "site", "referral", "broker", "campaign", "other"]


class CaptureCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CaptureStatus = "new"
    source: CaptureSource = "direct"
    contact_person_id: UUID | None = None
    responsible_user_id: UUID | None = None
    property_type: PropertyType | None = None
    property_address: AddressPayload = Field(default_factory=AddressPayload)
    estimated_rent: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=3000)


class CaptureResponse(BaseModel):
    id: UUID
    status: str
    source: str
    contact_person_id: UUID | None = None
    contact_person_name: str | None = None
    responsible_user_id: UUID | None = None
    converted_property_id: UUID | None = None
    property_type: str | None = None
    property_address: dict
    estimated_rent: Decimal | None = None
    notes: str | None = None
    lost_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class EconomicIndexValueResponse(BaseModel):
    index_code: str
    sgs_code: int
    competence: date
    monthly_rate: Decimal
    source: str
    fetched_at: datetime


class EconomicIndexSyncResponse(BaseModel):
    index_code: str
    status: str
    imported: int
    latest_competence: date | None = None
    next_retry_at: datetime | None = None
    message: str
