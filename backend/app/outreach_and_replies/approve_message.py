"""The §11.3 approval transaction, steps 2-6 (T-067a; §11.3, §11.4, §3.5, §7.2, §8.2).

§11.3 lists six steps for approving a message. Step 1 is about the *request* — identity, role,
session, CSRF, record versions, scope — and belongs to the endpoint (`T-067b`). This is everything
after it, and it is one function because steps 4 and 5 say "in one database transaction":

2. **Confirm the recipient and the immutable `message_revision_id`.** Both are arguments. ADR-008
   approves an exact recipient and an exact revision *together*, so neither is derived here — a
   recipient this function chose is a recipient nobody approved.
3. **Recheck.** Campaign, product status, approved claims, suppression, sender, and limits, at
   approval time rather than at review time. A reviewer read the card at some moment; the claim
   they relied on may have been superseded since, and `T-056` invalidates approvals for exactly
   that reason. Rechecking here closes the window between reading and approving.
4. **One transaction: the approval record and the immutable send command.**
5. **The outbox event**, in the same transaction — that is what "transactional outbox" means, and
   it is why nothing here commits: the caller owns the transaction boundary (§7.2), so a failure
   anywhere leaves the approval, the command, and the event all absent rather than some of them.
6. **Dispatch is the worker's**, not this function's. `T-035` owns it and rechecks everything again
   at dispatch time (§11.4), because more time passes.

**Shadow mode is not checked here, and that is deliberate.** This function writes rows; it causes
no external effect at all. Shadow mode is enforced where the effect would happen — in the adapter
(`outreach_and_replies.adapters`) — and a second check here would be a second place to get it
wrong, plus an invitation to believe *this* is what makes approval safe. What makes it safe is
that nothing in this path can send. `tests/test_approval_transaction.py` proves the outbox event
is still written under shadow mode, because suppressing the record would lose the audit trail for
a decision a human really made.

**It lives in `outreach_and_replies`, and the import graph decided that rather than taste.**
The transaction spans two modules: it grants an approval (`drafts_and_approvals`) and orders a
send (`outreach_and_replies`). Only one direction is available — `outreach_and_replies` already
imports `drafts_and_approvals`, in `commands` and `preconditions`, and
`tests/test_module_boundaries.py::test_no_import_cycles` refuses the reverse. Which is the right
way round anyway: what this produces is a **send order**, and the approval is its authorization.

**No agent callback exists in this path, and the test for that is structural.** §11.3 ends "no
agent callback is required", and §3.5 forbids external execution authority held only by the agent
runtime. The proof is an import walk over this module's transitive dependencies rather than a
reading of it: a callback added three modules down would satisfy any test that only read this file.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate
from app.campaigns.models import Campaign
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.approval import (
    Approval,
    approve,
    candidate_for_revision,
    request_approval,
)
from app.drafts_and_approvals.models import MessageRevision
from app.drafts_and_approvals.revisions import RevisionNotApprovable
from app.drafts_and_approvals.validation import validate_revision
from app.jobs_and_outbox.outbox import enqueue_outbox_event
from app.outreach_and_replies.commands import create_send_command
from app.outreach_and_replies.models import OutreachThread, SendCommand
from app.prospects.models import ContactPoint

log = structlog.get_logger(__name__)

#: The outbox event a completed approval publishes. The worker's dispatch reads it (step 6).
OUTBOX_EVENT_TYPE: Final = "outreach.send_command_ready"


class ApprovalTransactionRefused(Exception):
    """The approval was not granted, and nothing was written."""


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    """What one approval transaction produced. All three, or the exception and none of them."""

    approval: Approval
    send_command: SendCommand
    outbox_event_id: uuid.UUID
    thread: OutreachThread


def _recheck(
    session: Session,
    revision: MessageRevision,
    recipient: ContactPoint,
    candidate: CampaignCandidate,
    *,
    actor: Actor,
    moment: datetime,
    correlation_id: str | None,
) -> None:
    """§11.3 step 3, run at approval time rather than trusted from review time.

    Read-only, deliberately: `validate_revision` rather than `apply_validation`. A recheck that
    moved the revision would be a check with a side effect, and from `review_pending` the failing
    transition does not exist at all — so the applying form would raise rather than refuse.

    Delegated to `T-055`'s validation rather than reimplemented: it already checks claim citations,
    claim currency, campaign scope, product readiness, evidence citations, recipient contactability,
    suppression, product-statement grounding, and compliance elements — which is §11.3 step 3's list
    plus the grounding checks. A second implementation here would be a second set of rules to
    disagree with the first, and the one that drifts is always the copy nobody runs.
    """
    # `validate_revision`, not `apply_validation`: a recheck must not *move* the revision. The
    # applying form transitions to `review_pending` or `validation_failed`, and from
    # `review_pending` the failing edge does not exist — so the recheck would have raised
    # `IllegalTransition` instead of refusing, turning a safety check into a crash.
    result = validate_revision(session, revision, at=moment)
    if not result.is_valid:
        raise ApprovalTransactionRefused(
            f"revision {revision.id} no longer passes validation: "
            f"{[failure.check.value for failure in result.failures]}. What was true when the "
            f"reviewer read the card is not what is true now (§11.3 step 3)."
        )

    # §11.3 step 3 says "recheck current campaign", and `T-055` does not: validation asks whether
    # the *message* is sound, not whether the campaign is still running. A campaign paused between
    # review and approval is exactly the gap this step exists for — and discovering it at dispatch
    # instead would mean a human had already approved something the organisation had stopped.
    campaign = session.get(Campaign, candidate.campaign_id)
    if campaign is None:  # pragma: no cover - the foreign key prevents this
        raise ApprovalTransactionRefused(f"candidate {candidate.id} points at a missing campaign")
    if campaign.paused:
        raise ApprovalTransactionRefused(
            f"campaign {campaign.id} is paused; approving into a stopped campaign would order a "
            f"send nobody currently wants (§11.3 step 3)"
        )

    # Not covered by `T-055`, because validation is about the *message*: the recipient argument has
    # to be the one this revision was written to. ADR-008 approves a recipient and a revision
    # together, so a mismatch means the pair being approved is not the pair that was reviewed.
    #
    # Whether that address is *verified* is deliberately NOT rechecked here — `T-055`'s
    # `recipient_contactable` already refuses an unverified one, and a control proved a second
    # copy here was unreachable: deleting it failed no test. A rule enforced twice is a rule that
    # can disagree with itself, and the copy nobody exercises is the one that drifts.
    if recipient.id != revision.recipient_contact_point_id:
        raise ApprovalTransactionRefused(
            f"recipient {recipient.id} is not the address revision {revision.id} was written to; "
            f"an approval names an exact recipient and an exact revision together (ADR-008)"
        )


def approve_message(
    session: Session,
    revision: MessageRevision,
    *,
    recipient: ContactPoint,
    approver_id: str,
    actor: Actor,
    record_versions: dict[str, Any] | None = None,
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> ApprovalOutcome:
    """Approve one revision for one recipient. Adds to ``session`` without committing.

    Everything lands in the caller's transaction: the approval, the send command, the outbox
    event, and the thread transition. A partial approval — a command with no approval behind it,
    or an approval with no event to dispatch — is the state this must never leave (§7.2).

    Raises :class:`ApprovalTransactionRefused` before writing anything the caller would have to
    undo.
    """
    moment = at or datetime.now(UTC)

    # Asked of `drafts_and_approvals`, which owns the revision lifecycle: `test_invariants.py`
    # refuses any other package to name `MessageRevisionState`, and that rule is what moved this
    # pair there rather than leaving the state literal in this file (ADR-015).
    try:
        revisions.require_approvable(revision)
    except RevisionNotApprovable as refusal:
        raise ApprovalTransactionRefused(str(refusal)) from refusal

    candidate = candidate_for_revision(session, revision)
    if candidate is None:  # pragma: no cover - the draft's foreign key prevents this
        raise ApprovalTransactionRefused(f"revision {revision.id} belongs to no candidate")

    _recheck(
        session,
        revision,
        recipient,
        candidate,
        actor=actor,
        moment=moment,
        correlation_id=correlation_id,
    )

    # Step 4. `request_approval` writes the pending record and `approve` decides it; both are
    # `T-021`'s, and going through them keeps §8.2's approval lifecycle the only way an approval
    # reaches `approved`.
    approval = request_approval(
        session,
        revision=revision,
        approver_id=approver_id,
        actor=actor,
        now=moment,
        correlation_id=correlation_id,
    )
    approve(session, approval, actor=actor, now=moment, correlation_id=correlation_id)
    # And the revision itself. §8.2 gives the message-revision lifecycle an `approved` state, and
    # without this nothing ever moves it there — the approval record would say "approved" while
    # the revision it names still read `review_pending`. It also makes the refusal above the
    # thing that stops a second approval: without it, a repeat reached
    # `uq_approval_live_per_revision`
    # and failed as an integrity error rather than as a decision. Found by the test for exactly
    # that.
    revisions.mark_approved(session, revision, actor=actor, correlation_id=correlation_id)

    thread = _thread_for(session, candidate)
    command = create_send_command(
        session,
        thread=thread,
        approval=approval,
        campaign_id=candidate.campaign_id,
        actor=actor,
        record_versions=record_versions,
        now=moment,
        correlation_id=correlation_id,
    )

    # Step 5. Same transaction as the command — that is what makes the outbox transactional. The
    # idempotency key is the command's, so a replay publishes no second event.
    event = enqueue_outbox_event(
        session,
        event_type=OUTBOX_EVENT_TYPE,
        idempotency_key=command.idempotency_key,
        actor=actor,
        payload={
            "send_command_id": str(command.id),
            "approval_id": str(approval.id),
            "message_revision_id": str(revision.id),
        },
        correlation_id=correlation_id,
    )

    log.info(
        "message.approved",
        revision_id=str(revision.id),
        approval_id=str(approval.id),
        send_command_id=str(command.id),
        # The recipient address is a named person's mailbox; §15.5 keeps content and contact
        # details out of log lines. The identifier is enough to follow the trail.
        recipient_contact_point_id=str(recipient.id),
    )
    return ApprovalOutcome(
        approval=approval, send_command=command, outbox_event_id=event.id, thread=thread
    )


def _thread_for(session: Session, candidate: CampaignCandidate) -> OutreachThread:
    """This candidate's outreach thread, created if it has none.

    One thread per candidate: §8.1 makes the candidate the `campaign + account + contact` identity,
    and a second thread for the same one would split a conversation across two records that each
    look complete. The thread stays in `not_started` — `T-141` refuses it to leave without a send
    command, and by the time one exists the worker owns what happens next.
    """
    existing = session.execute(
        select(OutreachThread).where(OutreachThread.candidate_id == candidate.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    thread = OutreachThread(candidate_id=candidate.id)
    session.add(thread)
    session.flush()
    return thread
