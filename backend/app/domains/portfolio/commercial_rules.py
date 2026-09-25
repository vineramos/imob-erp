from sqlalchemy import event, inspect, select, update
from sqlalchemy.orm import Session

from app.domains.leases.models import LeaseContract
from app.domains.portfolio.site_models import CommercialProposal, PublicSiteInquiry

_installed = False
_ACTIVE_PROPOSAL_STATUSES = ("submitted", "accepted", "converted")


def install_commercial_lease_rule() -> None:
    """Fecha o funil comercial somente quando a locação realmente é assinada."""
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Session, "before_flush")
    def _close_competing_proposals(session: Session, flush_context, instances) -> None:  # noqa: ARG001
        signed_leases = []
        for item in session.dirty:
            if not isinstance(item, LeaseContract) or item.status != "signed":
                continue
            if inspect(item).attrs.status.history.has_changes():
                signed_leases.append(item)

        for lease in signed_leases:
            rows = session.execute(
                select(
                    CommercialProposal.id,
                    CommercialProposal.inquiry_id,
                    CommercialProposal.lease_contract_id,
                    CommercialProposal.status,
                ).where(
                    CommercialProposal.organization_id == lease.organization_id,
                    CommercialProposal.property_id == lease.property_id,
                    CommercialProposal.status.in_(_ACTIVE_PROPOSAL_STATUSES),
                )
            ).all()
            for proposal_id, inquiry_id, lease_contract_id, _ in rows:
                if lease_contract_id == lease.id:
                    session.execute(update(CommercialProposal).where(CommercialProposal.id == proposal_id).values(status="won", closed_reason=None))
                    session.execute(update(PublicSiteInquiry).where(PublicSiteInquiry.id == inquiry_id).values(status="won"))
                else:
                    session.execute(update(CommercialProposal).where(CommercialProposal.id == proposal_id).values(status="rejected", closed_reason="Imóvel locado por outra proposta."))
                    session.execute(update(PublicSiteInquiry).where(PublicSiteInquiry.id == inquiry_id).values(status="lost"))
