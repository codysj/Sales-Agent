"""Campaign membership as a job type (T-058b1; §17.1, §7.2, §8.3 step 2).

`T-058a` proved the pipeline works by calling each module's entry point in order from a test.
That is not how it will run. §7.2's cycle is *lease, load, run, then commit state and audit and
the next job atomically*, and this is the first step expressed that way.

**Registered here, not in `jobs_and_outbox`.** §18.2 and `tests/test_module_boundaries.py` keep
the queue generic: it moves work and guarantees delivery semantics, and the module that knows
what a campaign candidate is owns the handler. The queue gains no domain knowledge from this
file existing.

**Idempotent because `create_memberships` already is.** A replay finds the membership the first
run created — `find_membership` returns it and it lands in `existing` rather than `created` — so
no second candidate appears and no second audit event is written. The chained eligibility jobs
are enqueued for `candidate_ids`, both created *and* existing, on purpose: a replay after a
crash between the membership write and the enqueue must still produce the follow-on work, and an
eligibility job is itself idempotent (`qualification.jobs`).

**Import is not a job.** An operator uploading a CSV is a request, not background work: it
commits the batch and enqueues the first membership jobs. That keeps the whole file's outcome —
including its rejections — in front of the person who uploaded it, rather than in a queue they
would have to go looking for.
"""

import uuid
from datetime import timedelta
from typing import Any, Final

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, transition
from app.campaigns.membership import create_memberships
from app.core.lifecycles import CampaignCandidateState
from app.jobs_and_outbox.queue import enqueue
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.registry import registry as default_registry
from app.jobs_and_outbox.retry import PermanentFailure, RetryPolicy

log = structlog.get_logger(__name__)

MEMBERSHIP_JOB_TYPE: Final = "campaigns.create_membership"

#: The next step, named as a string rather than imported. `qualification.eligibility` already
#: imports `campaigns`, so importing `qualification.jobs` back would make the package graph
#: cyclic and `test_no_import_cycles` says so. Naming it is also what a queue is *for*: the
#: producer says what work is wanted, and `enqueue` resolves the payload model from the registry
#: and validates against it, so a wrong name is a refused enqueue rather than a bad job.
#: `test_pipeline_jobs.py` asserts this string equals `qualification.jobs.ELIGIBILITY_JOB_TYPE`.
NEXT_JOB_TYPE: Final = "qualification.apply_eligibility"

START_RESEARCH_JOB_TYPE: Final = "campaigns.start_research"
COMPLETE_RESEARCH_JOB_TYPE: Final = "campaigns.complete_research"

#: The research step this module brackets. A string for the same reason `NEXT_JOB_TYPE` is one:
#: `research_and_evidence.jobs` imports `campaigns`, so importing it back would make the package
#: graph cyclic. `test_pipeline_jobs.py` pins it to `research_and_evidence.jobs.CAPTURE_JOB_TYPE`.
CAPTURE_JOB_TYPE: Final = "research.capture_evidence"

#: What runs once research is complete (§8.3 step 7). Pinned to
#: `qualification.jobs.QUALIFY_JOB_TYPE` by `test_pipeline_jobs.py`.
QUALIFY_JOB_TYPE: Final = "qualification.qualify_candidate"

#: Jobs run unattended (§12.2). Named distinctly from the worker's own actor so an audit reader
#: can tell "the membership handler did this" from "the queue did this".
JOB_ACTOR: Final = Actor(type=ActorType.SERVICE, id="campaigns.membership-job")


class MembershipPayload(BaseModel):
    """One account/contact pairing and the campaigns a source named for it.

    ``extra="forbid"`` so a payload written against a future field lands as a rejected enqueue
    rather than a job that silently ignores half of what it was asked to do.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: uuid.UUID
    #: ``None`` is an account-level membership, which §8.1 permits and eligibility then refuses
    #: for want of anyone to contact. Kept representable rather than validated away: the refusal
    #: is the useful record.
    contact_id: uuid.UUID | None = None
    campaign_slugs: list[str] = Field(min_length=1)


def handle_membership(session: Session, payload: BaseModel, *, job_id: Any) -> None:
    """Create the memberships this payload names, then queue eligibility for each.

    Both writes share the caller's session, so §7.2's "commit state + audit + next job
    atomically" is a property of the transaction rather than a sequence this function has to get
    right.
    """
    if not isinstance(payload, MembershipPayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected MembershipPayload, got {type(payload).__name__}")

    result = create_memberships(
        session,
        account_id=payload.account_id,
        contact_id=payload.contact_id,
        campaign_slugs=payload.campaign_slugs,
        actor=JOB_ACTOR,
    )

    for candidate_id in result.candidate_ids:
        enqueue(
            session,
            job_type=NEXT_JOB_TYPE,
            payload={"candidate_id": str(candidate_id)},
            actor=JOB_ACTOR,
        )

    if result.unknown_slugs:
        # Reported, not raised: a file naming one campaign that does not exist should still
        # produce the memberships for the campaigns that do.
        log.warning(
            "membership.unknown_campaign_slugs",
            count=len(result.unknown_slugs),
            slugs=sorted(result.unknown_slugs),
        )


class CandidatePayload(BaseModel):
    """One candidate. Shared by both research-bracket job types, which need nothing else."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: uuid.UUID


