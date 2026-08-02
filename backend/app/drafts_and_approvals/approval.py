"""Approvals (specification §8.4, §11.3, §11.4, §8.2, ADR-008).

An approval is a human saying "send *this* message to *this* person, given what the product and
claims say right now". All four parts are pinned, and if any of them moves the approval is no
longer valid — §8.4: "a changed recipient, subject, body, material personalization fact, product
status, or claim version invalidates the approval."

Those six triggers are covered by exactly three pinned values:

* the revision's **content hash** — which already covers recipient, subject, body, and the
  evidence IDs behind every personalization fact (`T-020`);
* the effective **product status version** at approval time;
* the **approved claim set** at approval time.

Nothing here sends anything. Approval records a decision; `T-035` performs the §11.4 dispatch
rechecks against the same pinned values before any external effect.

**Scope note.** This models message approval only. `message_revision_id` is NOT NULL, so an
approval always names one exact immutable revision. Candidate approval is already a candidate
lifecycle transition with its own audit event (`T-018`), so a polymorphic entity pointer here
would be unused weight.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.audit_and_operations.service import Actor, record_audit_event
from app.campaigns.candidate import CampaignCandidate
from app.core.lifecycles import ApprovalState, CampaignCandidateState, assert_transition
from app.db.base import Base, TimestampMixin
from app.drafts_and_approvals.models import MessageDraft, MessageRevision
from app.drafts_and_approvals.revisions import RETIRED_STATES

ENTITY_TYPE = "approval"

#: How long an approval stays good for. Conservative because `Q-020` has not set review or
#: stop thresholds: a stale approval is a message somebody agreed to days ago, under product and
#: claim facts that may since have moved.
DEFAULT_APPROVAL_TTL = timedelta(hours=72)

#: States in which an approval is finished and can never come back (§8.2, §11.4).
TERMINAL_STATES = frozenset({ApprovalState.REJECTED, ApprovalState.EXPIRED, ApprovalState.REVOKED})


class ApprovalError(Exception):
    """An approval rule was violated."""


class ApprovalNotValid(ApprovalError):
    """The approval no longer authorizes anything.

    Raised rather than returning a boolean wherever an external effect is about to happen: a
    caller that forgets to check a return value must not be able to send.
    """


class RevocationNeedsReason(ApprovalError):
    """A revocation arrived with no reason, or with only whitespace (`T-137`, §17.6).

    Enforced at the function rather than only in the HTTP schema. §17.6 lists revoking an approval
    among the operational controls, and an operational action nobody can explain later is one a
    reviewer cannot tell apart from a fault. The endpoint already refused a blank reason, which
    left the rule true of one caller instead of true of the entity — and the worker, a fixture, or
    the next entry point is not bound by a Pydantic model.
    """


class ApprovalAlreadyClosed(ApprovalError):
    """The approval is already rejected, expired, or revoked (`T-137`, §8.2).

    A *domain* refusal rather than the lifecycle's `IllegalTransition`. Both stop the write, but
    an operator double-clicking Revoke has done nothing wrong, and "this approval is already
    revoked" is the answer; a transition error reads as a defect and says nothing about which of
    the three terminal states it landed in. The lifecycle table stays the authority on the edge —
    this only names the case it already refuses.
    """


class Approval(Base, TimestampMixin):
    """One human decision about one exact message revision."""

    __tablename__ = "approval"
    __table_args__ = (
        CheckConstraint("length(trim(approver_id)) > 0", name="approver_id_not_blank"),
        CheckConstraint(
            "approved_content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_is_sha256_hex"
        ),
        CheckConstraint("approval_expires_at > created_at", name="expiry_after_creation"),
        # A finished approval must say why and when it finished.
        CheckConstraint(
            "(state IN ('REJECTED', 'EXPIRED', 'REVOKED')) = (closed_at IS NOT NULL)",
            name="closed_state_needs_a_timestamp",
        ),
        # At most one live approval per revision. Two would make "the" approval ambiguous at
        # dispatch time, and §11.4 rechecks "the" approval. Partial, so a rejected or revoked
        # approval does not block a fresh request for the same revision.
        Index(
            "uq_approval_live_per_revision",
            "message_revision_id",
            unique=True,
            postgresql_where=text("state IN ('PENDING', 'APPROVED')"),
        ),
        Index("ix_approval_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: NOT NULL and RESTRICT: an approval always names one exact immutable revision, and that
    #: revision cannot be deleted while an approval points at it.
    message_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message_revision.id", ondelete="RESTRICT"), nullable=False
    )
    #: Pinned separately from the revision so a dispatch recheck can compare the recipient it was
    #: approved for without re-reading the revision (§11.4).
    recipient_contact_point_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact_point.id", ondelete="RESTRICT"), nullable=False
    )

    #: Who granted this approval — a foreign key to `app_user.email` with `RESTRICT`
    #: (`T-136c`, ADR-024). The email rather than the id, so the row still says *who* without a
    #: join, and so §11.4's comparison against `send_command.record_versions["approver_id"]`
    #: stays a string on both sides rather than a UUID against JSON text.
    approver_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("app_user.email", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )

    state: Mapped[ApprovalState] = mapped_column(nullable=False, default=ApprovalState.PENDING)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_reason: Mapped[str | None] = mapped_column(Text)

    # --- the pinned world at approval time (§11.4) ------------------------------------------
    #: Covers recipient, subject, body, and evidence citations in one value (`T-020`).
    approved_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: NULL means the message made no product statement, so no product status could invalidate it.
    product_status_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_status_version.id", ondelete="RESTRICT")
    )
    #: NULL means the message cited no approved claims.
    approved_claim_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approved_claim_set.id", ondelete="RESTRICT")
    )

    revision: Mapped[MessageRevision] = relationship()

    def is_live_at(self, moment: datetime) -> bool:
        """Approved, not closed, not expired. Says nothing about the pinned world."""
        if self.state is not ApprovalState.APPROVED:
            return False
        return moment < self.approval_expires_at

    def __repr__(self) -> str:
        return f"Approval({self.state.value} for revision {self.message_revision_id})"


#: Candidate states in which a message approval must be refused (§8.2, `T-140`).
#:
#: All four are decisions that a send should *not* happen, so granting an approval on top of one
#: would contradict a recorded human or policy decision. `deferred` is included because §10.6 makes
#: it "not now" rather than "no" — approving during a deferral would silently override the deferral.
#:
#: The earlier states (`imported`, `eligible`, `research_pending`, `researched`, `review_pending`)
#: are deliberately *allowed*: a draft can legitimately exist before review concludes, and refusing
#: there would break the drafting flow rather than protect anyone.
NON_APPROVABLE_CANDIDATE_STATES = frozenset(
    {
        CampaignCandidateState.INELIGIBLE,
        CampaignCandidateState.REJECTED,
        CampaignCandidateState.DEFERRED,
        CampaignCandidateState.INVALIDATED,
    }
)


class CandidateNotApprovable(ApprovalError):
    """The candidate behind this revision has already been decided against (§8.2)."""


def candidate_for_revision(session: Session, revision: MessageRevision) -> CampaignCandidate | None:
    """The candidate a revision is ultimately about, via its draft.

    Returns `None` only if the draft or candidate is missing, which the foreign keys make
    unreachable — handled rather than asserted so a missing row cannot become a crash on the
    approval path.
    """
    draft = session.get(MessageDraft, revision.draft_id)
    if draft is None:
        return None
    return session.get(CampaignCandidate, draft.candidate_id)


def candidate_refusal(session: Session, revision: MessageRevision) -> str | None:
    """Why this revision's candidate blocks approval, or `None` if it does not.

    A **read** of candidate state, never a write to it. ADR-015 keeps the two lifecycles
    independent, and independence forbids one module *transitioning* another's entity — it does not
    forbid consulting it, which is what any cross-entity invariant requires.
    """
    candidate = candidate_for_revision(session, revision)
    if candidate is None:
        return None
    if candidate.state in NON_APPROVABLE_CANDIDATE_STATES:
        return f"the candidate is {candidate.state.value}"
    return None


def require_approvable_candidate(session: Session, revision: MessageRevision) -> None:
    """Raise unless this revision's candidate still permits a send."""
    reason = candidate_refusal(session, revision)
    if reason is not None:
        raise CandidateNotApprovable(
            f"cannot approve revision {revision.id}: {reason}. Approving would contradict a "
            f"decision already recorded against this prospect (§8.2)."
        )


