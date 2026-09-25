from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.bank_catalog import bank_catalog, bank_institution, integration_status, purpose_fund_scope
from app.domains.finance.bank_models import BankAccount, BankTransaction
from app.domains.finance.bank_setup_models import BankAccountSetup
from app.domains.finance.bank_setup_schemas import (
    BankAccountCoreResponse,
    BankAccountProvisionRequest,
    BankAccountSetupCombinedResponse,
    BankAccountSetupResponse,
    BankAccountSetupUpdate,
    BankInstitutionResponse,
)
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit

router = APIRouter(prefix="/finance/bank-setup", tags=["finance-bank-setup"])
CENT = Decimal("0.01")
_SECRET_KEY_FRAGMENTS = ("secret", "token", "password", "privatekey", "apikey", "accesskey")


def money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    *,
    action: str,
    entity_id: str,
    after: dict[str, Any],
) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type="bank_account_setup",
        entity_id=entity_id,
        after_data=after,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _load_account(db: Session, organization_id: UUID, account_id: UUID) -> BankAccount:
    item = db.scalar(
        select(BankAccount).where(
            BankAccount.id == account_id,
            BankAccount.organization_id == organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Conta bancária não encontrada.")
    return item


def _account_balance(db: Session, account: BankAccount) -> Decimal:
    total = money(account.opening_balance)
    items = db.scalars(select(BankTransaction).where(BankTransaction.bank_account_id == account.id)).all()
    for item in items:
        total += money(item.amount) if item.direction == "credit" else -money(item.amount)
    return money(total)


def _core_account_response(db: Session, account: BankAccount) -> BankAccountCoreResponse:
    return BankAccountCoreResponse(
        id=account.id,
        code=f"BCO-{account.internal_number:04d}",
        name=account.name,
        bank_name=account.bank_name,
        bank_code=account.bank_code,
        branch=account.branch,
        account_number=account.account_number,
        account_digit=account.account_digit,
        account_type=account.account_type,
        fund_scope=account.fund_scope,
        core_provider=account.provider,
        pix_key=account.pix_key,
        opening_balance=money(account.opening_balance),
        current_balance=_account_balance(db, account),
        is_active=account.is_active,
        last_sync_at=account.last_sync_at,
        created_at=account.created_at,
    )


def _infer_institution(account: BankAccount) -> dict[str, Any]:
    if account.provider == "inter" or account.bank_code == "077" or "inter" in account.bank_name.lower():
        return bank_institution("inter") or {}
    for institution in bank_catalog():
        if institution.get("bank_code") and institution.get("bank_code") == account.bank_code:
            return institution
    item = bank_institution("other") or {}
    item["name"] = account.bank_name
    item["bank_code"] = account.bank_code
    return item


def _institution_for(setup: BankAccountSetup | None, account: BankAccount) -> dict[str, Any]:
    institution = bank_institution(setup.institution_key) if setup else _infer_institution(account)
    if not institution:
        institution = bank_institution("other") or {}
    if institution.get("key") == "other":
        institution["name"] = account.bank_name
        institution["bank_code"] = account.bank_code
    return institution


def _legacy_setup_response(account: BankAccount, institution: dict[str, Any]) -> BankAccountSetupResponse:
    is_inter_api = account.provider == "inter"
    integration_mode = "api" if is_inter_api else "manual"
    provider_key = "inter" if is_inter_api else str(institution.get("provider_key") or "manual")
    status = integration_status(institution, integration_mode)
    return BankAccountSetupResponse(
        id=account.id,
        bank_account_id=account.id,
        institution_key=str(institution.get("key") or "other"),
        account_purpose="rent_receipts_repasses" if account.fund_scope == "third_party" else "operating",
        integration_mode=integration_mode,
        provider_key=provider_key,
        environment="sandbox" if is_inter_api else "manual",
        provider_account_id=account.provider_account_id,
        credential_secret_ref=None,
        certificate_secret_ref=None,
        webhook_secret_ref=None,
        non_secret_config={},
        enabled_capabilities=list(institution.get("implemented_capabilities") or []) if is_inter_api else [],
        status=status,
        last_test_at=None,
        last_test_status=None,
        last_test_message=(
            "Adapter Inter existente usa configuração global; migração para credenciais por conta ainda é necessária."
            if is_inter_api
            else None
        ),
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _setup_response(setup: BankAccountSetup) -> BankAccountSetupResponse:
    return BankAccountSetupResponse(
        id=setup.id,
        bank_account_id=setup.bank_account_id,
        institution_key=setup.institution_key,
        account_purpose=setup.account_purpose,
        integration_mode=setup.integration_mode,
        provider_key=setup.provider_key,
        environment=setup.environment,
        provider_account_id=setup.provider_account_id,
        credential_secret_ref=setup.credential_secret_ref,
        certificate_secret_ref=setup.certificate_secret_ref,
        webhook_secret_ref=setup.webhook_secret_ref,
        non_secret_config=dict(setup.non_secret_config or {}),
        enabled_capabilities=list(setup.enabled_capabilities or []),
        status=setup.status,
        last_test_at=setup.last_test_at,
        last_test_status=setup.last_test_status,
        last_test_message=setup.last_test_message,
        created_at=setup.created_at,
        updated_at=setup.updated_at,
    )


def _combined(db: Session, account: BankAccount, setup: BankAccountSetup | None) -> BankAccountSetupCombinedResponse:
    institution = _institution_for(setup, account)
    setup_payload = _setup_response(setup) if setup else _legacy_setup_response(account, institution)
    return BankAccountSetupCombinedResponse(
        account=_core_account_response(db, account),
        setup=setup_payload,
        institution=BankInstitutionResponse(**institution),
    )


def _validate_non_secret_config(value: Any, path: str = "non_secret_config") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{path}.{key} parece conter uma credencial sensível. "
                        "Guarde o segredo no Secret Manager e informe apenas a referência no campo apropriado."
                    ),
                )
            _validate_non_secret_config(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_non_secret_config(nested, f"{path}[{index}]")


def _capabilities(institution: dict[str, Any], requested: list[str]) -> list[str]:
    implemented = set(institution.get("implemented_capabilities") or [])
    return sorted(set(requested).intersection(implemented))


def _core_provider(provider_key: str, integration_mode: str) -> str:
    # O contrato legado só conhece Inter e Manual. Outros providers ficam neutros
    # até o adaptador real ser implementado, evitando falso positivo ou crash.
    if integration_mode == "api" and provider_key == "inter":
        return "inter"
    return "manual"


@router.get("/catalog", response_model=list[BankInstitutionResponse])
def list_bank_catalog(
    context: UserContext = Depends(require_permission("finance.view")),
) -> list[BankInstitutionResponse]:
    _ = context
    return [BankInstitutionResponse(**item) for item in bank_catalog()]


@router.get("/accounts", response_model=list[BankAccountSetupCombinedResponse])
def list_bank_setups(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[BankAccountSetupCombinedResponse]:
    accounts = db.scalars(
        select(BankAccount)
        .where(BankAccount.organization_id == context.user.organization_id)
        .order_by(BankAccount.is_active.desc(), BankAccount.internal_number.asc())
    ).all()
    setup_by_account = {
        item.bank_account_id: item
        for item in db.scalars(
            select(BankAccountSetup).where(BankAccountSetup.organization_id == context.user.organization_id)
        ).all()
    }
    return [_combined(db, account, setup_by_account.get(account.id)) for account in accounts]


@router.get("/accounts/{account_id}", response_model=BankAccountSetupCombinedResponse)
def get_bank_setup(
    account_id: UUID,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> BankAccountSetupCombinedResponse:
    account = _load_account(db, context.user.organization_id, account_id)
    setup = db.scalar(
        select(BankAccountSetup).where(
            BankAccountSetup.organization_id == context.user.organization_id,
            BankAccountSetup.bank_account_id == account.id,
        )
    )
    return _combined(db, account, setup)


@router.post("/accounts", response_model=BankAccountSetupCombinedResponse, status_code=201)
def create_bank_setup_account(
    payload: BankAccountProvisionRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> BankAccountSetupCombinedResponse:
    institution = bank_institution(payload.institution_key)
    if institution is None:
        raise HTTPException(status_code=422, detail="Instituição bancária não reconhecida pelo catálogo.")
    if payload.integration_mode not in institution.get("supported_integration_modes", []):
        raise HTTPException(status_code=422, detail="Modo de integração não suportado para esta instituição.")

    if institution["key"] == "other":
        bank_name = (payload.custom_bank_name or "").strip()
        if len(bank_name) < 2:
            raise HTTPException(status_code=422, detail="Informe o nome do banco para a opção Outro banco.")
        bank_code = (payload.custom_bank_code or "").strip() or None
    else:
        bank_name = str(institution["name"])
        bank_code = str(institution.get("bank_code") or "") or None

    scope = purpose_fund_scope(payload.account_purpose, payload.fund_scope)
    provider_key = str(institution.get("provider_key") or "manual")
    environment = payload.environment if payload.integration_mode == "api" else "manual"
    status = integration_status(institution, payload.integration_mode)

    account = BankAccount(
        organization_id=context.user.organization_id,
        name=payload.name.strip(),
        bank_name=bank_name,
        bank_code=bank_code,
        branch=(payload.branch or "").strip() or None,
        account_number=(payload.account_number or "").strip() or None,
        account_digit=(payload.account_digit or "").strip() or None,
        account_type=payload.account_type,
        fund_scope=scope,
        provider=_core_provider(provider_key, payload.integration_mode),
        provider_account_id=(payload.provider_account_id or "").strip() or None,
        pix_key=(payload.pix_key or "").strip() or None,
        opening_balance=money(payload.opening_balance),
        created_by_user_id=context.user.id,
    )
    db.add(account)
    db.flush()

    setup = BankAccountSetup(
        organization_id=context.user.organization_id,
        bank_account_id=account.id,
        institution_key=str(institution["key"]),
        account_purpose=payload.account_purpose,
        integration_mode=payload.integration_mode,
        provider_key=provider_key,
        environment=environment,
        provider_account_id=(payload.provider_account_id or "").strip() or None,
        non_secret_config={},
        enabled_capabilities=[],
        status=status,
        last_test_message=(
            "Adapter Inter existente ainda usa configuração global; credenciais por conta serão migradas em etapa própria."
            if status == "api_legacy_adapter"
            else None
        ),
        created_by_user_id=context.user.id,
        updated_by_user_id=context.user.id,
    )
    db.add(setup)
    db.flush()
    _audit(
        db,
        request,
        context,
        action="finance.bank_setup.created",
        entity_id=str(setup.id),
        after={
            "bank_account_id": str(account.id),
            "institution_key": setup.institution_key,
            "account_purpose": setup.account_purpose,
            "fund_scope": account.fund_scope,
            "integration_mode": setup.integration_mode,
            "provider_key": setup.provider_key,
            "status": setup.status,
        },
    )
    db.commit()
    db.refresh(account)
    db.refresh(setup)
    return _combined(db, account, setup)


@router.put("/accounts/{account_id}", response_model=BankAccountSetupCombinedResponse)
def update_bank_setup(
    account_id: UUID,
    payload: BankAccountSetupUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> BankAccountSetupCombinedResponse:
    account = _load_account(db, context.user.organization_id, account_id)
    setup = db.scalar(
        select(BankAccountSetup).where(
            BankAccountSetup.organization_id == context.user.organization_id,
            BankAccountSetup.bank_account_id == account.id,
        )
    )
    institution = _institution_for(setup, account)
    if payload.integration_mode not in institution.get("supported_integration_modes", []):
        raise HTTPException(status_code=422, detail="Modo de integração não suportado para esta instituição.")
    _validate_non_secret_config(payload.non_secret_config)

    scope = purpose_fund_scope(payload.account_purpose, payload.fund_scope)
    provider_key = str(institution.get("provider_key") or "manual")
    environment = payload.environment if payload.integration_mode == "api" else "manual"
    status = integration_status(institution, payload.integration_mode)
    enabled_capabilities = _capabilities(institution, payload.enabled_capabilities)

    if setup is None:
        setup = BankAccountSetup(
            organization_id=context.user.organization_id,
            bank_account_id=account.id,
            institution_key=str(institution.get("key") or "other"),
            account_purpose=payload.account_purpose,
            integration_mode=payload.integration_mode,
            provider_key=provider_key,
            environment=environment,
            created_by_user_id=context.user.id,
        )
        db.add(setup)

    setup.account_purpose = payload.account_purpose
    setup.integration_mode = payload.integration_mode
    setup.provider_key = provider_key
    setup.environment = environment
    setup.provider_account_id = (payload.provider_account_id or "").strip() or None
    setup.credential_secret_ref = (payload.credential_secret_ref or "").strip() or None
    setup.certificate_secret_ref = (payload.certificate_secret_ref or "").strip() or None
    setup.webhook_secret_ref = (payload.webhook_secret_ref or "").strip() or None
    setup.non_secret_config = dict(payload.non_secret_config or {})
    setup.enabled_capabilities = enabled_capabilities
    setup.status = status
    setup.updated_by_user_id = context.user.id
    setup.last_test_at = None
    setup.last_test_status = None
    setup.last_test_message = (
        "Adapter Inter existente ainda usa configuração global; credenciais por conta serão migradas em etapa própria."
        if status == "api_legacy_adapter"
        else None
    )

    account.fund_scope = scope
    account.provider = _core_provider(provider_key, payload.integration_mode)
    account.provider_account_id = setup.provider_account_id
    db.flush()
    _audit(
        db,
        request,
        context,
        action="finance.bank_setup.updated",
        entity_id=str(setup.id),
        after={
            "bank_account_id": str(account.id),
            "institution_key": setup.institution_key,
            "account_purpose": setup.account_purpose,
            "fund_scope": account.fund_scope,
            "integration_mode": setup.integration_mode,
            "provider_key": setup.provider_key,
            "status": setup.status,
            "credential_reference_configured": bool(setup.credential_secret_ref),
            "certificate_reference_configured": bool(setup.certificate_secret_ref),
            "webhook_reference_configured": bool(setup.webhook_secret_ref),
        },
    )
    db.commit()
    db.refresh(account)
    db.refresh(setup)
    return _combined(db, account, setup)
