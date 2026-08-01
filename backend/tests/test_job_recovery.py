"""Lease expiry recovery (T-032; §17.1, §17.4, §19.5).

§19.5's question is "what happens when a worker crashes during a job". These tests answer it against
real transactions rather than by mocking a crash: a session leases a job, does some work, and is
rolled back without committing — which is exactly what a `SIGKILL` looks like to PostgreSQL.

The property that matters is that a crash loses no work *and* duplicates no effect.
"""

import uuid
from datetime import timedelta

import pytest
import structlog
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.core.lifecycles import ALLOWED_TRANSITIONS, JobState
from app.jobs_and_outbox.models import Job
from app.jobs_and_outbox.queue import enqueue, lease_jobs
from app.jobs_and_outbox.recovery import (
    RECOVERY_ACTOR,
    find_expired_leases,
    reclaim_expired_leases,
)
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.retry import RetryPolicy
from app.jobs_and_outbox.runner import execute
from app.prospects.models import Account
from tests.factories import NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
POLICY = RetryPolicy(max_attempts=3, base_delay=timedelta(seconds=1), jitter=0.0)


class EffectPayload(BaseModel):
    marker: str


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-recovery-test")


def effect_registry() -> JobRegistry:
    """A job type whose handler writes one committed row — a side effect we can count.

    An `Account` row rather than a counter in memory: the question is what *survives a rollback*,
    and only real database state can answer that.
    """

    def handler(session: Session, payload: BaseModel, *, job_id: object) -> None:
        assert isinstance(payload, EffectPayload)
        session.add(Account(name=f"SYNTHETIC {payload.marker}", domain=f"{payload.marker}.invalid"))

    registry = JobRegistry()
    registry.register(
        "synthetic.effect", EffectPayload, handler, retry_policy=POLICY, consequential=False
    )
    return registry


def add_job(session: Session, registry: JobRegistry, marker: str) -> Job:
    job = enqueue(
        session,
        job_type="synthetic.effect",
        payload={"marker": marker},
        actor=OPERATOR,
        registry=registry,
        run_at=NOW,
    )
    session.flush()
    return job


def effects_for(session: Session, marker: str) -> int:
    return session.execute(
        select(func.count(Account.id)).where(Account.domain == f"{marker}.invalid")
    ).scalar_one()


# --- finding expired leases --------------------------------------------------------------------


def test_a_live_lease_is_not_reclaimed(db_session: Session) -> None:
    """The whole design rests on this: a worker still working must not have its job taken."""
    registry = effect_registry()
    add_job(db_session, registry, "live")
    lease_jobs(db_session, worker_id="worker-a", limit=1, now=NOW)

    assert reclaim_expired_leases(db_session, now=NOW) == []


def test_an_expired_lease_is_reclaimed(db_session: Session) -> None:
    registry = effect_registry()
    add_job(db_session, registry, "expired")
    leased = lease_jobs(db_session, worker_id="worker-a", limit=1, now=NOW)[0]
    assert leased.lease_expires_at is not None
    later = leased.lease_expires_at + timedelta(seconds=1)

    reclaimed = reclaim_expired_leases(db_session, now=later)

    assert [job.id for job in reclaimed] == [leased.id]
    assert leased.state is JobState.QUEUED
    assert leased.leased_by is None
    assert leased.lease_expires_at is None


def test_a_queued_job_is_never_a_reclaim_candidate(db_session: Session) -> None:
    registry = effect_registry()
    add_job(db_session, registry, "queued")

    assert find_expired_leases(db_session, now=NOW + timedelta(days=1)) == []


def test_a_finished_job_is_invisible_to_reclaim(db_session: Session) -> None:
    """Not a separate guard — a finished job has no lease, so the query cannot see it.

    `leased_state_needs_a_holder` makes that structural: only a `LEASED` row may hold a lease, and
    the transaction that recorded the outcome released it (`T-030` commits both together).
    """
    registry = effect_registry()
    add_job(db_session, registry, "finished")
    job = lease_jobs(db_session, worker_id="worker-a", limit=1, now=NOW)[0]
    execute(db_session, job, registry=registry)
    db_session.flush()
    assert job.state is JobState.SUCCEEDED

    assert reclaim_expired_leases(db_session, now=NOW + timedelta(days=1)) == []


def test_reclaim_is_bounded(db_session: Session) -> None:
    """A long outage must not turn recovery into one enormous transaction."""
    registry = effect_registry()
    for index in range(5):
        add_job(db_session, registry, f"bulk{index}")
    lease_jobs(db_session, worker_id="worker-a", limit=5, now=NOW)

    reclaimed = reclaim_expired_leases(db_session, now=NOW + timedelta(hours=1), limit=2)

    assert len(reclaimed) == 2