def request_approval(
    session: Session,
    *,
    revision: MessageRevision,
    approver_id: str,
    actor: Actor,
    product_status_version_id: uuid.UUID | None = None,
    approved_claim_set_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
    correlation_id: str | None = None,
) -> Approval:
    """Open a pending approval pinned to the revision's current world."""
    moment = now or datetime.now(UTC)

    # §8.2: a candidate whose decision is already "no" cannot acquire an approval (T-140). Checked
    # at request time so a reviewer finds out before spending attention on the message, and again
    # at dispatch, because a candidate can be rejected after this point.
    require_approvable_candidate(session, revision)

    approval = Approval(
        message_revision_id=revision.id,
        recipient_contact_point_id=revision.recipient_contact_point_id,
        approver_id=approver_id,
        state=ApprovalState.PENDING,
        approval_expires_at=expires_at or (moment + DEFAULT_APPROVAL_TTL),
        approved_content_hash=revision.content_hash,
        product_status_version_id=product_status_version_id,
        approved_claim_set_id=approved_claim_set_id,
    )
    session.add(approval)
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="approval.requested",
        entity_type=ENTITY_TYPE,
        entity_id=approval.id,
        to_state=ApprovalState.PENDING,
        payload={
            "message_revision_id": str(revision.id),
            "content_hash": revision.content_hash,
        },
        correlation_id=correlation_id,
    )
    return approval


