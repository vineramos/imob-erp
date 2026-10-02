from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.portfolio import _capture_response, _ensure_owner_role, _property_response, _request_metadata
from app.core.database import get_db
from app.domains.foundation.access import UserContext, require_permission
from app.domains.foundation.audit import write_audit
from app.domains.foundation.models import AppUser
from app.domains.portfolio.capture_workflow_schemas import CaptureConversionResponse, CaptureWorkflowRequest
from app.domains.portfolio.models import Capture, Person, Property, PropertyOwner
from app.domains.portfolio.schemas import CaptureResponse


router = APIRouter(tags=["captures"])
_ACTIVE_STAGES = ("new", "negotiation", "documents", "inspection", "approved")


def _load_capture(db: Session, organization_id: UUID, capture_id: UUID) -> Capture:
    item = db.scalar(
        select(Capture)
        .options(selectinload(Capture.contact_person), selectinload(Capture.converted_property))
        .where(Capture.id == capture_id, Capture.organization_id == organization_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Captação não encontrada.")
    return item


def _responsible(db: Session, organization_id: UUID, user_id: UUID | None) -> AppUser | None:
    if user_id is None:
        return None
    user = db.scalar(
        select(AppUser).where(
            AppUser.id == user_id,
            AppUser.organization_id == organization_id,
            AppUser.is_active.is_(True),
            AppUser.blocked_at.is_(None),
        )
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Responsável inválido ou inativo.")
    return user


def _write_capture_audit(
    db: Session,
    *,
    request: Request,
    context: UserContext,
    item: Capture,
    action: str,
    before: dict,
    after: dict,
    reason: str | None = None,
) -> None:
    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action=action,
        module="captures",
        entity_type="capture",
        entity_id=str(item.id),
        before_data=before,
        after_data=after,
        reason=(reason or "").strip() or None,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.get("/captures/responsibles")
def list_capture_responsibles(
    context: UserContext = Depends(require_permission("captures.manage")),
    db: Session = Depends(get_db),
) -> list[dict]:
    users = db.scalars(
        select(AppUser).where(
            AppUser.organization_id == context.user.organization_id,
            AppUser.is_active.is_(True),
            AppUser.blocked_at.is_(None),
        ).order_by(AppUser.name.asc(), AppUser.email.asc())
    ).all()
    return [{"id": str(user.id), "name": user.name} for user in users]


@router.post("/captures/{capture_id}/workflow", response_model=CaptureResponse)
def update_capture_workflow(
    capture_id: UUID,
    payload: CaptureWorkflowRequest,
    request: Request,
    context: UserContext = Depends(require_permission("captures.manage")),
    db: Session = Depends(get_db),
) -> CaptureResponse:
    item = _load_capture(db, context.user.organization_id, capture_id)
    before = {
        "status": item.status,
        "responsible_user_id": str(item.responsible_user_id) if item.responsible_user_id else None,
        "lost_reason": item.lost_reason,
        "converted_property_id": str(item.converted_property_id) if item.converted_property_id else None,
    }

    if payload.action == "assign":
        responsible = _responsible(db, context.user.organization_id, payload.responsible_user_id)
        item.responsible_user_id = responsible.id if responsible else None
        action = "captures.responsible_updated"
        audit_reason = payload.reason
    else:
        if item.converted_property_id is not None or item.status == "available":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A captação já foi convertida em imóvel e não possui mais etapa comercial editável.")

        if payload.action == "advance":
            if item.status not in _ACTIVE_STAGES:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta captação não pode avançar a partir da etapa atual.")
            index = _ACTIVE_STAGES.index(item.status)
            if index == len(_ACTIVE_STAGES) - 1:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A captação já está aprovada. Converta-a em imóvel para concluir a entrada da carteira.")
            item.status = _ACTIVE_STAGES[index + 1]
            item.lost_reason = None
            action = "captures.stage_advanced"
            audit_reason = payload.reason
        elif payload.action == "back":
            if item.status not in _ACTIVE_STAGES or item.status == _ACTIVE_STAGES[0]:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta captação não possui uma etapa anterior disponível.")
            index = _ACTIVE_STAGES.index(item.status)
            item.status = _ACTIVE_STAGES[index - 1]
            item.lost_reason = None
            action = "captures.stage_returned"
            audit_reason = payload.reason
        elif payload.action == "lose":
            if item.status not in _ACTIVE_STAGES:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Somente captações em andamento podem ser marcadas como perdidas.")
            lost_reason = (payload.lost_reason or "").strip()
            if not lost_reason:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe o motivo da perda da captação.")
            item.status = "lost"
            item.lost_reason = lost_reason
            action = "captures.lost"
            audit_reason = lost_reason
        elif payload.action == "reopen":
            if item.status != "lost":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Somente uma captação perdida pode ser reaberta.")
            reason = (payload.reason or "").strip()
            if not reason:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe o motivo da reabertura da captação.")
            item.status = "negotiation"
            item.lost_reason = None
            action = "captures.reopened"
            audit_reason = reason
        else:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ação de captação inválida.")

    after = {
        "status": item.status,
        "responsible_user_id": str(item.responsible_user_id) if item.responsible_user_id else None,
        "lost_reason": item.lost_reason,
        "converted_property_id": str(item.converted_property_id) if item.converted_property_id else None,
    }
    _write_capture_audit(
        db,
        request=request,
        context=context,
        item=item,
        action=action,
        before=before,
        after=after,
        reason=audit_reason,
    )
    db.commit()
    item = _load_capture(db, context.user.organization_id, capture_id)
    return _capture_response(item)


@router.post("/captures/{capture_id}/convert", response_model=CaptureConversionResponse)
def convert_capture_to_property(
    capture_id: UUID,
    request: Request,
    context: UserContext = Depends(require_permission("captures.manage")),
    db: Session = Depends(get_db),
) -> CaptureConversionResponse:
    if "properties.create" not in context.permission_keys:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não possui permissão para criar o imóvel definitivo desta captação.")

    item = _load_capture(db, context.user.organization_id, capture_id)
    if item.converted_property_id is not None or item.status == "available":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta captação já foi convertida em imóvel.")
    if item.status != "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A captação precisa estar aprovada antes de ser convertida em imóvel.")
    if item.contact_person_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Vincule o proprietário antes de converter a captação.")
    if not item.property_type:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe o tipo do imóvel antes da conversão.")
    address = dict(item.property_address or {})
    if not str(address.get("street") or "").strip() or not str(address.get("city") or "").strip() or not str(address.get("state") or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe ao menos rua, cidade e UF antes da conversão.")

    owner = db.scalar(
        select(Person)
        .options(selectinload(Person.roles))
        .where(
            Person.id == item.contact_person_id,
            Person.organization_id == context.user.organization_id,
            Person.is_active.is_(True),
        )
    )
    if owner is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O proprietário vinculado não está mais disponível para a conversão.")

    property_item = Property(
        organization_id=context.user.organization_id,
        property_type=item.property_type,
        purpose="rent",
        status="available",
        address=address,
        rent_amount=item.estimated_rent,
        condo_amount=None,
        iptu_amount=None,
        area_m2=None,
        bedrooms=0,
        suites=0,
        bathrooms=0,
        parking_spaces=0,
        furnished=False,
        pets_allowed=False,
        public_title=None,
        public_description=None,
        publication_enabled=False,
        created_by_user_id=context.user.id,
    )
    db.add(property_item)
    db.flush()
    _ensure_owner_role(owner)
    property_item.owners.append(PropertyOwner(person_id=owner.id, ownership_percent=100))

    before = {
        "status": item.status,
        "converted_property_id": None,
        "contact_person_id": str(item.contact_person_id),
    }
    item.converted_property_id = property_item.id
    item.status = "available"
    item.lost_reason = None

    ip_address, user_agent = _request_metadata(request)
    write_audit(
        db,
        context=context,
        action="properties.created_from_capture",
        module="properties",
        entity_type="property",
        entity_id=str(property_item.id),
        after_data={
            "code": f"{property_item.internal_number:06d}",
            "status": property_item.status,
            "property_type": property_item.property_type,
            "capture_id": str(item.id),
            "owner_id": str(owner.id),
        },
        reason="Conversão de captação aprovada para o cadastro definitivo do imóvel.",
        ip_address=ip_address,
        user_agent=user_agent,
    )
    _write_capture_audit(
        db,
        request=request,
        context=context,
        item=item,
        action="captures.converted",
        before=before,
        after={
            "status": item.status,
            "converted_property_id": str(property_item.id),
            "property_code": f"{property_item.internal_number:06d}",
        },
        reason="Captação aprovada convertida em imóvel definitivo.",
    )
    db.commit()

    item = _load_capture(db, context.user.organization_id, capture_id)
    property_item = db.scalar(
        select(Property)
        .options(selectinload(Property.owners).selectinload(PropertyOwner.person))
        .where(Property.id == item.converted_property_id, Property.organization_id == context.user.organization_id)
    )
    if property_item is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="O imóvel foi criado, mas não pôde ser recarregado.")
    return CaptureConversionResponse(capture=_capture_response(item), property=_property_response(property_item))
