"""A reviewer's structured decision about a candidate (T-066a; §10.6, §12.3 item 7, §8.2, §17.5).

§10.6 asks for structured rejection and correction reasons with optional notes, and names eleven
categories. This records them, for the two decisions that end or pause a candidate: rejection and
deferral. Approval is `campaigns.approval`, which already existed and is a different shape — it
names a recipient and queues a draft.

**The categories are a database enum, not a string column with a convention.** A convention is
enforced by whoever remembers it; §10.6's list is the vocabulary the evaluation data is written
in, and a typo in it is a row that silently belongs to no category. The enum is created by the
migration, so the constraint holds for anything that reaches the database — including a script
nobody wrote a test for.

**A rejection without a category is refused twice.** Once here, with a sentence, and once by
`decision_category` being `NOT NULL`. The near check gives the reviewer something to act on; the
far one is the guarantee, because it holds even for a caller that never went through this module.

**A deferral must say what it waits for.** §10.6's eleventh category is "defer until a specific
date/event", and a deferral with neither is a candidate nobody will ever look at again — it
leaves review and no date brings it back. `ck_candidate_decision_deferral_has_a_waypoint` refuses
that combination in the database rather than trusting every future caller to check.

**This feedback rewrites no policy, and that is a property worth stating.** §10.6 is explicit:
the feedback becomes evaluation and policy-proposal data, and does not automatically rewrite
campaign policy. Nothing in this module touches `CampaignPolicyVersion` — the *absence* is the
behaviour, so `tests/test_corrections.py` asserts it directly rather than leaving it to be
noticed. A future task that proposes policy from this data will propose it for a human to
approve; it will not apply it here.

**It lives in `campaigns` because the transition does** — ADR-015 gives the candidate lifecycle
to `campaigns`, and ADR-020 held that line. The same rule that put approval here puts rejection
and deferral here.
"""

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Final

import structlog
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, transition
from app.core.lifecycles import CampaignCandidateState
from app.db.base import Base, TimestampMixin
from app.jobs_and_outbox.queue import enqueue, in_flight_for

log = structlog.get_logger(__name__)


class DecisionCategory(StrEnum):
    """§10.6's eleven categories, in the specification's order.

    The order is kept so the list can be checked against §10.6 by reading down it. The values are
    stable identifiers: a dashboard may relabel them, but a stored row means what it meant.
    """

    WRONG_CAMPAIGN = "wrong_campaign"
    WRONG_ACCOUNT_OR_DUPLICATE = "wrong_account_or_duplicate"
    POOR_BUYER_ROLE = "poor_buyer_role"
    WEAK_OR_STALE_EVIDENCE = "weak_or_stale_evidence"
    PRODUCT_NOT_READY = "product_not_ready"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    PERSONALIZATION_NOT_USEFUL = "personalization_not_useful"
    TONE_OR_POSITIONING_PROBLEM = "tone_or_positioning_problem"
    EXISTING_RELATIONSHIP = "existing_relationship"
    COMPLIANCE_OR_SUPPRESSION_CONCERN = "compliance_or_suppression_concern"
    DEFER_UNTIL_DATE_OR_EVENT = "defer_until_date_or_event"


class DecisionKind(StrEnum):
    """Which decision was taken. Approval is `campaigns.approval` and is not one of these.

    `REQUEST_RESEARCH` records a request for more evidence (ADR-022). It is not a transition — the
    candidate stays in `review_pending` — but it is a reviewer decision with a reason, which is
    what this table is for.
    """

    REJECT = "reject"
    DEFER = "defer"
    REQUEST_RESEARCH = "request_research"


#: The only state either decision may be taken from. §8.2 offers `review_pending -> rejected` and
#: `review_pending -> deferred` and no other edge into either.
DECIDABLE_STATE: Final = CampaignCandidateState.REVIEW_PENDING


class DecisionRefused(Exception):
    """The decision was not recorded, and the candidate did not move."""


