from __future__ import annotations

import re
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.finance_banking import _load_account
from app.core.database import get_db
from app.domains.finance.advanced_models import BillingBatch, BillingItem
from app.domains.finance.advanced_schemas import (
    BillingBatchResponse,
    BillingIssueRequest,
    BillingReceiptConfirmRequest,
    BillingItemResponse,
    BillingRunRequest,
    BillingRunResponse,
)
from app.domains.finance.advanced_service import ensure_billing_batch, money, refresh_billing_batch_counters
from app.domains.finance.advanced_service import generate_commissions_for_charge
from app.domains.finance.billing_settlement import settle_confirmed_billing_item
from app.domains.finance.late_charges import amount_due, charge_late_payment_terms, record_payment_with_late_charges
from app.domains.finance.models import RentCharge
from app.domains.finance.providers import BankProviderError, InterBankProvider
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.leases.models import LeaseContract

router = APIRouter(prefix="/billing")


def _audit(db: Session, request: Request, context: UserContext, action: str, entity_id: str | None, after: dict | None = None) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    write_audit(
        db,
        context=context,
        action=action,
        module="finance",
        entity_type="billing_batch",
        entity_id=entity_id,
        after_data=after,
        ip_address=forwarded or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )


def _load_batch(db: Session, organization_id: UUID, batch_id: UUID) -> BillingBatch:
    item = db.scalar(select(BillingBatch).where(BillingBatch.id == batch_id, BillingBatch.organization_id == organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Lote de cobrança não encontrado.")
    return item


def _property_code(charge: RentCharge) -> str:
    return str((charge.property_snapshot or {}).get("code") or "—")


def _tenant_name(charge: RentCharge) -> str:
    return next((str(item.get("name")) for item in list(charge.tenant_snapshot or []) if isinstance(item, dict) and item.get("name")), "Locatário")


def _item_response(db: Session, item: BillingItem) -> BillingItemResponse:
    charge = db.get(RentCharge, item.charge_id)
    if charge is None:
        raise HTTPException(status_code=409, detail="Cobrança vinculada ao lote não encontrada.")
    lease = db.get(LeaseContract, charge.lease_contract_id)
    value = charge.paid_amount if charge.status == "paid" and charge.paid_amount is not None else amount_due(db, charge)
    return BillingItemResponse(
        id=item.id,
        charge_id=charge.id,
        charge_code=f"COB-{charge.internal_number:06d}",
        lease_code=f"LOC-{lease.internal_number:06d}" if lease else "LOC-—",
        property_code=_property_code(charge),
        tenant_name=_tenant_name(charge),
        due_date=charge.due_date,
        amount=float(money(value)),
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


def _batch_response(db: Session, batch: BillingBatch) -> BillingBatchResponse:
    items = db.scalars(select(BillingItem).where(BillingItem.billing_batch_id == batch.id).order_by(BillingItem.created_at)).all()
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
        items=[_item_response(db, item) for item in items],
    )


def _digits(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def _payer(charge: RentCharge) -> dict:
    tenant = next((item for item in list(charge.tenant_snapshot or []) if isinstance(item, dict)), None) or {}
    name = str(tenant.get("name") or "").strip()
    document = _digits(str(tenant.get("document_number") or tenant.get("document") or tenant.get("cpf_cnpj") or ""))
    if not name or len(document) not in {11, 14}:
        raise ValueError("Locatário precisa ter nome e CPF/CNPJ válidos para emissão no Banco Inter.")
    address = tenant.get("address") if isinstance(tenant.get("address"), dict) else {}
    phone = _digits(str(tenant.get("phone") or ""))
    result = {
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
    email = str(tenant.get("email") or "").strip()
    if email:
        result["email"] = email[:80]
    if len(phone) >= 10:
        result["ddd"] = phone[:2]
        result["telefone"] = phone[2:][:11]
    return result


def _issue_payload(db: Session, charge: RentCharge) -> dict:
    terms = charge_late_payment_terms(db, charge)
    if terms.interest_type == "compound" and terms.interest_percent_monthly > 0:
        raise ValueError(
            "Este contrato usa juros compostos. O Banco Inter Cobrança V3 não possui parâmetro equivalente de capitalização composta; "
            "altere a condição do contrato antes da assinatura ou utilize outro meio de cobrança compatível."
        )
    payload = {
        "seuNumero": f"C{charge.internal_number}"[:15],
        "valorNominal": float(money(charge.gross_amount)),
        "dataVencimento": charge.due_date.isoformat(),
        "numDiasAgenda": 60,
        "pagador": _payer(charge),
        "mensagem": {"linha1": f"Aluguel/encargos {charge.competence:%m/%Y}", "linha2": f"Imóvel {_property_code(charge)}"},
        "formasRecebimento": ["BOLETO", "PIX"],
    }
    if terms.fee_percent > 0:
        payload["multa"] = {"codigo": "PERCENTUAL", "taxa": float(terms.fee_percent)}
    if terms.interest_percent_monthly > 0:
        payload["mora"] = {"codigo": "TAXAMENSAL", "taxa": float(terms.interest_percent_monthly)}
    return payload


def _apply_detail(item: BillingItem, data: dict) -> None:
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


@router.post("/run", response_model=BillingRunResponse)
def run_billing(payload: BillingRunRequest, request: Request, context: UserContext = Depends(require_permission("finance.charge.create")), db: Session = Depends(get_db)) -> BillingRunResponse:
    batch, generated, skipped_existing, skipped_ineligible = ensure_billing_batch(db, organization_id=context.user.organization_id, user_id=context.user.id, competence=payload.competence)
    _audit(db, request, context, "finance.billing.run", str(batch.id), {"competence": str(batch.competence), "generated": generated})
    db.commit()
    batch = _load_batch(db, context.user.organization_id, batch.id)
    return BillingRunResponse(generated=generated, skipped_existing=skipped_existing, skipped_ineligible=skipped_ineligible, batch=_batch_response(db, batch))


@router.get("/batches", response_model=list[BillingBatchResponse])
def list_batches(competence: date | None = Query(default=None), context: UserContext = Depends(require_permission("finance.view")), db: Session = Depends(get_db)) -> list[BillingBatchResponse]:
    stmt = select(BillingBatch).where(BillingBatch.organization_id == context.user.organization_id)
    if competence:
        stmt = stmt.where(BillingBatch.competence == competence.replace(day=1))
    return [_batch_response(db, item) for item in db.scalars(stmt.order_by(BillingBatch.competence.desc(), BillingBatch.internal_number.desc()).limit(36)).all()]


@router.post("/batches/{batch_id}/items/{item_id}/confirm-receipt", response_model=BillingBatchResponse)
def confirm_receipt(
    batch_id: UUID,
    item_id: UUID,
    payload: BillingReceiptConfirmRequest,
    request: Request,
    context: UserContext = Depends(require_permission("finance.reconcile")),
    db: Session = Depends(get_db),
) -> BillingBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    item = db.scalar(
        select(BillingItem).where(BillingItem.id == item_id, BillingItem.billing_batch_id == batch.id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item de cobrança não encontrado neste lote.")
    charge = db.get(RentCharge, item.charge_id)
    if charge is None or charge.status == "cancelled":
        raise HTTPException(status_code=409, detail="A cobrança não está disponível para recebimento.")
    if charge.status == "paid":
        raise HTTPException(status_code=409, detail="Esta cobrança já está recebida.")

    paid_at = payload.paid_at or datetime.now(timezone.utc)
    if paid_at > datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="A data do recebimento não pode estar no futuro.")
    effective_reference = (payload.payment_reference or f"MANUAL:{item.id}").strip()
    settlement = record_payment_with_late_charges(
        db,
        charge=charge,
        paid_amount=money(payload.paid_amount),
        paid_at=paid_at,
        payment_method=payload.payment_method,
        payment_reference=effective_reference,
        notes=payload.notes or "Recebimento confirmado manualmente no ERP.",
    )
    generate_commissions_for_charge(db, charge=charge, settlement=settlement)
    item.provider = "manual"
    item.provider_status = "MARCADO_RECEBIDO"
    item.confirmed_at = paid_at
    item.last_error = None
    item.response_snapshot = {
        **dict(item.response_snapshot or {}),
        "manual_receipt": {
            "paid_amount": float(money(payload.paid_amount)),
            "paid_at": paid_at.isoformat(),
            "payment_method": payload.payment_method,
            "payment_reference": effective_reference,
        },
    }
    refresh_billing_batch_counters(db, batch)
    _audit(
        db,
        request,
        context,
        "finance.billing.manual_receipt_confirmed",
        str(batch.id),
        {"item_id": str(item.id), "charge_id": str(charge.id), "paid_amount": str(money(payload.paid_amount))},
    )
    db.commit()
    return _batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/batches/{batch_id}/issue-inter", response_model=BillingBatchResponse)
def issue_inter(batch_id: UUID, payload: BillingIssueRequest, request: Request, context: UserContext = Depends(require_permission("finance.charge.create")), db: Session = Depends(get_db)) -> BillingBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    account = _load_account(db, context.user.organization_id, payload.bank_account_id)
    if account.provider != "inter" or account.fund_scope != "third_party":
        raise HTTPException(status_code=409, detail="Selecione uma conta Banco Inter de recursos de terceiros.")
    provider = InterBankProvider()
    if not provider.status().configured:
        raise HTTPException(status_code=409, detail="Banco Inter ainda não possui credenciais/certificado configurados no ambiente.")
    now = datetime.now(timezone.utc)
    for item in db.scalars(select(BillingItem).where(BillingItem.billing_batch_id == batch.id)).all():
        if item.provider_charge_id:
            continue
        charge = db.get(RentCharge, item.charge_id)
        if charge is None or charge.status == "cancelled":
            continue
        try:
            payload_inter = _issue_payload(db, charge)
            response = provider.issue_charge(payload_inter)
            provider_id = str(response.get("codigoSolicitacao") or "")
            if not provider_id:
                raise BankProviderError("Banco Inter não retornou o código da cobrança.")
            item.provider = "inter"
            item.provider_charge_id = provider_id
            item.provider_status = "EM_PROCESSAMENTO"
            item.request_snapshot = payload_inter
            item.response_snapshot = dict(response)
            item.issued_at = now
            item.last_error = None
            try:
                _apply_detail(item, provider.charge(provider_id))
                if item.confirmed_at:
                    settle_confirmed_billing_item(db, item, paid_at=item.confirmed_at)
            except (BankProviderError, ValueError) as exc:
                item.confirmed_at = None
                item.last_error = f"Falha ao liquidar recebimento: {exc}"
        except (BankProviderError, ValueError) as exc:
            item.provider = "inter"
            item.last_error = str(exc)
    batch.provider = "inter"
    refresh_billing_batch_counters(db, batch)
    _audit(db, request, context, "finance.billing.inter_issued", str(batch.id), {"issued": batch.issued_count, "errors": batch.error_count})
    db.commit()
    return _batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/batches/{batch_id}/sync-inter", response_model=BillingBatchResponse)
def sync_inter(batch_id: UUID, request: Request, context: UserContext = Depends(require_permission("finance.reconcile")), db: Session = Depends(get_db)) -> BillingBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    provider = InterBankProvider()
    if not provider.status().configured:
        raise HTTPException(status_code=409, detail="Banco Inter ainda não está configurado no ambiente.")
    for item in db.scalars(select(BillingItem).where(BillingItem.billing_batch_id == batch.id)).all():
        if not item.provider_charge_id:
            continue
        try:
            _apply_detail(item, provider.charge(item.provider_charge_id))
            if item.confirmed_at:
                settle_confirmed_billing_item(db, item, paid_at=item.confirmed_at)
            item.last_error = None
        except (BankProviderError, ValueError) as exc:
            item.confirmed_at = None
            item.last_error = f"Falha ao liquidar recebimento: {exc}"
    refresh_billing_batch_counters(db, batch)
    _audit(db, request, context, "finance.billing.inter_synced", str(batch.id), {"confirmed": batch.confirmed_count, "errors": batch.error_count})
    db.commit()
    return _batch_response(db, _load_batch(db, context.user.organization_id, batch.id))


@router.post("/batches/{batch_id}/mark-sent", response_model=BillingBatchResponse)
def mark_sent(batch_id: UUID, request: Request, context: UserContext = Depends(require_permission("finance.charge.create")), db: Session = Depends(get_db)) -> BillingBatchResponse:
    batch = _load_batch(db, context.user.organization_id, batch_id)
    now = datetime.now(timezone.utc)
    for item in db.scalars(select(BillingItem).where(BillingItem.billing_batch_id == batch.id)).all():
        charge = db.get(RentCharge, item.charge_id)
        if charge is None or charge.status in {"paid", "cancelled"}:
            continue
        item.sent_at = item.sent_at or now
        charge.sent_at = charge.sent_at or now
        if charge.due_date >= date.today():
            charge.status = "sent"
    refresh_billing_batch_counters(db, batch)
    _audit(db, request, context, "finance.billing.sent", str(batch.id), {"sent": batch.sent_count})
    db.commit()
    return _batch_response(db, _load_batch(db, context.user.organization_id, batch.id))