# --- the attempt budget ------------------------------------------------------------------------


def test_a_crash_consumes_exactly_one_attempt(db_session: Session) -> None:
    """The reclaim adds nothing to `attempt_count`, because the lease already charged it.

    Charging twice would dead-letter a job in half its configured attempts — so one unlucky restart
    would cost a job the retries its policy promised.
    """
    registry = effect_registry()
    add_job(db_session, registry, "budget")
    job = lease_jobs(db_session, worker_id="worker-a", limit=1, now=NOW)[0]
    assert job.attempt_count == 1

    reclaim_expired_leases(db_session, now=NOW + timedelta(hours=1))

    assert job.attempt_count == 1


def test_repeated_crashes_still_exhaust_the_budget(db_session: Session) -> None:
    """The other direction: a job that keeps killing workers must not retry forever."""
    registry = effect_registry()
    add_job(db_session, registry, "poison")
    moment = NOW

    for expected in (1, 2, 3):
        job = lease_jobs(db_session, worker_id="worker-a", limit=1, now=moment)[0]
        assert job.attempt_count == expected
        moment += timedelta(hours=1)
        reclaim_expired_leases(db_session, now=moment)

    assert job.attempt_count == POLICY.max_attempts


# --- the audit trail (criterion 3) -------------------------------------------------------------


def test_reclaim_writes_an_audit_event(db_session: Session) -> None:
    registry = effect_registry()
    add_job(db_session, registry, "audited")
    job = lease_jobs(db_session, worker_id="worker-a", limit=1, now=NOW)[0]

    reclaim_expired_leases(db_session, now=NOW + timedelta(hours=1))
    db_session.flush()

    audit = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(job.id), AuditEvent.action == "job.lease_reclaimed"
        )
    ).scalar_one()
    assert audit.from_state == JobState.LEASED.value
    assert audit.to_state == JobState.QUEUED.value
    assert audit.actor_id == RECOVERY_ACTOR.id
    # An operator needs to tell one dead worker from a flapping fleet.
    assert audit.payload["previous_holder"] == "worker-a"
    assert audit.payload["lease_expired_at"]


def test_only_a_leased_job_may_return_to_the_queue() -> None:
    """`LEASED -> QUEUED` exists in the table specifically for reclaim (§17.1), and nowhere else.

    `reclaim_expired_leases` calls `assert_transition` even though its own query can only ever
    select `LEASED` rows, so the assertion cannot fire today — a negative control that removes it
    breaks nothing, and that is recorded rather than papered over. It is there for the edit that
    widens the query. What *is* pinned here is the rule the assertion enforces: no terminal or
    already-queued state has a path back to `queued`, so a widened query would fail loudly.
    """
    assert JobState.QUEUED in ALLOWED_TRANSITIONS[JobState.LEASED]

    for state in (JobState.SUCCEEDED, JobState.DEAD, JobState.CANCELLED, JobState.QUEUED):
        assert JobState.QUEUED not in ALLOWED_TRANSITIONS[state], (
            f"{state.value} must not be reclaimable"
        )


# --- a simulated crash (criteria 1 and 2) -------------------------------------------------------


def test_a_crash_before_commit_leaves_no_effect_and_loses_no_work(
    migrated_engine: Engine,
) -> None:
    """Criterion 2, against a real rollback.

    A worker leases the job, its handler writes the effect, and the process dies before committing.
    PostgreSQL rolls the whole transaction back — including the lease — so the job is still `queued`
    and the effect never happened. Recovery then runs it exactly once.
    """
    marker = f"crash{uuid.uuid4().hex[:8]}"
    registry = effect_registry()

    try:
        with Session(migrated_engine) as setup:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            add_job(setup, registry, marker)
            setup.commit()

        # The crash: lease, run, never commit.
        with Session(migrated_engine) as crashing:
            job = lease_jobs(crashing, worker_id="worker-doomed", limit=1)[0]
            execute(crashing, job, registry=registry)
            crashing.rollback()

        with Session(migrated_engine) as check:
            assert effects_for(check, marker) == 0, "an uncommitted effect must not survive"
            stored = check.execute(
                select(Job).where(Job.job_type == "synthetic.effect", Job.correlation_id == marker)
            ).scalar_one()
            assert stored.state is JobState.QUEUED, "the lease died with the transaction"
            assert stored.attempt_count == 0, "and so did the attempt it had charged"

        # Recovery: a healthy worker takes it and finishes.
        with Session(migrated_engine) as healthy:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            reclaim_expired_leases(healthy)
            job = lease_jobs(healthy, worker_id="worker-healthy", limit=1)[0]
            execute(healthy, job, registry=registry)
            healthy.commit()

        with Session(migrated_engine) as check:
            assert effects_for(check, marker) == 1, "exactly one committed effect"
            stored = check.execute(
                select(Job).where(Job.job_type == "synthetic.effect", Job.correlation_id == marker)
            ).scalar_one()
            assert stored.state is JobState.SUCCEEDED
    finally:
        cleanup(migrated_engine, marker)


