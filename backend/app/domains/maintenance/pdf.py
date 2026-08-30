from __future__ import annotations

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _money(value: Any) -> str:
    if value in (None, ""):
        return "—"
    number = float(value)
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _date(value: Any) -> str:
    if not value:
        return "—"
    text = str(value)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}/{text[5:7]}/{text[:4]}"
    return text


def _address(value: dict[str, Any]) -> str:
    return ", ".join(
        str(part)
        for part in [
            value.get("street"), value.get("number"), value.get("complement"), value.get("neighborhood"),
            value.get("city"), value.get("state"), value.get("postal_code"),
        ]
        if part
    ) or "não informado"


def build_maintenance_quote_pdf(*, maintenance: Any, property_item: Any, quote: dict[str, Any], logo_bytes: bytes | None = None) -> bytes:
    """Orçamento do parceiro. Valores exibidos são somente os efetivamente cobrados pelo parceiro."""
    partner = dict(quote.get("partner_snapshot") or {})
    if not partner:
        raise ValueError("Orçamento não possui snapshot de parceiro terceirizado.")

    buffer = BytesIO()
    code = str(quote.get("quote_code") or f"MAN-{maintenance.internal_number:06d}-ORC")
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Orçamento {code}",
        author=str(partner.get("name") or "Parceiro de manutenção"),
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("QuoteTitle", parent=styles["Title"], fontSize=14, leading=17, textColor=colors.HexColor("#102a56"), alignment=TA_RIGHT)
    heading = ParagraphStyle("QuoteHeading", parent=styles["Heading2"], fontSize=10.5, leading=13, textColor=colors.HexColor("#102a56"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("QuoteBody", parent=styles["BodyText"], fontSize=9, leading=13)
    small = ParagraphStyle("QuoteSmall", parent=styles["BodyText"], fontSize=7.8, leading=10, textColor=colors.HexColor("#667085"))
    total_style = ParagraphStyle("QuoteTotal", parent=styles["BodyText"], fontSize=13, leading=16, alignment=TA_RIGHT, textColor=colors.HexColor("#102a56"))

    issuer_lines = [
        f"<b>{escape(str(partner.get('name') or ''))}</b>",
        escape(str(partner.get("legal_name") or "")),
        f"CPF/CNPJ: {escape(str(partner.get('document_number') or 'não informado'))}",
    ]
    contacts = " · ".join(item for item in [str(partner.get("phone") or "").strip(), str(partner.get("whatsapp") or "").strip(), str(partner.get("email") or "").strip()] if item)
    if contacts:
        issuer_lines.append(escape(contacts))
    issuer_lines.append(escape(_address(dict(partner.get("address") or {}))))

    logo_flowable: Any
    if logo_bytes:
        try:
            logo_flowable = Image(BytesIO(logo_bytes), width=34 * mm, height=20 * mm, kind="proportional")
        except Exception:
            logo_flowable = Paragraph("", body)
    else:
        logo_flowable = Paragraph("", body)

    header = Table(
        [[logo_flowable, Paragraph("<br/>".join(line for line in issuer_lines if line), body), Paragraph(f"<b>ORÇAMENTO</b><br/>{escape(code)}<br/><font size='7'>Emitido em {_date(quote.get('created_at'))}</font>", title)]],
        colWidths=[38 * mm, 83 * mm, 55 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#d9e1ec")),
    ]))

    prop_address = dict(getattr(property_item, "address", {}) or {})
    property_title = getattr(property_item, "public_title", None) or f"Imóvel {getattr(property_item, 'internal_number', 0):06d}"
    story = [header, Spacer(1, 6), Paragraph("Dados do serviço", heading)]
    service_rows = [
        ["Chamado", f"MAN-{maintenance.internal_number:06d}"],
        ["Imóvel", property_title],
        ["Endereço", _address(prop_address)],
        ["Solicitação", str(getattr(maintenance, "title", "") or "Manutenção")],
    ]
    service_table = Table(service_rows, colWidths=[34 * mm, 142 * mm])
    service_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475467")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9e1ec")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(service_table)

    items = [dict(item) for item in list(quote.get("items") or [])]
    if items:
        rows: list[list[Any]] = [["Serviço", "Qtd.", "Valor"]]
        for item in items:
            title_text = escape(str(item.get("title") or "Serviço"))
            description = str(item.get("description") or "").strip()
            if description:
                title_text += f"<br/><font size='7' color='#667085'>{escape(description)}</font>"
            quantity = f"{item.get('quantity') or '1'} {item.get('unit') or ''}".strip()
            rows.append([Paragraph(title_text, body), quantity, _money(item.get("partner_cost"))])
        value_table = Table(rows, colWidths=[116 * mm, 24 * mm, 36 * mm], repeatRows=1)
        total_value = quote.get("partner_cost_total") or quote.get("amount")
    else:
        rows = [["Descrição", "Valor"], [str(quote.get("description") or "Serviço de manutenção"), _money(quote.get("amount"))]]
        value_table = Table(rows, colWidths=[137 * mm, 39 * mm], repeatRows=1)
        total_value = quote.get("amount")

    value_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f5f9")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9e1ec")),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([Paragraph("Serviços e valores", heading), value_table, Spacer(1, 6), Paragraph(f"<b>TOTAL: {_money(total_value)}</b>", total_style)])

    details: list[str] = []
    if quote.get("valid_until"):
        details.append(f"<b>Validade:</b> {_date(quote.get('valid_until'))}")
    if quote.get("payment_terms"):
        details.append(f"<b>Condições de pagamento:</b> {escape(str(quote.get('payment_terms')))}")
    if partner.get("pix_key"):
        details.append(f"<b>Chave Pix:</b> {escape(str(partner.get('pix_key')))}")
    bank = dict(partner.get("bank_details") or {})
    bank_line = " · ".join(str(bank.get(key) or "").strip() for key in ("bank_name", "agency", "account") if bank.get(key))
    if bank_line:
        details.append(f"<b>Dados bancários:</b> {escape(bank_line)}")
    if quote.get("notes"):
        details.append(f"<b>Observações:</b> {escape(str(quote.get('notes')))}")
    if details:
        story.extend([Paragraph("Condições comerciais", heading), Paragraph("<br/>".join(details), body)])

    specialties = [str(item) for item in list(partner.get("specialties") or []) if str(item).strip()]
    if specialties:
        story.extend([Paragraph("Parceiro responsável", heading), Paragraph(f"Especialidades cadastradas: {escape(', '.join(specialties))}.", small)])

    doc.build(story)
    return buffer.getvalue()
