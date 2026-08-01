"""Qualification job types (T-058b1, T-058b2b1; §17.1, §7.2, §8.3 steps 4 and 7-8, §10.1).

The second half of the chain `campaigns.jobs` starts. A membership job creates candidates and
queues one of these per candidate; this runs the deterministic rules and moves the candidate to
`eligible` or `ineligible`.

**Idempotent by a state guard, not by luck.** `apply_eligibility` ends in a `transition`, and
§8.2 has no `imported -> imported`, no `eligible -> eligible`, and nothing at all out of
`ineligible` (`T-010`). A replayed job that called it again would raise an illegal-transition
error, be classified as a permanent failure, and dead-letter a job that had in fact already
succeeded. So the guard is explicit: a candidate that has left `imported` has already been
evaluated, and the job returns having done nothing. That is the honest reading of a replay —
the work is done — and it keeps `IMPORTED` as the single state in which this job has anything
to do, which a test pins.

**No override, here or anywhere.** `apply_eligibility` takes no argument that would let a caller
force the outcome, and this handler adds none. A job payload that could say "treat this one as
eligible" would be exactly the bypass §10.1 and §3.5 exist to prevent, and the way to notice it
would be reading the payload model — so the payload is one candidate ID and nothing else.

**Qualification (§8.3 step 7) ends the automatic cascade.** It moves the candidate
`researched -> review_pending` and enqueues *nothing*. That is not an omission: §8.3 step 9 says
a draft is created "on candidate approval", so a chain that drafted here would encode "draft
without approval" into the production path. The next thing that happens to this candidate is a
person looking at it, and producing that approval is the Stage 2 dashboard's job behind gate
**G-02**. `test_pipeline_jobs.py` asserts the queue is empty afterwards.

`qualification` may perform that transition where `research_and_evidence` may not: it is already
a `LIFECYCLE_OWNERS` member for the candidate lifecycle, on the argument ADR-020 records — the
`imported -> eligible` decision *is* eligibility's outcome. Step 7's outcome is a
`QualificationRun`, so by that same argument the transition belongs with the owner, and here the
owner and the performer happen to be the same module.

**Versions are resolved, not passed.** §7.2's cycle begins "validate policy and input version",
and §14.5 requires a run to cite the exact versions it used. The handler looks up the currently
effective prompt, schema, and model-config versions and fails permanently if any is missing:
running against no known version produces a result nobody can later explain (§17.5).
"""

import uuid
from datetime import timedelta
from typing import Any, Final

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.audit_and_operations.versioning import (
    ModelConfigVersion,
    PromptVersion,
    SchemaVersion,
    VersionNotFound,
    require_effective_version,
)
from app.campaigns.candidate import CampaignCandidate, transition
from app.core.lifecycles import CampaignCandidateState
from app.jobs_and_outbox.queue import enqueue
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.registry import registry as default_registry
from app.jobs_and_outbox.retry import PermanentFailure, RetryPolicy
from app.model_gateway.gateway import DatabaseModelGateway
from app.model_gateway.schemas import QUALIFICATION_KEY
from app.qualification.eligibility import apply_eligibility
from app.qualification.qualify import TASK_NAME, qualify_candidate

log = structlog.get_logger(__name__)

ELIGIBILITY_JOB_TYPE: Final = "qualification.apply_eligibility"

#: The next step, named as a string rather than imported: `campaigns.jobs` imports nothing from
#: here but the graph is easier to keep acyclic this way, and `enqueue` resolves the payload model
#: from the registry, so a wrong name is a refused enqueue rather than a bad job.
#:
#: It is `campaigns.start_research`, not the capture job, because `campaigns` owns the candidate
#: lifecycle and brackets the research step from either side (ADR-020). `test_pipeline_jobs.py`
#: asserts this equals `campaigns.jobs.START_RESEARCH_JOB_TYPE`.
NEXT_JOB_TYPE: Final = "campaigns.start_research"

JOB_ACTOR: Final = Actor(type=ActorType.SERVICE, id="qualification.eligibility-job")

#: The only state this job has work to do in. Every other state means some run already decided,
#: and §8.2 offers no edge back.
PENDING_STATE: Final = CampaignCandidateState.IMPORTED


