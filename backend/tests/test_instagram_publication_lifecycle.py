from app.domains.portfolio.instagram_publication import inactivate_instagram_publication
from app.domains.portfolio.models import Property


def _property(state: dict) -> Property:
    return Property(
        organization_id=None,
        property_type="apartment",
        purpose="rent",
        status="available",
        address={},
        instagram_publication=state,
    )


def test_instagram_draft_is_inactivated_with_property():
    item = _property({"status": "ready", "caption": "Teste", "photo_ids": ["1"]})

    changed = inactivate_instagram_publication(item, reason="Imóvel inativo.")

    assert changed is True
    assert item.instagram_publication["status"] == "inactive"
    assert item.instagram_publication["inactivation_reason"] == "Imóvel inativo."
    assert item.instagram_publication["external_removal_pending"] is False


def test_published_instagram_media_marks_external_removal_pending():
    item = _property({"status": "published", "media_id": "IG-123", "caption": "Teste"})

    changed = inactivate_instagram_publication(item, reason="Imóvel locado.")

    assert changed is True
    assert item.instagram_publication["status"] == "inactive"
    assert item.instagram_publication["external_removal_pending"] is True