def test_a_lease_that_outlives_its_worker_is_reclaimed_and_run_once(
    migrated_engine: Engine,
) -> None:
    """The harder shape: the lease was *committed* before the worker died.

    This is the case recovery exists for. The lease survives in the database with nobody working
    it, so without reclaim the job would sit `leased` forever. Afterwards it must have run once.
    """
    marker = f"orphan{uuid.uuid4().hex[:8]}"
    registry = effect_registry()

    try:
        with Session(migrated_engine) as setup:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            add_job(setup, registry, marker)
            # Lease and commit, then "die" without ever finishing the job.
            lease_jobs(setup, worker_id="worker-doomed", limit=1)
            setup.commit()

        with Session(migrated_engine) as check:
            stranded = check.execute(select(Job).where(Job.correlation_id == marker)).scalar_one()
            assert stranded.state is JobState.LEASED
            assert stranded.leased_by == "worker-doomed"
            assert effects_for(check, marker) == 0

        with Session(migrated_engine) as healthy:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            # Nothing to reclaim yet: the lease has not expired.
            assert reclaim_expired_leases(healthy) == []
            stranded = healthy.execute(select(Job).where(Job.correlation_id == marker)).scalar_one()
            assert stranded.lease_expires_at is not None
            future = stranded.lease_expires_at + timedelta(seconds=1)

            assert len(reclaim_expired_leases(healthy, now=future)) == 1
            job = lease_jobs(healthy, worker_id="worker-healthy", limit=1, now=future)[0]
            execute(healthy, job, registry=registry)
            healthy.commit()

        with Session(migrated_engine) as check:
            assert effects_for(check, marker) == 1
            stored = check.execute(select(Job).where(Job.correlation_id == marker)).scalar_one()
            assert stored.state is JobState.SUCCEEDED
            assert stored.attempt_count == 2, "the crashed attempt plus the successful one"
    finally:
        cleanup(migrated_engine, marker)


def test_two_recovery_passes_reclaim_a_job_exactly_once(migrated_engine: Engine) -> None:
    """Criterion 1, against two real connections holding real row locks.

    Two reclaims of one job would produce two queued copies of the same work — or, with the state
    machine enforcing transitions, an `IllegalTransition` crash in whichever pass ran second.
    """
    marker = f"race{uuid.uuid4().hex[:8]}"
    registry = effect_registry()

    try:
        with Session(migrated_engine) as setup:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            for index in range(4):
                add_job(setup, registry, f"{marker}-{index}")
            leased = lease_jobs(setup, worker_id="worker-doomed", limit=4)
            expiry = leased[0].lease_expires_at
            assert expiry is not None
            setup.commit()

        future = expiry + timedelta(seconds=1)
        with Session(migrated_engine) as first, Session(migrated_engine) as second:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            first_ids = {job.id for job in reclaim_expired_leases(first, now=future, limit=2)}
            second_ids = {job.id for job in reclaim_expired_leases(second, now=future, limit=2)}
            first.commit()
            second.commit()

        assert len(first_ids) == 2
        assert len(second_ids) == 2, "the second pass must not have blocked"
        assert first_ids.isdisjoint(second_ids), "one job was reclaimed twice"
    finally:
        cleanup(migrated_engine, marker)


def cleanup(engine: Engine, marker: str) -> None:
    """These tests commit, unlike the rolled-back `db_session` fixture.

    Audit events are deliberately left behind: `audit_event` is append-only by design (`T-011`) and
    refuses DELETE. The session database is thrown away anyway.
    """
    with Session(engine) as session:
        for job in session.execute(select(Job).where(Job.correlation_id == marker)).scalars().all():
            session.delete(job)
        for account in (
            session.execute(select(Account).where(Account.name.like(f"SYNTHETIC {marker}%")))
            .scalars()
            .all()
        ):
            session.delete(account)
        session.commit()