def _candidate_in(
    session: Session, candidate_id: uuid.UUID, expected: CampaignCandidateState
) -> CampaignCandidate | None:
    """The candidate if it is in ``expected``, or ``None`` if some run already moved it.

    Missing rows are permanent failures; an unexpected *state* is not. §8.2 has no self-edges
    (`T-010`), so a replay that transitioned again would raise, be classified permanent, and
    dead-letter a job that had already succeeded.
    """
    candidate = session.get(CampaignCandidate, candidate_id)
    if candidate is None:
        raise PermanentFailure(f"no campaign candidate {candidate_id}")
    if candidate.state is not expected:
        log.info(
            "candidate.already_advanced",
            candidate_id=str(candidate.id),
            state=candidate.state.value,
            expected=expected.value,
        )
        return None
    return candidate


def handle_start_research(session: Session, payload: BaseModel, *, job_id: Any) -> None:
    """Move an eligible candidate into research and queue the capture that does the work."""
    if not isinstance(payload, CandidatePayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected CandidatePayload, got {type(payload).__name__}")

    candidate = _candidate_in(session, payload.candidate_id, CampaignCandidateState.ELIGIBLE)
    if candidate is None:
        return

    transition(
        session,
        candidate,
        CampaignCandidateState.RESEARCH_PENDING,
        actor=JOB_ACTOR,
        policy_decision="research:started",
    )
    # Same transaction as the transition (§7.2). A candidate in `research_pending` with no
    # capture job queued would be one nothing will ever finish.
    enqueue(
        session,
        job_type=CAPTURE_JOB_TYPE,
        payload={"candidate_id": str(candidate.id)},
        actor=JOB_ACTOR,
    )


def handle_complete_research(session: Session, payload: BaseModel, *, job_id: Any) -> None:
    """Close the research bracket. Queued by the capture job once its evidence is stored."""
    if not isinstance(payload, CandidatePayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected CandidatePayload, got {type(payload).__name__}")

    candidate = _candidate_in(
        session, payload.candidate_id, CampaignCandidateState.RESEARCH_PENDING
    )
    if candidate is None:
        return

    transition(
        session,
        candidate,
        CampaignCandidateState.RESEARCHED,
        actor=JOB_ACTOR,
        policy_decision="research:complete",
    )
    # Same transaction as the transition (§7.2). `researched` is the state §8.3 step 7 evaluates
    # from, and qualification is where the automatic cascade ends — step 9 waits on an approval.
    enqueue(
        session,
        job_type=QUALIFY_JOB_TYPE,
        payload={"candidate_id": str(candidate.id)},
        actor=JOB_ACTOR,
    )


def register(registry: JobRegistry | None = None) -> None:
    """Register the membership job type.

    Not consequential in §17.6's sense. A pause stops work *going out*; creating a candidate
    produces no external effect, and stopping it would only hide the queue an operator paused the
    system to inspect.
    """
    target = registry or default_registry
    if target.is_registered(MEMBERSHIP_JOB_TYPE):
        return
    target.register(
        MEMBERSHIP_JOB_TYPE,
        MembershipPayload,
        handle_membership,
        # The work is idempotent, so a transient database error costs nothing to repeat.
        retry_policy=RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=10)),
        consequential=False,
    )

    for name, handler in (
        (START_RESEARCH_JOB_TYPE, handle_start_research),
        (COMPLETE_RESEARCH_JOB_TYPE, handle_complete_research),
    ):
        if not target.is_registered(name):
            target.register(
                name,
                CandidatePayload,
                handler,
                retry_policy=RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=10)),
                # Advancing a candidate through the workflow produces no external effect.
                consequential=False,
            )
