from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.routes.finance import _owner_statement
from app.api.routes.finance_banking import _fingerprint, _load_account
from app.core.config import get_settings
from app.core.database import get_db
from app.domains.finance.advanced_models import (
    BillingBatch,
    BillingItem,
    CommissionEntry,
    CommissionRule,
    DelinquencyCase,
    InterWebhookEvent,
    PortalAccess,
)
from app.domains.finance.advanced_schemas import (
    AnnualIncomeLine,
    AnnualIncomeReport,
    BillingBatchResponse,
    BillingIssueRequest,
    BillingItemResponse,
    BillingRunRequest,
    BillingRunResponse,
    CommissionEntryResponse,
    CommissionRuleCreate,
    CommissionRuleResponse,
    CommissionRuleUpdate,
    DelinquencyActionRequest,
    DelinquencyCaseResponse,
    DreLine,
    DreReport,
    FinanceReportOverview,
    InterStatusResponse,
    InterSyncResponse,
    PortalAccessCreate,
    PortalAccessCreated,
    PortalAccessResponse,
    PortalCharge,
    PortalPayload,
    PortalProperty,
    PortalRepasse,
)
from app.domains.finance.advanced_service import (
    annual_income_values,
    dre_values,
    ensure_billing_batch,
    generate_commissions_for_charge,
    money,
    refresh_billing_batch_counters,
    refresh_delinquency_cases,
    sync_commission_status,
)
from app.domains.finance.bank_models import BankAccount, BankTransaction
from app.domains.finance.core_models import FinancialTitle
from app.domains.finance.models import FinancialSettlement, MaintenanceFinancialEntry, OwnerRepasse, RentCharge
from app.domains.finance.pdf import build_owner_statement_pdf
from app.domains.finance.providers import BankProviderError, InterBankProvider
from app.domains.finance.service import record_payment
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization
from app.domains.leases.models import LeaseContract
from app.domains.portfolio.models import Person, Property, PropertyOwner

router = APIRouter(prefix="/finance/advanced", tags=["finance-advanced"])
public_router = APIRouter(prefix="/portal", tags=["external-portal"])
webhook_router = APIRouter(prefix="/integrations/inter", tags=["inter-webhook"])
ZERO = Decimal("0.00")


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else None), request.headers.get("user-agent")


def _audit(
    db: Session,
    request: Request,
    context: UserContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    after: dict | None = None,
    reason: str | None = None,
) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type=entity_type,
        entity_id=entity_id,
        after_data=after,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _property_code(snapshot: dict | None) -> str:
    return str((snapshot or {}).get("code") or "—")


def _tenant_name(charge: RentCharge) -> str:
    return next(
        (str(item.get("name")) for item in list(charge.tenant_snapshot or []) if isinstance(item, dict) and item.get("name")),
        "Locatário",
    )


def _billing_item_response(db: Session, item: BillingItem) -> BillingItemResponse:
    charge = db.get(RentCharge, item.charge_id)
    if charge is None:
        raise HTTPException(status_code=409, detail="Cobrança vinculada ao lote não foi encontrada.")
    lease = db.get(LeaseContract, charge.lease_contract_id)
    return BillingItemResponse(
        id=item.id,
        charge_id=charge.id,
        charge_code=f"COB-{charge.internal_number:06d}",
        lease_code=f"LOC-{lease.internal_number:06d}" if lease else "LOC-—",
        property_code=_property_code(charge.property_snapshot),
        tenant_name=_tenant_name(charge),
        due_date=charge.due_date,
        amount=float(money(charge.gross_amount)),
        charge_status=charge.status,
        provider=item.provider,
        provider_charge_id=item.provider_charge_id,
        provider_status=item.provider_status,
        boleto_line=item.boleto_line,
        pix_copy_paste=item.pix_copy_paste,
        issued_at=item.issued_at,
        sent_at=item.sent_at,
        confirmed_at=item.confirmed_at,
        last_error=item.last_error,
    )


def _billing_batch_response(db: Session, batch: BillingBatch) -> BillingBatchResponse:
    items = db.scalars(
        select(BillingItem).where(BillingItem.billing_batch_id == batch.id).order_by(BillingItem.created_at)
    ).all()
    return BillingBatchResponse(
        id=batch.id,
        code=f"FAT-{batch.internal_number:05d}",
        competence=batch.competence,
        status=batch.status,
        provider=batch.provider,
        generated_count=int(batch.generated_count),
        issued_count=int(batch.issued_count),
        sent_count=int(batch.sent_count),
        confirmed_count=int(batch.confirmed_count),
        error_count=int(batch.error_count),
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        items=[_billing_item_response(db, item) for item in items],
    )


