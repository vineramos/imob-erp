from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import Organization, OrganizationSettings
from app.domains.portfolio.models import Property, PropertyPhoto
from app.integrations.document_storage import DocumentStorageError, get_document_storage

router = APIRouter(tags=["portal-feeds"])

PORTALS = ("olx", "vrsync")

OLX_TYPE = {
    "apartment": "Apartamento Padrão",
    "studio": "Studio",
    "house": "Casa Padrão",
    "land": "Terreno Padrão",
    "commercial": "Conjunto Comercial",
}
OLX_SUBTYPE_ALLOWED = {
    "apartment": {"Apartamento", "Apartamento de Condomínio", "Apartamento Duplex Residencial", "Apartamento Padrão", "Apartamento Residencial", "Apartamento Triplex Residencial", "Conjunto Residencial", "Padrão", "Cobertura", "Cobertura Duplex", "Cobertura Residencial", "Cobertura Triplex", "Penthouse Residencial", "Flat", "Flat Padrão", "Flat Residencial", "Loft", "Loft Residencial", "Kitchenette / Conjugados", "Kitchenette / Studio", "Kitnet", "Kitnet / Conjugado", "Kitnet Residencial", "Studio"},
    "studio": {"Studio", "Kitchenette / Studio", "Kitnet", "Kitnet / Conjugado", "Kitnet Residencial"},
    "house": {"Casa", "Casa de Rua", "Casa Padrão", "Casa Padrão Térrea", "Casa Residencial", "Sobrado", "Sobrado Residencial", "Village Residencial", "Casa de Condomínio", "Casa em Condomínio", "Casa de Vila"},
    "land": {"Loteamento Condomínio", "Loteamento Padrão", "Sítio", "Sítio Chácara", "Sítio Rural", "Terreno", "Terreno Padrão", "Chácara", "Chácara Rural", "Fazenda", "Fazenda Rural", "Haras", "Haras Rural"},
    "commercial": {"Andar", "Casa Comercial", "Conjunto Comercial", "Conjunto Comercial / Sala", "Laje Comercial", "Salão Comercial", "Sobrado Comercial", "Área Comercial", "Galpão / Depósito / Armazém", "Galpão / Depósito / Barracão", "Galpão Comercial", "Indústria", "Box Garagem", "Hotel", "Hotel Residencial", "Motel", "Pousada / Chalé", "Barracão Comercial", "Centro Comercial", "Comercial", "Loja", "Loja Comercial", "Loja de Shopping", "Loja de Shopping / Centro Comercial", "Loja Salão", "Ponto Comercial", "Prédio", "Prédio Comercial", "Prédio Inteiro", "Sala", "Sala Comercial"},
}
VRSYNC_TYPE = {
    "apartment": "Residential / Apartment",
    "studio": "Residential / Studio",
    "house": "Residential / Home",
    "land": "Residential / Land Lot",
    "commercial": "Commercial / Office",
}


class PortalSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    olx: bool = False
    vrsync: bool = False


class PortalIntegrationConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(not_configured|pending_homologation|active|rejected)$")
    notes: str = Field(default="", max_length=1000)


def _settings(db: Session, organization_id: UUID) -> OrganizationSettings:
    row = db.scalar(select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id))
    if row is None:
        row = OrganizationSettings(organization_id=organization_id, erp_theme={}, site_theme={}, operational_defaults={}, integrations={})
        db.add(row)
        db.flush()
    return row


def _portal_settings(db: Session, organization_id: UUID) -> dict:
    row = _settings(db, organization_id)
    return dict(row.portal_integrations or {})


def _portal_config_item(db: Session, organization_id: UUID, request: Request, portal: str) -> dict:
    config = dict(_portal_settings(db, organization_id).get(portal) or {})
    return {
        "key": portal,
        "label": "OLX" if portal == "olx" else "ZAP Imóveis + Viva Real",
        "status": str(config.get("status") or "not_configured"),
        "notes": str(config.get("notes") or ""),
        "last_validated_at": config.get("last_validated_at"),
        "last_validation": config.get("last_validation"),
        "feed_url": _feed_url(request, organization_id, portal),
    }