def _transition(
    session: Session,
    approval: Approval,
    target: ApprovalState,
    *,
    actor: Actor,
    reason: str | None,
    now: datetime | None,
    correlation_id: str | None,
) -> Approval:
    previous = approval.state
    assert_transition(previous, target)
    moment = now or datetime.now(UTC)

    approval.state = target
    if target is ApprovalState.APPROVED:
        approval.decided_at = moment
    if target in TERMINAL_STATES:
        approval.closed_at = moment
        approval.closed_reason = reason
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="approval.transitioned",
        entity_type=ENTITY_TYPE,
        entity_id=approval.id,
        from_state=previous,
        to_state=target,
        payload={"reason": reason} if reason else None,
        correlation_id=correlation_id,
    )
    return approval


def approve(
    session: Session,
    approval: Approval,
    *,
    actor: Actor,
    now: datetime | None = None,
    correlation_id: str | None = None,
) -> Approval:
    """Record the human decision to approve (§11.3 step 4)."""
    # Re-read rather than trusting the request-time check: a candidate can be rejected between
    # opening the approval and granting it, which is precisely the window a reviewer sits in.
    revision = session.get(MessageRevision, approval.message_revision_id)
    if revision is not None:
        require_approvable_candidate(session, revision)

    return _transition(
        session,
        approval,
        ApprovalState.APPROVED,
        actor=actor,
        reason=None,
        now=now,
        correlation_id=correlation_id,
    )


def reject(
    session: Session,
    approval: Approval,
    *,
    actor: Actor,
    reason: str,
    now: datetime | None = None,
    correlation_id: str | None = None,
) -> Approval:
    return _transition(
        session,
        approval,
        ApprovalState.REJECTED,
        actor=actor,
        reason=reason,
        now=now,
        correlation_id=correlation_id,
    )


def revoke(
    session: Session,
    approval: Approval,
    *,
    actor: Actor,
    reason: str,
    now: datetime | None = None,
    correlation_id: str | None = None,
) -> Approval:
    """Withdraw an approval (§17.6 operational control).

    Two refusals happen here rather than in the caller (`T-137`):

    * **A blank reason.** Checked before anything is written, so a revocation nobody can explain
      never reaches the audit trail in the first place.
    * **An already-closed approval.** `pending` is deliberately *not* covered: §8.2 offers no
      `pending -> revoked` edge either, and that is the lifecycle table's refusal to give, not
      this function's — revoking something never approved is a different mistake from revoking
      something twice, and `assert_transition` already says so precisely.
    """
    if not reason.strip():
        raise RevocationNeedsReason(
            f"cannot revoke approval {approval.id} without a reason; §17.6 operational actions "
            f"are explicable or they are indistinguishable from a fault"
        )
    if approval.state in TERMINAL_STATES:
        raise ApprovalAlreadyClosed(
            f"approval {approval.id} is already {approval.state.value}; it was closed at "
            f"{approval.closed_at.isoformat() if approval.closed_at else 'an unrecorded time'} "
            f"and cannot be revoked again (§8.2)"
        )

    return _transition(
        session,
        approval,
        ApprovalState.REVOKED,
        actor=actor,
        reason=reason,
        now=now,
        correlation_id=correlation_id,
    )


