"""Durable jobs with safe concurrent leasing (T-030; §17.1, §7.2, ADR-003).

The property that matters most is the one that is easiest to get wrong: two workers pulling from
the same queue must never get the same job. That is tested against two real database connections,
not by mocking the lock.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.core.lifecycles import IllegalTransition, JobState
from app.jobs_and_outbox.models import DEFAULT_PRIORITY, RUNNABLE_STATES, Job
from app.jobs_and_outbox.queue import (
    InvalidJobPayload,
    QueueError,
    cancel,
    enqueue,
    lease_jobs,
    mark_dead,
    mark_for_retry,
    mark_succeeded,
)
from app.jobs_and_outbox.registry import (
    JobRegistry,
    JobRegistryError,
    UnknownJobType,
)
from app.jobs_and_outbox.retry import RetryPolicy
from app.jobs_and_outbox.runner import execute, run_once

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
#: §17.1 makes retry policy mandatory per job type (T-031). These tests are about leasing, so the
#: policy is deliberately permissive and the retry semantics are exercised in `test_job_retries.py`.
TEST_POLICY = RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=1), jitter=0.0)
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


class NoOpPayload(BaseModel):
    label: str
    count: int = 1


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-job-test")


@pytest.fixture
def registry() -> JobRegistry:
    """A registry per test, so registrations never leak between them."""
    return JobRegistry()


@pytest.fixture
def noop_registry(registry: JobRegistry) -> JobRegistry:
    registry.register(
        "synthetic.noop",
        NoOpPayload,
        lambda session, payload, *, job_id: None,
        retry_policy=TEST_POLICY,
        consequential=False,
    )
    return registry


def add_job(db_session: Session, registry: JobRegistry, **overrides: object) -> Job:
    kwargs: dict[str, object] = {
        "job_type": "synthetic.noop",
        "payload": {"label": "SYNTHETIC"},
        "actor": OPERATOR,
        "registry": registry,
        # Eligible at the fixed NOW these tests lease against. `enqueue` otherwise defaults to
        # the real clock, which is later than NOW and would make every job invisible.
        "run_at": NOW,
    }
    kwargs.update(overrides)
    return enqueue(db_session, **kwargs)  # type: ignore[arg-type]


# --- payload validation before insert (criterion 2) -----------------------------------------------


def test_a_valid_payload_is_queued(db_session: Session, noop_registry: JobRegistry) -> None:
    job = add_job(db_session, noop_registry)
    db_session.flush()

    assert job.state is JobState.QUEUED
    assert job.payload == {"label": "SYNTHETIC", "count": 1}
    assert job.attempt_count == 0


def test_an_invalid_payload_never_reaches_the_queue(
    db_session: Session, noop_registry: JobRegistry
) -> None:
    """§17.1: a malformed job must not be discovered by a worker later."""
    with pytest.raises(InvalidJobPayload) as exc:
        add_job(db_session, noop_registry, payload={"count": "not-a-number"})

    assert "NoOpPayload" in str(exc.value)
    assert db_session.query(Job).count() == 0


def test_an_unregistered_job_type_is_refused(
    db_session: Session, noop_registry: JobRegistry
) -> None:
    """A queued job nobody can run is a silent backlog."""
    with pytest.raises(UnknownJobType):
        add_job(db_session, noop_registry, job_type="synthetic.unregistered")


def test_a_job_without_a_correlation_id_is_refused(
    db_session: Session, noop_registry: JobRegistry
) -> None:
    structlog.contextvars.clear_contextvars()

    with pytest.raises(QueueError, match="correlation_id"):
        add_job(db_session, noop_registry)


def test_registering_a_name_twice_is_refused(registry: JobRegistry) -> None:
    """Two handlers for one name means the one that runs depends on import order."""
    registry.register(
        "synthetic.noop",
        NoOpPayload,
        lambda s, p, *, job_id: None,
        retry_policy=TEST_POLICY,
        consequential=False,
    )

    with pytest.raises(JobRegistryError, match="already registered"):
        registry.register(
            "synthetic.noop",
            NoOpPayload,
            lambda s, p, *, job_id: None,
            retry_policy=TEST_POLICY,
            consequential=False,
        )


# --- leasing and concurrency (criterion 1) --------------------------------------------------------


def test_leasing_marks_the_job_and_counts_the_attempt(
    db_session: Session, noop_registry: JobRegistry
) -> None:
    add_job(db_session, noop_registry)
    db_session.flush()

    leased = lease_jobs(db_session, worker_id="worker-a", limit=5, now=NOW)

    assert len(leased) == 1
    assert leased[0].state is JobState.LEASED
    assert leased[0].leased_by == "worker-a"
    assert leased[0].lease_expires_at is not None
    assert leased[0].attempt_count == 1


def test_a_future_dated_job_is_not_leased(db_session: Session, noop_registry: JobRegistry) -> None:
    add_job(db_session, noop_registry, run_at=NOW + timedelta(hours=1))
    db_session.flush()

    assert lease_jobs(db_session, worker_id="worker-a", now=NOW) == []


def test_higher_priority_is_leased_first(db_session: Session, noop_registry: JobRegistry) -> None:
    add_job(db_session, noop_registry, priority=DEFAULT_PRIORITY, payload={"label": "ordinary"})
    add_job(db_session, noop_registry, priority=1, payload={"label": "urgent"})
    db_session.flush()

    leased = lease_jobs(db_session, worker_id="worker-a", limit=1, now=NOW)

    assert leased[0].payload["label"] == "urgent"


def test_two_concurrent_workers_never_lease_the_same_job(
    migrated_engine: Engine, noop_registry: JobRegistry
) -> None:
    """The criterion-1 case, against two real connections holding real row locks.

    Both workers lease *before* either commits — which is exactly the race `SKIP LOCKED` exists
    to settle. Without it the second worker would block on the first's locks and then take the
    same rows.
    """
    marker = f"conc-{uuid.uuid4().hex[:8]}"
    with Session(migrated_engine) as setup:
        structlog.contextvars.bind_contextvars(correlation_id=marker)
        for index in range(6):
            enqueue(
                setup,
                job_type="synthetic.noop",
                payload={"label": f"{marker}-{index}"},
                actor=OPERATOR,
                registry=noop_registry,
                correlation_id=marker,
            )
        setup.commit()

    try:
        with Session(migrated_engine) as first, Session(migrated_engine) as second:
            first_batch = lease_jobs(first, worker_id="worker-a", limit=3)
            second_batch = lease_jobs(second, worker_id="worker-b", limit=3)
            first_ids = {job.id for job in first_batch}
            second_ids = {job.id for job in second_batch}
            first.commit()
            second.commit()

        assert len(first_ids) == 3, "first worker should have taken a full batch"
        assert len(second_ids) == 3, "second worker should not have blocked"
        assert first_ids.isdisjoint(second_ids), "two workers leased the same job"
    finally:
        # This test commits, unlike the rolled-back `db_session` fixture, so it clears its own
        # jobs. The audit events it produced are deliberately left: `audit_event` is append-only
        # by design (T-011) and refuses DELETE — the session database is thrown away anyway.
        with Session(migrated_engine) as cleanup:
            cleanup.execute(
                text("DELETE FROM job WHERE correlation_id = :marker"), {"marker": marker}
            )
            cleanup.commit()


def test_the_leasing_query_actually_uses_skip_locked(migrated_engine: Engine) -> None:
    """Assert the mechanism, not just the outcome.

    The disjointness test above would still pass without ``SKIP LOCKED`` — the second worker
    would simply *block* until the first committed, then find nothing. That is a very different
    system: one where a slow job stalls every other worker. Checking the compiled SQL pins the
    behaviour that makes leasing non-blocking.
    """
    statement = (
        select(Job.id)
        .where(Job.state.in_(RUNNABLE_STATES))
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    compiled = str(statement.compile(migrated_engine)).upper()

    assert "FOR UPDATE" in compiled
    assert "SKIP LOCKED" in compiled


def test_a_second_lease_finds_nothing_left(db_session: Session, noop_registry: JobRegistry) -> None:
    add_job(db_session, noop_registry)
    db_session.flush()
    lease_jobs(db_session, worker_id="worker-a", now=NOW)

    assert lease_jobs(db_session, worker_id="worker-b", now=NOW) == []


def test_a_leased_job_must_name_its_holder(db_session: Session, noop_registry: JobRegistry) -> None:
    """An orphaned lease is something recovery (T-032) cannot reason about."""
    job = add_job(db_session, noop_registry)
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(text("UPDATE job SET state = 'LEASED' WHERE id = :id"), {"id": job.id})


# --- running a job (criterion 3) ------------------------------------------------------------------


def test_a_job_runs_and_commits_state_and_audit(db_session: Session, registry: JobRegistry) -> None:
    ran: list[str] = []
    registry.register(
        "synthetic.noop",
        NoOpPayload,
        lambda session, payload, *, job_id: ran.append(payload.label),
        retry_policy=TEST_POLICY,
        consequential=False,
    )
    job = add_job(db_session, registry)
    db_session.flush()
    leased = lease_jobs(db_session, worker_id="worker-a", now=NOW)

    assert execute(db_session, leased[0], registry=registry) is True
    db_session.flush()

    assert ran == ["SYNTHETIC"]
    assert job.state is JobState.SUCCEEDED
    assert job.leased_by is None
    events = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="job", entity_id=str(job.id))
        .order_by(AuditEvent.occurred_at)
        .all()
    )
    assert [e.action for e in events] == ["job.enqueued", "job.finished"]
    assert (events[1].from_state, events[1].to_state) == ("leased", "succeeded")


def test_a_handlers_writes_share_the_job_transaction(
    db_session: Session, registry: JobRegistry
) -> None:
    """§7.2: state, audit, and the handler's own work commit together or not at all."""
    written: list[uuid.UUID] = []

    def handler(session: Session, payload: NoOpPayload, *, job_id: uuid.UUID) -> None:
        written.append(job_id)
        assert session is db_session

    registry.register(
        "synthetic.noop", NoOpPayload, handler, retry_policy=TEST_POLICY, consequential=False
    )
    add_job(db_session, registry)
    db_session.flush()
    leased = lease_jobs(db_session, worker_id="worker-a", now=NOW)

    execute(db_session, leased[0], registry=registry)

    assert written == [leased[0].id]