def _load_property(db: Session, organization_id: UUID, property_id: UUID) -> Property:
    item = db.scalar(select(Property).where(Property.id == property_id, Property.organization_id == organization_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Imóvel não encontrado.")
    return item


def _photos(db: Session, property_id: UUID) -> list[PropertyPhoto]:
    return list(db.scalars(
        select(PropertyPhoto)
        .where(PropertyPhoto.property_id == property_id)
        .order_by(PropertyPhoto.is_cover.desc(), PropertyPhoto.position.asc(), PropertyPhoto.created_at.asc())
    ).all())


def _issues(item: Property, photo_count: int, portal: str) -> list[str]:
    address = item.address or {}
    issues: list[str] = []
    if item.status != "available":
        issues.append("O imóvel precisa estar com status Disponível.")
    if item.property_type not in (OLX_TYPE if portal == "olx" else VRSYNC_TYPE):
        issues.append("Tipo de imóvel ainda não mapeado para este portal.")
    if not (item.public_title or "").strip():
        issues.append("Informe o título público.")
    if len((item.public_description or "").strip()) < 30:
        issues.append("A descrição pública precisa ter ao menos 30 caracteres.")
    if not str(address.get("postal_code") or "").strip():
        issues.append("Informe o CEP.")
    for field, label in (("city", "cidade"), ("state", "UF"), ("neighborhood", "bairro")):
        if not str(address.get(field) or "").strip():
            issues.append(f"Informe {label}.")
    if item.purpose == "rent" and not (item.rent_amount and item.rent_amount > 0):
        issues.append("Informe um valor de aluguel maior que zero.")
    if item.purpose == "sale" and not (item.rent_amount and item.rent_amount > 0):
        issues.append("Informe o valor comercial do imóvel.")
    if portal == "vrsync" and photo_count < 5:
        issues.append("ZAP/Viva Real exigem ao menos 5 fotos.")
    if portal == "olx":
        subtype = OLX_TYPE.get(item.property_type)
        if subtype and subtype not in OLX_SUBTYPE_ALLOWED.get(item.property_type, set()):
            issues.append("Subtipo do imóvel não está na taxonomia XML oficial da OLX.")
        code = f"IMO{item.internal_number:06d}"
        if len(code) > 20:
            issues.append("Código do imóvel excede o limite de 20 caracteres da OLX.")
        title = (item.public_title or "").strip()
        if len(title) > 90:
            issues.append("Título público excede o limite de 90 caracteres da OLX.")
        description = (item.public_description or "").strip()
        if len(description) > 6000:
            issues.append("Descrição pública excede o limite de 6.000 caracteres da OLX.")
        cep = "".join(ch for ch in str(address.get("postal_code") or "") if ch.isdigit())
        if cep and len(cep) != 8:
            issues.append("CEP precisa conter 8 dígitos para a integração OLX.")
        if item.property_type in {"apartment", "studio", "house"} and item.bedrooms is None:
            issues.append("Quantidade de dormitórios é obrigatória para apartamentos e casas na OLX.")
        if photo_count < 1:
            issues.append("Adicione ao menos uma foto antes da homologação.")
    return issues


def _selection(item: Property) -> dict[str, bool]:
    raw = item.portal_publications or {}
    return {portal: bool((raw.get(portal) or {}).get("enabled")) for portal in PORTALS}


def _public_base_url(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    if forwarded_proto in {"http", "https"} and "://" in base:
        base = forwarded_proto + "://" + base.split("://", 1)[1]
    elif request.url.hostname and request.url.hostname.endswith(".run.app") and base.startswith("http://"):
        base = "https://" + base.removeprefix("http://")
    return base


def _feed_url(request: Request, organization_id: UUID, portal: str) -> str:
    return f"{_public_base_url(request)}/api/public/feeds/{organization_id}/{portal}.xml"


@router.get("/integrations/portals")
def get_portal_integrations(
    request: Request,
    context: UserContext = Depends(require_permission("settings.view")),
    db: Session = Depends(get_db),
):
    return {"channels": [_portal_config_item(db, context.user.organization_id, request, portal) for portal in PORTALS]}


@router.put("/integrations/portals/{portal}")
def update_portal_integration(
    portal: str,
    payload: PortalIntegrationConfigUpdate,
    request: Request,
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
):
    if portal not in PORTALS:
        raise HTTPException(status_code=404, detail="Portal não suportado.")
    settings = _settings(db, context.user.organization_id)
    portal_integrations = dict(settings.portal_integrations or {})
    before = dict(portal_integrations.get(portal) or {})
    after = {**before, "status": payload.status, "notes": payload.notes.strip(), "updated_at": datetime.now(timezone.utc).isoformat()}
    portal_integrations[portal] = after
    settings.portal_integrations = portal_integrations
    settings.updated_by_user_id = context.user.id
    write_audit(
        db,
        context=context,
        action="integrations.portal.updated",
        module="settings",
        entity_type="portal_integration",
        entity_id=portal,
        before_data=before,
        after_data=after,
        ip_address=request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip() or (request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return _portal_config_item(db, context.user.organization_id, request, portal)


@router.post("/integrations/portals/{portal}/validate")
def validate_portal_integration(
    portal: str,
    request: Request,
    context: UserContext = Depends(require_permission("settings.company.manage")),
    db: Session = Depends(get_db),
):
    if portal not in PORTALS:
        raise HTTPException(status_code=404, detail="Portal não suportado.")
    selected = _selected_properties(db, context.user.organization_id, portal)
    invalid = []
    for item in selected:
        problems = _issues(item, len(_photos(db, item.id)), portal)
        if problems:
            invalid.append({"code": f"IMO-{item.internal_number:06d}", "issues": problems})
    response = olx_feed(context.user.organization_id, request, db) if portal == "olx" else vrsync_feed(context.user.organization_id, request, db)
    xml_valid = False
    xml_error = None
    document_issues: list[str] = []
    try:
        ET.fromstring(response.body)
        xml_valid = True
        if portal == "olx":
            document_issues = _validate_olx_document(response.body)
    except ET.ParseError as exc:
        xml_error = str(exc)
    validation = {
        "valid": xml_valid and not invalid and not document_issues and len(selected) > 0,
        "xml_valid": xml_valid,
        "xml_error": xml_error,
        "document_issues": document_issues,
        "selected_count": len(selected),
        "invalid_count": len(invalid),
        "invalid_properties": invalid[:20],
        "compliance_profile": "OLX Imóveis XML" if portal == "olx" else "VRSync",
        "requirements_checked": [
            "XML bem-formado",
            "URL pública HTTPS",
            "Código do imóvel",
            "Subtipo aceito",
            "CEP",
            "Descrição",
            "Preço",
            "Campos obrigatórios da subcategoria",
        ] if portal == "olx" else ["XML bem-formado", "URL pública HTTPS", "campos mínimos VRSync"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    settings = _settings(db, context.user.organization_id)
    portal_integrations = dict(settings.portal_integrations or {})
    current = dict(portal_integrations.get(portal) or {})
    current["last_validated_at"] = validation["checked_at"]
    current["last_validation"] = validation
    portal_integrations[portal] = current
    settings.portal_integrations = portal_integrations
    settings.updated_by_user_id = context.user.id
    db.commit()
    return {**_portal_config_item(db, context.user.organization_id, request, portal), "validation": validation}


@router.get("/properties/{property_id}/portal-publications")
def get_portal_publications(
    property_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("properties.view")),
    db: Session = Depends(get_db),
):
    item = _load_property(db, context.user.organization_id, property_id)
    photo_count = len(_photos(db, item.id))
    selected = _selection(item)
    channels = []
    for portal in PORTALS:
        issues = _issues(item, photo_count, portal)
        channels.append({
            "key": portal,
            "label": "OLX" if portal == "olx" else "ZAP Imóveis + Viva Real",
            "enabled": selected[portal],
            "ready": not issues,
            "issues": issues,
            "feed_url": _feed_url(request, context.user.organization_id, portal),
        })
    return {"property_id": str(item.id), "channels": channels}


@router.put("/properties/{property_id}/portal-publications")
def update_portal_publications(
    property_id: UUID,
    payload: PortalSelection,
    request: Request,
    context: UserContext = Depends(require_permission("properties.publish")),
    db: Session = Depends(get_db),
):
    item = _load_property(db, context.user.organization_id, property_id)
    photo_count = len(_photos(db, item.id))
    requested = payload.model_dump()
    next_value = dict(item.portal_publications or {})
    for portal, enabled in requested.items():
        if enabled:
            issues = _issues(item, photo_count, portal)
            if issues:
                raise HTTPException(status_code=422, detail=f"{'OLX' if portal == 'olx' else 'ZAP/Viva Real'}: " + " ".join(issues))
        next_value[portal] = {
            "enabled": enabled,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by_user_id": str(context.user.id),
        }
    item.portal_publications = next_value
    db.commit()
    return get_portal_publications(property_id, request, context, db)


def _selected_properties(db: Session, organization_id: UUID, portal: str) -> list[Property]:
    items = list(db.scalars(
        select(Property)
        .where(Property.organization_id == organization_id, Property.status == "available")
        .order_by(Property.internal_number.asc())
        .limit(1000)
    ).all())
    return [item for item in items if bool(((item.portal_publications or {}).get(portal) or {}).get("enabled"))]


def _photo_urls(request: Request, organization_id: UUID, item: Property, photos: list[PropertyPhoto]) -> list[tuple[PropertyPhoto, str]]:
    base = _public_base_url(request)
    return [(photo, f"{base}/api/public/feeds/{organization_id}/properties/{item.id}/photos/{photo.id}") for photo in photos]


@router.get("/public/feeds/{organization_id}/properties/{property_id}/photos/{photo_id}")
def portal_photo(
    organization_id: UUID,
    property_id: UUID,
    photo_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    item = db.scalar(select(Property).where(Property.id == property_id, Property.organization_id == organization_id, Property.status == "available"))
    if item is None or not any(bool(((item.portal_publications or {}).get(portal) or {}).get("enabled")) for portal in PORTALS):
        raise HTTPException(status_code=404, detail="Imagem não disponível.")
    photo = db.scalar(select(PropertyPhoto).where(PropertyPhoto.id == photo_id, PropertyPhoto.property_id == property_id, PropertyPhoto.organization_id == organization_id))
    if photo is None:
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")
    try:
        body = get_document_storage().download_bytes(photo.storage_reference)
    except DocumentStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=body, media_type=photo.content_type, headers={"Cache-Control": "public, max-age=86400"})


def _money_int(value: Decimal | None) -> str:
    return str(int(value or 0))


def _validate_olx_document(xml_body: bytes) -> list[str]:
    issues: list[str] = []
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError as exc:
        return [f"XML inválido: {exc}"]
    if root.tag != "Carga":
        issues.append("A raiz do XML da OLX deve ser <Carga>.")
        return issues
    imoveis = root.find("Imoveis")
    if imoveis is None:
        issues.append("O XML da OLX precisa conter <Imoveis>.")
        return issues
    allowed_subtypes = set().union(*OLX_SUBTYPE_ALLOWED.values())
    for index, node in enumerate(imoveis.findall("Imovel"), start=1):
        prefix = f"Imóvel #{index}"
        def text_of(tag: str) -> str:
            child = node.find(tag)
            return (child.text or "").strip() if child is not None else ""
        code = text_of("CodigoImovel")
        subtype = text_of("SubTipoImovel")
        cep = "".join(ch for ch in text_of("CEP") if ch.isdigit())
        description = text_of("Observacao")
        title = text_of("TituloAnuncio") or text_of("Titulo")
        if not code:
            issues.append(f"{prefix}: <CodigoImovel> é obrigatório.")
        elif len(code) > 20:
            issues.append(f"{prefix}: <CodigoImovel> excede 20 caracteres.")
        if subtype not in allowed_subtypes:
            issues.append(f"{prefix}: <SubTipoImovel> não está na taxonomia oficial.")
        if len(cep) != 8:
            issues.append(f"{prefix}: <CEP> deve conter 8 dígitos.")
        if not description:
            issues.append(f"{prefix}: <Observacao> é obrigatória.")
        elif len(description) > 6000:
            issues.append(f"{prefix}: <Observacao> excede 6.000 caracteres.")
        if title and len(title) > 90:
            issues.append(f"{prefix}: título excede 90 caracteres.")
        prices = [text_of("PrecoVenda"), text_of("PrecoLocacao"), text_of("PrecoLocacaoTemporada")]
        if not any(prices):
            issues.append(f"{prefix}: informe ao menos um preço de venda ou locação.")
        for tag in ("PrecoVenda", "PrecoLocacao", "PrecoLocacaoTemporada", "PrecoCondominio", "ValorIPTU", "AreaTotal", "AreaUtil"):
            value = text_of(tag)
            if value and not value.isdigit():
                issues.append(f"{prefix}: <{tag}> deve ser número inteiro sem separadores.")
        if subtype in OLX_SUBTYPE_ALLOWED["apartment"] or subtype in OLX_SUBTYPE_ALLOWED["studio"] or subtype in OLX_SUBTYPE_ALLOWED["house"]:
            bedrooms = text_of("QtdDormitorios")
            if bedrooms not in {"0", "1", "2", "3", "4", "5"}:
                issues.append(f"{prefix}: <QtdDormitorios> deve ser um valor de 0 a 5.")
        for photo in node.findall("./Fotos/Foto"):
            url = (photo.findtext("URLArquivo") or "").strip()
            if url and not url.startswith("https://"):
                issues.append(f"{prefix}: URL de foto deve ser pública em HTTPS.")
    return issues


@router.get("/public/feeds/{organization_id}/olx.xml")
def olx_feed(organization_id: UUID, request: Request, db: Session = Depends(get_db)) -> Response:
    organization = db.get(Organization, organization_id)
    if organization is None or not organization.is_active:
        raise HTTPException(status_code=404, detail="Feed não encontrado.")
    root = ET.Element("Carga", {"xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance", "xmlns:xsd": "http://www.w3.org/2001/XMLSchema"})
    imoveis = ET.SubElement(root, "Imoveis")
    for item in _selected_properties(db, organization_id, "olx"):
        photos = _photos(db, item.id)
        if _issues(item, len(photos), "olx"):
            continue
        address = item.address or {}
        node = ET.SubElement(imoveis, "Imovel")
        ET.SubElement(node, "CodigoImovel").text = f"IMO{item.internal_number:06d}"
        ET.SubElement(node, "TituloAnuncio").text = (item.public_title or f"Imóvel {item.internal_number:06d}")[:90]
        ET.SubElement(node, "SubTipoImovel").text = OLX_TYPE[item.property_type]
        ET.SubElement(node, "Cidade").text = str(address.get("city") or "")
        ET.SubElement(node, "Bairro").text = str(address.get("neighborhood") or "")
        ET.SubElement(node, "CEP").text = "".join(ch for ch in str(address.get("postal_code") or "") if ch.isdigit())
        ET.SubElement(node, "PrecoLocacao" if item.purpose == "rent" else "PrecoVenda").text = _money_int(item.rent_amount)
        if item.condo_amount:
            ET.SubElement(node, "PrecoCondominio").text = _money_int(item.condo_amount)
        if item.iptu_amount:
            ET.SubElement(node, "ValorIPTU").text = _money_int(item.iptu_amount)
        if item.property_type not in {"land", "commercial"}:
            ET.SubElement(node, "QtdDormitorios").text = str(min(int(item.bedrooms or 0), 5))
            ET.SubElement(node, "QtdBanheiros").text = str(min(int(item.bathrooms or 0), 5))
        ET.SubElement(node, "QtdVagas").text = str(min(int(item.parking_spaces or 0), 5))
        if item.area_m2:
            ET.SubElement(node, "AreaTotal" if item.property_type == "land" else "AreaUtil").text = str(int(item.area_m2))
        ET.SubElement(node, "Observacao").text = (item.public_description or "")[:6000]
        photo_root = ET.SubElement(node, "Fotos")
        for photo, url in _photo_urls(request, organization_id, item, photos):
            photo_node = ET.SubElement(photo_root, "Foto")
            if photo.is_cover:
                ET.SubElement(photo_node, "Principal").text = "1"
            ET.SubElement(photo_node, "URLArquivo").text = url
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml, media_type="application/xml; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})


@router.get("/public/feeds/{organization_id}/vrsync.xml")
def vrsync_feed(organization_id: UUID, request: Request, db: Session = Depends(get_db)) -> Response:
    organization = db.get(Organization, organization_id)
    if organization is None or not organization.is_active:
        raise HTTPException(status_code=404, detail="Feed não encontrado.")
    ns = "http://www.vivareal.com/schemas/1.0/VRSync"
    ET.register_namespace("", ns)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root = ET.Element(f"{{{ns}}}ListingDataFeed", {"{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": f"{ns} http://xml.vivareal.com/vrsync.xsd"})
    header = ET.SubElement(root, f"{{{ns}}}Header")
    ET.SubElement(header, f"{{{ns}}}Provider").text = "Imob ERP"
    ET.SubElement(header, f"{{{ns}}}Email").text = organization.contact_email or "contato@imob.local"
    ET.SubElement(header, f"{{{ns}}}ContactName").text = organization.display_name
    ET.SubElement(header, f"{{{ns}}}PublishDate").text = datetime.now(timezone.utc).isoformat()
    if organization.contact_phone:
        ET.SubElement(header, f"{{{ns}}}Telephone").text = organization.contact_phone
    listings = ET.SubElement(root, f"{{{ns}}}Listings")
    for item in _selected_properties(db, organization_id, "vrsync"):
        photos = _photos(db, item.id)
        if _issues(item, len(photos), "vrsync"):
            continue
        address = item.address or {}
        listing = ET.SubElement(listings, f"{{{ns}}}Listing")
        ET.SubElement(listing, f"{{{ns}}}ListingID").text = f"IMO-{item.internal_number:06d}"
        ET.SubElement(listing, f"{{{ns}}}Title").text = (item.public_title or f"Imóvel {item.internal_number:06d}")[:100]
        ET.SubElement(listing, f"{{{ns}}}TransactionType").text = "For Rent" if item.purpose == "rent" else "For Sale"
        ET.SubElement(listing, f"{{{ns}}}PublicationType").text = "STANDARD"
        media = ET.SubElement(listing, f"{{{ns}}}Media")
        for photo, url in _photo_urls(request, organization_id, item, photos):
            attrs = {"medium": "image"}
            if photo.is_cover:
                attrs["primary"] = "true"
            media_item = ET.SubElement(media, f"{{{ns}}}Item", attrs)
            if photo.caption:
                media_item.set("caption", photo.caption[:100])
            media_item.text = url
        details = ET.SubElement(listing, f"{{{ns}}}Details")
        ET.SubElement(details, f"{{{ns}}}PropertyType").text = VRSYNC_TYPE[item.property_type]
        if item.purpose == "rent":
            price = ET.SubElement(details, f"{{{ns}}}RentalPrice", {"currency": "BRL", "period": "Monthly"})
        else:
            price = ET.SubElement(details, f"{{{ns}}}ListPrice", {"currency": "BRL"})
        price.text = _money_int(item.rent_amount)
        ET.SubElement(details, f"{{{ns}}}Description").text = (item.public_description or "")[:3000]
        area_tag = "LotArea" if item.property_type == "land" else "LivingArea"
        if item.area_m2:
            ET.SubElement(details, f"{{{ns}}}{area_tag}", {"unit": "square metres"}).text = str(int(item.area_m2))
        if item.property_type != "land":
            ET.SubElement(details, f"{{{ns}}}Bedrooms").text = str(max(1, int(item.bedrooms or 0)) if item.property_type == "studio" else int(item.bedrooms or 0))
            ET.SubElement(details, f"{{{ns}}}Bathrooms").text = str(int(item.bathrooms or 0))
        ET.SubElement(details, f"{{{ns}}}Garage").text = str(int(item.parking_spaces or 0))
        ET.SubElement(details, f"{{{ns}}}Suites").text = str(int(item.suites or 0))
        ET.SubElement(details, f"{{{ns}}}UsageType").text = "Commercial" if item.property_type == "commercial" else "Residential"
        location = ET.SubElement(listing, f"{{{ns}}}Location", {"displayAddress": "Neighborhood"})
        ET.SubElement(location, f"{{{ns}}}Country", {"abbreviation": "BR"}).text = "Brasil"
        ET.SubElement(location, f"{{{ns}}}State", {"abbreviation": str(address.get("state") or "")}).text = str(address.get("state") or "")
        ET.SubElement(location, f"{{{ns}}}City").text = str(address.get("city") or "")
        ET.SubElement(location, f"{{{ns}}}Neighborhood").text = str(address.get("neighborhood") or "")
        ET.SubElement(location, f"{{{ns}}}Address").text = str(address.get("street") or "")
        ET.SubElement(location, f"{{{ns}}}StreetNumber").text = str(address.get("number") or "")
        ET.SubElement(location, f"{{{ns}}}Complement").text = str(address.get("complement") or "")
        ET.SubElement(location, f"{{{ns}}}PostalCode").text = str(address.get("postal_code") or "")
        contact = ET.SubElement(listing, f"{{{ns}}}ContactInfo")
        ET.SubElement(contact, f"{{{ns}}}Name").text = organization.display_name
        ET.SubElement(contact, f"{{{ns}}}Email").text = organization.contact_email or "contato@imob.local"
        if organization.contact_phone:
            ET.SubElement(contact, f"{{{ns}}}Telephone").text = organization.contact_phone
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml, media_type="application/xml; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})