def _load_batch(db: Session, organization_id: UUID, batch_id: UUID) -> BillingBatch:
    item = db.scalar(
        select(BillingBatch).where(BillingBatch.id == batch_id, BillingBatch.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Lote de cobrança não encontrado.")
    return item


def _digits(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def _inter_payer(charge: RentCharge) -> dict:
    tenant = next((item for item in list(charge.tenant_snapshot or []) if isinstance(item, dict)), None) or {}
    name = str(tenant.get("name") or "").strip()
    document = _digits(str(tenant.get("document_number") or tenant.get("document") or tenant.get("cpf_cnpj") or ""))
    if not name or len(document) not in {11, 14}:
        raise ValueError("Locatário precisa ter nome e CPF/CNPJ válidos para emissão no Banco Inter.")
    address = tenant.get("address") if isinstance(tenant.get("address"), dict) else {}
    phone = _digits(str(tenant.get("phone") or ""))
    email = str(tenant.get("email") or "").strip()
    payload = {
        "cpfCnpj": document,
        "tipoPessoa": "FISICA" if len(document) == 11 else "JURIDICA",
        "nome": name[:100],
        "endereco": str(address.get("street") or address.get("logradouro") or "Não informado")[:100],
        "numero": str(address.get("number") or address.get("numero") or "S/N")[:20],
        "bairro": str(address.get("neighborhood") or address.get("bairro") or "Não informado")[:60],
        "cidade": str(address.get("city") or address.get("cidade") or "Curitiba")[:60],
        "uf": str(address.get("state") or address.get("uf") or "PR")[:2].upper(),
        "cep": _digits(str(address.get("postal_code") or address.get("cep") or "00000000"))[:8],
    }
    complement = str(address.get("complement") or address.get("complemento") or "").strip()
    if complement:
        payload["complemento"] = complement[:60]
    if email:
        payload["email"] = email[:80]
    if len(phone) >= 10:
        payload["ddd"] = phone[:2]
        payload["telefone"] = phone[2:][:11]
    return payload


def _inter_charge_payload(charge: RentCharge) -> dict:
    return {
        "seuNumero": f"C{charge.internal_number}"[:15],
        "valorNominal": float(money(charge.gross_amount)),
        "dataVencimento": charge.due_date.isoformat(),
        "numDiasAgenda": 60,
        "pagador": _inter_payer(charge),
        "mensagem": {
            "linha1": f"Aluguel/encargos {charge.competence:%m/%Y}",
            "linha2": f"Imóvel {_property_code(charge.property_snapshot)}",
        },
        "formasRecebimento": ["BOLETO", "PIX"],
    }


def _apply_inter_detail(item: BillingItem, data: dict) -> None:
    cobranca = data.get("cobranca") if isinstance(data.get("cobranca"), dict) else data
    boleto = data.get("boleto") if isinstance(data.get("boleto"), dict) else {}
    pix = data.get("pix") if isinstance(data.get("pix"), dict) else {}
    item.provider_status = str(cobranca.get("situacao") or item.provider_status or "EM_PROCESSAMENTO")
    item.boleto_line = str(boleto.get("linhaDigitavel") or "") or item.boleto_line
    item.barcode = str(boleto.get("codigoBarras") or "") or item.barcode
    item.pix_copy_paste = str(pix.get("pixCopiaECola") or "") or item.pix_copy_paste
    item.pix_txid = str(pix.get("txid") or "") or item.pix_txid
    item.response_snapshot = dict(data)
    if item.provider_status.upper() in {"RECEBIDO", "MARCADO_RECEBIDO"}:
        item.confirmed_at = item.confirmed_at or datetime.now(timezone.utc)


def _delinquency_response(db: Session, item: DelinquencyCase) -> DelinquencyCaseResponse:
    charge = db.get(RentCharge, item.charge_id)
    if charge is None:
        raise HTTPException(status_code=409, detail="Cobrança da inadimplência não foi encontrada.")
    lease = db.get(LeaseContract, item.lease_contract_id)
    days = max(0, (date.today() - charge.due_date).days) if charge.status == "overdue" else 0
    return DelinquencyCaseResponse(
        id=item.id,
        code=f"INA-{item.internal_number:05d}",
        charge_id=charge.id,
        charge_code=f"COB-{charge.internal_number:06d}",
        lease_contract_id=item.lease_contract_id,
        lease_code=f"LOC-{lease.internal_number:06d}" if lease else "LOC-—",
        property_id=item.property_id,
        property_code=_property_code(charge.property_snapshot),
        tenant_name=_tenant_name(charge),
        due_date=charge.due_date,
        amount=float(money(charge.gross_amount)),
        days_overdue=days,
        critical=days >= item.critical_after_days and item.status != "resolved",
        status=item.status,
        insurer_protocol=item.insurer_protocol,
        opened_at=item.opened_at,
        critical_at=item.critical_at,
        last_contact_at=item.last_contact_at,
        next_action_at=item.next_action_at,
        insurer_triggered_at=item.insurer_triggered_at,
        resolved_at=item.resolved_at,
        notes=item.notes,
        action_log=list(item.action_log or []),
    )


def _commission_rule_response(item: CommissionRule) -> CommissionRuleResponse:
    return CommissionRuleResponse(
        id=item.id,
        code=f"COMR-{item.internal_number:04d}",
        name=item.name,
        event_type=item.event_type,
        basis=item.basis,
        calculation_type=item.calculation_type,
        value=float(item.value),
        beneficiary_type=item.beneficiary_type,
        beneficiary_person_id=item.beneficiary_person_id,
        beneficiary_name=item.beneficiary_name,
        property_id=item.property_id,
        lease_contract_id=item.lease_contract_id,
        due_days=item.due_days,
        priority=item.priority,
        is_active=item.is_active,
        notes=item.notes,
        created_at=item.created_at,
    )


def _commission_entry_response(db: Session, item: CommissionEntry) -> CommissionEntryResponse:
    sync_commission_status(db, item)
    return CommissionEntryResponse(
        id=item.id,
        code=f"COM-{item.internal_number:06d}",
        rule_id=item.rule_id,
        source_type=item.source_type,
        source_id=item.source_id,
        source_code=item.source_code,
        beneficiary_type=item.beneficiary_type,
        beneficiary_person_id=item.beneficiary_person_id,
        beneficiary_name=item.beneficiary_name,
        competence=item.competence,
        basis_amount=float(money(item.basis_amount)),
        amount=float(money(item.amount)),
        due_date=item.due_date,
        status=item.status,
        financial_title_id=item.financial_title_id,
        paid_at=item.paid_at,
        payment_reference=item.payment_reference,
        created_at=item.created_at,
    )


@router.post("/billing/run", response_model=BillingRunResponse)
def billing_run(
    payload: BillingRunRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.charge.create")),
    db: Session = Depends(get_db),
) -> BillingRunResponse:
    batch, generated, skipped_existing, skipped_ineligible = ensure_billing_batch(
        db,
        organization_id=context.user.organization_id,
        user_id=context.user.id,
        competence=payload.competence,
    )
    _audit(
        db,
        request,
        context,
        action="finance.billing.run",
        entity_type="billing_batch",
        entity_id=str(batch.id),
        after={"competence": str(batch.competence), "generated": generated},
    )
    db.commit()
    batch = _load_batch(db, context.user.organization_id, batch.id)
    return BillingRunResponse(
        generated=generated,
        skipped_existing=skipped_existing,
        skipped_ineligible=skipped_ineligible,
        batch=_billing_batch_response(db, batch),
    )


@router.get("/billing/batches", response_model=list[BillingBatchResponse])
def billing_batches(
    competence: date | None = Query(default=None),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[BillingBatchResponse]:
    stmt = select(BillingBatch).where(BillingBatch.organization_id == context.user.organization_id)
    if competence:
        stmt = stmt.where(BillingBatch.competence == competence.replace(day=1))
    items = db.scalars(stmt.order_by(BillingBatch.competence.desc(), BillingBatch.internal_number.desc()).limit(36)).all()
    return [_billing_batch_response(db, item) for item in items]


@router.post("/billing/batches/{batch_id}/issue-inter", response_model=BillingBatchResponse)
def issue_billing_inter(
    batch_id: UUID,
    payload: BillingIssueRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.charge.create")),
    db: Session = Depends(get_db),
) -> BillingBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    account = _load_account(db, context.user.organization_id, payload.bank_account_id)
    if account.provider != "inter":
        raise HTTPException(status_code=409, detail="A conta selecionada não usa o provedor Banco Inter.")
    if account.fund_scope != "third_party":
        raise HTTPException(status_code=409, detail="Cobranças de aluguel devem ser emitidas na conta de recursos de terceiros.")
    provider = InterBankProvider()
    if not provider.status().configured:
        raise HTTPException(status_code=409, detail="Banco Inter ainda não possui credenciais/certificado configurados no ambiente.")

    items = db.scalars(select(BillingItem).where(BillingItem.billing_batch_id == batch.id)).all()
    now = datetime.now(timezone.utc)
    for item in items:
        if item.provider_charge_id:
            continue
        charge = db.get(RentCharge, item.charge_id)
        if charge is None or charge.status == "cancelled":
            continue
        try:
            request_payload = _inter_charge_payload(charge)
            result = provider.issue_charge(request_payload)
            provider_id = str(result.get("codigoSolicitacao") or "")
            if not provider_id:
                raise BankProviderError("Banco Inter não retornou codigoSolicitacao para a cobrança.")
            item.provider = "inter"
            item.provider_charge_id = provider_id
            item.provider_status = "EM_PROCESSAMENTO"
            item.request_snapshot = request_payload
            item.response_snapshot = dict(result)
            item.issued_at = now
            item.last_error = None
            try:
                _apply_inter_detail(item, provider.charge(provider_id))
            except BankProviderError:
                pass
        except (BankProviderError, ValueError) as exc:
            item.provider = "inter"
            item.last_error = str(exc)
    batch.provider = "inter"
    refresh_billing_batch_counters(db, batch)
    _audit(db, request, context, action="finance.billing.inter_issued", entity_type="billing_batch", entity_id=str(batch.id), after={"issued": batch.issued_count, "errors": batch.error_count})
    db.commit()
    return _billing_batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/billing/batches/{batch_id}/sync-inter", response_model=BillingBatchResponse)
def sync_billing_inter(
    batch_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> BillingBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    provider = InterBankProvider()
    if not provider.status().configured:
        raise HTTPException(status_code=409, detail="Banco Inter ainda não está configurado no ambiente.")
    items = db.scalars(select(BillingItem).where(BillingItem.billing_batch_id == batch.id)).all()
    for item in items:
        if not item.provider_charge_id:
            continue
        try:
            _apply_inter_detail(item, provider.charge(item.provider_charge_id))
            item.last_error = None
        except BankProviderError as exc:
            item.last_error = str(exc)
    refresh_billing_batch_counters(db, batch)
    _audit(db, request, context, action="finance.billing.inter_synced", entity_type="billing_batch", entity_id=str(batch.id), after={"confirmed": batch.confirmed_count, "errors": batch.error_count})
    db.commit()
    return _billing_batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/billing/batches/{batch_id}/mark-sent", response_model=BillingBatchResponse)
def mark_billing_sent(
    batch_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.charge.create")),
    db: Session = Depends(get_db),
) -> BillingBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    items = db.scalars(select(BillingItem).where(BillingItem.billing_batch_id == batch.id)).all()
    now = datetime.now(timezone.utc)
    for item in items:
        charge = db.get(RentCharge, item.charge_id)
        if charge is None or charge.status in {"paid", "cancelled"}:
            continue
        if item.sent_at is None:
            item.sent_at = now
        if charge.sent_at is None:
            charge.sent_at = now
        if charge.due_date >= date.today():
            charge.status = "sent"
    refresh_billing_batch_counters(db, batch)
    _audit(db, request, context, action="finance.billing.sent", entity_type="billing_batch", entity_id=str(batch.id), after={"sent": batch.sent_count})
    db.commit()
    return _billing_batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/delinquency/refresh", response_model=list[DelinquencyCaseResponse])
def refresh_delinquency(
    request: Request,
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[DelinquencyCaseResponse]:
    items = refresh_delinquency_cases(db, organization_id=context.user.organization_id)
    _audit(db, request, context, action="finance.delinquency.refreshed", entity_type="delinquency", entity_id=None, after={"cases": len(items)})
    db.commit()
    return [_delinquency_response(db, item) for item in items]


@router.get("/delinquency", response_model=list[DelinquencyCaseResponse])
def list_delinquency(
    case_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[DelinquencyCaseResponse]:
    items = refresh_delinquency_cases(db, organization_id=context.user.organization_id)
    db.commit()
    if case_status:
        items = [item for item in items if item.status == case_status]
    items.sort(key=lambda item: (item.status == "resolved", db.get(RentCharge, item.charge_id).due_date if db.get(RentCharge, item.charge_id) else date.max))
    return [_delinquency_response(db, item) for item in items]


@router.post("/delinquency/{case_id}/action", response_model=DelinquencyCaseResponse)
def delinquency_action(
    case_id: UUID,
    payload: DelinquencyActionRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> DelinquencyCaseResponse:
    item = db.scalar(select(DelinquencyCase).where(DelinquencyCase.id == case_id, DelinquencyCase.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Caso de inadimplência não encontrado.")
    now = datetime.now(timezone.utc)
    previous = item.status
    item.status = payload.status
    item.notes = (payload.notes or item.notes or "").strip() or None
    item.next_action_at = payload.next_action_at
    if payload.status in {"contacted", "negotiating"}:
        item.last_contact_at = now
    if payload.status == "insurer_triggered":
        item.insurer_triggered_at = item.insurer_triggered_at or now
        item.insurer_protocol = (payload.insurer_protocol or item.insurer_protocol or "").strip() or None
    if payload.status == "resolved":
        item.resolved_at = now
    elif previous == "resolved":
        item.resolved_at = None
    item.action_log = [
        *list(item.action_log or []),
        {
            "at": now.isoformat(),
            "action": payload.status,
            "actor_user_id": str(context.user.id),
            "notes": payload.notes,
            "insurer_protocol": item.insurer_protocol,
        },
    ]
    _audit(db, request, context, action="finance.delinquency.action", entity_type="delinquency_case", entity_id=str(item.id), after={"from": previous, "to": item.status, "protocol": item.insurer_protocol})
    db.commit()
    return _delinquency_response(db, item)


@router.get("/reports/dre", response_model=DreReport)
def dre_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    regime: str = Query(default="cash", pattern="^(cash|competence)$"),
    context: UserContext = Depends(require_permission("reports.view")),
    db: Session = Depends(get_db),
) -> DreReport:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="Período inválido.")
    values = dre_values(db, organization_id=context.user.organization_id, start_date=start_date, end_date=end_date, regime=regime)
    lines = [
        DreLine(key="administration", label="Taxas de administração", kind="revenue", amount=float(values["administration"])),
        DreLine(key="intermediation", label="Intermediação", kind="revenue", amount=float(values["intermediation"])),
        DreLine(key="maintenance_revenue", label="Receitas de manutenção", kind="revenue", amount=float(values["maintenance_revenue"])),
        DreLine(key="other_revenue", label="Outras receitas operacionais", kind="revenue", amount=float(values["other_revenue"])),
        DreLine(key="maintenance_cost", label="Custos de parceiros de manutenção", kind="expense", amount=float(values["maintenance_cost"])),
        DreLine(key="commissions", label="Comissões", kind="expense", amount=float(values["commissions"])),
        DreLine(key="other_expense", label="Outras despesas operacionais", kind="expense", amount=float(values["other_expense"])),
    ]
    revenue = money(sum((Decimal(str(line.amount)) for line in lines if line.kind == "revenue"), ZERO))
    expenses = money(sum((Decimal(str(line.amount)) for line in lines if line.kind == "expense"), ZERO))
    result = money(revenue - expenses)
    margin = float((result / revenue * Decimal("100")) if revenue else ZERO)
    return DreReport(start_date=start_date, end_date=end_date, regime=regime, total_revenue=float(revenue), total_expenses=float(expenses), result=float(result), margin_percent=round(margin, 2), lines=lines)


@router.get("/reports/overview", response_model=FinanceReportOverview)
def report_overview(
    start_date: date = Query(...),
    end_date: date = Query(...),
    context: UserContext = Depends(require_permission("reports.view")),
    db: Session = Depends(get_db),
) -> FinanceReportOverview:
    charges = db.scalars(select(RentCharge).where(RentCharge.organization_id == context.user.organization_id)).all()
    paid = [item for item in charges if item.status == "paid" and item.paid_at and start_date <= item.paid_at.date() <= end_date]
    open_items = [item for item in charges if item.status in {"generated", "sent", "overdue"} and item.due_date <= end_date]
    overdue = [item for item in open_items if item.status == "overdue"]
    settlements = {item.charge_id: item for item in db.scalars(select(FinancialSettlement).where(FinancialSettlement.organization_id == context.user.organization_id)).all()}
    repasses = db.scalars(select(OwnerRepasse).where(OwnerRepasse.organization_id == context.user.organization_id, OwnerRepasse.status == "paid")).all()
    maintenance = db.scalars(select(MaintenanceFinancialEntry).where(MaintenanceFinancialEntry.organization_id == context.user.organization_id, MaintenanceFinancialEntry.settled_at.is_not(None))).all()
    commissions = db.scalars(select(CommissionEntry).where(CommissionEntry.organization_id == context.user.organization_id)).all()
    for item in commissions:
        sync_commission_status(db, item)
    db.flush()
    return FinanceReportOverview(
        start_date=start_date,
        end_date=end_date,
        tenant_collections=float(money(sum((money(item.paid_amount) for item in paid), ZERO))),
        agency_revenue=float(money(sum((money(settlements[item.id].agency_fee_withheld) for item in paid if item.id in settlements), ZERO))),
        owner_repasses=float(money(sum((money(item.amount) for item in repasses if item.paid_at and start_date <= item.paid_at.date() <= end_date), ZERO))),
        maintenance_revenue=float(money(sum((money(item.settled_amount) for item in maintenance if item.direction == "receivable" and item.collection_method != "owner_repasse_deduction" and item.settled_at and start_date <= item.settled_at.date() <= end_date), ZERO))),
        maintenance_cost=float(money(sum((money(item.settled_amount) for item in maintenance if item.direction == "payable" and item.settled_at and start_date <= item.settled_at.date() <= end_date), ZERO))),
        commissions=float(money(sum((money(item.amount) for item in commissions if item.status == "paid" and item.paid_at and start_date <= item.paid_at.date() <= end_date), ZERO))),
        overdue_amount=float(money(sum((money(item.gross_amount) for item in overdue), ZERO))),
        overdue_count=len(overdue),
        paid_charges=len(paid),
        open_charges=len(open_items),
    )


@router.get("/reports/annual-income", response_model=AnnualIncomeReport)
def annual_income(
    year: int = Query(..., ge=2000, le=2200),
    party_type: str = Query(default="tenant", pattern="^(tenant|owner)$"),
    person_id: UUID = Query(...),
    context: UserContext = Depends(require_permission("reports.view")),
    db: Session = Depends(get_db),
) -> AnnualIncomeReport:
    try:
        person, raw_lines, allocation_method = annual_income_values(db, organization_id=context.user.organization_id, year=year, party_type=party_type, person_id=person_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    lines = [AnnualIncomeLine(**{**line, key: float(value) if isinstance(value, Decimal) else value for key, value in line.items()}) for line in raw_lines]
    return AnnualIncomeReport(
        year=year,
        party_type=party_type,
        person_id=person.id,
        person_name=person.name,
        allocation_method=allocation_method,
        total_rent=float(money(sum((money(item["rent_amount"]) for item in raw_lines), ZERO))),
        total_additional_charges=float(money(sum((money(item["additional_charges"]) for item in raw_lines), ZERO))),
        total_paid=float(money(sum((money(item["total_amount"]) for item in raw_lines), ZERO))),
        total_administration_fee=float(money(sum((money(item["administration_fee"]) for item in raw_lines), ZERO))),
        total_owner_net=float(money(sum((money(item["owner_net_amount"]) for item in raw_lines), ZERO))),
        lines=lines,
    )


@router.get("/commissions/rules", response_model=list[CommissionRuleResponse])
def commission_rules(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[CommissionRuleResponse]:
    items = db.scalars(select(CommissionRule).where(CommissionRule.organization_id == context.user.organization_id).order_by(CommissionRule.priority, CommissionRule.internal_number)).all()
    return [_commission_rule_response(item) for item in items]


@router.post("/commissions/rules", response_model=CommissionRuleResponse, status_code=status.HTTP_201_CREATED)
def create_commission_rule(
    payload: CommissionRuleCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> CommissionRuleResponse:
    person = db.scalar(select(Person).where(Person.id == payload.beneficiary_person_id, Person.organization_id == context.user.organization_id, Person.is_active.is_(True)))
    if person is None:
        raise HTTPException(status_code=422, detail="Beneficiário da comissão não encontrado.")
    item = CommissionRule(
        organization_id=context.user.organization_id,
        name=payload.name.strip(),
        event_type=payload.event_type,
        basis=payload.basis,
        calculation_type=payload.calculation_type,
        value=Decimal(str(payload.value)),
        beneficiary_type=payload.beneficiary_type,
        beneficiary_person_id=person.id,
        beneficiary_name=person.name,
        property_id=payload.property_id,
        lease_contract_id=payload.lease_contract_id,
        due_days=payload.due_days,
        priority=payload.priority,
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    _audit(db, request, context, action="finance.commission_rule.created", entity_type="commission_rule", entity_id=str(item.id), after={"name": item.name, "beneficiary": item.beneficiary_name})
    db.commit()
    return _commission_rule_response(item)


@router.put("/commissions/rules/{rule_id}", response_model=CommissionRuleResponse)
def update_commission_rule(
    rule_id: UUID,
    payload: CommissionRuleUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> CommissionRuleResponse:
    item = db.scalar(select(CommissionRule).where(CommissionRule.id == rule_id, CommissionRule.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Regra de comissão não encontrada.")
    person = db.scalar(select(Person).where(Person.id == payload.beneficiary_person_id, Person.organization_id == context.user.organization_id, Person.is_active.is_(True)))
    if person is None:
        raise HTTPException(status_code=422, detail="Beneficiário da comissão não encontrado.")
    item.name = payload.name.strip()
    item.event_type = payload.event_type
    item.basis = payload.basis
    item.calculation_type = payload.calculation_type
    item.value = Decimal(str(payload.value))
    item.beneficiary_type = payload.beneficiary_type
    item.beneficiary_person_id = person.id
    item.beneficiary_name = person.name
    item.property_id = payload.property_id
    item.lease_contract_id = payload.lease_contract_id
    item.due_days = payload.due_days
    item.priority = payload.priority
    item.is_active = payload.is_active
    item.notes = (payload.notes or "").strip() or None
    _audit(db, request, context, action="finance.commission_rule.updated", entity_type="commission_rule", entity_id=str(item.id), after={"active": item.is_active, "beneficiary": item.beneficiary_name})
    db.commit()
    return _commission_rule_response(item)


@router.post("/commissions/generate", response_model=list[CommissionEntryResponse])
def generate_commissions(
    start_date: date = Query(...),
    end_date: date = Query(...),
    request: Request = None,
    context: UserContext = Depends(require_permission("finance.payment.prepare")),
    db: Session = Depends(get_db),
) -> list[CommissionEntryResponse]:
    charges = db.scalars(select(RentCharge).where(RentCharge.organization_id == context.user.organization_id, RentCharge.status == "paid")).all()
    settlements = {item.charge_id: item for item in db.scalars(select(FinancialSettlement).where(FinancialSettlement.organization_id == context.user.organization_id)).all()}
    created: list[CommissionEntry] = []
    for charge in charges:
        if not charge.paid_at or charge.paid_at.date() < start_date or charge.paid_at.date() > end_date:
            continue
        settlement = settlements.get(charge.id)
        if settlement:
            created.extend(generate_commissions_for_charge(db, charge=charge, settlement=settlement))
    if request is not None:
        _audit(db, request, context, action="finance.commissions.generated", entity_type="commission_batch", entity_id=f"{start_date}:{end_date}", after={"created": len(created)})
    db.commit()
    return [_commission_entry_response(db, item) for item in created]


@router.get("/commissions", response_model=list[CommissionEntryResponse])
def commission_entries(
    competence: date | None = Query(default=None),
    entry_status: str | None = Query(default=None, alias="status"),
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[CommissionEntryResponse]:
    stmt = select(CommissionEntry).where(CommissionEntry.organization_id == context.user.organization_id)
    if competence:
        stmt = stmt.where(CommissionEntry.competence == competence.replace(day=1))
    items = db.scalars(stmt.order_by(CommissionEntry.due_date.desc(), CommissionEntry.internal_number.desc()).limit(500)).all()
    responses = [_commission_entry_response(db, item) for item in items]
    db.commit()
    if entry_status:
        responses = [item for item in responses if item.status == entry_status]
    return responses


@router.post("/commissions/{entry_id}/approve", response_model=CommissionEntryResponse)
def approve_commission(
    entry_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> CommissionEntryResponse:
    item = db.scalar(select(CommissionEntry).where(CommissionEntry.id == entry_id, CommissionEntry.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    if item.status in {"paid", "cancelled"}:
        raise HTTPException(status_code=409, detail="Esta comissão não pode mais ser aprovada.")
    item.status = "approved"
    item.approved_by_user_id = context.user.id
    item.approved_at = datetime.now(timezone.utc)
    _audit(db, request, context, action="finance.commission.approved", entity_type="commission_entry", entity_id=str(item.id), after={"amount": str(item.amount), "beneficiary": item.beneficiary_name})
    db.commit()
    return _commission_entry_response(db, item)


@router.post("/commissions/{entry_id}/cancel", response_model=CommissionEntryResponse)
def cancel_commission(
    entry_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> CommissionEntryResponse:
    item = db.scalar(select(CommissionEntry).where(CommissionEntry.id == entry_id, CommissionEntry.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    sync_commission_status(db, item)
    if item.status == "paid":
        raise HTTPException(status_code=409, detail="Comissão já paga não pode ser cancelada.")
    item.status = "cancelled"
    if item.financial_title_id:
        title = db.get(FinancialTitle, item.financial_title_id)
        if title and title.status != "settled":
            title.status = "cancelled"
    _audit(db, request, context, action="finance.commission.cancelled", entity_type="commission_entry", entity_id=str(item.id))
    db.commit()
    return _commission_entry_response(db, item)


def _portal_access_response(db: Session, item: PortalAccess) -> PortalAccessResponse:
    person = db.get(Person, item.person_id)
    return PortalAccessResponse(
        id=item.id,
        person_id=item.person_id,
        person_name=person.name if person else "Pessoa",
        portal_type=item.portal_type,
        label=item.label,
        is_active=item.is_active and item.revoked_at is None and item.expires_at > datetime.now(timezone.utc),
        expires_at=item.expires_at,
        revoked_at=item.revoked_at,
        last_used_at=item.last_used_at,
        created_at=item.created_at,
    )


@router.get("/portal/access", response_model=list[PortalAccessResponse])
def portal_accesses(
    context: UserContext = Depends(require_permission("finance.view")),
    db: Session = Depends(get_db),
) -> list[PortalAccessResponse]:
    items = db.scalars(select(PortalAccess).where(PortalAccess.organization_id == context.user.organization_id).order_by(PortalAccess.created_at.desc()).limit(500)).all()
    return [_portal_access_response(db, item) for item in items]


@router.post("/portal/access", response_model=PortalAccessCreated, status_code=status.HTTP_201_CREATED)
def create_portal_access(
    payload: PortalAccessCreate,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> PortalAccessCreated:
    person = db.scalar(select(Person).where(Person.id == payload.person_id, Person.organization_id == context.user.organization_id, Person.is_active.is_(True)))
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    item = PortalAccess(
        organization_id=context.user.organization_id,
        person_id=person.id,
        portal_type=payload.portal_type,
        token_hash=token_hash,
        label=(payload.label or "").strip() or None,
        is_active=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_days),
        created_by_user_id=context.user.id,
    )
    db.add(item)
    db.flush()
    _audit(db, request, context, action="finance.portal_access.created", entity_type="portal_access", entity_id=str(item.id), after={"person": person.name, "portal_type": item.portal_type, "expires_at": item.expires_at.isoformat()})
    db.commit()
    base = _portal_access_response(db, item)
    return PortalAccessCreated(**base.model_dump(), token=token, path=f"/portal/{token}")


@router.post("/portal/access/{access_id}/revoke", response_model=PortalAccessResponse)
def revoke_portal_access(
    access_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> PortalAccessResponse:
    item = db.scalar(select(PortalAccess).where(PortalAccess.id == access_id, PortalAccess.organization_id == context.user.organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Acesso externo não encontrado.")
    item.is_active = False
    item.revoked_at = datetime.now(timezone.utc)
    _audit(db, request, context, action="finance.portal_access.revoked", entity_type="portal_access", entity_id=str(item.id))
    db.commit()
    return _portal_access_response(db, item)


def _load_public_access(db: Session, token: str) -> PortalAccess:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    item = db.scalar(select(PortalAccess).where(PortalAccess.token_hash == digest))
    now = datetime.now(timezone.utc)
    if item is None or not item.is_active or item.revoked_at is not None or item.expires_at <= now:
        raise HTTPException(status_code=404, detail="Acesso externo inválido ou expirado.")
    item.last_used_at = now
    return item


def _portal_payload(db: Session, access: PortalAccess) -> PortalPayload:
    organization = db.get(Organization, access.organization_id)
    person = db.get(Person, access.person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa vinculada ao portal não foi encontrada.")
    properties: list[PortalProperty] = []
    charges_response: list[PortalCharge] = []
    repasses_response: list[PortalRepasse] = []
    current_year_total = ZERO
    open_amount = ZERO

    if access.portal_type == "owner":
        owner_links = db.scalars(
            select(PropertyOwner).where(PropertyOwner.person_id == person.id)
        ).all()
        property_ids = [item.property_id for item in owner_links]
        property_map = {item.id: item for item in db.scalars(select(Property).where(Property.id.in_(property_ids))).all()} if property_ids else {}
        for link in owner_links:
            prop = property_map.get(link.property_id)
            if prop:
                properties.append(PortalProperty(id=prop.id, code=f"{prop.internal_number:06d}", address=dict(prop.address or {}), ownership_percent=float(link.ownership_percent)))
        repasses = db.scalars(select(OwnerRepasse).where(OwnerRepasse.organization_id == access.organization_id, OwnerRepasse.owner_person_id == person.id).order_by(OwnerRepasse.due_date.desc()).limit(100)).all()
        for repasse in repasses:
            charge = db.get(RentCharge, repasse.charge_id)
            if not charge:
                continue
            repasses_response.append(PortalRepasse(id=repasse.id, competence=charge.competence, property_code=_property_code(charge.property_snapshot), amount=float(money(repasse.amount)), due_date=repasse.due_date, status=repasse.status, paid_at=repasse.paid_at))
            if repasse.status == "paid" and repasse.paid_at and repasse.paid_at.year == date.today().year:
                current_year_total += money(repasse.amount)
            if repasse.status == "pending":
                open_amount += money(repasse.amount)
    else:
        leases = db.scalars(select(LeaseContract).where(LeaseContract.organization_id == access.organization_id)).all()
        lease_ids = [lease.id for lease in leases if any(isinstance(item, dict) and str(item.get("person_id")) == str(person.id) for item in list(lease.tenant_snapshot or []))]
        property_ids = list({lease.property_id for lease in leases if lease.id in lease_ids})
        property_map = {item.id: item for item in db.scalars(select(Property).where(Property.id.in_(property_ids))).all()} if property_ids else {}
        for prop in property_map.values():
            properties.append(PortalProperty(id=prop.id, code=f"{prop.internal_number:06d}", address=dict(prop.address or {})))
        charges = db.scalars(select(RentCharge).where(RentCharge.organization_id == access.organization_id, RentCharge.lease_contract_id.in_(lease_ids)).order_by(RentCharge.due_date.desc()).limit(100)).all() if lease_ids else []
        billing_items = {item.charge_id: item for item in db.scalars(select(BillingItem).where(BillingItem.charge_id.in_([charge.id for charge in charges]))).all()} if charges else {}
        for charge in charges:
            billing = billing_items.get(charge.id)
            charges_response.append(PortalCharge(id=charge.id, code=f"COB-{charge.internal_number:06d}", competence=charge.competence, due_date=charge.due_date, property_code=_property_code(charge.property_snapshot), amount=float(money(charge.gross_amount)), status=charge.status, paid_at=charge.paid_at, boleto_line=billing.boleto_line if billing else None, pix_copy_paste=billing.pix_copy_paste if billing else None))
            if charge.status == "paid" and charge.paid_at and charge.paid_at.year == date.today().year:
                current_year_total += money(charge.paid_amount)
            if charge.status in {"generated", "sent", "overdue"}:
                open_amount += money(charge.gross_amount)
    return PortalPayload(
        organization_name=organization.display_name if organization else "Imobiliária",
        portal_type=access.portal_type,
        person_id=person.id,
        person_name=person.name,
        expires_at=access.expires_at,
        properties=properties,
        charges=charges_response,
        repasses=repasses_response,
        current_year_total=float(money(current_year_total)),
        open_amount=float(money(open_amount)),
    )


@public_router.get("/{token}", response_model=PortalPayload)
def external_portal(token: str, db: Session = Depends(get_db)) -> PortalPayload:
    access = _load_public_access(db, token)
    payload = _portal_payload(db, access)
    db.commit()
    return payload


@public_router.get("/{token}/statement.pdf")
def external_owner_statement_pdf(
    token: str,
    competence: date = Query(...),
    property_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    access = _load_public_access(db, token)
    if access.portal_type != "owner":
        raise HTTPException(status_code=403, detail="Este acesso não pertence ao portal do proprietário.")
    statement = _owner_statement(db, access.organization_id, access.person_id, competence, property_id)
    organization = db.get(Organization, access.organization_id)
    pdf = build_owner_statement_pdf(statement=statement, organization_name=organization.display_name if organization else "Imobiliária")
    db.commit()
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="prestacao-contas-{competence:%Y-%m}.pdf"'})


@router.get("/inter/status", response_model=InterStatusResponse)
def inter_status(context: UserContext = Depends(require_permission("finance.view"))) -> InterStatusResponse:
    status_data = InterBankProvider().status()
    return InterStatusResponse(**status_data.__dict__)


def _inter_external_balance(data: dict) -> Decimal | None:
    for key in ("disponivel", "saldoDisponivel", "saldo", "valor"):
        if data.get(key) is not None:
            try:
                return money(data[key])
            except Exception:
                continue
    return None


@router.post("/inter/accounts/{account_id}/sync", response_model=InterSyncResponse)
def sync_inter_account(
    account_id: UUID,
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> InterSyncResponse:
    if end_date < start_date or (end_date - start_date).days > 90:
        raise HTTPException(status_code=422, detail="O período do extrato deve ter no máximo 90 dias.")
    account = _load_account(db, context.user.organization_id, account_id)
    if account.provider != "inter":
        raise HTTPException(status_code=409, detail="A conta selecionada não usa Banco Inter.")
    provider = InterBankProvider()
    if not provider.status().configured:
        raise HTTPException(status_code=409, detail="Banco Inter ainda não está configurado no ambiente.")
    try:
        statement = provider.statement(start_date=start_date, end_date=end_date, enriched=True)
        balance_data = provider.balance()
    except BankProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    transactions = statement.get("transacoes") if isinstance(statement, dict) else []
    transactions = transactions if isinstance(transactions, list) else []
    created = 0
    duplicates = 0
    now = datetime.now(timezone.utc)
    for source in transactions:
        if not isinstance(source, dict):
            continue
        operation = str(source.get("tipoOperacao") or "").upper()
        direction = "credit" if operation == "C" else "debit"
        try:
            amount = money(abs(Decimal(str(source.get("valor") or 0))))
        except Exception:
            continue
        if amount <= 0:
            continue
        raw_date = str(source.get("dataTransacao") or source.get("dataInclusao") or start_date.isoformat())[:10]
        try:
            tx_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        details = source.get("detalhes") if isinstance(source.get("detalhes"), dict) else {}
        description = str(source.get("descricao") or source.get("titulo") or source.get("tipoTransacao") or "Movimento Banco Inter").strip()
        external_id = str(source.get("idTransacao") or details.get("codigoSolicitacao") or details.get("endToEndId") or "").strip() or None
        reference = str(details.get("endToEndId") or details.get("txId") or source.get("numeroDocumento") or "").strip() or None
        fingerprint = _fingerprint(account.id, transaction_date=tx_date, direction=direction, amount=amount, description=description, external_id=external_id, reference=reference)
        exists = db.scalar(select(BankTransaction.id).where(BankTransaction.bank_account_id == account.id, BankTransaction.fingerprint == fingerprint))
        if exists:
            duplicates += 1
            continue
        counterparty = str(details.get("nomePagador") or details.get("nomeRecebedor") or "").strip() or None
        document = str(details.get("cpfCnpjPagador") or details.get("cpfCnpjRecebedor") or source.get("numeroDocumento") or "").strip() or None
        db.add(BankTransaction(
            organization_id=context.user.organization_id,
            bank_account_id=account.id,
            external_id=external_id,
            fingerprint=fingerprint,
            transaction_date=tx_date,
            posted_at=None,
            direction=direction,
            amount=amount,
            description=description,
            document=document,
            counterparty_name=counterparty,
            bank_reference=reference,
            source="inter",
            status="pending",
            raw_data=source,
            created_by_user_id=context.user.id,
        ))
        created += 1
    account.last_sync_at = now
    external_balance = _inter_external_balance(balance_data if isinstance(balance_data, dict) else {})
    _audit(db, request, context, action="finance.inter.synced", entity_type="bank_account", entity_id=str(account.id), after={"created": created, "duplicates": duplicates, "from": str(start_date), "to": str(end_date)})
    db.commit()
    return InterSyncResponse(account_id=account.id, start_date=start_date, end_date=end_date, created=created, duplicates=duplicates, external_balance=float(external_balance) if external_balance is not None else None, synced_at=now)


@router.post("/inter/webhook/register")
def register_inter_webhook(
    webhook_url: str = Query(..., min_length=12, max_length=700),
    request: Request = None,
    context: UserContext = Depends(require_permission("finance.payment.approve")),
    db: Session = Depends(get_db),
) -> dict:
    provider = InterBankProvider()
    try:
        provider.set_billing_webhook(webhook_url)
    except BankProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if request is not None:
        _audit(db, request, context, action="finance.inter.webhook_registered", entity_type="integration", entity_id="inter", after={"url": webhook_url})
        db.commit()
    return {"ok": True, "webhook_url": webhook_url}


@webhook_router.post("/webhook/{secret}", status_code=204)
def inter_webhook(secret: str, request: Request, payload: dict, db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    expected = settings.inter_webhook_secret
    if not expected or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=404, detail="Webhook não encontrado.")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if db.scalar(select(InterWebhookEvent.id).where(InterWebhookEvent.event_hash == event_hash)):
        return Response(status_code=204)
    provider_id = str(payload.get("codigoSolicitacao") or (payload.get("cobranca") or {}).get("codigoSolicitacao") or "")
    billing_item = db.scalar(select(BillingItem).where(BillingItem.provider_charge_id == provider_id)) if provider_id else None
    event = InterWebhookEvent(
        organization_id=billing_item.organization_id if billing_item else None,
        event_hash=event_hash,
        event_type="billing",
        payload=payload,
        status="received",
    )
    db.add(event)
    try:
        if billing_item:
            _apply_inter_detail(billing_item, payload)
            batch = db.get(BillingBatch, billing_item.billing_batch_id)
            if batch:
                refresh_billing_batch_counters(db, batch)
            event.status = "processed"
        else:
            event.status = "unmatched"
        event.processed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        event.status = "error"
        event.error = str(exc)[:2000]
        db.commit()
        raise
    return Response(status_code=204)