def test_a_failing_handler_does_not_stop_the_queue(
    db_session: Session, registry: JobRegistry
) -> None:
    def explode(session: Session, payload: NoOpPayload, *, job_id: uuid.UUID) -> None:
        raise RuntimeError("SYNTHETIC failure with payload detail inside")

    registry.register(
        "synthetic.noop", NoOpPayload, explode, retry_policy=TEST_POLICY, consequential=False
    )
    job = add_job(db_session, registry)
    db_session.commit()
    leased = lease_jobs(db_session, worker_id="worker-a", now=NOW)

    assert execute(db_session, leased[0], registry=registry) is False
    db_session.commit()

    refreshed = db_session.get(Job, job.id)
    assert refreshed is not None
    assert refreshed.state is JobState.RETRY


def test_a_failure_records_only_the_exception_type(
    db_session: Session, registry: JobRegistry
) -> None:
    """An exception message can quote payload contents (§15.5)."""

    def explode(session: Session, payload: NoOpPayload, *, job_id: uuid.UUID) -> None:
        raise RuntimeError("secret-looking payload detail")

    registry.register(
        "synthetic.noop", NoOpPayload, explode, retry_policy=TEST_POLICY, consequential=False
    )
    job = add_job(db_session, registry)
    db_session.commit()
    leased = lease_jobs(db_session, worker_id="worker-a", now=NOW)
    execute(db_session, leased[0], registry=registry)
    db_session.commit()

    refreshed = db_session.get(Job, job.id)
    assert refreshed is not None
    assert refreshed.last_error == "RuntimeError"
    assert "secret-looking" not in (refreshed.last_error or "")


