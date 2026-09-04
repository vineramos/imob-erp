from __future__ import annotations

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def lease_contract_code(contract: Any) -> str:
    return f"LOC-{contract.internal_number:06d}"


def _money(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _address(address: dict[str, Any]) -> str:
    parts = [
        address.get("street"),
        address.get("number"),
        address.get("complement"),
        address.get("neighborhood"),
        address.get("city"),
        address.get("state"),
        address.get("postal_code"),
    ]
    return ", ".join(str(item) for item in parts if item)


def _date(value: Any) -> str:
    if not value:
        return "—"
    text = str(value)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}/{text[5:7]}/{text[:4]}"
    return text


def _monthly_rules(contract: Any) -> list[dict[str, Any]]:
    rules = dict(getattr(contract, "rules_snapshot", {}) or {})
    return [dict(item) for item in list(rules.get("monthly_charges") or []) if isinstance(item, dict)]


def build_lease_contract_pdf(*, contract: Any, organization: Any) -> bytes:
    """Gera o PDF operacional determinístico da versão congelada do contrato."""
    buffer = BytesIO()
    code = lease_contract_code(contract)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Contrato de Locação {contract.internal_number:06d}",
        author=getattr(organization, "display_name", "Imobiliária"),
        invariant=1,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("LeaseTitle", parent=styles["Title"], fontSize=15, leading=18, alignment=TA_CENTER, spaceAfter=8)
    subtitle = ParagraphStyle("LeaseSubtitle", parent=styles["Normal"], fontSize=8.5, leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#5a6472"), spaceAfter=12)
    heading = ParagraphStyle("LeaseHeading", parent=styles["Heading2"], fontSize=10.5, leading=13, spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("LeaseBody", parent=styles["BodyText"], fontSize=9.2, leading=13)
    small = ParagraphStyle("LeaseSmall", parent=styles["BodyText"], fontSize=7.8, leading=10, textColor=colors.HexColor("#5a6472"))

    story = [
        Paragraph("CONTRATO DE LOCAÇÃO DE IMÓVEL", title),
        Paragraph(f"{code} · versão {contract.current_version}", subtitle),
        Paragraph("1. Administradora", heading),
        Paragraph(
            f"<b>{escape(str(getattr(organization, 'display_name', '') or ''))}</b> · "
            f"{escape(str(getattr(organization, 'legal_name', '') or ''))}<br/>"
            f"CNPJ: {escape(str(getattr(organization, 'document_number', None) or 'não informado'))} · "
            f"CRECI PJ: {escape(str(getattr(organization, 'creci_pj', None) or 'não informado'))}",
            body,
        ),
    ]

    property_snapshot = dict(contract.property_snapshot or {})
    story.extend([
        Paragraph("2. Imóvel locado", heading),
        Paragraph(
            f"Imóvel #{escape(str(property_snapshot.get('code') or '—'))} · "
            f"{escape(_address(dict(property_snapshot.get('address') or {})))}<br/>"
            f"Finalidade: {escape(str(property_snapshot.get('purpose') or '—'))} · "
            f"Tipo: {escape(str(property_snapshot.get('property_type') or '—'))}",
            body,
        ),
    ])

    story.append(Paragraph("3. Locador(es) / proprietário(s)", heading))
    owner_rows = [["Nome", "CPF/CNPJ", "Participação"]]
    for owner in list(contract.owner_snapshot or []):
        owner_rows.append([
            owner.get("name") or "—",
            owner.get("document_number") or "—",
            f"{owner.get('ownership_percent') or '—'}%",
        ])
    owner_table = Table(owner_rows, colWidths=[92 * mm, 55 * mm, 25 * mm], repeatRows=1)
    owner_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f4f7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8dee6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(owner_table)

    story.append(Paragraph("4. Locatário(s)", heading))
    tenant_rows = [["Nome", "CPF/CNPJ", "E-mail"]]
    for tenant in list(contract.tenant_snapshot or []):
        tenant_rows.append([
            tenant.get("name") or "—",
            tenant.get("document_number") or "—",
            tenant.get("email") or "—",
        ])
    tenant_table = Table(tenant_rows, colWidths=[80 * mm, 48 * mm, 44 * mm], repeatRows=1)
    tenant_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f4f7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.0),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8dee6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tenant_table)

    story.append(Paragraph("5. Condições econômicas e prazo", heading))
    conditions = [
        ["Aluguel", _money(contract.rent_amount)],
        ["Vencimento", f"dia {contract.due_day} de cada mês"],
        ["Prazo", f"{contract.term_months} meses"],
        ["Início", _date(contract.start_date)],
        ["Término", _date(contract.end_date)],
        ["Reajuste", f"{contract.adjustment_index} a cada {contract.adjustment_period_months} mês(es)"],
        ["Data-base", _date(contract.adjustment_base_date)],
        ["Próximo reajuste", _date(contract.next_adjustment_date)],
        ["Multa rescisória-base", f"{contract.termination_fine_months} aluguel(is), proporcional ao período restante"],
        ["Contestação da vistoria inicial", f"{contract.inspection_contest_days} dia(s) corrido(s)"],
        ["Garantia", str(contract.guarantee_type).replace("_", " ")],
    ]
    conditions_table = Table(conditions, colWidths=[64 * mm, 108 * mm])
    conditions_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.4),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8dee6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(conditions_table)

    story.append(Paragraph("6. Composição mensal e encargos recorrentes", heading))
    payer_labels = {"tenant": "Locatário", "owner": "Proprietário", "agency": "Imobiliária"}
    beneficiary_labels = {"owner": "Proprietário", "agency": "Imobiliária", "third_party": "Terceiro"}
    monthly_rows = [["Encargo", "Valor", "Responsável", "Destino", "Vigência"]]
    monthly_rows.append(["Aluguel", _money(contract.rent_amount), "Locatário", "Proprietário", "todo o contrato"])
    tenant_total = float(contract.rent_amount)
    for rule in _monthly_rules(contract):
        if not bool(rule.get("active", True)):
            continue
        amount = float(rule.get("amount") or 0)
        if amount <= 0:
            continue
        payer = str(rule.get("payer") or "tenant")
        if payer == "tenant":
            tenant_total += amount
        start = _date(rule.get("start_date")) if rule.get("start_date") else "início do contrato"
        end = _date(rule.get("end_date")) if rule.get("end_date") else "fim do contrato"
        monthly_rows.append([
            rule.get("label") or "Encargo mensal",
            _money(amount),
            payer_labels.get(payer, payer),
            beneficiary_labels.get(str(rule.get("beneficiary") or "third_party"), "Terceiro"),
            f"{start} a {end}",
        ])
    monthly_table = Table(monthly_rows, colWidths=[48 * mm, 27 * mm, 31 * mm, 31 * mm, 35 * mm], repeatRows=1)
    monthly_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f4f7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.4),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8dee6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([
        monthly_table,
        Paragraph(f"Cobrança mensal estimada do locatário nesta versão: <b>{_money(tenant_total)}</b>. Itens com vigência específica entram apenas nas competências correspondentes.", small),
    ])

    story.extend([
        Paragraph("7. Regras operacionais essenciais", heading),
        Paragraph(
            "O imóvel permanece sob administração conforme o contrato de administração vigente. "
            "IPTU, condomínio, seguros, consumos, repasses, inadimplência, vistoria, chaves e demais encargos "
            "seguem as regras congeladas nesta versão e os documentos operacionais vinculados ao ERP.",
            body,
        ),
        Paragraph("8. Garantia locatícia", heading),
        Paragraph(escape(str(contract.guarantee_details or {})), body),
    ])

    if contract.notes:
        story.extend([Paragraph("9. Condições especiais", heading), Paragraph(escape(str(contract.notes)), body)])

    story.append(Paragraph("10. Signatários desta versão", heading))
    signers = list(contract.signers_snapshot or [])
    if signers:
        rows = [["Papel", "Nome", "E-mail", "Ordem"]]
        for signer in signers:
            rows.append([
                signer.get("role") or "—",
                signer.get("name") or "—",
                signer.get("email") or "—",
                str(signer.get("sign_order") or 1),
            ])
        table = Table(rows, colWidths=[30 * mm, 57 * mm, 68 * mm, 17 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f4f7")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.8),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8dee6")),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("Nenhum signatário registrado.", body))

    story.extend([
        Spacer(1, 12),
        Paragraph(
            "Documento gerado pelo ERP a partir da versão congelada do contrato. Alterações exigem nova versão e novo hash. "
            "A locação somente é considerada formalmente concluída no ERP após a assinatura eletrônica e o arquivamento do PDF final assinado no storage próprio.",
            small,
        ),
    ])
    doc.build(story)
    return buffer.getvalue()