class EligibilityPayload(BaseModel):
    """One candidate to evaluate. Deliberately nothing else — see the module docstring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: uuid.UUID


def handle_eligibility(session: Session, payload: BaseModel, *, job_id: Any) -> None:
    """Evaluate one candidate, or do nothing if one already has."""
    if not isinstance(payload, EligibilityPayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected EligibilityPayload, got {type(payload).__name__}")

    candidate = session.get(CampaignCandidate, payload.candidate_id)
    if candidate is None:
        # Permanent: no number of retries will make a missing row appear, and spending five
        # attempts proving that is how a queue fills with work nobody will ever complete.
        raise PermanentFailure(f"no campaign candidate {payload.candidate_id}")

    if candidate.state is not PENDING_STATE:
        log.info(
            "eligibility.already_decided",
            candidate_id=str(candidate.id),
            state=candidate.state.value,
        )
        return

    decision = apply_eligibility(session, candidate, actor=JOB_ACTOR)

    if decision.is_eligible:
        # Only on a pass. §8.3 researches *eligible* candidates (step 5 after step 4), and
        # `ineligible` is terminal in §8.2 — queueing research for one would be work that could
        # never be used, against a candidate no later step may touch.
        enqueue(
            session,
            job_type=NEXT_JOB_TYPE,
            payload={"candidate_id": str(candidate.id)},
            actor=JOB_ACTOR,
        )

    log.info(
        "eligibility.decided",
        candidate_id=str(candidate.id),
        eligible=decision.is_eligible,
        # Rule names, never the values that failed them: §15.5 keeps row content out of the log.
        failed_rules=[failure.rule.value for failure in decision.failures],
    )


def register(registry: JobRegistry | None = None) -> None:
    """Register both job types this module owns.

    Not consequential in §17.6's sense: deciding a candidate is ineligible produces no external
    effect, and a pause that stopped candidates being *refused* would be the wrong way round.
    """
    target = registry or default_registry
    if target.is_registered(ELIGIBILITY_JOB_TYPE):
        return
    target.register(
        ELIGIBILITY_JOB_TYPE,
        EligibilityPayload,
        handle_eligibility,
        retry_policy=RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=10)),
        consequential=False,
    )
    register_qualify(target)


# --- §8.3 step 7: qualification (T-058b2b1) ------------------------------------------------------

QUALIFY_JOB_TYPE: Final = "qualification.qualify_candidate"

QUALIFY_ACTOR: Final = Actor(type=ActorType.SERVICE, id="qualification.qualify-job")

#: The state step 7 evaluates from. `campaigns.complete_research` puts a candidate here.
QUALIFIABLE_STATE: Final = CampaignCandidateState.RESEARCHED

#: The model-config version this task runs under, unless a payload names another. A deployment
#: decision rather than a task one, which is why it is a payload field at all.
DEFAULT_MODEL_CONFIG_KEY: Final = "qualification-model-config"


class QualifyPayload(BaseModel):
    """One candidate to qualify, and which model configuration to run it under."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: uuid.UUID
    model_config_key: str = DEFAULT_MODEL_CONFIG_KEY


def handle_qualify(session: Session, payload: BaseModel, *, job_id: Any) -> None:
    """Qualify one researched candidate and present it for review. Enqueues nothing."""
    if not isinstance(payload, QualifyPayload):  # pragma: no cover - the registry types it
        raise TypeError(f"expected QualifyPayload, got {type(payload).__name__}")

    candidate = session.get(CampaignCandidate, payload.candidate_id)
    if candidate is None:
        raise PermanentFailure(f"no campaign candidate {payload.candidate_id}")

    if candidate.state is not QUALIFIABLE_STATE:
        log.info(
            "qualify.already_done",
            candidate_id=str(candidate.id),
            state=candidate.state.value,
        )
        return

    try:
        prompt = require_effective_version(session, PromptVersion, TASK_NAME)
        schema = require_effective_version(session, SchemaVersion, QUALIFICATION_KEY)
        config = require_effective_version(session, ModelConfigVersion, payload.model_config_key)
    except VersionNotFound as exc:
        # Permanent. A retry cannot register a version, and a run against an unknown one would
        # produce a result nobody can later explain (§17.5).
        raise PermanentFailure(str(exc)) from exc

    qualify_candidate(
        session,
        candidate,
        DatabaseModelGateway(),
        prompt_version_id=prompt.id,
        schema_version_id=schema.id,
        model_config_version_id=config.id,
        actor=QUALIFY_ACTOR,
    )

    transition(
        session,
        candidate,
        CampaignCandidateState.REVIEW_PENDING,
        actor=QUALIFY_ACTOR,
        policy_decision="qualification:presented-for-review",
    )
    # Nothing is enqueued. §8.3 step 8 presents the candidate; step 9 waits on an approval.
    log.info("qualify.presented_for_review", candidate_id=str(candidate.id))


def register_qualify(registry: JobRegistry | None = None) -> None:
    """Register the qualification job type.

    Not consequential in §17.6's sense: it runs a bounded model task against a fake provider and
    presents a candidate to a human. Nothing leaves the system.
    """
    target = registry or default_registry
    if target.is_registered(QUALIFY_JOB_TYPE):
        return
    target.register(
        QUALIFY_JOB_TYPE,
        QualifyPayload,
        handle_qualify,
        retry_policy=RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=10)),
        consequential=False,
    )
