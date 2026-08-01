"""Invalidating dependent work when a claim or readiness version changes (T-056; §14.4, §8.4).

§14.4: "A new status or claim version triggers an invalidation job for dependent pending drafts
and approvals." This is the **push** side of claim currency. `T-055` is the pull side — it fails a
revision whose claim has lapsed at the moment someone validates it — and both are needed, because
a revision sitting in `review_pending` is not being validated. It is waiting on a person, who
would otherwise open a message approved against wording that has since been withdrawn.

**It lives here, not in `products_and_claims`.** The ledger's file line said otherwise, but
`drafts_and_approvals` already imports `products_and_claims`, so putting it there would make the
import graph cyclic and `test_no_import_cycles` says so. What invalidation *changes* is revisions
and approvals, which this module owns; what triggers it is a claim, which it may read.

What it touches, and what it deliberately does not:

* **`review_pending` and `approved` revisions become `invalidated`**, and their approvals are
  revoked (or expired, from `pending`) naming the triggering version. These are the states where
  a human is about to act or has acted.
* **`draft` revisions are left alone.** §8.2 has no `draft → invalidated` edge (`T-010`), and it
  does not need one: a draft citing a lapsed claim cannot pass `T-055`'s validation, so it can
  never reach a reviewer. Recorded as `R-005` rather than resolved by widening the lifecycle
  table to satisfy a different section — that is the drift ADR-015 exists to prevent.
* **An already-sent message is never altered (criterion 3).** Whether a revision was dispatched
  is a fact `outreach_and_replies` owns, and §18.2 forbids importing it from here, so the caller
  injects an `AlreadySentCheck` — the same shape `T-035c` uses to get the §11.4 rechecks into the
  dispatcher. With no check supplied nothing is considered sent, which is correct in shadow mode
  where nothing sends at all, and the worker wires the real one when that changes.

**Idempotent by construction.** Every query filters on current state, so a second run finds
nothing to change and writes no second audit event. That is what makes the job safe to retry
(§17.1), and why the report counts what *this* run changed rather than what is affected in total.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor, record_audit_event
from app.core.lifecycles import ApprovalState, MessageRevisionState
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.approval import Approval, expire, revoke
from app.drafts_and_approvals.models import MessageRevision
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.registry import registry as default_registry
from app.jobs_and_outbox.retry import RetryPolicy
from app.products_and_claims.claim_models import ApprovedClaim
from app.products_and_claims.models import ProductStatusVersion

ENTITY_TYPE: Final = "message_revision"

#: The job type name. Registered at import time, like every other domain handler.
INVALIDATION_JOB_TYPE: Final = "claims.invalidate_by_version"

#: Revision states an invalidation may move. `draft` is absent because §8.2 has no edge from it
#: (see the module docstring and `R-005`); the terminal states are absent because they are done.
INVALIDATABLE_REVISION_STATES: Final = frozenset(
    {MessageRevisionState.REVIEW_PENDING, MessageRevisionState.APPROVED}
)

#: Whether a revision's message has already been dispatched. Supplied by the caller because
#: `drafts_and_approvals` may not import `outreach_and_replies` (§18.2).
AlreadySentCheck = Callable[[Session, uuid.UUID], bool]


@dataclass(frozen=True, slots=True)
class InvalidationReport:
    """What one run changed. Empty on a re-run, which is how idempotence shows up."""

    trigger_kind: str
    trigger_id: uuid.UUID
    invalidated_revisions: list[uuid.UUID] = field(default_factory=list)
    revoked_approvals: list[uuid.UUID] = field(default_factory=list)
    expired_approvals: list[uuid.UUID] = field(default_factory=list)
    #: Revisions left untouched because their message was already delivered (criterion 3).
    skipped_already_sent: list[uuid.UUID] = field(default_factory=list)

    @property
    def changed_anything(self) -> bool:
        return bool(self.invalidated_revisions or self.revoked_approvals or self.expired_approvals)


class InvalidationPayload(BaseModel):
    """The job payload: which version changed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: `"claim"` or `"product_status"`. A string rather than an enum because the payload is stored
    #: as JSON and read back by a worker that may be running older code.
    trigger_kind: str
    trigger_id: uuid.UUID


