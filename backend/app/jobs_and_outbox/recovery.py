"""Lease expiry recovery (specification §17.1, §17.4, §19.5).

§19.5 asks what happens when a worker crashes mid-job. The answer PostgreSQL-as-a-queue gives is
that nothing is lost: the job is a row, its lease has an expiry, and once that passes another worker
may take it. This module is the "once that passes" part.

**A crash consumes exactly one attempt, and the reclaim does not add another.** `lease_jobs` already
incremented `attempt_count` when the lease was taken, so the crashed attempt is counted. Counting it
again here would charge one crash twice, and a job that crashes its worker would dead-letter in half
the configured attempts. That matters in the direction that bites: a genuinely poisonous job still
exhausts its budget and stops, but a job caught by one unlucky restart keeps the retries its policy
promised. A test pins the count at 1 after one crash.

**Reclaim can only see `LEASED` rows.** A job that finished — successfully or not — has no lease
(the `leased_state_needs_a_holder` check constraint makes that structural), so a completed job is
invisible to the query below. That, not a separate guard, is what stops an effect from being redone:
if the outcome was recorded, the transaction that recorded it also released the lease, because
`T-030` puts both in the same transaction.

**Outbox dispatch leases recover differently, and the difference is the whole point.** A job that
died mid-run committed nothing, so returning it to `queued` is safe. A *dispatcher* that died may
have reached the provider first — the effect may have happened and the acknowledgement been lost —
so requeueing it would be precisely the blind retry §17.3 forbids. An expired dispatch lease
therefore resolves to `DELIVERY_UNKNOWN`, and reconciliation is the only way out (`T-138`).
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor, record_audit_event
from app.core.lifecycles import JobState, assert_transition
from app.jobs_and_outbox.dispatch import EffectOutcome
from app.jobs_and_outbox.models import Job
from app.jobs_and_outbox.outbox import ENTITY_TYPE as OUTBOX_ENTITY_TYPE
from app.jobs_and_outbox.outbox import (
    OutboxEvent,
    OutboxState,
    assert_outbox_transition,
)
from app.jobs_and_outbox.queue import ENTITY_TYPE

log = structlog.get_logger(__name__)

#: Reclaim runs unattended, so the actor is the system rather than an unknown human (§12.2).
RECOVERY_ACTOR = Actor(type=ActorType.SERVICE, id="lease-recovery")

#: How many expired leases one pass reclaims. Bounded so a long outage that expired thousands of
#: leases does not turn recovery into one enormous transaction.
DEFAULT_RECLAIM_LIMIT = 100


def find_expired_leases(
    session: Session, *, now: datetime | None = None, limit: int = DEFAULT_RECLAIM_LIMIT
) -> list[Job]:
    """Jobs whose lease has run out, locked for this transaction.

    `FOR UPDATE SKIP LOCKED` for the same reason as leasing: two recovery passes must not reclaim
    one job, and neither may block behind the other.
    """
    moment = now or datetime.now(UTC)

    ids = (
        session.execute(
            select(Job.id)
            .where(Job.state == JobState.LEASED, Job.lease_expires_at <= moment)
            .order_by(Job.lease_expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    if not ids:
        return []

    return list(session.execute(select(Job).where(Job.id.in_(ids))).scalars().all())


def reclaim_expired_leases(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = DEFAULT_RECLAIM_LIMIT,
    actor: Actor = RECOVERY_ACTOR,
) -> list[Job]:
    """Return jobs whose lease expired to the queue. Does not commit.

    The caller's transaction decides whether the reclaim sticks, so the state change and its audit
    event land together or not at all (§17.2).
    """
    moment = now or datetime.now(UTC)
    reclaimed: list[Job] = []

    for job in find_expired_leases(session, now=moment, limit=limit):
        previous = job.state
        assert_transition(previous, JobState.QUEUED)

        held_by = job.leased_by
        expired_at = job.lease_expires_at

        job.state = JobState.QUEUED
        job.leased_by = None
        job.lease_expires_at = None
        # `attempt_count` is deliberately untouched — see the module docstring.
        session.flush()

        record_audit_event(
            session,
            actor=actor,
            action="job.lease_reclaimed",
            entity_type=ENTITY_TYPE,
            entity_id=job.id,
            from_state=previous,
            to_state=JobState.QUEUED,
            payload={
                "job_type": job.job_type,
                "attempt": job.attempt_count,
                # Who held the lease, so an operator can tell one dead worker from a flapping fleet.
                "previous_holder": held_by,
                "lease_expired_at": expired_at.isoformat() if expired_at else None,
            },
            correlation_id=job.correlation_id,
        )
        reclaimed.append(job)

    if reclaimed:
        log.warning(
            "job.leases_reclaimed",
            count=len(reclaimed),
            job_types=sorted({job.job_type for job in reclaimed}),
        )
    return reclaimed


# --- outbox dispatch leases (T-138) --------------------------------------------------------------


def find_expired_dispatch_leases(
    session: Session, *, now: datetime | None = None, limit: int = DEFAULT_RECLAIM_LIMIT
) -> list[OutboxEvent]:
    """Outbox events whose dispatch lease has run out, locked for this transaction."""
    moment = now or datetime.now(UTC)

    ids = (
        session.execute(
            select(OutboxEvent.id)
            .where(
                OutboxEvent.state == OutboxState.DISPATCHING,
                OutboxEvent.lease_expires_at <= moment,
            )
            .order_by(OutboxEvent.lease_expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    if not ids:
        return []

    return list(session.execute(select(OutboxEvent).where(OutboxEvent.id.in_(ids))).scalars().all())


def reclaim_expired_dispatch_leases(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = DEFAULT_RECLAIM_LIMIT,
    actor: Actor = RECOVERY_ACTOR,
) -> list[OutboxEvent]:
    """Resolve outbox events whose dispatcher died to `DELIVERY_UNKNOWN`. Does not commit.

    **Not** back to `PENDING`. The dispatcher held this lease while talking to a provider; it may
    have been accepted before the process died, with the acknowledgement lost. §17.3 forbids
    retrying that blindly, and `DELIVERY_UNKNOWN` is the state that says so: it is not a
    dispatchable state, so no worker can pick the event up again, and `reconcile_unknown` is the
    only exit.

    Doing nothing would also be safe, but it would strand the event in `DISPATCHING` forever with a
    lease nobody holds, invisible to both the dispatcher and to reconciliation.
    """
    moment = now or datetime.now(UTC)
    reclaimed: list[OutboxEvent] = []

    for event in find_expired_dispatch_leases(session, now=moment, limit=limit):
        previous = event.state
        assert_outbox_transition(previous, OutboxState.DELIVERY_UNKNOWN)

        held_by = event.leased_by
        expired_at = event.lease_expires_at

        event.state = OutboxState.DELIVERY_UNKNOWN
        event.leased_by = None
        event.lease_expires_at = None
        event.last_outcome = EffectOutcome.AMBIGUOUS.value
        event.last_detail = (
            f"dispatch lease held by {held_by!r} expired without a recorded result; the effect may "
            f"or may not have happened (§17.3)"
        )
        session.flush()

        record_audit_event(
            session,
            actor=actor,
            action="outbox.lease_reclaimed",
            entity_type=OUTBOX_ENTITY_TYPE,
            entity_id=event.id,
            from_state=previous,
            to_state=OutboxState.DELIVERY_UNKNOWN,
            payload={
                "event_type": event.event_type,
                "attempt": event.attempt_count,
                "previous_holder": held_by,
                "lease_expired_at": expired_at.isoformat() if expired_at else None,
            },
            correlation_id=event.correlation_id,
        )
        reclaimed.append(event)

    if reclaimed:
        # Warning, not info: every one of these is an external effect whose outcome is unknown and
        # which now needs reconciliation before anything else can happen to it.
        log.warning(
            "outbox.leases_reclaimed",
            count=len(reclaimed),
            event_types=sorted({event.event_type for event in reclaimed}),
        )
    return reclaimed
