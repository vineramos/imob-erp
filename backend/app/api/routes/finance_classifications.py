from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.finance.core_models import FinancialTitle
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.defaults import OPERATIONAL_DEFAULTS
from app.domains.foundation.models import OrganizationSettings

router = APIRouter(prefix="/classifications")

DEFAULT_RULES = [
    {"key": "rent_receivable", "label": "Aluguéis recebidos", "direction": "receivable", "fund_scope": "third_party", "category": "Aluguéis"},
    {"key": "owner_repasse_payable", "label": "Parte dos proprietários / repasses", "direction": "payable", "fund_scope": "third_party", "category": "Parte dos proprietários / repasses"},
    {"key": "maintenance_receivable", "label": "Manutenções cobradas", "direction": "receivable", "fund_scope": "operating", "category": "Manutenções · recebimentos"},
    {"key": "maintenance_payable", "label": "Manutenções pagas a parceiros", "direction": "payable", "fund_scope": "operating", "category": "Manutenções · parceiros"},
    {"key": "commission_broker_payable", "label": "Comissões de corretores", "direction": "payable", "fund_scope": "operating", "category": "Comissões · corretores"},
    {"key": "commission_referrer_payable", "label": "Angariações", "direction": "payable", "fund_scope": "operating", "category": "Angariações"},
]


class ClassificationRuleUpdate(BaseModel):
    key: str = Field(min_length=2, max_length=80)
    category: str = Field(min_length=2, max_length=120)


class ClassificationsUpdate(BaseModel):
    rules: list[ClassificationRuleUpdate]


class CustomClassificationCreate(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    direction: Literal["receivable", "payable"]
    fund_scope: Literal["operating", "third_party"] = "operating"


def _settings(db: Session, context: UserContext) -> OrganizationSettings:
    item = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == context.user.organization_id))
    if item is None:
        item = OrganizationSettings(
            organization_id=context.user.organization_id,
            erp_theme={},
            site_theme={},
            operational_defaults=dict(OPERATIONAL_DEFAULTS),
            integrations={},
            updated_by_user_id=context.user.id,
        )
        db.add(item)
        db.flush()
    return item


def _custom_rules(settings: OrganizationSettings) -> list[dict]:
    operational = dict(settings.operational_defaults or {})
    raw = operational.get("finance_custom_classifications") or []
    if not isinstance(raw, list):
        return []
    result: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or item.get("category") or "").strip()
        direction = str(item.get("direction") or "")
        fund_scope = str(item.get("fund_scope") or "operating")
        if not key or not label or direction not in {"receivable", "payable"} or fund_scope not in {"operating", "third_party"}:
            continue
        result.append({"key": key, "label": label, "direction": direction, "fund_scope": fund_scope, "category": str(item.get("category") or label).strip() or label})
    return result


def _merged_rules(settings: OrganizationSettings) -> list[dict]:
    operational = dict(settings.operational_defaults or {})
    custom_names = operational.get("finance_classifications") or {}
    if not isinstance(custom_names, dict):
        custom_names = {}
    result = []
    for default in DEFAULT_RULES:
        override = custom_names.get(default["key"])
        category = str(override or default["category"]).strip() or default["category"]
        result.append({**default, "category": category, "scope_locked": True, "custom": False, "deletable": False})
    for custom in _custom_rules(settings):
        override = custom_names.get(custom["key"])
        category = str(override or custom["category"]).strip() or custom["category"]
        result.append({**custom, "category": category, "scope_locked": False, "custom": True, "deletable": True})
    return result


def _audit_settings(db: Session, request: Request, context: UserContext, settings: OrganizationSettings, *, action: str, before: dict, after: dict) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type="organization_settings",
        entity_id=str(settings.id),
        before_data=before,
        after_data=after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )


@router.get("")
def list_classifications(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> dict:
    return {"rules": _merged_rules(_settings(db, context))}


@router.put("")
def update_classifications(
    payload: ClassificationsUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> dict:
    settings = _settings(db, context)
    allowed = {item["key"] for item in _merged_rules(settings)}
    current = dict(settings.operational_defaults or {})
    previous = dict(current.get("finance_classifications") or {})
    updated = dict(previous)
    for rule in payload.rules:
        if rule.key in allowed:
            updated[rule.key] = rule.category.strip()
    current["finance_classifications"] = updated
    settings.operational_defaults = current
    settings.updated_by_user_id = context.user.id
    _audit_settings(db, request, context, settings, action="finance.classifications.updated", before={"finance_classifications": previous}, after={"finance_classifications": updated})
    db.commit()
    return {"rules": _merged_rules(settings)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_classification(
    payload: CustomClassificationCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> dict:
    settings = _settings(db, context)
    current = dict(settings.operational_defaults or {})
    previous = list(current.get("finance_custom_classifications") or [])
    label = payload.label.strip()
    existing_labels = {str(item.get("label") or item.get("category") or "").strip().casefold() for item in previous if isinstance(item, dict)}
    if label.casefold() in existing_labels:
        raise HTTPException(status_code=409, detail="Já existe uma categoria personalizada com este nome.")
    created = {
        "key": f"custom_{uuid4().hex[:12]}",
        "label": label,
        "category": label,
        "direction": payload.direction,
        "fund_scope": payload.fund_scope,
    }
    updated = [*previous, created]
    current["finance_custom_classifications"] = updated
    settings.operational_defaults = current
    settings.updated_by_user_id = context.user.id
    _audit_settings(db, request, context, settings, action="finance.classification.created", before={"finance_custom_classifications": previous}, after={"finance_custom_classifications": updated})
    db.commit()
    return {"rules": _merged_rules(settings), "created_key": created["key"]}


@router.delete("/{rule_key}")
def delete_classification(
    rule_key: str,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> dict:
    settings = _settings(db, context)
    current = dict(settings.operational_defaults or {})
    previous = list(current.get("finance_custom_classifications") or [])
    updated = [item for item in previous if not (isinstance(item, dict) and str(item.get("key")) == rule_key)]
    if len(updated) == len(previous):
        raise HTTPException(status_code=404, detail="Categoria personalizada não encontrada.")
    current["finance_custom_classifications"] = updated
    overrides = dict(current.get("finance_classifications") or {})
    overrides.pop(rule_key, None)
    current["finance_classifications"] = overrides
    settings.operational_defaults = current
    settings.updated_by_user_id = context.user.id
    _audit_settings(db, request, context, settings, action="finance.classification.deleted", before={"finance_custom_classifications": previous}, after={"finance_custom_classifications": updated})
    db.commit()
    return {"rules": _merged_rules(settings)}


@router.get("/suggestion")
def classification_suggestion(
    person_id: UUID = Query(...),
    direction: Literal["receivable", "payable"] = Query(...),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> dict:
    candidates = db.scalars(
        select(FinancialTitle)
        .where(
            FinancialTitle.organization_id == context.user.organization_id,
            FinancialTitle.direction == direction,
            FinancialTitle.source_type == "manual",
        )
        .order_by(FinancialTitle.created_at.desc())
        .limit(300)
    ).all()
    person_key = str(person_id)
    for item in candidates:
        snapshot = dict(item.source_snapshot or {})
        if str(snapshot.get("counterparty_person_id") or "") == person_key:
            return {
                "found": True,
                "category": item.category,
                "fund_scope": item.fund_scope,
                "source_title_id": str(item.id),
            }
    return {"found": False, "category": None, "fund_scope": None, "source_title_id": None}
