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


def _date(value: Any) -> str:
    text = str(value or "")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}/{text[5:7]}/{text[:4]}"
    return text or "—"


def _address(address: dict[str, Any]) -> str:
    return ", ".join(str(address.get(key)) for key in ("street", "number", "neighborhood", "city", "state") if address.get(key)) or "—"


def build_owner_statement_pdf(*, statement: Any, organization_name: str) -> bytes:
    buffer = BytesIO()
    competence = statement.competence
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Prestação de Contas {competence:%m/%Y} - {statement.owner_name}",
        author=organization_name,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("FinanceTitle", parent=styles["Title"], fontSize=14, leading=17, spaceAfter=5)
    subtitle = ParagraphStyle("FinanceSubtitle", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#5f6876"), spaceAfter=10)
    small = ParagraphStyle("FinanceSmall", parent=styles["Normal"], fontSize=7.5, leading=9, textColor=colors.HexColor("#5f6876"))

    story = [
        Paragraph("PRESTAÇÃO DE CONTAS DO PROPRIETÁRIO", title),
        Paragraph(
            f"{escape(organization_name)} · competência {competence:%m/%Y}<br/>"
            f"Proprietário: <b>{escape(statement.owner_name)}</b>",
            subtitle,
        ),
    ]

    summary = [
        ["Recebido dos locatários", _money(statement.total_received_from_tenants)],
        ["Taxas / intermediação calculadas", _money(statement.total_agency_fees)],
        ["Direito econômico do proprietário", _money(statement.total_owner_entitlement)],
        ["Repasses previstos", _money(statement.total_repasse)],
        ["Repasses pagos", _money(statement.total_repasse_paid)],
    ]
    table = Table(summary, colWidths=[100 * mm, 70 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9dee6")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([table, Spacer(1, 10)])

    rows = [["Cobrança", "Imóvel", "Recebimento", "Bruto", "Taxas", "Participação", "Repasse", "Situação"]]
    for line in statement.lines:
        rows.append([
            line.charge_code,
            f"#{line.property_code}\n{_address(line.property_address)}",
            _date(line.paid_at),
            _money(line.gross_charge),
            _money(line.admin_fee + line.intermediation_fee),
            f"{line.ownership_percent}%",
            _money(line.repasse_amount),
            "Pago" if line.repasse_status == "paid" else f"Prev. {_date(line.repasse_due_date)}",
        ])
    if len(rows) == 1:
        rows.append(["—", "Nenhum recebimento na competência", "—", "—", "—", "—", "—", "—"])
    detail = Table(rows, colWidths=[21*mm, 47*mm, 22*mm, 20*mm, 20*mm, 20*mm, 21*mm, 23*mm], repeatRows=1)
    detail.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f4f7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.7),
        ("LEADING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9dee6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))
    story.extend([
        detail,
        Spacer(1, 10),
        Paragraph(
            "Documento gerado pelo ERP com base nas cobranças liquidadas, taxas contratuais e repasses registrados. "
            "Valores recebidos em nome de proprietários permanecem segregados do caixa próprio da imobiliária.",
            small,
        ),
    ])
    doc.build(story)
    return buffer.getvalue()
