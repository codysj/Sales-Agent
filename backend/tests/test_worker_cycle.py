"""The worker's composed cycle (T-139; §17.2 step 4, §18.1, §17.6).

`run_once`, `dispatch_once`, and both reclaims each have their own tests. This file tests the thing
none of those can: that a *running worker* actually calls them. Before `T-139` every one of those
functions was tested and callable, and nothing in a running process called the outbox ones — so a
committed decision never reached its effect without a human.

`one_pass` rather than `main`, because `main` adds only a `while` loop, a signal handler, and a
sleep, none of which can be asserted on without a process.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.flags import FlagKey, set_flag
from app.core.settings import Settings
from app.jobs_and_outbox.dispatch import lease_outbox_events
from app.jobs_and_outbox.outbox import OutboxEvent, OutboxState, enqueue_outbox_event
from app.outreach_and_replies.adapters import build_effect_adapter
from app.outreach_and_replies.adapters.fake import FakeExternalEffectAdapter
from app.outreach_and_replies.commands import create_send_command
from app.prospects.models import Account
from app.worker import PassResult, one_pass
from tests.factories import APPROVER, NOW, OPERATOR, World

WORKER_ID = "worker-under-test"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-worker-test")


def live_settings() -> Settings:
    """Both deploy-time switches off, so the test is about the worker and not about shadow mode."""
    return Settings(shadow_mode=False, outbound_email_enabled=True)


@pytest.fixture
def world(db_session: Session) -> World:
    w = World(db_session)
    w.activate()
    return w


def a_dispatchable_event(db_session: Session, world: World) -> OutboxEvent:
    """A pending outbox event with a valid §11.4 contract behind it."""
    command = create_send_command(
        db_session,
        thread=world.thread,
        approval=world.approval(),
        campaign_id=world.campaign.id,
        actor=OPERATOR,
        record_versions={"approver_id": APPROVER},
        now=NOW,
    )
    db_session.flush()
    event = enqueue_outbox_event(
        db_session,
        event_type="send.email",
        idempotency_key=command.idempotency_key,
        actor=OPERATOR,
        payload={"channel": "email"},
    )
    db_session.flush()
    return event


# --- the adapter the worker uses ---------------------------------------------------------------


def test_the_worker_dispatches_through_the_fake_adapter() -> None:
    """Stage 1 has no provider account; `G-07` is what changes that (§19.6)."""
    assert isinstance(build_effect_adapter(live_settings()), FakeExternalEffectAdapter)


def test_the_worker_adapter_is_subject_to_the_email_switch() -> None:
    """`is_email` is what makes `OUTBOUND_EMAIL_DISABLED` apply to it as well as shadow mode."""
    assert build_effect_adapter(live_settings()).is_email is True


def test_the_adapter_is_the_fake_even_with_every_switch_off() -> None:
    """There is no configuration path to a real adapter, because none exists to configure."""
    assert isinstance(
        build_effect_adapter(Settings(shadow_mode=False, outbound_email_enabled=True)),
        FakeExternalEffectAdapter,
    )


# --- one pass dispatches (criterion 1) ---------------------------------------------------------


def test_one_pass_dispatches_a_pending_outbox_event(db_session: Session, world: World) -> None:
    """Criterion 1 — the gap `T-139` exists to close."""
    event = a_dispatchable_event(db_session, world)
    adapter = FakeExternalEffectAdapter()

    result = one_pass(db_session, worker_id=WORKER_ID, adapter=adapter, settings=live_settings())

    assert result.events_dispatched == 1
    assert event.state is OutboxState.DISPATCHED
    assert adapter.effect_count == 1


def test_one_pass_applies_the_dispatch_time_rechecks(db_session: Session, world: World) -> None:
    """The composition detail that matters most.

    `jobs_and_outbox` cannot import `outreach_and_replies` (§18.2), so the §11.4 check has to be
    injected here or it never runs in production. Pausing the campaign proves the worker really
    passes it: without the injection the send would go through.
    """
    event = a_dispatchable_event(db_session, world)
    world.campaign.paused = True
    db_session.flush()
    adapter = FakeExternalEffectAdapter()

    one_pass(db_session, worker_id=WORKER_ID, adapter=adapter, settings=live_settings())

    assert adapter.calls == [], "the recheck must have refused before the adapter was reached"
    assert adapter.effect_count == 0
    assert event.state is OutboxState.PENDING, "a paused campaign is recoverable, so it is held"


def test_one_pass_reports_an_idle_cycle(db_session: Session) -> None:
    """`did_nothing` is what `main` sleeps on, so it has to mean what it says."""
    result = one_pass(
        db_session,
        worker_id=WORKER_ID,
        adapter=FakeExternalEffectAdapter(),
        settings=live_settings(),
    )

    assert result == PassResult(
        jobs_reclaimed=0, jobs_run=0, dispatch_leases_reclaimed=0, events_dispatched=0
    )
    assert result.did_nothing is True


def test_a_pass_that_dispatched_is_not_idle(db_session: Session, world: World) -> None:
    a_dispatchable_event(db_session, world)

    result = one_pass(
        db_session,
        worker_id=WORKER_ID,
        adapter=FakeExternalEffectAdapter(),
        settings=live_settings(),
    )

    assert result.did_nothing is False


# --- one pass recovers dispatch leases (criterion 2) -------------------------------------------


def test_one_pass_reclaims_an_expired_dispatch_lease(db_session: Session, world: World) -> None:
    """Criterion 2. Before this, no running process reclaimed a dead dispatcher's lease."""
    marker = f"reclaim{uuid.uuid4().hex[:6]}"
    db_session.add(Account(name=f"Synthetic {marker}", domain=f"{marker}.invalid"))
    enqueue_outbox_event(
        db_session,
        event_type="send.email",
        idempotency_key=hashlib.sha256(marker.encode()).hexdigest(),
        actor=OPERATOR,
    )
    db_session.flush()
    stranded = lease_outbox_events(db_session, dispatcher_id="dispatcher-doomed", limit=1)[0]
    # Backdate the lease rather than travelling forward: `one_pass` takes no `now`, because a real
    # worker has no reason to accept one.
    stranded.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.flush()

    result = one_pass(
        db_session,
        worker_id=WORKER_ID,
        adapter=FakeExternalEffectAdapter(),
        settings=live_settings(),
    )

    assert result.dispatch_leases_reclaimed == 1
    assert stranded.state is OutboxState.DELIVERY_UNKNOWN, "ambiguous, not requeued (§17.3)"


