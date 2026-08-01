"""Retry policy, backoff, and terminal dispositions (T-031; §17.1, §7.2).

The property that matters here is that failure is never silent. A job stops being retried only by
reaching `dead`, and a dead job always says why — enforced by the database, not just by the caller.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.core.lifecycles import JobState
from app.jobs_and_outbox.models import Job
from app.jobs_and_outbox.queue import QueueError, enqueue, lease_jobs, mark_for_human_review
from app.jobs_and_outbox.registry import JobHandler, JobRegistry
from app.jobs_and_outbox.retry import (
    FailureOutcome,
    NeedsHumanReview,
    PermanentFailure,
    RetryPolicy,
    RetryPolicyError,
    classify,
    compute_backoff,
)
from app.jobs_and_outbox.runner import execute
from tests.factories import NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")

#: A policy with jitter off, so tests that are about *progression* are not also about randomness.
STEADY = RetryPolicy(
    max_attempts=3,
    base_delay=timedelta(seconds=10),
    max_delay=timedelta(minutes=5),
    jitter=0.0,
)


class NoOpPayload(BaseModel):
    label: str


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-retry-test")


def registry_with(handler: JobHandler, policy: RetryPolicy = STEADY) -> JobRegistry:
    registry = JobRegistry()
    registry.register(
        "synthetic.failing", NoOpPayload, handler, retry_policy=policy, consequential=False
    )
    return registry


def raiser(exc: BaseException) -> JobHandler:
    def handler(session: Session, payload: BaseModel, *, job_id: object) -> None:
        raise exc

    return handler


def leased_job(db_session: Session, registry: JobRegistry, attempts: int = 1) -> Job:
    """Enqueue and lease one job, leaving it with ``attempts`` attempts already spent."""
    enqueue(
        db_session,
        job_type="synthetic.failing",
        payload={"label": "SYNTHETIC"},
        actor=OPERATOR,
        registry=registry,
        run_at=NOW,
    )
    db_session.flush()
    job = lease_jobs(db_session, worker_id="worker-a", limit=1, now=NOW)[0]
    job.attempt_count = attempts
    db_session.flush()
    return job


# --- policy is explicit per job type (criterion 1) ------------------------------------------------


def test_registering_without_a_retry_policy_fails() -> None:
    """§17.1: retry policy is explicit per job type, so there is no default to fall back on."""
    registry = JobRegistry()

    with pytest.raises(TypeError, match="retry_policy"):
        registry.register(  # type: ignore[call-arg]
            "synthetic.no_policy", NoOpPayload, lambda s, p, *, job_id: None
        )

    assert not registry.is_registered("synthetic.no_policy")


def test_a_registered_job_type_exposes_its_policy() -> None:
    registry = registry_with(raiser(RuntimeError("boom")))

    assert registry.get("synthetic.failing").retry_policy is STEADY


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_attempts": 0}, "at least 1"),
        ({"base_delay": timedelta(seconds=-1)}, "negative"),
        ({"max_delay": timedelta(seconds=1)}, "below base_delay"),
        ({"jitter": 1.5}, "fraction"),
    ],
)
def test_an_incoherent_policy_is_refused(kwargs: dict[str, object], message: str) -> None:
    """A policy is validated where it is declared, not where it first misbehaves."""
    base: dict[str, object] = {"max_attempts": 3, "base_delay": timedelta(seconds=10)}

    with pytest.raises(RetryPolicyError, match=message):
        RetryPolicy(**{**base, **kwargs})  # type: ignore[arg-type]


# --- backoff progression (criterion 3) ------------------------------------------------------------


def test_backoff_doubles_each_attempt() -> None:
    delays = [compute_backoff(STEADY, attempt_count=n).total_seconds() for n in range(1, 5)]

    assert delays == [10.0, 20.0, 40.0, 80.0]


def test_backoff_is_capped_at_max_delay() -> None:
    """Without a cap, attempt 20 would schedule the job well past the heat death of the pilot."""
    assert compute_backoff(STEADY, attempt_count=20) == timedelta(minutes=5)


def test_jitter_is_deterministic_under_a_seeded_source() -> None:
    """Criterion 3. Two runs of the same seed must agree, or the progression is untestable."""
    jittery = RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=10), jitter=0.5)

    first = [compute_backoff(jittery, attempt_count=n, rng=random.Random(7)) for n in range(1, 4)]
    second = [compute_backoff(jittery, attempt_count=n, rng=random.Random(7)) for n in range(1, 4)]

    assert first == second


def test_jitter_stays_within_its_declared_fraction() -> None:
    jittery = RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=100), jitter=0.25)
    source = random.Random(1234)

    for _ in range(200):
        seconds = compute_backoff(jittery, attempt_count=1, rng=source).total_seconds()
        assert 75.0 <= seconds <= 125.0


def test_jitter_actually_varies() -> None:
    """A jitter implementation that returns a constant would pass every test above."""
    jittery = RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=100), jitter=0.25)
    source = random.Random(99)

    seen = {compute_backoff(jittery, attempt_count=1, rng=source) for _ in range(50)}

    assert len(seen) > 1


def test_backoff_rejects_a_zeroth_attempt() -> None:
    with pytest.raises(RetryPolicyError, match="starts at 1"):
        compute_backoff(STEADY, attempt_count=0)


# --- classification -------------------------------------------------------------------------------


def test_a_retryable_error_within_budget_retries() -> None:
    outcome, reason = classify(STEADY, RuntimeError("flaky"), attempt_count=1)

    assert outcome is FailureOutcome.RETRY
    assert reason == "RuntimeError"


def test_exhausting_the_budget_is_dead_not_retry() -> None:
    outcome, reason = classify(STEADY, RuntimeError("flaky"), attempt_count=3)

    assert outcome is FailureOutcome.DEAD
    assert "exhausted 3 attempts" in reason


def test_a_permanent_failure_short_circuits_the_budget() -> None:
    """Criterion 2: no point spending three attempts proving the same thing."""
    outcome, reason = classify(STEADY, PermanentFailure("row is malformed"), attempt_count=1)

    assert outcome is FailureOutcome.DEAD
    assert "row is malformed" in reason


def test_an_unlisted_exception_class_is_permanent() -> None:
    """``retryable`` is a whitelist: an unrecognized error is more likely a bug than a hiccup."""
    narrow = RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=1), retryable=(TimeoutError,))

    outcome, reason = classify(narrow, ValueError("unexpected"), attempt_count=1)

    assert outcome is FailureOutcome.DEAD
    assert "ValueError is not retryable" in reason
    assert classify(narrow, TimeoutError(), attempt_count=1)[0] is FailureOutcome.RETRY


def test_human_review_is_distinct_from_dead() -> None:
    """§7.2's fourth outcome. Nothing is broken; a person must decide."""
    outcome, reason = classify(STEADY, NeedsHumanReview("claim looks unsupported"), attempt_count=1)

    assert outcome is FailureOutcome.HUMAN_REVIEW
    assert "claim looks unsupported" in reason