def expire(
    session: Session,
    approval: Approval,
    *,
    actor: Actor,
    now: datetime | None = None,
    correlation_id: str | None = None,
) -> Approval:
    return _transition(
        session,
        approval,
        ApprovalState.EXPIRED,
        actor=actor,
        reason="approval window elapsed",
        now=now,
        correlation_id=correlation_id,
    )


class InvalidationTrigger(StrEnum):
    """Which §8.4 condition stopped an approval authorizing a send.

    §8.4 lists six changes that invalidate an approval — recipient, subject, body, material
    personalization fact, product status, and claim version — plus the two lifecycle facts that
    also stop one being usable: the approval's own state, and its expiry. The three pinned values
    on the row cover all six of the §8.4 six, which is why there are fewer members here than that
    list has entries: the content hash covers recipient, subject, body, and personalization
    together, because any of them changing changes the hash.
    """

    NOT_APPROVED = "not_approved"
    EXPIRED = "expired"
    REVISION_MISSING = "revision_missing"
    REVISION_RETIRED = "revision_retired"
    CONTENT_CHANGED = "content_changed"
    RECIPIENT_CHANGED = "recipient_changed"
    PRODUCT_STATUS_SUPERSEDED = "product_status_superseded"
    CLAIM_SET_SUPERSEDED = "claim_set_superseded"

    #: Not one of §8.4's six changes, but the reason none of them can be evaluated (`T-193b`).
    #: An approval missing either pin cannot be shown to be current, and §11.4 requires the
    #: dispatch transaction to recheck "product-status and approved-claim versions". This used to
    #: read as valid; it now refuses, because the alternative is authorizing a send whose currency
    #: nobody can establish.
    CURRENCY_UNVERIFIABLE = "currency_unverifiable"


@dataclass(frozen=True, slots=True)
class Invalidation:
    """Why an approval no longer authorizes a send, and what made it so.

    **The identifier is the point.** `invalidation_reason` answered in prose — "approved claim set
    has been superseded" — which tells a reviewer the category of problem and nothing they can act
    on. §7.5 asks the application to *flag* stale approvals, and a flag nobody can trace back to a
    version is a flag that starts an investigation rather than ending one. `triggering_id` is the
    row that changed: the claim set that was superseded, the product status version that stopped
    being effective, the revision whose content moved.

    `triggering_id` is `None` only where the trigger genuinely names no other row — an approval
    that expired, or one whose own state is not `approved`. Those two are facts about the approval
    itself, and `reason` already carries the timestamp or the state.
    """

    trigger: InvalidationTrigger
    reason: str
    #: The record whose change caused this. `None` for triggers that name no other row.
    triggering_id: uuid.UUID | None = None


def invalidation_detail(
    session: Session,
    approval: Approval,
    *,
    now: datetime | None = None,
) -> Invalidation | None:
    """Why this approval no longer authorizes a send, or ``None`` if it still does.

    Checks every §8.4 trigger. `invalidation_reason` is this function's prose form and is kept so
    no existing caller changes — the dispatch path (§11.4) wants a sentence to raise with, and the
    dashboard wants an identifier to link to.
    """
    moment = now or datetime.now(UTC)

    if approval.state is not ApprovalState.APPROVED:
        return Invalidation(
            trigger=InvalidationTrigger.NOT_APPROVED,
            reason=f"approval is {approval.state.value}, not approved",
        )
    if moment >= approval.approval_expires_at:
        return Invalidation(
            trigger=InvalidationTrigger.EXPIRED,
            reason=f"approval expired at {approval.approval_expires_at.isoformat()}",
        )

    revision = session.get(MessageRevision, approval.message_revision_id)
    if revision is None:
        return Invalidation(
            trigger=InvalidationTrigger.REVISION_MISSING,
            reason="the approved revision no longer exists",
            triggering_id=approval.message_revision_id,
        )
    if revision.state in RETIRED_STATES:
        return Invalidation(
            trigger=InvalidationTrigger.REVISION_RETIRED,
            reason=f"the approved revision is {revision.state.value}",
            triggering_id=revision.id,
        )
    if revision.content_hash != approval.approved_content_hash:
        return Invalidation(
            trigger=InvalidationTrigger.CONTENT_CHANGED,
            reason="message content changed since approval",
            triggering_id=revision.id,
        )
    if revision.recipient_contact_point_id != approval.recipient_contact_point_id:
        return Invalidation(
            trigger=InvalidationTrigger.RECIPIENT_CHANGED,
            reason="recipient changed since approval",
            triggering_id=revision.recipient_contact_point_id,
        )

    # Bound to locals so the two checks below read as unconditional, which is the point: they
    # used to be wrapped in `if ... is not None`, and a null pin therefore **skipped** them and
    # left the approval reading as valid (`T-193b`). §11.4 says every external action *contains*
    # `product_status_version` and `approved_claim_set_version`, and lists "product-status and
    # approved-claim versions" among the dispatch rechecks — a recheck that cannot run is not a
    # recheck, so the absence has to be the refusal rather than a reason to stop looking.
    status_version_id = approval.product_status_version_id
    claim_set_id = approval.approved_claim_set_id
    if status_version_id is None or claim_set_id is None:
        return Invalidation(
            trigger=InvalidationTrigger.CURRENCY_UNVERIFIABLE,
            reason=(
                "the approval does not record which product status version and approved claim "
                "set it was granted against, so §8.4's currency checks cannot be run against it"
            ),
        )

    from app.products_and_claims.models import ProductStatusVersion

    pinned = session.get(ProductStatusVersion, status_version_id)
    if pinned is None or not pinned.is_effective_at(moment):
        return Invalidation(
            trigger=InvalidationTrigger.PRODUCT_STATUS_SUPERSEDED,
            reason="product status version is no longer effective",
            triggering_id=status_version_id,
        )

    from app.products_and_claims.claim_models import ApprovedClaimSet

    claim_set = session.get(ApprovedClaimSet, claim_set_id)
    if claim_set is None or claim_set.superseded_at is not None:
        return Invalidation(
            trigger=InvalidationTrigger.CLAIM_SET_SUPERSEDED,
            reason="approved claim set has been superseded",
            triggering_id=claim_set_id,
        )

    return None