def test_one_pass_reclaims_an_expired_job_lease(db_session: Session, world: World) -> None:
    """The job half, so a regression in either reclaim is visible from the worker's own tests."""
    from pydantic import BaseModel

    from app.jobs_and_outbox.models import Job
    from app.jobs_and_outbox.queue import enqueue, lease_jobs
    from app.jobs_and_outbox.registry import JobRegistry
    from app.jobs_and_outbox.retry import RetryPolicy

    class Payload(BaseModel):
        label: str

    registry = JobRegistry()
    registry.register(
        "synthetic.noop",
        Payload,
        lambda s, p, *, job_id: None,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=timedelta(seconds=1), jitter=0.0),
        consequential=False,
    )
    enqueue(
        db_session,
        job_type="synthetic.noop",
        payload={"label": "SYNTHETIC"},
        actor=OPERATOR,
        registry=registry,
    )
    db_session.flush()
    job = lease_jobs(db_session, worker_id="worker-doomed", limit=1)[0]
    job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.flush()

    result = one_pass(
        db_session,
        worker_id=WORKER_ID,
        adapter=FakeExternalEffectAdapter(),
        settings=live_settings(),
    )

    assert result.jobs_reclaimed == 1
    assert db_session.get(Job, job.id) is not None


# --- shadow mode leaves everything alone (criterion 3) -----------------------------------------


def test_shadow_mode_leaves_a_pending_event_pending(db_session: Session, world: World) -> None:
    """Criterion 3, and the property that matters most while `G-07` is locked.

    The worker still *attempts* the dispatch — refusing to try would hide the switch. What must not
    happen is an effect. The kill switch is enforced inside the adapter's inherited guard, so the
    event ends up back in `PENDING` rather than dispatched.
    """
    event = a_dispatchable_event(db_session, world)
    adapter = FakeExternalEffectAdapter()

    one_pass(db_session, worker_id=WORKER_ID, adapter=adapter, settings=Settings())

    assert adapter.calls == [], "shadow mode must stop the adapter before it acts"
    assert adapter.effect_count == 0
    assert event.state is OutboxState.PENDING, "and the work must not be lost"


def test_the_shadow_mode_flag_also_stops_the_worker(db_session: Session, world: World) -> None:
    """The runtime switch, not only the deploy-time one (§17.6)."""
    event = a_dispatchable_event(db_session, world)
    set_flag(db_session, key=FlagKey.SHADOW_MODE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()
    adapter = FakeExternalEffectAdapter()

    one_pass(db_session, worker_id=WORKER_ID, adapter=adapter, settings=live_settings())

    assert adapter.effect_count == 0
    assert event.state is OutboxState.PENDING


def test_a_global_pause_stops_the_worker_dispatching(db_session: Session, world: World) -> None:
    event = a_dispatchable_event(db_session, world)
    set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()
    adapter = FakeExternalEffectAdapter()

    one_pass(db_session, worker_id=WORKER_ID, adapter=adapter, settings=live_settings())

    assert adapter.effect_count == 0
    assert event.state is OutboxState.PENDING


def test_the_shipped_defaults_dispatch_nothing(db_session: Session, world: World) -> None:
    """`Settings()` is what a worker starts with if nobody configures it (§19.6 Stage 1)."""
    a_dispatchable_event(db_session, world)
    adapter = build_effect_adapter(Settings())

    one_pass(db_session, worker_id=WORKER_ID, adapter=adapter, settings=Settings())

    assert adapter.effect_count == 0


# --- the composition is real, not incidental ---------------------------------------------------


def test_the_worker_actually_calls_the_outbox_dispatcher() -> None:
    """A structural guard on the gap `T-139` closed.

    `one_pass` referencing `dispatch_once` and `reclaim_expired_dispatch_leases` by name is what
    makes the outbox reachable from a running process at all. An edit that drops either call would
    restore exactly the silent gap this task existed to fix, and the behavioural tests above would
    catch it — this asserts it at the source, where the omission would be made.
    """
    referenced = one_pass.__code__.co_names

    assert "dispatch_once" in referenced
    assert "reclaim_expired_dispatch_leases" in referenced
    assert "reclaim_expired_leases" in referenced
    assert "run_once" in referenced
    assert "send_precondition_check" in referenced


def test_the_dispatched_event_kept_its_send_command_key(db_session: Session, world: World) -> None:
    """End to end, the §17.3 key survives from approval to provider."""
    event = a_dispatchable_event(db_session, world)
    adapter = FakeExternalEffectAdapter()

    one_pass(db_session, worker_id=WORKER_ID, adapter=adapter, settings=live_settings())

    stored = db_session.execute(select(OutboxEvent).where(OutboxEvent.id == event.id)).scalar_one()
    assert adapter.calls[0].idempotency_key == stored.idempotency_key
    assert stored.provider_correlation_id is not None
