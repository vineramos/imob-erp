from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _money(value: Any) -> str:
    number = float(value or 0)
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.astimezone().strftime("%d/%m/%Y %H:%M")
    return value.strftime("%d/%m/%Y")


def _address(value: dict[str, Any]) -> str:
    keys = ("street", "number", "complement", "neighborhood", "city", "state")
    return ", ".join(str(value.get(key)) for key in keys if value.get(key)) or "—"


def _method(value: str | None) -> str:
    return {
        "pix": "Pix",
        "boleto": "Boleto",
        "transfer": "Transferência",
        "cash": "Dinheiro",
        "other": "Outro",
    }.get(str(value or "").lower(), str(value or "—"))


def build_tenant_receipt_pdf(
    *,
    organization_name: str,
    tenant_name: str,
    lease_code: str,
    property_code: str,
    property_address: dict[str, Any],
    charge_code: str,
    competence: date,
    due_date: date,
    paid_at: datetime,
    paid_amount: Decimal,
    payment_method: str | None,
    payment_reference: str | None,
    charge_items: list[dict[str, Any]],
) -> bytes:
    """Gera recibo externo sem qualquer composição interna de repasses ou margens."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Recibo {charge_code} - {tenant_name}",
        author=organization_name,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("ReceiptTitle", parent=styles["Title"], fontSize=15, leading=18, spaceAfter=4)
    subtitle = ParagraphStyle("ReceiptSubtitle", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#5f6876"), spaceAfter=10)
    small = ParagraphStyle("ReceiptSmall", parent=styles["Normal"], fontSize=7.5, leading=9, textColor=colors.HexColor("#5f6876"))

    story = [
        Paragraph("RECIBO DE PAGAMENTO", title),
        Paragraph(
            f"{escape(organization_name)} · {escape(charge_code)} · competência {competence:%m/%Y}<br/>"
            f"Locatário: <b>{escape(tenant_name)}</b>",
            subtitle,
        ),
    ]
    summary = [
        ["Contrato", lease_code],
        ["Imóvel", f"{property_code} · {_address(property_address)}"],
        ["Vencimento", _date(due_date)],
        ["Pagamento", _date(paid_at)],
        ["Forma de pagamento", _method(payment_method)],
        ["Referência", payment_reference or "—"],
        ["Valor recebido", _money(paid_amount)],
    ]
    table = Table(summary, colWidths=[48 * mm, 126 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9dee6")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([table, Spacer(1, 12)])

    rows = [["Composição da cobrança", "Valor"]]
    for item in charge_items:
        label = str(item.get("label") or "Encargo")
        amount = item.get("amount") or 0
        rows.append([label, _money(amount)])
    if len(rows) == 1:
        rows.append(["Mensalidade da locação", _money(paid_amount)])
    details = Table(rows, colWidths=[135 * mm, 39 * mm], repeatRows=1)
    details.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f4f7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9dee6")),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([
        details,
        Spacer(1, 12),
        Paragraph(
            "Este recibo confirma a liquidação integral da cobrança identificada acima. "
            "A composição exibida corresponde somente aos valores cobrados do locatário; "
            "repasses, retenções e controles internos da imobiliária não integram este documento.",
            small,
        ),
    ])
    doc.build(story)
    return buffer.getvalue()
