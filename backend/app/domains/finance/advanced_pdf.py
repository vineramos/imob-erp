from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domains.finance.advanced_schemas import AnnualIncomeReport, DreReport


def _currency(value: float) -> str:
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _base_document(title: str, organization_name: str) -> tuple[BytesIO, SimpleDocTemplate, list, dict]:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallGray", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#64748b"), leading=11))
    styles.add(ParagraphStyle(name="MoneyRight", parent=styles["Normal"], fontSize=9, alignment=TA_RIGHT))
    story = [Paragraph(organization_name, styles["SmallGray"]), Paragraph(title, styles["Title"]), Spacer(1, 4 * mm)]
    return buffer, doc, story, styles


def build_dre_pdf(report: DreReport, organization_name: str) -> bytes:
    buffer, doc, story, styles = _base_document("Demonstração do Resultado — DRE", organization_name)
    story.append(Paragraph(f"Período: {report.start_date:%d/%m/%Y} a {report.end_date:%d/%m/%Y} · Regime: {'Caixa' if report.regime == 'cash' else 'Competência'}", styles["SmallGray"]))
    story.append(Spacer(1, 4 * mm))
    rows = [["Conta", "Tipo", "Valor"]]
    for line in report.lines:
        rows.append([line.label, "Receita" if line.kind == "revenue" else "Despesa", _currency(line.amount)])
    rows.extend([
        ["Receita operacional", "", _currency(report.total_revenue)],
        ["Despesas/custos", "", _currency(report.total_expenses)],
        ["Resultado", "", _currency(report.result)],
        ["Margem", "", f"{report.margin_percent:.2f}%"],
    ])
    table = Table(rows, colWidths=[105 * mm, 32 * mm, 38 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -4), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("A DRE considera somente recursos operacionais da imobiliária. Valores recebidos e repassados em nome de proprietários não são reconhecidos como receita da imobiliária.", styles["SmallGray"]))
    doc.build(story)
    return buffer.getvalue()


def build_annual_income_pdf(report: AnnualIncomeReport, organization_name: str) -> bytes:
    title = "Informe anual do proprietário" if report.party_type == "owner" else "Informe anual do locatário"
    buffer, doc, story, styles = _base_document(title, organization_name)
    story.append(Paragraph(f"Ano-calendário: {report.year} · {report.person_name}", styles["Heading2"]))
    story.append(Paragraph(f"Critério de rateio: {report.allocation_method}", styles["SmallGray"]))
    story.append(Spacer(1, 4 * mm))

    if report.party_type == "owner":
        rows = [["Competência", "Repasse", "Imóvel", "Aluguel bruto", "Taxas", "Ajustes", "Líquido"]]
        for line in report.lines:
            rows.append([
                line.competence.strftime("%m/%Y"),
                line.payment_date.strftime("%d/%m/%Y") if line.payment_date else "—",
                line.property_code,
                _currency(line.rent_amount),
                _currency(line.administration_fee),
                _currency(line.additional_charges),
                _currency(line.owner_net_amount),
            ])
        rows.append([
            "TOTAL", "", "",
            _currency(report.total_rent),
            _currency(report.total_administration_fee),
            _currency(report.total_additional_charges),
            _currency(report.total_owner_net),
        ])
        table = Table(rows, colWidths=[23 * mm, 26 * mm, 23 * mm, 29 * mm, 27 * mm, 27 * mm, 30 * mm], repeatRows=1)
    else:
        rows = [["Competência", "Pagamento", "Imóvel", "Aluguel", "Encargos", "Total"]]
        for line in report.lines:
            rows.append([
                line.competence.strftime("%m/%Y"),
                line.payment_date.strftime("%d/%m/%Y") if line.payment_date else "—",
                line.property_code,
                _currency(line.rent_amount),
                _currency(line.additional_charges),
                _currency(line.total_amount),
            ])
        rows.append(["TOTAL", "", "", _currency(report.total_rent), _currency(report.total_additional_charges), _currency(report.total_paid)])
        table = Table(rows, colWidths=[25 * mm, 28 * mm, 26 * mm, 31 * mm, 31 * mm, 34 * mm], repeatRows=1)

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("FONTSIZE", (0, 0), (-1, -1), 7.8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    if report.party_type == "owner":
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(
            "O informe considera o regime de caixa do proprietário: a data do repasse efetivamente pago. "
            f"Taxas atribuídas: {_currency(report.total_administration_fee)} · "
            f"Ajustes/deduções posteriores ao direito econômico: {_currency(report.total_additional_charges)} · "
            f"Valor líquido efetivamente repassado: {_currency(report.total_owner_net)}.",
            styles["SmallGray"],
        ))
    doc.build(story)
    return buffer.getvalue()
