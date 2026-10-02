from __future__ import annotations

from typing import Any


BANK_INSTITUTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "bb",
        "name": "Banco do Brasil",
        "bank_code": "001",
        "ispb": None,
        "provider_key": "bb",
        "api_status": "planned",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "santander",
        "name": "Santander",
        "bank_code": "033",
        "ispb": None,
        "provider_key": "santander",
        "api_status": "planned",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "inter",
        "name": "Banco Inter",
        "bank_code": "077",
        "ispb": None,
        "provider_key": "inter",
        "api_status": "legacy_available",
        "account_scoped_api": False,
        "implemented_capabilities": ["statement", "balance", "billing", "pix_payment"],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "caixa",
        "name": "Caixa Econômica Federal",
        "bank_code": "104",
        "ispb": None,
        "provider_key": "caixa",
        "api_status": "planned",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "btg",
        "name": "BTG Pactual",
        "bank_code": "208",
        "ispb": None,
        "provider_key": "btg",
        "api_status": "planned",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "bradesco",
        "name": "Bradesco",
        "bank_code": "237",
        "ispb": None,
        "provider_key": "bradesco",
        "api_status": "planned",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "itau",
        "name": "Itaú Unibanco",
        "bank_code": "341",
        "ispb": None,
        "provider_key": "itau",
        "api_status": "planned",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "safra",
        "name": "Banco Safra",
        "bank_code": "422",
        "ispb": None,
        "provider_key": "safra",
        "api_status": "planned",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "sicredi",
        "name": "Sicredi",
        "bank_code": "748",
        "ispb": None,
        "provider_key": "sicredi",
        "api_status": "planned",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "sicoob",
        "name": "Sicoob",
        "bank_code": "756",
        "ispb": None,
        "provider_key": "sicoob",
        "api_status": "planned",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab", "api"],
    },
    {
        "key": "other",
        "name": "Outro banco",
        "bank_code": None,
        "ispb": None,
        "provider_key": "manual",
        "api_status": "not_available",
        "account_scoped_api": False,
        "implemented_capabilities": [],
        "supported_integration_modes": ["manual", "import", "cnab"],
    },
)

BANK_INSTITUTIONS_BY_KEY = {item["key"]: item for item in BANK_INSTITUTIONS}

PURPOSE_SCOPES: dict[str, str | None] = {
    "operating": "operating",
    "rent_receipts_repasses": "third_party",
    "security_deposits": "third_party",
    "taxes": "operating",
    "other": None,
}


def bank_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in BANK_INSTITUTIONS]


def bank_institution(key: str) -> dict[str, Any] | None:
    item = BANK_INSTITUTIONS_BY_KEY.get((key or "").strip().lower())
    return dict(item) if item else None


def purpose_fund_scope(purpose: str, requested_scope: str | None = None) -> str:
    normalized = (purpose or "other").strip().lower()
    forced = PURPOSE_SCOPES.get(normalized)
    if forced:
        return forced
    return "third_party" if requested_scope == "third_party" else "operating"


def integration_status(institution: dict[str, Any], integration_mode: str) -> str:
    mode = (integration_mode or "manual").strip().lower()
    if mode == "manual":
        return "manual_ready"
    if mode == "import":
        return "import_ready"
    if mode == "cnab":
        return "cnab_foundation"
    if mode != "api":
        return "manual_ready"

    api_status = str(institution.get("api_status") or "not_available")
    if api_status == "legacy_available":
        return "api_legacy_adapter"
    if api_status == "planned":
        return "api_provider_pending"
    return "api_unavailable"