def test_human_review_outranks_an_exhausted_budget() -> None:
    """A job on its last attempt that asks for a human must not be filed as "we gave up"."""
    outcome, _ = classify(STEADY, NeedsHumanReview("needs a decision"), attempt_count=99)

    assert outcome is FailureOutcome.HUMAN_REVIEW


def test_the_recorded_reason_never_quotes_an_arbitrary_exception_message() -> None:
    """§15.5: a payload value must not leak into `last_error` via an exception message."""
    secret = "prospect@example.invalid"
    _, reason = classify(STEADY, RuntimeError(secret), attempt_count=1)

    assert secret not in reason


# --- the runner applies the policy ----------------------------------------------------------------


def test_a_failing_job_is_rescheduled_with_backoff(db_session: Session) -> None:
    registry = registry_with(raiser(RuntimeError("flaky")))
    job = leased_job(db_session, registry)
    before = datetime.now(UTC)

    assert execute(db_session, job, registry=registry, rng=random.Random(3)) is False

    assert job.state is JobState.RETRY
    assert job.last_error == "RuntimeError"
    # attempt 1 with jitter off waits exactly base_delay.
    assert job.next_run_at >= before + timedelta(seconds=10)


def test_a_failing_job_out_of_attempts_becomes_dead_with_a_reason(db_session: Session) -> None:
    """Criterion 2, end to end through the runner."""
    registry = registry_with(raiser(RuntimeError("flaky")))
    job = leased_job(db_session, registry, attempts=STEADY.max_attempts)

    assert execute(db_session, job, registry=registry) is False

    assert job.state is JobState.DEAD
    assert job.last_error is not None and job.last_error.strip()
    assert "exhausted" in job.last_error
    assert job.requires_human_review is False