def invalidation_reason(
    session: Session,
    approval: Approval,
    *,
    now: datetime | None = None,
) -> str | None:
    """The prose form of :func:`invalidation_detail`, or ``None``.

    Kept as the shape the dispatch path already raises with (§11.4). Deriving it rather than
    duplicating the checks is the point: two implementations of "is this approval still good"
    would eventually disagree, and the one that drifts is the one fewer callers exercise.
    """
    detail = invalidation_detail(session, approval, now=now)
    return detail.reason if detail is not None else None


def approvals_needing_attention(
    session: Session,
    *,
    campaign_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[tuple[Approval, Invalidation]]:
    """Every approval that no longer authorizes a send, with why (§7.5).

    Scans approvals in `approved` only. An already-revoked or rejected approval is not an
    *attention item* — somebody has dealt with it — and listing them would bury the ones nobody
    has looked at. The expiry case is included, which is why the scan cannot be a state filter
    alone: an approval sitting in `approved` past its expiry is exactly the stale one §7.5 asks
    the application to flag.
    """
    moment = now or datetime.now(UTC)
    query = select(Approval).where(Approval.state == ApprovalState.APPROVED)
    if campaign_id is not None:
        query = (
            query.join(MessageRevision, MessageRevision.id == Approval.message_revision_id)
            .join(MessageDraft, MessageDraft.id == MessageRevision.draft_id)
            .join(CampaignCandidate, CampaignCandidate.id == MessageDraft.candidate_id)
            .where(CampaignCandidate.campaign_id == campaign_id)
        )

    found: list[tuple[Approval, Invalidation]] = []
    for approval in session.execute(query.order_by(Approval.created_at.asc())).scalars().all():
        detail = invalidation_detail(session, approval, now=moment)
        if detail is not None:
            found.append((approval, detail))
    return found


def is_valid(session: Session, approval: Approval, *, now: datetime | None = None) -> bool:
    return invalidation_reason(session, approval, now=now) is None


def require_valid(session: Session, approval: Approval, *, now: datetime | None = None) -> None:
    """Raise unless the approval still authorizes exactly what it authorized.

    The form the dispatch transaction calls (§11.4). Raising rather than returning a boolean so a
    caller cannot send by forgetting to look at the result.
    """
    reason = invalidation_reason(session, approval, now=now)
    if reason is not None:
        raise ApprovalNotValid(f"approval {approval.id} does not authorize a send: {reason} (§8.4)")


def live_approval(session: Session, message_revision_id: uuid.UUID) -> Approval | None:
    """The approval for a revision that is still pending or approved, if any."""
    return session.execute(
        select(Approval)
        .where(
            Approval.message_revision_id == message_revision_id,
            Approval.state.not_in(TERMINAL_STATES),
        )
        .order_by(Approval.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