def revisions_citing_claim(session: Session, claim_id: uuid.UUID) -> list[MessageRevision]:
    """Revisions in an invalidatable state whose citation list contains this claim.

    Filtered in Python rather than with an array-containment operator: the set is bounded by
    "revisions currently awaiting or holding approval", which §19.6's five-sends-a-day pilot keeps
    small, and a portable query is worth more here than an index.
    """
    awaiting = (
        session.execute(
            select(MessageRevision).where(MessageRevision.state.in_(INVALIDATABLE_REVISION_STATES))
        )
        .scalars()
        .all()
    )
    return [revision for revision in awaiting if claim_id in (revision.approved_claim_ids or [])]


def _retire_approvals(
    session: Session,
    revision: MessageRevision,
    *,
    reason: str,
    actor: Actor,
    moment: datetime,
    report: InvalidationReport,
    correlation_id: str | None,
) -> None:
    """Revoke or expire every approval bound to this revision.

    §8.2 allows `approved → revoked` but not `pending → revoked`, so a pending approval is
    expired instead — the edge that exists, and the same outcome for a reviewer: it is no longer
    actionable.
    """
    for approval in (
        session.execute(select(Approval).where(Approval.message_revision_id == revision.id))
        .scalars()
        .all()
    ):
        if approval.state is ApprovalState.APPROVED:
            revoke(
                session,
                approval,
                actor=actor,
                reason=reason,
                now=moment,
                correlation_id=correlation_id,
            )
            report.revoked_approvals.append(approval.id)
        elif approval.state is ApprovalState.PENDING:
            expire(session, approval, actor=actor, now=moment, correlation_id=correlation_id)
            report.expired_approvals.append(approval.id)


