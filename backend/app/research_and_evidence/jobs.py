"""Evidence capture as a job type (T-058b2a; §17.1, §7.2, §8.3 steps 5-6, §8.2).

The third link in the chain `campaigns.jobs` starts. An eligibility job that ends `eligible`
queues one of these; this captures evidence for the candidate from a named source.

**This job does not move the candidate, and that is not an oversight.** `research_and_evidence`
is a *reader* of `CampaignCandidateState` (`LIFECYCLE_READERS`), not an owner, and
`test_a_reader_never_transitions_what_it_reads` fails the moment this file imports `transition`.
Writing this handler to advance the candidate is how that was found (`T-147`). `campaigns` owns
the lifecycle and brackets this step instead: `campaigns.start_research` puts the candidate in
`research_pending` and queues this job, and this job queues `campaigns.complete_research` to
close the bracket. ADR-020 records why, and what it rejected.

**The adapter is named, not passed.** `JobHandler` is `(session, payload, *, job_id)`, so there
is no argument for one; the payload carries a name and `adapters.registry` resolves it. That
registry is empty by default because the only Stage 1 adapter reads `app/fixtures/`, which
`T-040` forbids production code to import — see its module docstring.

**Idempotent because `capture_evidence` is.** It dedupes facts by `(content_hash, excerpt)`,
so a replay stores no second snapshot and writes no second audit event. The state check here is
a read that keeps the refusal readable: a candidate outside the researchable states would raise
`CaptureRefused` inside the handler, and a job that dead-letters on "already done" is worse than
one that returns.
"""

import uuid
from datetime import timedelta
from typing import Any, Final

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate
from app.core.lifecycles import CampaignCandidateState
from app.jobs_and_outbox.queue import enqueue
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.registry import registry as default_registry
from app.jobs_and_outbox.retry import PermanentFailure, RetryPolicy
from app.research_and_evidence.adapters.registry import (
    FIXTURE_ADAPTER_NAME,
    SourceAdapterNotAvailable,
    build_source_adapter,
)
from app.research_and_evidence.capture import capture_evidence

log = structlog.get_logger(__name__)

CAPTURE_JOB_TYPE: Final = "research.capture_evidence"

#: Closes the bracket. Named as a string, and owned by `campaigns` because the transition is
#: theirs (ADR-020); `test_pipeline_jobs.py` pins it to `campaigns.jobs.COMPLETE_RESEARCH_JOB_TYPE`.
NEXT_JOB_TYPE: Final = "campaigns.complete_research"

JOB_ACTOR: Final = Actor(type=ActorType.SERVICE, id="research.capture-job")

#: A separate identity so the audit trail distinguishes the first research pass from a
#: reviewer-requested one (ADR-022, §17.5). Same module, different question being answered.
RECAPTURE_ACTOR: Final = Actor(type=ActorType.SERVICE, id="research.recapture-job")

#: States this job may capture in. Deliberately the same set `capture.RESEARCHABLE_STATES`
#: enforces — read here so a candidate past research returns rather than raising `CaptureRefused`
#: and dead-lettering a job whose work was already done. `eligible` remains valid because a job
#: may be enqueued directly, not only through `campaigns.start_research`.
PENDING_STATES: Final = frozenset(
    {CampaignCandidateState.ELIGIBLE, CampaignCandidateState.RESEARCH_PENDING}
)


