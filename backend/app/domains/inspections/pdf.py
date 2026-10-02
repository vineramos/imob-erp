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


def inspection_code(inspection: Any) -> str:
    prefix = "VIN" if inspection.inspection_type == "initial" else "VOUT"
    return f"{prefix}-{inspection.internal_number:06d}"


def _address(address: dict[str, Any]) -> str:
    parts = [address.get("street"), address.get("number"), address.get("complement"), address.get("neighborhood"), address.get("city"), address.get("state")]
    return ", ".join(str(item) for item in parts if item) or "Endereço não informado"


def _condition(value: str) -> str:
    return {
        "excellent": "Excelente", "good": "Bom", "regular": "Regular", "poor": "Ruim",
        "damaged": "Danificado", "not_applicable": "N/A",
    }.get(value, value)


def build_inspection_pdf(*, inspection: Any, organization: Any) -> bytes:
    buffer = BytesIO()
    code = inspection_code(inspection)
    lease = dict(inspection.lease_snapshot or {})
    property_snapshot = dict(lease.get("property") or {})
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Laudo de Vistoria {code}", author=getattr(organization, "display_name", "Imobiliária"),
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("InspectionTitle", parent=styles["Title"], fontSize=15, leading=18, alignment=TA_CENTER, spaceAfter=6)
    subtitle = ParagraphStyle("InspectionSubtitle", parent=styles["Normal"], fontSize=8.5, leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#5a6472"), spaceAfter=12)
    heading = ParagraphStyle("InspectionHeading", parent=styles["Heading2"], fontSize=10.5, leading=13, spaceBefore=10, spaceAfter=5)
    body = ParagraphStyle("InspectionBody", parent=styles["BodyText"], fontSize=8.7, leading=12)
    small = ParagraphStyle("InspectionSmall", parent=styles["BodyText"], fontSize=7.6, leading=10, textColor=colors.HexColor("#5a6472"))

    story = [
        Paragraph("LAUDO DE VISTORIA INICIAL" if inspection.inspection_type == "initial" else "LAUDO DE VISTORIA FINAL", title),
        Paragraph(f"{code} · versão {inspection.current_version} · contrato {escape(str(lease.get('lease_code') or '—'))}", subtitle),
        Paragraph("Identificação", heading),
        Paragraph(
            f"<b>Imóvel:</b> #{escape(str(property_snapshot.get('code') or '—'))} · {escape(_address(dict(property_snapshot.get('address') or {})))}<br/>"
            f"<b>Vistoriador:</b> {escape(str(inspection.inspector_name or 'não informado'))}<br/>"
            f"<b>Locatário(s):</b> {escape(' / '.join(str(item.get('name') or '') for item in list(lease.get('tenants') or [])) or '—')}",
            body,
        ),
    ]

    for environment in list(inspection.environments or []):
        story.append(Paragraph(escape(str(environment.get("name") or "Ambiente")), heading))
        rows = [["Item", "Estado", "Observações", "Fotos"]]
        for item in list(environment.get("items") or []):
            rows.append([
                str(item.get("label") or "—"),
                _condition(str(item.get("condition") or "good")),
                str(item.get("notes") or "—"),
                str(len(item.get("photos") or [])),
            ])
        table = Table(rows, colWidths=[48 * mm, 26 * mm, 90 * mm, 16 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f4f7")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.7),
            ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#d8dee6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
        if environment.get("notes"):
            story.append(Paragraph(f"Observação do ambiente: {escape(str(environment['notes']))}", small))

    contestations = list(inspection.contestations or [])
    if contestations:
        story.append(Paragraph("Contestações registradas", heading))
        for contestation in contestations:
            status = "Resolvida" if contestation.get("resolved_at") else "Pendente"
            story.append(Paragraph(
                f"<b>{escape(str(contestation.get('environment_key') or ''))} / {escape(str(contestation.get('item_key') or ''))}</b> · {status}<br/>"
                f"{escape(str(contestation.get('description') or ''))}"
                + (f"<br/><b>Tratativa:</b> {escape(str(contestation.get('resolution')))}" if contestation.get("resolution") else ""),
                body,
            ))

    if inspection.notes:
        story.extend([Paragraph("Observações gerais", heading), Paragraph(escape(str(inspection.notes)), body)])

    story.extend([
        Spacer(1, 10),
        Paragraph(
            "Este laudo é versionado e auditável. Cada alteração gera nova versão. A entrega de chaves somente pode ser registrada quando o contrato de locação estiver assinado e arquivado e a vistoria inicial estiver concluída com hash do laudo.",
            small,
        ),
    ])
    doc.build(story)
    return buffer.getvalue()
