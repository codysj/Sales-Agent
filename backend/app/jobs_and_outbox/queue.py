"""Enqueueing and leasing (specification §17.1, §7.2).

Leasing uses ``SELECT ... FOR UPDATE SKIP LOCKED``: each worker locks the rows it takes and skips
rows another worker already holds, so two workers never lease the same job and neither blocks
waiting for the other. The lock is held until the transaction commits, which is also when the
lease becomes visible — there is no window where a job looks free but is not.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor, current_correlation_id, record_audit_event
from app.core.lifecycles import JobState, assert_transition
from app.jobs_and_outbox.models import DEFAULT_PRIORITY, RUNNABLE_STATES, Job
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.registry import registry as default_registry

ENTITY_TYPE = "job"

#: How long a worker holds a job before the lease may be reclaimed (T-032). Short enough that a
#: crashed worker's jobs come back quickly, long enough that a slow model call does not lose its
#: lease mid-flight.
DEFAULT_LEASE = timedelta(minutes=5)


class QueueError(Exception):
    """A queue operation was refused."""


class InvalidJobPayload(QueueError):
    """The payload does not match the registered model for this job type."""


def enqueue(
    session: Session,
    *,
    job_type: str,
    payload: BaseModel | dict[str, object],
    actor: Actor,
    priority: int = DEFAULT_PRIORITY,
    run_at: datetime | None = None,
    correlation_id: str | None = None,
    registry: JobRegistry | None = None,
) -> Job:
    """Validate a payload and queue the work.

    Validation happens **before insert** (§17.1): a malformed job must never reach the queue to
    be discovered by a worker later. Added to the caller's session without committing, so the job
    and whatever state change caused it land together (§7.2).
    """
    active = registry or default_registry
    job_type_definition = active.get(job_type)

    try:
        validated = (
            payload
            if isinstance(payload, job_type_definition.payload_model)
            else job_type_definition.payload_model.model_validate(payload)
        )
    except ValidationError as exc:
        raise InvalidJobPayload(
            f"payload for job type {job_type!r} does not match "
            f"{job_type_definition.payload_model.__name__}: {exc}"
        ) from exc

    resolved_correlation = correlation_id or current_correlation_id()
    if not resolved_correlation:
        raise QueueError(
            f"no correlation_id for job {job_type!r}; a job that cannot be traced to its cause "
            f"is much weaker evidence (§17.5)"
        )

    job = Job(
        job_type=job_type,
        payload=validated.model_dump(mode="json"),
        state=JobState.QUEUED,
        priority=priority,
        attempt_count=0,
        next_run_at=run_at or datetime.now(UTC),
        correlation_id=resolved_correlation,
    )
    session.add(job)
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="job.enqueued",
        entity_type=ENTITY_TYPE,
        entity_id=job.id,
        to_state=JobState.QUEUED,
        payload={"job_type": job_type, "priority": priority},
        correlation_id=resolved_correlation,
    )
    return job


def lease_jobs(
    session: Session,
    *,
    worker_id: str,
    limit: int = 1,
    lease: timedelta = DEFAULT_LEASE,
    now: datetime | None = None,
    exclude_types: Sequence[str] = (),
) -> list[Job]:
    """Claim up to ``limit`` runnable jobs for this worker.

    ``SKIP LOCKED`` is what makes concurrent workers safe *and* non-blocking: a worker steps over
    rows another worker has locked rather than waiting behind them.

    ``exclude_types`` is how a §17.6 pause is enforced: the paused job types are never leased at
    all, so their rows stay `queued` with their attempt counts untouched. That is what §17.1 means
    by preventing new work "while preserving inspectability" — refusing them *after* leasing would
    burn attempts and eventually dead-letter work nobody meant to abandon.
    """
    moment = now or datetime.now(UTC)

    conditions = [Job.state.in_(RUNNABLE_STATES), Job.next_run_at <= moment]
    if exclude_types:
        conditions.append(Job.job_type.notin_(exclude_types))

    candidate_ids = (
        session.execute(
            select(Job.id)
            .where(*conditions)
            .order_by(Job.priority, Job.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    if not candidate_ids:
        return []

    session.execute(
        update(Job)
        .where(Job.id.in_(candidate_ids))
        .values(
            state=JobState.LEASED,
            leased_by=worker_id,
            lease_expires_at=moment + lease,
            attempt_count=Job.attempt_count + 1,
        )
    )
    session.flush()

    return list(session.execute(select(Job).where(Job.id.in_(candidate_ids))).scalars().all())


def _finish(
    session: Session,
    job: Job,
    target: JobState,
    *,
    actor: Actor,
    error: str | None,
    next_run_at: datetime | None,
) -> Job:
    previous = job.state
    assert_transition(previous, target)

    job.state = target
    job.leased_by = None
    job.lease_expires_at = None
    if error is not None:
        job.last_error = error
    if next_run_at is not None:
        job.next_run_at = next_run_at
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="job.finished",
        entity_type=ENTITY_TYPE,
        entity_id=job.id,
        from_state=previous,
        to_state=target,
        payload={"job_type": job.job_type, "attempt": job.attempt_count},
        correlation_id=job.correlation_id,
    )
    return job


def mark_succeeded(session: Session, job: Job, *, actor: Actor) -> Job:
    return _finish(session, job, JobState.SUCCEEDED, actor=actor, error=None, next_run_at=None)


def mark_for_retry(
    session: Session,
    job: Job,
    *,
    actor: Actor,
    error: str,
    next_run_at: datetime | None = None,
) -> Job:
    """Return a job to the queue after a failure.

    Backoff, attempt limits, and the decision to dead-letter instead are `T-031`; this records the
    failure and makes the job runnable again.
    """
    return _finish(session, job, JobState.RETRY, actor=actor, error=error, next_run_at=next_run_at)


def mark_dead(session: Session, job: Job, *, actor: Actor, error: str) -> Job:
    """Give up on a job. §17.1 requires a human-readable reason, so ``error`` is not optional."""
    if not error.strip():
        raise QueueError("a dead job must carry a human-readable reason (§17.1)")
    return _finish(session, job, JobState.DEAD, actor=actor, error=error, next_run_at=None)


def mark_for_human_review(session: Session, job: Job, *, actor: Actor, reason: str) -> Job:
    """§7.2's fourth outcome: terminal, but because a person must decide, not because we failed.

    Reaches the same `dead` state as `mark_dead` — §8.2 has no review state — with
    ``requires_human_review`` set so the two are never one queue (R-003).
    """
    if not reason.strip():
        raise QueueError("a job sent to human review must say what needs deciding (§17.1)")
    job.requires_human_review = True
    return _finish(session, job, JobState.DEAD, actor=actor, error=reason, next_run_at=None)


def cancel(session: Session, job: Job, *, actor: Actor, reason: str) -> Job:
    return _finish(session, job, JobState.CANCELLED, actor=actor, error=reason, next_run_at=None)


def get_job(session: Session, job_id: uuid.UUID) -> Job | None:
    return session.get(Job, job_id)
