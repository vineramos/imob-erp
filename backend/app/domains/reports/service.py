from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.finance.advanced_schemas import AnnualIncomeLine, AnnualIncomeReport
from app.domains.finance.advanced_service import annual_income_values, money
from app.domains.finance.models import RentCharge
from app.domains.foundation.models import Organization
from app.domains.reports.schemas import DimobValidationIssue, DimobValidationResponse

ZERO = Decimal("0.00")


def annual_income_report(
    db: Session,
    *,
    organization_id: UUID,
    year: int,
    party_type: str,
    person_id: UUID,
) -> AnnualIncomeReport:
    person, raw_lines, allocation_method = annual_income_values(
        db,
        organization_id=organization_id,
        year=year,
        party_type=party_type,
        person_id=person_id,
    )
    converted: list[AnnualIncomeLine] = []
    for raw in raw_lines:
        data = {key: float(value) if isinstance(value, Decimal) else value for key, value in raw.items()}
        converted.append(AnnualIncomeLine(**data))
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
        lines=converted,
    )


def annual_income_csv(report: AnnualIncomeReport) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\n")
    writer.writerow([
        "Competência", "Data do pagamento", "Imóvel", "Cobrança", "Aluguel", "Encargos",
        "Total pago", "Taxa de administração", "Líquido do proprietário",
    ])
    for line in report.lines:
        writer.writerow([
            line.competence.strftime("%m/%Y"),
            line.payment_date.strftime("%d/%m/%Y") if line.payment_date else "",
            line.property_code,
            line.charge_code,
            f"{line.rent_amount:.2f}".replace(".", ","),
            f"{line.additional_charges:.2f}".replace(".", ","),
            f"{line.total_amount:.2f}".replace(".", ","),
            f"{line.administration_fee:.2f}".replace(".", ","),
            f"{line.owner_net_amount:.2f}".replace(".", ","),
        ])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _document_is_present(value: str | None) -> bool:
    return len(_digits(value)) in {11, 14}


def _ownership_total(owners: list[dict]) -> Decimal | None:
    if not owners:
        return None
    total = ZERO
    try:
        for owner in owners:
            total += Decimal(str(owner.get("ownership_percent") or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return total


def dimob_validation(db: Session, *, organization_id: UUID, year: int) -> DimobValidationResponse:
    organization = db.scalar(select(Organization).where(Organization.id == organization_id))
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    charges = db.scalars(
        select(RentCharge).where(
            RentCharge.organization_id == organization_id,
            RentCharge.status == "paid",
            RentCharge.paid_at.is_not(None),
            RentCharge.paid_at >= start,
            RentCharge.paid_at < end,
        ).order_by(RentCharge.paid_at, RentCharge.internal_number)
    ).all()

    issues: list[DimobValidationIssue] = []
    if organization is None or len(_digits(organization.document_number if organization else None)) != 14:
        issues.append(DimobValidationIssue(
            severity="error", code="organization_document", scope="organization",
            message="Informe um CNPJ utilizável no cadastro da imobiliária antes da revisão da DIMOB.",
        ))

    owner_keys: set[str] = set()
    tenant_keys: set[str] = set()
    lease_ids: set[UUID] = set()
    if not charges:
        issues.append(DimobValidationIssue(
            severity="warning", code="no_paid_rent_operations", scope="year", reference=str(year),
            message="Nenhum pagamento de locação foi encontrado no ano selecionado.",
        ))

    for charge in charges:
        lease_ids.add(charge.lease_contract_id)
        charge_code = f"COB-{charge.internal_number:06d}"
        property_snapshot = dict(charge.property_snapshot or {})
        address = dict(property_snapshot.get("address") or {})
        missing_address = [label for key, label in (
            ("street", "logradouro"), ("number", "número"), ("city", "município"), ("state", "UF"),
        ) if not str(address.get(key) or "").strip()]
        if missing_address:
            issues.append(DimobValidationIssue(
                severity="error", code="property_address", scope="charge", reference=charge_code,
                message=f"Complete o endereço do imóvel: {', '.join(missing_address)}.",
            ))

        owners = [item for item in list(charge.owner_snapshot or []) if isinstance(item, dict)]
        tenants = [item for item in list(charge.tenant_snapshot or []) if isinstance(item, dict)]
        if not owners:
            issues.append(DimobValidationIssue(
                severity="error", code="missing_owner", scope="charge", reference=charge_code,
                message="A cobrança não possui proprietário identificado no snapshot contratual.",
            ))
        if not tenants:
            issues.append(DimobValidationIssue(
                severity="error", code="missing_tenant", scope="charge", reference=charge_code,
                message="A cobrança não possui locatário identificado no snapshot contratual.",
            ))

        for owner in owners:
            owner_key = str(owner.get("person_id") or owner.get("document_number") or owner.get("name") or "")
            if owner_key:
                owner_keys.add(owner_key)
            if not _document_is_present(str(owner.get("document_number") or "")):
                issues.append(DimobValidationIssue(
                    severity="error", code="owner_document", scope="charge", reference=charge_code,
                    message=f"Proprietário {owner.get('name') or 'sem nome'} está sem CPF/CNPJ utilizável.",
                ))
        for tenant in tenants:
            tenant_key = str(tenant.get("person_id") or tenant.get("document_number") or tenant.get("name") or "")
            if tenant_key:
                tenant_keys.add(tenant_key)
            if not _document_is_present(str(tenant.get("document_number") or "")):
                issues.append(DimobValidationIssue(
                    severity="error", code="tenant_document", scope="charge", reference=charge_code,
                    message=f"Locatário {tenant.get('name') or 'sem nome'} está sem CPF/CNPJ utilizável.",
                ))

        ownership_total = _ownership_total(owners)
        if ownership_total is not None and ownership_total != Decimal("100"):
            issues.append(DimobValidationIssue(
                severity="warning", code="ownership_percent", scope="charge", reference=charge_code,
                message=f"Percentuais dos proprietários somam {ownership_total}% em vez de 100%.",
            ))

    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    status = "no_operations" if not charges else ("attention_required" if error_count else "ready_for_review")
    return DimobValidationResponse(
        year=year,
        status=status,
        operation_count=len(charges),
        lease_count=len(lease_ids),
        owner_count=len(owner_keys),
        tenant_count=len(tenant_keys),
        error_count=error_count,
        warning_count=warning_count,
        official_layout_export_available=False,
        issues=issues,
        note=(
            "Pré-validação interna dos dados cadastrais e dos pagamentos de locação. "
            "Ela não substitui a validação/importação no PGD DIMOB nem representa o arquivo oficial da Receita."
        ),
    )
