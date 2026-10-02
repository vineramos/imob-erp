from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _money(value) -> str:
    number = float(value or 0)
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _date(value) -> str:
    if not value:
        return "—"
    text = str(value)
    return f"{text[8:10]}/{text[5:7]}/{text[:4]}" if len(text) >= 10 else text


def build_commission_batch_pdf(*, batch, items: list[dict]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Title"], fontSize=14, leading=17, spaceAfter=6)
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=8.5, leading=11)
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=7.5, leading=9, textColor=colors.HexColor("#5f6876"))
    code = f"COM-{batch.competence:%Y}-{batch.internal_number:06d}"
    story = [
        Paragraph("RELATÓRIO DE COMISSÕES", title),
        Paragraph(
            f"Protocolo: <b>{escape(code)}</b><br/>Competência: <b>{batch.competence:%m/%Y}</b><br/>"
            f"Corretor: <b>{escape(batch.beneficiary_name)}</b><br/>"
            f"Razão social do prestador: <b>{escape(batch.broker_legal_name or 'Não informada')}</b><br/>"
            f"CNPJ do prestador: <b>{escape(batch.broker_document_number or 'Não informado')}</b>",
            body,
        ),
        Spacer(1, 8),
        Paragraph("<b>Dados para emissão da Nota Fiscal</b>", body),
        Paragraph(
            f"Tomador: {escape(batch.organization_legal_name)}<br/>"
            f"CNPJ: {escape(batch.organization_document_number or 'Não informado')}<br/>"
            f"Valor: <b>{_money(batch.total_amount)}</b><br/>"
            f"Descrição sugerida: {escape(batch.service_description)}",
            body,
        ),
        Spacer(1, 10),
    ]
    rows = [["Comissão", "Contrato / imóvel", "Cliente", "Recebimento", "Base", "Comissão"]]
    for item in items:
        s = item.get("snapshot") or {}
        rows.append([
            s.get("commission_code") or "—",
            f"{s.get('lease_code') or '—'} / #{s.get('property_code') or '—'}",
            s.get("tenant_name") or "—",
            _date(s.get("paid_at")),
            _money(s.get("basis_amount")),
            _money(item.get("amount")),
        ])
    rows.append(["", "", "", "", "TOTAL", _money(batch.total_amount)])
    table = Table(rows, colWidths=[25*mm, 48*mm, 38*mm, 27*mm, 25*mm, 27*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#f1f4f7")),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTNAME",(-2,-1),(-1,-1),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),6.8),
        ("LEADING",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-2),0.3,colors.HexColor("#d9dee6")),
        ("LINEABOVE",(-2,-1),(-1,-1),0.6,colors.HexColor("#8d96a3")),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("PADDING",(0,0),(-1,-1),3),
    ]))
    story.extend([table, Spacer(1,10), Paragraph(
        "Este relatório consolida apenas comissões vinculadas a recebimentos efetivamente registrados no financeiro no período indicado. "
        "A liberação para pagamento depende da conferência e aprovação da Nota Fiscal pelo setor financeiro.",
        small,
    )])
    doc.build(story)
    return buffer.getvalue()