def invalidate_for_claim(
    session: Session,
    claim: ApprovedClaim,
    *,
    actor: Actor,
    already_sent: AlreadySentCheck | None = None,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> InvalidationReport:
    """Invalidate everything pending that depends on ``claim``. Adds without committing."""
    moment = at or datetime.now(UTC)
    report = InvalidationReport(trigger_kind="claim", trigger_id=claim.id)
    reason = (
        f"approved claim {claim.claim_key} v{claim.version} was superseded or withdrawn (§14.4); "
        f"a new revision must be drafted from the current claim set"
    )

    for revision in revisions_citing_claim(session, claim.id):
        if already_sent is not None and already_sent(session, revision.id):
            # Delivered. Rewriting the record now would be a lie about what was sent; the audit
            # event below is the flag a reviewer sees instead.
            record_audit_event(
                session,
                actor=actor,
                action="message_revision.claim_withdrawn_after_send",
                entity_type=ENTITY_TYPE,
                entity_id=revision.id,
                payload={
                    "claim_key": claim.claim_key,
                    "claim_version": str(claim.version),
                    "note": "already delivered; flagged, not altered",
                },
                correlation_id=correlation_id,
            )
            report.skipped_already_sent.append(revision.id)
            continue

        _retire_approvals(
            session,
            revision,
            reason=reason,
            actor=actor,
            moment=moment,
            report=report,
            correlation_id=correlation_id,
        )
        revisions.transition(
            session,
            revision,
            MessageRevisionState.INVALIDATED,
            actor=actor,
            reason=reason,
            correlation_id=correlation_id,
        )
        report.invalidated_revisions.append(revision.id)

    record_audit_event(
        session,
        actor=actor,
        action="approved_claim.invalidation_run",
        entity_type="approved_claim",
        entity_id=claim.id,
        payload={
            "claim_key": claim.claim_key,
            "claim_version": str(claim.version),
            "invalidated_revisions": len(report.invalidated_revisions),
            "revoked_approvals": len(report.revoked_approvals),
            "expired_approvals": len(report.expired_approvals),
            "skipped_already_sent": len(report.skipped_already_sent),
        },
        correlation_id=correlation_id,
    )
    session.flush()
    return report


def invalidate_for_product_status(
    session: Session,
    status: ProductStatusVersion,
    *,
    actor: Actor,
    already_sent: AlreadySentCheck | None = None,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> InvalidationReport:
    """Invalidate pending work depending on any claim for the product whose readiness changed.

    Readiness is what a claim presumes (§14.4), so a readiness change reaches revisions *through*
    that product's claims rather than directly — one rule about what invalidates a revision
    instead of two that could disagree.
    """
    moment = at or datetime.now(UTC)
    report = InvalidationReport(trigger_kind="product_status", trigger_id=status.id)

    for claim in (
        session.execute(select(ApprovedClaim).where(ApprovedClaim.product_id == status.product_id))
        .scalars()
        .all()
    ):
        one = invalidate_for_claim(
            session,
            claim,
            actor=actor,
            already_sent=already_sent,
            at=moment,
            correlation_id=correlation_id,
        )
        report.invalidated_revisions.extend(one.invalidated_revisions)
        report.revoked_approvals.extend(one.revoked_approvals)
        report.expired_approvals.extend(one.expired_approvals)
        report.skipped_already_sent.extend(one.skipped_already_sent)

    record_audit_event(
        session,
        actor=actor,
        action="product_status_version.invalidation_run",
        entity_type="product_status_version",
        entity_id=status.id,
        payload={
            "product_id": str(status.product_id),
            "readiness": status.readiness_category.value,
            "invalidated_revisions": len(report.invalidated_revisions),
            "revoked_approvals": len(report.revoked_approvals),
        },
        correlation_id=correlation_id,
    )
    session.flush()
    return report


#: The actor an unattended invalidation records. A system act, and it says so: §17.5 wants every
#: event attributable, and pretending a person withdrew an approval would be worse than useless.
JOB_ACTOR: Final = Actor(type=ActorType.SYSTEM, id="invalidation-job")


def handle_invalidation(session: Session, payload: BaseModel, *, job_id: object) -> None:
    """Job handler. Resolves the trigger and runs the matching invalidation.

    No `already_sent` check is passed: the worker composes that when a send path exists, the same
    way it composes the §11.4 precondition check today.
    """
    if not isinstance(payload, InvalidationPayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected InvalidationPayload, got {type(payload).__name__}")

    if payload.trigger_kind == "claim":
        claim = session.get(ApprovedClaim, payload.trigger_id)
        if claim is None:
            raise ValueError(f"no approved claim {payload.trigger_id}")
        invalidate_for_claim(session, claim, actor=JOB_ACTOR)
        return

    if payload.trigger_kind == "product_status":
        status = session.get(ProductStatusVersion, payload.trigger_id)
        if status is None:
            raise ValueError(f"no product status version {payload.trigger_id}")
        invalidate_for_product_status(session, status, actor=JOB_ACTOR)
        return

    raise ValueError(f"unknown trigger kind {payload.trigger_kind!r}")


def register(registry: JobRegistry | None = None) -> None:
    """Register the invalidation job type.

    Not consequential in §17.6's sense: it produces no external effect, and a pause must not stop
    the system from *withdrawing* work. Pausing is how an operator stops things going out, and
    invalidation is on the same side as the pause.
    """
    target = registry or default_registry
    if target.is_registered(INVALIDATION_JOB_TYPE):
        return
    target.register(
        INVALIDATION_JOB_TYPE,
        InvalidationPayload,
        handle_invalidation,
        # Retried a few times with a short backoff: the work is idempotent, so a
        # transient database error costs nothing to repeat.
        retry_policy=RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=10)),
        consequential=False,
    )
