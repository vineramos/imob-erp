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


def _lease_months(start: Any, end: Any) -> str:
    if not start or not end:
        return "—"
    months = (end.year - start.year) * 12 + end.month - start.month
    return f"{months} meses" if months > 0 else "—"


def build_administration_contract_pdf(*, contract: Any, organization: Any) -> bytes:
    """Gera a representação PDF determinística da versão corrente congelada.

    O modo ``invariant`` do ReportLab elimina timestamps/IDs variáveis do arquivo.
    Assim, a mesma versão contratual produz sempre os mesmos bytes e o SHA-256
    registrado pode ser validado novamente antes do envio para assinatura.
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
        invariant=1,
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
    rules_snapshot = dict(contract.rules_snapshot or {})
    end_action = str(rules_snapshot.get("end_of_term_action") or "renew_indefinite")
    end_action_label = "Fim do contrato" if end_action == "end_contract" else "Renovação por prazo indeterminado"
    story.append(Paragraph("4. Condições econômicas e operacionais", heading))
    rules = [
        ["Plano", str(contract.plan).title()],
        ["Administração após intermediação", fee],
        ["Intermediação inicial", f"{_percent(contract.intermediation_percent)} do aluguel em {contract.intermediation_installments} parcela(s) inicial(is)"],
        ["Repasse ao proprietário", f"D+{contract.owner_repasse_business_days} dias úteis após liquidação confirmada"],
        ["Condomínio · pagador operacional", str(contract.condo_operational_payer)],
        ["IPTU · pagador operacional", str(contract.iptu_operational_payer)],
        ["Prazo previsto da locação", _lease_months(contract.start_date, contract.end_date)],
        ["Ao fim do prazo", end_action_label],
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
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "A intermediação substitui a taxa de administração durante as parcelas iniciais acima. Encerrada a intermediação, passa a incidir a taxa de administração nas competências seguintes. Quando a intermediação for de 100% em uma única parcela, o primeiro aluguel pertence integralmente à administradora e a administração começa no segundo aluguel.",
        small,
    ))

    if contract.notes:
        story.extend([Paragraph("5. Condições especiais", heading), Paragraph(str(contract.notes), body)])

    story.append(Paragraph("6. Signatários desta versão", heading))
    signers = list(contract.signers_snapshot or [])
    role_labels = {"owner": "Proprietário", "tenant": "Locatário", "agency": "Imobiliária", "witness": "Testemunha", "other": "Outro"}
    if signers:
        rows = [["Papel", "Nome", "E-mail", "Ordem"]]
        for signer in signers:
            role = str(signer.get("role") or "—")
            rows.append([role_labels.get(role, role), signer.get("name") or "—", signer.get("email") or "—", str(signer.get("sign_order") or 1)])
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
