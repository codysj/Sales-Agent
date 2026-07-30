"""Running leased jobs (specification §7.2).

One pass of the §7.2 cycle: lease, load, run, then commit state and audit atomically. A handler's
writes, the job's new state, and the audit event share one transaction, so a job either fully
happened or did not happen at all.
"""

import random
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.orm import Session

from app.audit_and_operations.flags import ConsequentialWorkPaused, FlagKey, is_set
from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.jobs_and_outbox.models import Job
from app.jobs_and_outbox.queue import (
    lease_jobs,
    mark_dead,
    mark_for_human_review,
    mark_for_retry,
    mark_succeeded,
)
from app.jobs_and_outbox.registry import JobRegistry, UnknownJobType
from app.jobs_and_outbox.registry import registry as default_registry
from app.jobs_and_outbox.retry import (
    FailureOutcome,
    RetryPolicy,
    classify,
    compute_backoff,
)

log = structlog.get_logger(__name__)

#: Jobs run unattended, so the actor is the system rather than an unknown human (§12.2).
WORKER_ACTOR = Actor(type=ActorType.SERVICE, id="worker")

#: Delay for a job type this process does not know. Not from a policy — there is no policy to
#: look up — just long enough that the worker does not spin while a rollout finishes.
UNKNOWN_TYPE_BACKOFF = timedelta(minutes=1)


def _record_failure(
    session: Session,
    job: Job,
    exc: BaseException,
    *,
    actor: Actor,
    policy: RetryPolicy,
    rng: random.Random | None,
) -> None:
    """Apply the job type's retry policy to a failed attempt (§17.1, §7.2)."""
    outcome, reason = classify(policy, exc, attempt_count=job.attempt_count)

    if outcome is FailureOutcome.HUMAN_REVIEW:
        mark_for_human_review(session, job, actor=actor, reason=reason)
    elif outcome is FailureOutcome.DEAD:
        mark_dead(session, job, actor=actor, error=reason)
    else:
        delay = compute_backoff(policy, attempt_count=job.attempt_count, rng=rng)
        mark_for_retry(
            session,
            job,
            actor=actor,
            error=reason,
            next_run_at=datetime.now(UTC) + delay,
        )

    log.warning(
        "job.failed",
        job_type=job.job_type,
        outcome=outcome.value,
        attempt=job.attempt_count,
        max_attempts=policy.max_attempts,
        # The reason, not the exception message: `classify` already reduced anything that could
        # quote payload contents down to a type name (§15.5).
        reason=reason,
    )


def execute(
    session: Session,
    job: Job,
    *,
    actor: Actor = WORKER_ACTOR,
    registry: JobRegistry | None = None,
    rng: random.Random | None = None,
) -> bool:
    """Run one leased job. Returns whether it succeeded.

    A failing handler is caught rather than allowed to kill the worker: one bad job must not stop
    the queue. The failure is recorded on the job and the worker moves on.
    """
    active = registry or default_registry
    structlog.contextvars.bind_contextvars(correlation_id=job.correlation_id, job_id=str(job.id))

    try:
        definition = active.get(job.job_type)
    except UnknownJobType as exc:
        # Retried rather than killed: this process may simply be older than the deploy that
        # registered the type. But with a fixed delay, because there is no policy to consult and
        # an immediate retry would spin the worker on the same row.
        mark_for_retry(
            session,
            job,
            actor=actor,
            error=str(exc),
            next_run_at=datetime.now(UTC) + UNKNOWN_TYPE_BACKOFF,
        )
        log.error("job.unknown_type", job_type=job.job_type)
        return False

    if definition.consequential and is_set(session, FlagKey.GLOBAL_PAUSE):
        # Defence in depth. `run_once` already excludes paused types from leasing, which is the
        # enforcement that keeps attempt counts untouched; this catches a caller that leased the
        # job some other way, or a pause thrown between the lease and here.
        log.warning("job.refused_paused", job_type=job.job_type)
        raise ConsequentialWorkPaused(
            f"{job.job_type!r} is consequential and a global pause is in force (§17.6)"
        )

    try:
        payload = definition.payload_model.model_validate(job.payload)
        # A SAVEPOINT, not the whole transaction. Rolling back everything would discard the lease
        # itself — including the incremented attempt count — so a job that fails forever would
        # look like a job that had never been tried.
        with session.begin_nested():
            definition.handler(session, payload, job_id=job.id)
    except Exception as exc:
        _record_failure(session, job, exc, actor=actor, policy=definition.retry_policy, rng=rng)
        return False

    mark_succeeded(session, job, actor=actor)
    log.info("job.succeeded", job_type=job.job_type, attempt=job.attempt_count)
    return True


def run_once(
    session: Session,
    *,
    worker_id: str,
    limit: int = 1,
    registry: JobRegistry | None = None,
    rng: random.Random | None = None,
) -> int:
    """Lease and run up to ``limit`` jobs. Returns how many were run.

    Split out from any polling loop so the whole cycle is testable without sleeping.

    Under a §17.6 global pause, consequential job types are excluded from the lease rather than
    refused after it, so paused work stays `queued` and visible with nothing spent on it.
    """
    active = registry or default_registry
    excluded = active.consequential_names() if is_set(session, FlagKey.GLOBAL_PAUSE) else ()

    jobs = lease_jobs(session, worker_id=worker_id, limit=limit, exclude_types=excluded)
    if not jobs:
        return 0

    for job in jobs:
        execute(session, job, registry=registry, rng=rng)
        session.commit()
    return len(jobs)
