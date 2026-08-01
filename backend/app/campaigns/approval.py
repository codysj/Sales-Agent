"""Approving a candidate for outreach (T-058b2b2a; §8.3 steps 8-9, §8.2, ADR-008, ADR-020).

§8.3 step 8 presents a candidate for human review; step 9 creates a draft **on candidate
approval**. This is that approval: the transition `review_pending -> approved`, and the drafting
job it triggers, committed together (§7.2).

**This is the mechanism, not the authority.** Who may approve a candidate is `Q-005`, and where
they do it is the Stage 2 dashboard behind gate **G-02**. Nothing here decides either. The
function takes an `Actor` and records it; it does not check roles, does not know what a session
is, and must not grow either — when the dashboard exists it authenticates the approver and calls
this, and the day it does, nothing in this file should need to change.

**It lives in `campaigns` because the transition does.** ADR-015 gives the candidate lifecycle to
`campaigns`, and ADR-020 held that line for the research bracket. Approval is a candidate-state
change, so the same rule puts it here rather than in `drafts_and_approvals` — which owns the
*message* approval, a different lifecycle and a different decision (§8.2 has both, deliberately).

**It is not the safety guarantee.** A caller that skipped this and enqueued a drafting job
directly must still get nothing, so `drafts.jobs` refuses any candidate that is not `approved`.
That refusal is the guarantee; this is the ordinary path to it. A precondition on the handler
holds whoever calls it; a convention about who enqueues holds nobody.

**The recipient is an argument, not something this derives.** ADR-008 approves an exact
recipient and an exact revision together, so which address was approved is part of *the
approver's decision* — deriving it here would mean the system chose and the approver ratified
something they were never shown. It also keeps `campaigns` from importing `prospects`, which
`test_no_import_cycles` refuses (`prospects` already imports `campaigns`). Whether the address is
usable at all is checked where that knowledge lives: `Rule.CONTACTABILITY` refuses a candidate
without a verified email long before this, and `T-055`'s `RECIPIENT_CONTACTABLE` check refuses a
revision written to one.
"""

import uuid
from typing import Final

import structlog
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, transition
from app.core.lifecycles import CampaignCandidateState
from app.jobs_and_outbox.queue import enqueue

log = structlog.get_logger(__name__)

#: The drafting job this approval triggers. A string rather than an import:
#: `drafts_and_approvals` imports `campaigns`, so importing it back would make the package graph
#: cyclic, and `enqueue` resolves the payload model from the registry either way.
#: `test_pipeline_jobs.py` pins it to `drafts_and_approvals.jobs.DRAFT_JOB_TYPE`.
DRAFT_JOB_TYPE: Final = "drafts.draft_message"

#: The only state a candidate may be approved from. §8.2 offers no other edge into `approved`,
#: and approving one nobody has reviewed would defeat step 8.
APPROVABLE_STATE: Final = CampaignCandidateState.REVIEW_PENDING


class ApprovalRefused(Exception):
    """The candidate could not be approved for outreach."""


def approve_candidate(
    session: Session,
    candidate: CampaignCandidate,
    *,
    recipient_contact_point_id: uuid.UUID,
    actor: Actor,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Approve a reviewed candidate for the named recipient and queue its draft.

    Adds to ``session`` without committing, so the transition, the audit event, and the drafting
    job land together (§7.2). Raises :class:`ApprovalRefused` before writing anything if the
    candidate is not in review.
    """
    if candidate.state is not APPROVABLE_STATE:
        raise ApprovalRefused(
            f"candidate {candidate.id} is {candidate.state.value}; §8.3 step 8 presents a "
            f"candidate for review before step 9 drafts for it"
        )

    transition(
        session,
        candidate,
        CampaignCandidateState.APPROVED,
        actor=actor,
        reason=reason,
        policy_decision="candidate:approved-for-outreach",
        correlation_id=correlation_id,
    )
    enqueue(
        session,
        job_type=DRAFT_JOB_TYPE,
        payload={
            "candidate_id": str(candidate.id),
            "recipient_contact_point_id": str(recipient_contact_point_id),
        },
        actor=actor,
        correlation_id=correlation_id,
    )
    log.info(
        "candidate.approved_for_outreach",
        candidate_id=str(candidate.id),
        actor_type=actor.type.value,
    )
