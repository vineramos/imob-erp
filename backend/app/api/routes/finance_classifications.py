from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
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


def _merged_rules(settings: OrganizationSettings) -> list[dict]:
    operational = dict(settings.operational_defaults or {})
    custom = operational.get("finance_classifications") or {}
    if not isinstance(custom, dict):
        custom = {}
    result = []
    for default in DEFAULT_RULES:
        override = custom.get(default["key"])
        category = str(override or default["category"]).strip() or default["category"]
        result.append({**default, "category": category, "scope_locked": True})
    return result


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
    allowed = {item["key"] for item in DEFAULT_RULES}
    current = dict(settings.operational_defaults or {})
    previous = dict(current.get("finance_classifications") or {})
    updated = dict(previous)
    for rule in payload.rules:
        if rule.key in allowed:
            updated[rule.key] = rule.category.strip()
    current["finance_classifications"] = updated
    settings.operational_defaults = current
    settings.updated_by_user_id = context.user.id
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action="finance.classifications.updated",
        module="finance",
        entity_type="organization_settings",
        entity_id=str(settings.id),
        before_data={"finance_classifications": previous},
        after_data={"finance_classifications": updated},
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return {"rules": _merged_rules(settings)}


@router.get("/suggestion")
def classification_suggestion(
    person_id: UUID = Query(...),
    direction: Literal["receivable", "payable"] = Query(...),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> dict:
    # A própria história financeira vira a memória da contraparte. A última
    # classificação usada para a Pessoa/CNPJ é sugerida no próximo lançamento.
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