def test_a_permanently_failing_job_dies_on_its_first_attempt(db_session: Session) -> None:
    registry = registry_with(raiser(PermanentFailure("unparseable record")))
    job = leased_job(db_session, registry)

    execute(db_session, job, registry=registry)

    assert job.state is JobState.DEAD
    assert job.attempt_count == 1, "should not have burned the whole budget"
    assert job.last_error is not None and "unparseable record" in job.last_error


def test_a_job_needing_review_is_flagged_not_just_dead(db_session: Session) -> None:
    registry = registry_with(raiser(NeedsHumanReview("evidence is thin")))
    job = leased_job(db_session, registry)

    execute(db_session, job, registry=registry)

    assert job.state is JobState.DEAD
    assert job.requires_human_review is True
    assert job.last_error is not None and "evidence is thin" in job.last_error


def test_a_successful_job_is_untouched_by_the_policy(db_session: Session) -> None:
    registry = JobRegistry()
    registry.register(
        "synthetic.failing",
        NoOpPayload,
        lambda s, p, *, job_id: None,
        retry_policy=STEADY,
        consequential=False,
    )
    job = leased_job(db_session, registry)

    assert execute(db_session, job, registry=registry) is True
    assert job.state is JobState.SUCCEEDED
    assert job.requires_human_review is False


def test_an_unknown_job_type_backs_off_instead_of_spinning(db_session: Session) -> None:
    """No policy exists to consult, but an immediate retry would spin the worker on one row."""
    registry = registry_with(raiser(RuntimeError("never called")))
    job = leased_job(db_session, registry)
    job.job_type = "synthetic.not_registered"
    before = datetime.now(UTC)

    assert execute(db_session, job, registry=registry) is False

    assert job.state is JobState.RETRY
    assert job.next_run_at > before


# --- the database enforces it too -----------------------------------------------------------------


def test_the_database_refuses_a_dead_job_without_a_reason(db_session: Session) -> None:
    """§17.1 in the schema, not only in `mark_dead`: no future code path can bypass it."""
    registry = registry_with(raiser(RuntimeError("x")))
    job = leased_job(db_session, registry)
    job.state = JobState.DEAD
    job.last_error = None
    job.leased_by = None
    job.lease_expires_at = None

    with pytest.raises(IntegrityError, match="dead_job_must_carry_a_reason"):
        db_session.flush()


def test_the_database_refuses_a_blank_reason(db_session: Session) -> None:
    registry = registry_with(raiser(RuntimeError("x")))
    job = leased_job(db_session, registry)
    job.state = JobState.DEAD
    job.last_error = "   "
    job.leased_by = None
    job.lease_expires_at = None

    with pytest.raises(IntegrityError, match="dead_job_must_carry_a_reason"):
        db_session.flush()


def test_the_database_refuses_review_on_a_live_job(db_session: Session) -> None:
    """A job awaiting a person must not also look runnable to a worker."""
    registry = registry_with(raiser(RuntimeError("x")))
    job = leased_job(db_session, registry)
    job.state = JobState.QUEUED
    job.leased_by = None
    job.lease_expires_at = None
    job.requires_human_review = True

    with pytest.raises(IntegrityError, match="human_review_is_a_terminal_disposition"):
        db_session.flush()


def test_marking_for_review_requires_a_reason(db_session: Session) -> None:
    registry = registry_with(raiser(RuntimeError("x")))
    job = leased_job(db_session, registry)

    with pytest.raises(QueueError, match="what needs deciding"):
        mark_for_human_review(db_session, job, actor=OPERATOR, reason="  ")


def test_a_reviewed_job_is_not_leasable(db_session: Session) -> None:
    """The disposition has to actually take the job out of circulation."""
    registry = registry_with(raiser(NeedsHumanReview("decide this")))
    job = leased_job(db_session, registry)
    execute(db_session, job, registry=registry)
    db_session.flush()

    assert lease_jobs(db_session, worker_id="worker-b", limit=10, now=NOW) == []
    assert isinstance(job.id, uuid.UUID)
