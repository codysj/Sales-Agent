"""Campaign candidates — the unit of qualification (specification §8.1, §8.2, §14.2, ADR-015).

"A lead is not an intrinsic property of a company. Qualification belongs to an account/contact's
membership in a specific campaign" (§8.1). The effective identity is therefore
``campaign_id + account_id + contact_id``, and the same person evaluated for the sodium-battery
and DC-fast-charging campaigns is **two candidates** with independent states, evidence, and
review decisions — not one record with two opinions.

State moves only through :func:`transition`, which asks ``app.core.lifecycles`` whether the move
is legal and writes an audit event recording both ends. A bare assignment to ``state`` bypasses
both; a trigger makes that impossible.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.audit_and_operations.service import Actor, record_audit_event
from app.core.lifecycles import CampaignCandidateState, assert_transition
from app.db.base import Base, TimestampMixin

#: Written into every audit event this module produces.
ENTITY_TYPE = "campaign_candidate"


class CampaignCandidate(Base, TimestampMixin):
    """One account/contact's membership in one campaign."""

    __tablename__ = "campaign_candidate"
    __table_args__ = (
        # `contact_id` is nullable — §14.2 says a candidate joins one campaign, one account, and
        # *usually* one contact. `NULLS NOT DISTINCT` (PostgreSQL 15+) is essential: with the
        # default NULL handling, two account-only candidates for the same campaign would both be
        # accepted, because NULL never equals NULL.
        UniqueConstraint(
            "campaign_id",
            "account_id",
            "contact_id",
            name="uq_campaign_candidate_identity",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_campaign_candidate_campaign_id", "campaign_id"),
        Index("ix_campaign_candidate_account_id", "account_id"),
        Index("ix_campaign_candidate_state", "state"),
        CheckConstraint(
            "state <> 'INELIGIBLE' OR ineligible_reason IS NOT NULL",
            name="ineligible_needs_a_reason",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE")
    )

    state: Mapped[CampaignCandidateState] = mapped_column(
        nullable=False, default=CampaignCandidateState.IMPORTED
    )

    #: Why the candidate was ruled out. Required whenever the state is `ineligible`, so a
    #: rejection is always explainable (§10.1). Structured failure detail arrives with T-045.
    ineligible_reason: Mapped[str | None] = mapped_column(Text)

    campaign: Mapped["object"] = relationship("Campaign", viewonly=True)

    def __repr__(self) -> str:
        return f"CampaignCandidate({self.campaign_id}/{self.account_id} {self.state.value})"


def create_candidate(
    session: Session,
    *,
    campaign_id: uuid.UUID,
    account_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    actor: Actor,
    correlation_id: str | None = None,
) -> CampaignCandidate:
    """Create a membership in the initial ``imported`` state and record it.

    Added to the caller's session without committing, so the candidate and its audit event land
    together or not at all (§17.2).
    """
    candidate = CampaignCandidate(
        campaign_id=campaign_id,
        account_id=account_id,
        contact_id=contact_id,
        state=CampaignCandidateState.IMPORTED,
    )
    session.add(candidate)
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="campaign_candidate.created",
        entity_type=ENTITY_TYPE,
        entity_id=candidate.id,
        to_state=CampaignCandidateState.IMPORTED,
        payload={"campaign_id": str(campaign_id), "account_id": str(account_id)},
        correlation_id=correlation_id,
    )
    return candidate


def transition(
    session: Session,
    candidate: CampaignCandidate,
    target: CampaignCandidateState,
    *,
    actor: Actor,
    reason: str | None = None,
    policy_decision: str | None = None,
    correlation_id: str | None = None,
) -> CampaignCandidate:
    """Move a candidate to ``target``, or raise.

    Refuses anything ``app.core.lifecycles`` does not permit — including a transition into
    another lifecycle's state — and writes an audit event carrying both ends of the move (§3.5).
    """
    previous = candidate.state
    assert_transition(previous, target)

    if target is CampaignCandidateState.INELIGIBLE:
        if not (reason and reason.strip()):
            raise ValueError(
                "a candidate cannot be marked ineligible without a reason; "
                "a rejection that cannot be explained is not reviewable (§10.1)"
            )
        candidate.ineligible_reason = reason

    candidate.state = target
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="campaign_candidate.transitioned",
        entity_type=ENTITY_TYPE,
        entity_id=candidate.id,
        from_state=previous,
        to_state=target,
        policy_decision=policy_decision,
        payload={"reason": reason} if reason else None,
        correlation_id=correlation_id,
    )
    return candidate