class CandidateDecision(Base, TimestampMixin):
    """One reviewer decision, kept as evaluation data (§10.6).

    Rows accumulate: a candidate deferred and later rejected has two, in order, because *when a
    reviewer changed their mind* is exactly what evaluation data is for. Nothing here is updated
    after it is written.
    """

    __tablename__ = "candidate_decision"
    __table_args__ = (
        # §10.6's eleventh category is the only one that answers "until when", and a deferral that
        # answers neither is a candidate that leaves review and never comes back.
        # `'DEFER'`, not `'defer'`: SQLAlchemy stores the enum member's *name*, which is the
        # convention every other enum column in this repository follows. A constraint written
        # against the lowercase value would compare against something no row ever holds and would
        # therefore never fire — passing every test that only checks the happy path.
        CheckConstraint(
            "kind <> 'DEFER' OR defer_until_date IS NOT NULL OR "
            "(defer_until_event IS NOT NULL AND length(trim(defer_until_event)) > 0)",
            name="deferral_has_a_waypoint",
        ),
        # A rejection cannot wait for anything, and storing a date on one would make the deferral
        # queue wrong in a way nobody would look for.
        CheckConstraint(
            "kind = 'DEFER' OR (defer_until_date IS NULL AND defer_until_event IS NULL)",
            name="only_deferrals_wait",
        ),
        CheckConstraint(
            "notes IS NULL OR length(trim(notes)) > 0",
            name="notes_not_blank",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign_candidate.id"), nullable=False, index=True
    )
    kind: Mapped[DecisionKind] = mapped_column(nullable=False)
    #: `NOT NULL` is the guarantee; the refusal in `reject_candidate` is the message.
    category: Mapped[DecisionCategory] = mapped_column(nullable=False)
    #: §10.6: "with optional notes". Optional, but never blank — a whitespace note is a note that
    #: reads as present and says nothing.
    notes: Mapped[str | None] = mapped_column(Text)
    #: One of these is required on a deferral, by check constraint. A date for "after the fiscal
    #: year"; an event for "when they publish their storage roadmap", which has no date yet.
    defer_until_date: Mapped[date | None] = mapped_column(Date)
    defer_until_event: Mapped[str | None] = mapped_column(String(500))
    #: §17.5 wants the human/service actor on every decision. Denormalized from the audit event on
    #: purpose: this table is the evaluation dataset, and a dataset that needs a join to another
    #: subsystem to say who decided is a dataset people will analyse without the actor.
    decided_by_type: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(255), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _record(
    session: Session,
    candidate: CampaignCandidate,
    *,
    kind: DecisionKind,
    category: DecisionCategory,
    notes: str | None,
    actor: Actor,
    at: datetime | None,
    defer_until_date: date | None = None,
    defer_until_event: str | None = None,
) -> CandidateDecision:
    decision = CandidateDecision(
        candidate_id=candidate.id,
        kind=kind,
        category=category,
        notes=notes.strip() if notes and notes.strip() else None,
        defer_until_date=defer_until_date,
        defer_until_event=(
            defer_until_event.strip() if defer_until_event and defer_until_event.strip() else None
        ),
        decided_by_type=actor.type.value,
        decided_by=actor.id,
        decided_at=at or datetime.now(UTC),
    )
    session.add(decision)
    session.flush()
    return decision


def reject_candidate(
    session: Session,
    candidate: CampaignCandidate,
    *,
    category: DecisionCategory,
    actor: Actor,
    notes: str | None = None,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> CandidateDecision:
    """End this candidate, with the reason it ended. Adds to ``session`` without committing.

    ``category`` has no default, and that is the point of the signature: §10.6 structures the
    reason so the feedback is analysable, and a default would make "whatever the first category
    is" the most common value in the dataset.
    """
    if candidate.state is not DECIDABLE_STATE:
        raise DecisionRefused(
            f"candidate {candidate.id} is {candidate.state.value}; §8.2 offers "
            f"`review_pending -> rejected` and no other edge into rejection"
        )
    if category is DecisionCategory.DEFER_UNTIL_DATE_OR_EVENT:
        raise DecisionRefused(
            "`defer_until_date_or_event` is a deferral, not a rejection; a candidate rejected "
            "for waiting is a candidate nobody will look at again"
        )

    decision = _record(
        session,
        candidate,
        kind=DecisionKind.REJECT,
        category=category,
        notes=notes,
        actor=actor,
        at=at,
    )
    transition(
        session,
        candidate,
        CampaignCandidateState.REJECTED,
        actor=actor,
        reason=category.value,
        policy_decision=f"candidate:rejected:{category.value}",
        correlation_id=correlation_id,
    )
    log.info(
        "candidate.rejected",
        candidate_id=str(candidate.id),
        category=category.value,
        actor_type=actor.type.value,
        # The notes are a reviewer's free text about a named prospect (§15.5 keeps content out of
        # logs). Whether they were written is useful; what they said belongs in the row.
        has_notes=decision.notes is not None,
    )
    return decision


def defer_candidate(
    session: Session,
    candidate: CampaignCandidate,
    *,
    actor: Actor,
    until_date: date | None = None,
    until_event: str | None = None,
    category: DecisionCategory = DecisionCategory.DEFER_UNTIL_DATE_OR_EVENT,
    notes: str | None = None,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> CandidateDecision:
    """Pause this candidate until a date or an event. Adds to ``session`` without committing.

    One of ``until_date`` or ``until_event`` is required. A deferral with neither leaves review
    and nothing brings it back — the database refuses it too, so the guarantee does not depend on
    every caller coming through here.

    ``category`` defaults to §10.6's eleventh, which is what a plain "not now" is. A reviewer who
    is deferring *because* the product is not ready may say so, and that is the more useful row.
    """
    if candidate.state is not DECIDABLE_STATE:
        raise DecisionRefused(
            f"candidate {candidate.id} is {candidate.state.value}; §8.2 offers "
            f"`review_pending -> deferred` and no other edge into deferral"
        )
    if until_date is None and not (until_event and until_event.strip()):
        raise DecisionRefused(
            "a deferral needs a date or an event to wait for; without one the candidate leaves "
            "review and nothing brings it back (§10.6)"
        )

    decision = _record(
        session,
        candidate,
        kind=DecisionKind.DEFER,
        category=category,
        notes=notes,
        actor=actor,
        at=at,
        defer_until_date=until_date,
        defer_until_event=until_event,
    )
    transition(
        session,
        candidate,
        CampaignCandidateState.DEFERRED,
        actor=actor,
        reason=category.value,
        policy_decision=f"candidate:deferred:{category.value}",
        correlation_id=correlation_id,
    )
    log.info(
        "candidate.deferred",
        candidate_id=str(candidate.id),
        category=category.value,
        actor_type=actor.type.value,
        waits_for="date" if until_date is not None else "event",
    )
    return decision


#: The job a request queues. A string, not an import: `research_and_evidence` imports `campaigns`,
#: so importing it back would make the package graph cyclic. `tests/test_pipeline_jobs.py` pins it
#: to `research_and_evidence.jobs.RECAPTURE_JOB_TYPE`.
RECAPTURE_JOB_TYPE: Final = "research.recapture_evidence"


def request_more_research(
    session: Session,
    candidate: CampaignCandidate,
    *,
    category: DecisionCategory,
    actor: Actor,
    notes: str | None = None,
    source_adapter: str | None = None,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> CandidateDecision:
    """Ask for more evidence about a candidate that stays in review (ADR-022).

    Records the request as a decision — who asked, and the §10.6 category that says why — and
    queues one evidence pass. Adds to ``session`` without committing, so the decision and the job
    land together (§7.2).

    **No transition happens, and that is the decision ADR-022 records.** §8.2 offers no edge from
    `review_pending` back to `research_pending`, and adding one would take the candidate out of
    the reviewer's queue while they believed they were still looking at it.

    Raises :class:`DecisionRefused` if a pass is already in flight. A reviewer who clicks twice
    wants one more pass, not two.
    """
    if candidate.state is not DECIDABLE_STATE:
        raise DecisionRefused(
            f"candidate {candidate.id} is {candidate.state.value}; more research can only be "
            f"asked for while a candidate is in review (ADR-022)"
        )

    if in_flight_for(
        session,
        job_type=RECAPTURE_JOB_TYPE,
        payload_key="candidate_id",
        payload_value=str(candidate.id),
    ):
        raise DecisionRefused(
            f"a research pass for candidate {candidate.id} is already in flight; a second request "
            f"would duplicate the work rather than deepen it"
        )

    decision = _record(
        session,
        candidate,
        kind=DecisionKind.REQUEST_RESEARCH,
        category=category,
        notes=notes,
        actor=actor,
        at=at,
    )
    payload: dict[str, object] = {"candidate_id": str(candidate.id)}
    if source_adapter is not None:
        payload["source_adapter"] = source_adapter
    enqueue(
        session,
        job_type=RECAPTURE_JOB_TYPE,
        payload=payload,
        actor=actor,
        correlation_id=correlation_id,
    )

    log.info(
        "candidate.more_research_requested",
        candidate_id=str(candidate.id),
        category=category.value,
        actor_type=actor.type.value,
    )
    return decision