class CapturePayload(BaseModel):
    """One candidate to research, and which source to research it from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: uuid.UUID
    #: Resolved through `adapters.registry`, which is empty unless a caller registered one. The
    #: default is the conventional Stage 1 name, so a payload written by hand does the expected
    #: thing in a process that registered the fixture adapter and fails loudly in one that did not.
    source_adapter: str = FIXTURE_ADAPTER_NAME


def handle_capture(session: Session, payload: BaseModel, *, job_id: Any) -> None:
    """Capture evidence for one candidate from the source its payload names."""
    if not isinstance(payload, CapturePayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected CapturePayload, got {type(payload).__name__}")

    candidate = session.get(CampaignCandidate, payload.candidate_id)
    if candidate is None:
        raise PermanentFailure(f"no campaign candidate {payload.candidate_id}")

    if candidate.state not in PENDING_STATES:
        log.info(
            "capture.already_done",
            candidate_id=str(candidate.id),
            state=candidate.state.value,
        )
        return

    try:
        adapter = build_source_adapter(payload.source_adapter)
    except SourceAdapterNotAvailable as exc:
        # Permanent. Retrying cannot register an adapter, and five attempts would only delay the
        # operator seeing that this environment has no source configured.
        raise PermanentFailure(str(exc)) from exc

    result = capture_evidence(session, candidate, adapter, actor=JOB_ACTOR)

    # Same transaction as the snapshots (§7.2). The transition itself belongs to `campaigns`.
    enqueue(
        session,
        job_type=NEXT_JOB_TYPE,
        payload={"candidate_id": str(candidate.id)},
        actor=JOB_ACTOR,
    )

    log.info(
        "capture.done",
        candidate_id=str(candidate.id),
        captured=result.captured,
        duplicates=result.duplicates,
    )


RECAPTURE_JOB_TYPE: Final = "research.recapture_evidence"

#: The only state a re-request comes from. A candidate reaches `review_pending` by way of
#: `researched`, so "more research" means *additional* evidence about a candidate that has already
#: been researched once — and it stays in review while the pass runs (ADR-022).
RECAPTURABLE_STATES: Final = frozenset({CampaignCandidateState.REVIEW_PENDING})


class RecapturePayload(BaseModel):
    """One candidate to research again, and which source to research it from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: uuid.UUID
    source_adapter: str = FIXTURE_ADAPTER_NAME


def handle_recapture(session: Session, payload: BaseModel, *, job_id: Any) -> None:
    """Capture more evidence for a candidate that stays in `review_pending` (ADR-022).

    **This enqueues nothing afterwards, and that is the whole difference from `handle_capture`.**
    That job chains to `campaigns.complete_research` because its purpose is the
    `research_pending -> researched` transition. Here there is no transition to make: §8.2 offers
    no edge out of `review_pending` except approve, reject, defer, and invalidate, and a request
    for more evidence is none of those. The chain ends with the evidence.
    """
    if not isinstance(payload, RecapturePayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected RecapturePayload, got {type(payload).__name__}")

    candidate = session.get(CampaignCandidate, payload.candidate_id)
    if candidate is None:
        raise PermanentFailure(f"no campaign candidate {payload.candidate_id}")

    if candidate.state not in RECAPTURABLE_STATES:
        # The reviewer decided something else while the pass was queued — approved it, rejected
        # it, deferred it. Returning rather than raising: the request is moot, not broken, and a
        # dead-lettered job would send an operator looking for a fault that is not there.
        log.info(
            "recapture.no_longer_in_review",
            candidate_id=str(candidate.id),
            state=candidate.state.value,
        )
        return

    try:
        adapter = build_source_adapter(payload.source_adapter)
    except SourceAdapterNotAvailable as exc:
        raise PermanentFailure(str(exc)) from exc

    result = capture_evidence(
        session, candidate, adapter, actor=RECAPTURE_ACTOR, allowed_states=RECAPTURABLE_STATES
    )

    log.info(
        "recapture.done",
        candidate_id=str(candidate.id),
        captured=result.captured,
        duplicates=result.duplicates,
    )


def register(registry: JobRegistry | None = None) -> None:
    """Register this module's job types.

    Neither is consequential in §17.6's sense: reading a local document and storing a snapshot
    produces no external effect. That stops being true the day a network source is permitted (gate
    **G-06**), and the flag is where that change has to be made deliberately.

    Each type is guarded separately. A single early return on the first would have meant that
    adding a second type registered nothing in any process that had already registered the first —
    idempotent and silently incomplete, which is `T-148` again.
    """
    target = registry or default_registry
    for job_type, payload_model, handler in (
        (CAPTURE_JOB_TYPE, CapturePayload, handle_capture),
        (RECAPTURE_JOB_TYPE, RecapturePayload, handle_recapture),
    ):
        if target.is_registered(job_type):
            continue
        target.register(
            job_type,
            payload_model,
            handler,
            retry_policy=RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=10)),
            consequential=False,
        )