def test_run_once_reports_nothing_to_do(db_session: Session, noop_registry: JobRegistry) -> None:
    assert run_once(db_session, worker_id="worker-a", registry=noop_registry) == 0


# --- finishing states -----------------------------------------------------------------------------


def test_a_dead_job_must_carry_a_reason(db_session: Session, noop_registry: JobRegistry) -> None:
    """§17.1: permanent failures move to dead "with a human-readable reason"."""
    add_job(db_session, noop_registry)
    db_session.flush()
    leased = lease_jobs(db_session, worker_id="worker-a", now=NOW)

    with pytest.raises(QueueError, match="human-readable reason"):
        mark_dead(db_session, leased[0], actor=OPERATOR, error="   ")


def test_a_dead_job_records_its_reason(db_session: Session, noop_registry: JobRegistry) -> None:
    add_job(db_session, noop_registry)
    db_session.flush()
    leased = lease_jobs(db_session, worker_id="worker-a", now=NOW)

    mark_dead(db_session, leased[0], actor=OPERATOR, error="payload references a deleted campaign")
    db_session.flush()

    assert leased[0].state is JobState.DEAD
    assert leased[0].last_error == "payload references a deleted campaign"


def test_a_retried_job_becomes_runnable_again(
    db_session: Session, noop_registry: JobRegistry
) -> None:
    add_job(db_session, noop_registry)
    db_session.flush()
    leased = lease_jobs(db_session, worker_id="worker-a", now=NOW)

    mark_for_retry(db_session, leased[0], actor=OPERATOR, error="TimeoutError")
    db_session.flush()

    assert leased[0].state is JobState.RETRY
    assert leased[0].leased_by is None
    assert lease_jobs(db_session, worker_id="worker-b", now=NOW)[0].id == leased[0].id


def test_a_succeeded_job_is_terminal(db_session: Session, noop_registry: JobRegistry) -> None:
    add_job(db_session, noop_registry)
    db_session.flush()
    leased = lease_jobs(db_session, worker_id="worker-a", now=NOW)
    mark_succeeded(db_session, leased[0], actor=OPERATOR)

    with pytest.raises(IllegalTransition):
        mark_for_retry(db_session, leased[0], actor=OPERATOR, error="too late")


def test_a_queued_job_can_be_cancelled(db_session: Session, noop_registry: JobRegistry) -> None:
    job = add_job(db_session, noop_registry)
    db_session.flush()

    cancel(db_session, job, actor=OPERATOR, reason="campaign paused")
    db_session.flush()

    assert job.state is JobState.CANCELLED
    assert lease_jobs(db_session, worker_id="worker-a", now=NOW) == []


def test_lease_expiry_is_detectable(db_session: Session, noop_registry: JobRegistry) -> None:
    """The signal T-032's recovery sweep will act on."""
    add_job(db_session, noop_registry)
    db_session.flush()
    leased = lease_jobs(db_session, worker_id="worker-a", now=NOW)

    assert not leased[0].is_lease_expired_at(NOW)
    assert leased[0].is_lease_expired_at(NOW + timedelta(hours=1))
