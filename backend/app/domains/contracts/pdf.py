from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _money(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _percent(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:g}%".replace(".", ",")


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


def build_administration_contract_pdf(*, contract: Any, organization: Any) -> bytes:
    """Gera a representação PDF da versão corrente já congelada no contrato.

    O documento é operacional e versionado; o texto jurídico definitivo poderá ser
    evoluído por template sem alterar a regra de snapshots/hashes.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Contrato de Administração {contract.internal_number:06d}",
        author=getattr(organization, "display_name", "Imobiliária"),
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("ContractTitle", parent=styles["Title"], fontSize=15, leading=18, alignment=TA_CENTER, spaceAfter=8)
    subtitle = ParagraphStyle("ContractSubtitle", parent=styles["Normal"], fontSize=8.5, leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#5a6472"), spaceAfter=12)
    heading = ParagraphStyle("ContractHeading", parent=styles["Heading2"], fontSize=10.5, leading=13, spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("ContractBody", parent=styles["BodyText"], fontSize=9.2, leading=13)
    small = ParagraphStyle("ContractSmall", parent=styles["BodyText"], fontSize=7.8, leading=10, textColor=colors.HexColor("#5a6472"))

    story = [
        Paragraph("CONTRATO DE ADMINISTRAÇÃO DE IMÓVEL", title),
        Paragraph(f"{contract_code(contract)} · versão {contract.current_version}", subtitle),
    ]

    story.append(Paragraph("1. Identificação da administradora", heading))
    story.append(Paragraph(
        f"<b>{getattr(organization, 'display_name', '')}</b> · {getattr(organization, 'legal_name', '')}<br/>"
        f"CNPJ: {getattr(organization, 'document_number', None) or 'não informado'} · CRECI PJ: {getattr(organization, 'creci_pj', None) or 'não informado'}",
        body,
    ))

    property_snapshot = dict(contract.property_snapshot or {})
    story.append(Paragraph("2. Imóvel administrado", heading))
    story.append(Paragraph(
        f"Imóvel #{property_snapshot.get('code') or '—'} · {_address(dict(property_snapshot.get('address') or {}))}<br/>"
        f"Finalidade: {property_snapshot.get('purpose') or '—'} · Tipo: {property_snapshot.get('property_type') or '—'} · Aluguel de referência: {_money(property_snapshot.get('rent_amount'))}",
        body,
    ))

    story.append(Paragraph("3. Proprietário(s)", heading))
    owner_rows = [["Nome", "CPF/CNPJ", "Participação"]]
    for owner in list(contract.owner_snapshot or []):
        owner_rows.append([owner.get("name") or "—", owner.get("document_number") or "—", _percent(owner.get("ownership_percent"))])
    owner_table = Table(owner_rows, colWidths=[92 * mm, 55 * mm, 25 * mm], repeatRows=1)
    owner_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f4f7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#283241")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8dee6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(owner_table)

    fee = _percent(contract.admin_fee_percent) if contract.admin_fee_type == "percent" else _money(contract.admin_fee_amount)
    story.append(Paragraph("4. Condições econômicas e operacionais", heading))
    rules = [
        ["Plano", str(contract.plan).title()],
        ["Taxa de administração", fee],
        ["Intermediação", f"{_percent(contract.intermediation_percent)} em {contract.intermediation_installments} parcela(s)"],
        ["Repasse ao proprietário", f"D+{contract.owner_repasse_business_days} dias úteis após liquidação confirmada"],
        ["Condomínio · pagador operacional", str(contract.condo_operational_payer)],
        ["IPTU · pagador operacional", str(contract.iptu_operational_payer)],
        ["Autonomia de manutenção", _money(contract.maintenance_limit_amount)],
        ["Limite emergencial", _money(contract.emergency_limit_amount)],
        ["Aprovação para publicação", "Obrigatória" if contract.publication_requires_owner_approval else "Dispensada"],
        ["Início", str(contract.start_date or "—")],
        ["Fim previsto", str(contract.end_date or "—")],
    ]
    rules_table = Table(rules, colWidths=[64 * mm, 108 * mm])
    rules_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.4),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8dee6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(rules_table)

    if contract.notes:
        story.extend([Paragraph("5. Condições especiais", heading), Paragraph(str(contract.notes), body)])

    story.append(Paragraph("6. Signatários desta versão", heading))
    signers = list(contract.signers_snapshot or [])
    if signers:
        rows = [["Papel", "Nome", "E-mail", "Ordem"]]
        for signer in signers:
            rows.append([signer.get("role") or "—", signer.get("name") or "—", signer.get("email") or "—", str(signer.get("sign_order") or 1)])
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
            "Documento gerado pelo ERP a partir da versão congelada do contrato. Alterações posteriores exigem nova versão e novo hash. A efetivação jurídica depende do fluxo de assinatura eletrônica e do arquivamento do documento final.",
            small,
        ),
    ])

    doc.build(story)
    return buffer.getvalue()


def contract_code(contract: Any) -> str:
    return f"ADM-{contract.internal_number:06d}"
