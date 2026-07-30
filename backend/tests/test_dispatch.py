"""The external-effect boundary and the outbox dispatcher (T-035a, T-035b; §17.2, §17.3, ADR-016).

Three things are being pinned here. That the boundary *cannot* act while a kill switch is on — not
that it happens not to. That an outcome which might have happened is representable, so the
dispatcher is never forced to guess between "sent" and "failed". And that an ambiguous result is
never retried blindly: `DELIVERY_UNKNOWN` is simply not a leasable state, so there is no branch to
forget.
"""

import ast
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.audit_and_operations.flags import (
    ConsequentialWorkPaused,
    ExternalEffectBlocked,
    FlagKey,
    set_flag,
)
from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.core.settings import Settings
from app.jobs_and_outbox.dispatch import (
    SAFE_TO_RETRY,
    DispatchRefused,
    EffectOutcome,
    EffectRequest,
    EffectResult,
    ExternalEffectAdapter,
    SupportsReconciliation,
    dispatch_event,
    dispatch_once,
    lease_outbox_events,
    reconcile_unknown,
)
from app.jobs_and_outbox.outbox import (
    DISPATCHABLE_STATES,
    OUTBOX_TRANSITIONS,
    IllegalOutboxTransition,
    OutboxError,
    OutboxEvent,
    OutboxState,
    assert_outbox_transition,
    enqueue_outbox_event,
)
from app.jobs_and_outbox.recovery import (
    RECOVERY_ACTOR,
    find_expired_dispatch_leases,
    reclaim_expired_dispatch_leases,
)
from app.outreach_and_replies.adapters.fake import (
    FakeExternalEffectAdapter,
    Scenario,
)
from app.prospects.models import Account

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
KEY = "a" * 64

#: Modules that make up the dispatch path. Criterion 2 is asserted against exactly these.
DISPATCH_PATH = (
    Path("app/jobs_and_outbox/dispatch.py"),
    Path("app/jobs_and_outbox/outbox.py"),
    Path("app/jobs_and_outbox/runner.py"),
    Path("app/jobs_and_outbox/queue.py"),
    # Added with `T-138`: recovery now settles outbox events, so it is on the dispatch path and
    # must be held to the same no-network rule.
    Path("app/jobs_and_outbox/recovery.py"),
    Path("app/outreach_and_replies/adapters/__init__.py"),
    Path("app/outreach_and_replies/adapters/fake.py"),
)

#: Anything that could reach a network. Gate **G-07** is what unlocks a real client.
NETWORK_MODULES = frozenset(
    {
        "smtplib",
        "imaplib",
        "poplib",
        "socket",
        "ssl",
        "http",
        "urllib",
        "urllib3",
        "httpx",
        "httpx2",
        "requests",
        "aiohttp",
        "websockets",
        "ftplib",
        "telnetlib",
        "xmlrpc",
        "boto3",
        "google",
        "sendgrid",
        "hubspot",
    }
)


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-dispatch-test")


def unlocked_settings() -> Settings:
    """Every deploy-time switch off, so a test can prove some *other* thing does the blocking."""
    return Settings(shadow_mode=False, outbound_email_enabled=True)


def a_request(key: str = KEY) -> EffectRequest:
    return EffectRequest(idempotency_key=key, event_type="send.email", payload={"channel": "email"})


# --- no network client in the dispatch path (criterion 2) ------------------------------------


def imported_modules(path: Path) -> set[str]:
    """Top-level module names imported by a file, from its AST rather than from a text search."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("module_path", DISPATCH_PATH, ids=lambda p: str(p))
def test_no_network_client_exists_in_the_dispatch_path(module_path: Path) -> None:
    """Criterion 2, by inspection rather than by convention.

    Parsed with `ast`, not grepped: a text search would be fooled by the word appearing in a
    comment, and — more importantly — would miss an import written any way but the one searched
    for. Stage 1 has no provider account, and gate **G-07** is what changes that.
    """
    assert module_path.exists(), f"{module_path} is listed in DISPATCH_PATH but does not exist"

    offending = imported_modules(module_path) & NETWORK_MODULES

    assert not offending, f"{module_path} imports {sorted(offending)}; §19.6 gates this behind G-07"


def test_the_dispatch_path_list_is_not_silently_empty() -> None:
    """A guard on the guard: an empty parametrize list would make the test above vacuous."""
    assert len(DISPATCH_PATH) >= 7


# --- the guard cannot be bypassed (criterion 1) ----------------------------------------------


def test_the_adapter_acts_when_every_switch_permits_it(db_session: Session) -> None:
    adapter = FakeExternalEffectAdapter()

    result = adapter.perform(db_session, unlocked_settings(), a_request())

    assert result.outcome is EffectOutcome.ACCEPTED
    assert len(adapter.calls) == 1


def test_shadow_mode_stops_the_adapter_and_records_no_call(db_session: Session) -> None:
    """Criterion 1. The default settings are the blocking ones, which is the point."""
    adapter = FakeExternalEffectAdapter()

    with pytest.raises(ExternalEffectBlocked, match="shadow mode"):
        adapter.perform(db_session, Settings(), a_request())

    assert adapter.calls == [], "the adapter body must not have been reached"
    assert adapter.effect_count == 0, "and nothing may have happened"


def test_the_shadow_mode_flag_also_stops_it(db_session: Session) -> None:
    """The runtime switch, not just the deploy-time one."""
    adapter = FakeExternalEffectAdapter()
    set_flag(db_session, key=FlagKey.SHADOW_MODE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()

    with pytest.raises(ExternalEffectBlocked):
        adapter.perform(db_session, unlocked_settings(), a_request())

    assert adapter.calls == []


def test_a_global_pause_stops_the_adapter(db_session: Session) -> None:
    adapter = FakeExternalEffectAdapter()
    set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()

    with pytest.raises(ConsequentialWorkPaused):
        adapter.perform(db_session, unlocked_settings(), a_request())

    assert adapter.calls == []


def test_the_email_switch_stops_only_email_adapters(db_session: Session) -> None:
    set_flag(
        db_session,
        key=FlagKey.OUTBOUND_EMAIL_DISABLED,
        enabled=True,
        actor=OPERATOR,
        reason="deliverability check",
    )
    db_session.flush()
    settings = unlocked_settings()

    email = FakeExternalEffectAdapter(is_email=True)
    with pytest.raises(ExternalEffectBlocked, match="outbound email"):
        email.perform(db_session, settings, a_request())
    assert email.calls == []

    other = FakeExternalEffectAdapter()
    assert other.perform(db_session, settings, a_request()).outcome is EffectOutcome.ACCEPTED


def test_the_adapter_never_writes_its_own_entry_point() -> None:
    """The structural half of criterion 1.

    `FakeExternalEffectAdapter` defines `_perform`, never `perform`. That is what makes the guard
    impossible to skip: a subclass added later inherits the check whether or not its author knew
    the check existed.
    """
    assert "perform" not in FakeExternalEffectAdapter.__dict__
    assert "_perform" in FakeExternalEffectAdapter.__dict__
    assert "perform" not in ExternalEffectAdapter.__dict__


def test_the_base_adapter_refuses_to_be_used_directly(db_session: Session) -> None:
    """A subclass that forgets `_perform` fails loudly rather than silently doing nothing."""
    with pytest.raises(NotImplementedError):
        ExternalEffectAdapter().perform(db_session, unlocked_settings(), a_request())


# --- every outcome the dispatcher must branch on (criterion 3) --------------------------------


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        (Scenario.SUCCESS, EffectOutcome.ACCEPTED),
        (Scenario.TIMEOUT, EffectOutcome.AMBIGUOUS),
        (Scenario.AMBIGUOUS_ACCEPTANCE, EffectOutcome.AMBIGUOUS),
        (Scenario.RATE_LIMITED, EffectOutcome.TRANSIENT_FAILURE),
        (Scenario.REJECTED, EffectOutcome.REJECTED),
    ],
)
def test_each_scenario_produces_its_outcome(
    db_session: Session, scenario: Scenario, expected: EffectOutcome
) -> None:
    adapter = FakeExternalEffectAdapter(scenario)

    result = adapter.perform(db_session, unlocked_settings(), a_request())

    assert result.outcome is expected
    assert result.detail, "every outcome must be explainable to a human (§17.5)"


def test_every_outcome_is_reachable_through_the_fake(db_session: Session) -> None:
    """Criterion 3: the fake must cover the whole enum, or a dispatcher branch is untestable."""
    reached = {
        FakeExternalEffectAdapter(scenario)
        .perform(db_session, unlocked_settings(), a_request())
        .outcome
        for scenario in Scenario
    }

    assert reached == set(EffectOutcome)


def test_timeout_and_ambiguous_acceptance_are_indistinguishable_downstream(
    db_session: Session,
) -> None:
    """Criterion 3's real content.

    They arrive differently — one is silence, one is a provider saying "maybe" — and §17.3 requires
    both to be handled the same way. If the outcomes differed, someone would eventually treat the
    timeout as a failure and retry it blindly.
    """
    settings = unlocked_settings()
    timeout = FakeExternalEffectAdapter(Scenario.TIMEOUT).perform(db_session, settings, a_request())
    accepted = FakeExternalEffectAdapter(Scenario.AMBIGUOUS_ACCEPTANCE).perform(
        db_session, settings, a_request()
    )

    assert timeout.outcome is accepted.outcome is EffectOutcome.AMBIGUOUS
    assert not timeout.is_safe_to_retry
    assert not accepted.is_safe_to_retry


def test_only_a_demonstrably_unlanded_request_is_safe_to_retry() -> None:
    """§17.3: no blind retry after anything that might have happened."""
    assert {EffectOutcome.TRANSIENT_FAILURE} == SAFE_TO_RETRY
    assert EffectOutcome.AMBIGUOUS not in SAFE_TO_RETRY
    assert EffectOutcome.ACCEPTED not in SAFE_TO_RETRY


def test_an_accepted_result_must_carry_a_correlation_id() -> None:
    """§17.3 has nothing to reconcile against without one, so the type refuses to be built."""
    with pytest.raises(ValueError, match="correlation ID"):
        EffectResult(outcome=EffectOutcome.ACCEPTED)


def test_a_non_accepted_result_needs_no_correlation_id() -> None:
    assert EffectResult(outcome=EffectOutcome.AMBIGUOUS).provider_correlation_id is None


def test_a_result_is_immutable() -> None:
    """It is evidence. Something that rewrites it rewrites the record of what happened."""
    result = EffectResult(outcome=EffectOutcome.REJECTED, detail="refused")

    with pytest.raises(AttributeError):
        result.detail = "actually fine"  # type: ignore[misc]


# --- reconciliation (criterion 4) ------------------------------------------------------------


def test_reconcile_reports_an_effect_that_really_happened(db_session: Session) -> None:
    adapter = FakeExternalEffectAdapter()
    adapter.perform(db_session, unlocked_settings(), a_request())

    reconciled = adapter.reconcile(KEY)

    assert reconciled is not None
    assert reconciled.outcome is EffectOutcome.ACCEPTED


def test_reconcile_reports_nothing_for_an_unknown_key(db_session: Session) -> None:
    assert FakeExternalEffectAdapter().reconcile("f" * 64) is None


def test_reconcile_discovers_the_truth_behind_a_timeout(db_session: Session) -> None:
    """The case §17.3 exists for.

    The caller saw silence and cannot tell whether the effect landed. It did. Reconciliation is the
    only thing standing between that and a duplicate send, which is why `T-035b` must call it
    before any retry of an ambiguous attempt.
    """
    adapter = FakeExternalEffectAdapter(Scenario.TIMEOUT)
    result = adapter.perform(db_session, unlocked_settings(), a_request())
    assert result.outcome is EffectOutcome.AMBIGUOUS

    truth = adapter.reconcile(KEY)

    assert truth is not None, "a blind retry here would duplicate a real effect"
    assert truth.outcome is EffectOutcome.ACCEPTED


def test_reconcile_reports_nothing_after_a_transient_failure(db_session: Session) -> None:
    """The mirror case: nothing landed, so nothing to reconcile, so retrying is safe."""
    adapter = FakeExternalEffectAdapter(Scenario.RATE_LIMITED)
    adapter.perform(db_session, unlocked_settings(), a_request())

    assert adapter.reconcile(KEY) is None
    assert adapter.effect_count == 0


def test_the_adapter_satisfies_the_reconciliation_protocol() -> None:
    assert isinstance(FakeExternalEffectAdapter(), SupportsReconciliation)


# --- the fake keeps real state, not just a call log ------------------------------------------


def test_the_fake_records_every_attempt_including_failed_ones(db_session: Session) -> None:
    adapter = FakeExternalEffectAdapter(Scenario.RATE_LIMITED)
    settings = unlocked_settings()

    for _ in range(3):
        adapter.perform(db_session, settings, a_request())

    assert len(adapter.calls) == 3, "retry behaviour is only observable against a full record"
    assert adapter.effect_count == 0, "and none of them did anything"


def test_repeating_one_key_is_distinguishable_from_two_effects(db_session: Session) -> None:
    """What `T-035b`'s effectively-once criterion will be measured against.

    Two attempts with one key are two *calls* but one *effect*. A mock that only counted calls
    could not tell that apart from a genuine duplicate send.
    """
    adapter = FakeExternalEffectAdapter()
    settings = unlocked_settings()

    adapter.perform(db_session, settings, a_request())
    adapter.perform(db_session, settings, a_request())

    assert len(adapter.calls) == 2
    assert adapter.effect_count == 1


def test_two_different_keys_are_two_effects(db_session: Session) -> None:
    adapter = FakeExternalEffectAdapter()
    settings = unlocked_settings()

    adapter.perform(db_session, settings, a_request("a" * 64))
    adapter.perform(db_session, settings, a_request("b" * 64))

    assert adapter.effect_count == 2


def test_the_recorded_call_carries_what_was_asked_for(db_session: Session) -> None:
    adapter = FakeExternalEffectAdapter()

    adapter.perform(db_session, unlocked_settings(), a_request())

    call = adapter.calls[0]
    assert call.idempotency_key == KEY
    assert call.event_type == "send.email"
    assert call.payload == {"channel": "email"}
    assert call.scenario is Scenario.SUCCESS


# =================================================================================================
# T-035b — the dispatcher
# =================================================================================================


def pending_event(session: Session, key: str = KEY, marker: str = "dispatch") -> OutboxEvent:
    """One outbox event, paired with the business row §17.2 requires it to travel with."""
    session.add(Account(name=f"Synthetic {marker}", domain=f"{marker}-{key[:6]}.invalid"))
    event = enqueue_outbox_event(
        session,
        event_type="send.email",
        idempotency_key=key,
        actor=OPERATOR,
        payload={"channel": "email"},
    )
    session.flush()
    return event


def lease_one(session: Session, dispatcher_id: str = "dispatcher-a") -> OutboxEvent:
    leased = lease_outbox_events(session, dispatcher_id=dispatcher_id, limit=1)
    assert len(leased) == 1
    return leased[0]


# --- leasing ---------------------------------------------------------------------------------


def test_leasing_marks_the_event_and_counts_the_attempt(db_session: Session) -> None:
    pending_event(db_session)

    event = lease_one(db_session)

    assert event.state is OutboxState.DISPATCHING
    assert event.leased_by == "dispatcher-a"
    assert event.lease_expires_at is not None
    assert event.attempt_count == 1


def test_a_future_dated_event_is_not_leased(db_session: Session) -> None:
    event = pending_event(db_session)
    event.next_attempt_at = datetime.now(UTC) + timedelta(hours=1)
    db_session.flush()

    assert lease_outbox_events(db_session, dispatcher_id="dispatcher-a") == []


def test_the_leasing_query_uses_skip_locked(migrated_engine: Engine) -> None:
    """The outcome test below would pass in a blocking implementation too, so pin the mechanism.

    A dispatcher that blocks behind another is worse here than in the job queue: the lease it is
    waiting for may be mid-flight to a provider.
    """
    statement = (
        select(OutboxEvent.id)
        .where(OutboxEvent.state.in_(DISPATCHABLE_STATES))
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    compiled = str(statement.compile(migrated_engine)).upper()

    assert "FOR UPDATE" in compiled
    assert "SKIP LOCKED" in compiled


def test_two_concurrent_dispatchers_never_take_the_same_event(migrated_engine: Engine) -> None:
    """Criterion 4, against two real connections.

    A double lease here is worse than in the job queue: it is a double external effect.
    """
    marker = f"conc-{uuid.uuid4().hex[:8]}"
    keys = [hashlib.sha256(f"{marker}-{i}".encode()).hexdigest() for i in range(6)]

    with Session(migrated_engine) as setup:
        structlog.contextvars.bind_contextvars(correlation_id=marker)
        for key in keys:
            setup.add(Account(name=f"Synthetic {marker}", domain=f"{key[:10]}.invalid"))
            enqueue_outbox_event(
                setup,
                event_type="send.email",
                idempotency_key=key,
                actor=OPERATOR,
                correlation_id=marker,
            )
        setup.commit()

    try:
        with Session(migrated_engine) as first, Session(migrated_engine) as second:
            first_ids = {e.id for e in lease_outbox_events(first, dispatcher_id="a", limit=3)}
            second_ids = {e.id for e in lease_outbox_events(second, dispatcher_id="b", limit=3)}
            first.commit()
            second.commit()

        assert len(first_ids) == 3
        assert len(second_ids) == 3, "the second dispatcher must not have blocked"
        assert first_ids.isdisjoint(second_ids), "two dispatchers leased the same effect"
    finally:
        with Session(migrated_engine) as cleanup:
            for row in (
                cleanup.execute(select(OutboxEvent).where(OutboxEvent.idempotency_key.in_(keys)))
                .scalars()
                .all()
            ):
                cleanup.delete(row)
            for account in (
                cleanup.execute(select(Account).where(Account.name == f"Synthetic {marker}"))
                .scalars()
                .all()
            ):
                cleanup.delete(account)
            cleanup.commit()


def test_dispatching_an_unleased_event_is_refused(db_session: Session) -> None:
    """The lease is the mutual exclusion. Bypassing it is how one effect happens twice."""
    event = pending_event(db_session)

    with pytest.raises(OutboxError, match="not leased for dispatch"):
        dispatch_event(db_session, event, FakeExternalEffectAdapter(), unlocked_settings())


# --- outcomes are recorded ---------------------------------------------------------------------


def test_an_accepted_effect_is_dispatched_with_its_correlation_id(db_session: Session) -> None:
    pending_event(db_session)
    event = lease_one(db_session)
    adapter = FakeExternalEffectAdapter()

    dispatch_event(db_session, event, adapter, unlocked_settings())

    assert event.state is OutboxState.DISPATCHED
    assert event.provider_correlation_id is not None
    assert event.last_outcome == EffectOutcome.ACCEPTED.value
    assert event.leased_by is None, "the lease must be released"


def test_a_rejected_effect_fails_and_is_not_retried(db_session: Session) -> None:
    pending_event(db_session)
    event = lease_one(db_session)

    dispatch_event(
        db_session, event, FakeExternalEffectAdapter(Scenario.REJECTED), unlocked_settings()
    )

    assert event.state is OutboxState.FAILED
    assert lease_outbox_events(db_session, dispatcher_id="dispatcher-b", limit=5) == []


def test_a_transient_failure_returns_to_pending_with_backoff(db_session: Session) -> None:
    """The one outcome §17.3 says demonstrably never landed, so retrying it is safe."""
    pending_event(db_session)
    event = lease_one(db_session)
    before = datetime.now(UTC)

    dispatch_event(
        db_session, event, FakeExternalEffectAdapter(Scenario.RATE_LIMITED), unlocked_settings()
    )

    assert event.state is OutboxState.PENDING
    assert event.next_attempt_at > before
    assert event.attempt_count == 1


def test_every_dispatch_writes_an_audit_event(db_session: Session) -> None:
    pending_event(db_session)
    event = lease_one(db_session)

    dispatch_event(db_session, event, FakeExternalEffectAdapter(), unlocked_settings())
    db_session.flush()

    audit = (
        db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_id == str(event.id), AuditEvent.action == "outbox.dispatched"
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].payload["outcome"] == EffectOutcome.ACCEPTED.value


# --- ambiguous acceptance (criterion 1) -------------------------------------------------------


def test_an_ambiguous_result_becomes_delivery_unknown(db_session: Session) -> None:
    pending_event(db_session)
    event = lease_one(db_session)

    dispatch_event(
        db_session,
        event,
        FakeExternalEffectAdapter(Scenario.AMBIGUOUS_ACCEPTANCE),
        unlocked_settings(),
    )

    assert event.state is OutboxState.DELIVERY_UNKNOWN
    assert event.last_outcome == EffectOutcome.AMBIGUOUS.value


def test_a_timeout_becomes_delivery_unknown_too(db_session: Session) -> None:
    pending_event(db_session)
    event = lease_one(db_session)

    dispatch_event(
        db_session, event, FakeExternalEffectAdapter(Scenario.TIMEOUT), unlocked_settings()
    )

    assert event.state is OutboxState.DELIVERY_UNKNOWN


def test_a_delivery_unknown_event_is_never_leased_again(db_session: Session) -> None:
    """Criterion 1's "zero retries", enforced structurally.

    `DELIVERY_UNKNOWN` is not in `DISPATCHABLE_STATES`, so the lease query cannot see the row at
    all. That is stronger than a branch that declines to retry, because there is no branch to
    forget.
    """
    pending_event(db_session)
    event = lease_one(db_session)
    adapter = FakeExternalEffectAdapter(Scenario.TIMEOUT)
    dispatch_event(db_session, event, adapter, unlocked_settings())
    db_session.flush()

    assert lease_outbox_events(db_session, dispatcher_id="dispatcher-b", limit=10) == []
    assert len(adapter.calls) == 1, "no second attempt may have been made"


def test_delivery_unknown_is_not_reachable_from_pending() -> None:
    """It is a dispatch outcome, not a state something can be created in."""
    assert OutboxState.DELIVERY_UNKNOWN not in OUTBOX_TRANSITIONS[OutboxState.PENDING]
    assert OutboxState.DELIVERY_UNKNOWN in OUTBOX_TRANSITIONS[OutboxState.DISPATCHING]


def test_the_only_exits_from_delivery_unknown_are_reconciliation_outcomes() -> None:
    assert OUTBOX_TRANSITIONS[OutboxState.DELIVERY_UNKNOWN] == frozenset(
        {OutboxState.DISPATCHED, OutboxState.PENDING}
    )


def test_a_terminal_state_has_no_exit() -> None:
    assert OUTBOX_TRANSITIONS[OutboxState.DISPATCHED] == frozenset()
    assert OUTBOX_TRANSITIONS[OutboxState.FAILED] == frozenset()


def test_an_illegal_transition_is_refused(db_session: Session) -> None:
    with pytest.raises(IllegalOutboxTransition, match="illegal outbox transition"):
        assert_outbox_transition(OutboxState.DISPATCHED, OutboxState.PENDING)


def test_re_entering_the_same_state_is_refused() -> None:
    """A self-transition would write an audit event describing a change that did not happen."""
    with pytest.raises(IllegalOutboxTransition):
        assert_outbox_transition(OutboxState.PENDING, OutboxState.PENDING)


# --- reconciliation before retry (criterion 3) -------------------------------------------------


def test_reconciliation_finds_the_effect_already_happened_and_sends_nothing(
    db_session: Session,
) -> None:
    """Criterion 3, and the whole reason §17.3 exists.

    The caller saw a timeout. The effect had in fact landed. Reconciliation resolves the event to
    `DISPATCHED` without the adapter being asked to send anything a second time.
    """
    pending_event(db_session)
    event = lease_one(db_session)
    adapter = FakeExternalEffectAdapter(Scenario.TIMEOUT)
    dispatch_event(db_session, event, adapter, unlocked_settings())
    assert event.state is OutboxState.DELIVERY_UNKNOWN

    truth = reconcile_unknown(db_session, event, adapter)

    assert truth is not None
    assert truth.outcome is EffectOutcome.ACCEPTED
    assert event.state is OutboxState.DISPATCHED
    assert event.provider_correlation_id is not None
    assert len(adapter.calls) == 1, "reconciliation must not send"
    assert adapter.effect_count == 1


def test_reconciliation_returns_the_event_to_pending_when_nothing_happened(
    db_session: Session,
) -> None:
    """The mirror: the provider has no record, so a retry is safe for the first time."""
    pending_event(db_session)
    event = lease_one(db_session)
    # An adapter whose ledger is empty stands in for a provider that never received the request.
    adapter = FakeExternalEffectAdapter(Scenario.AMBIGUOUS_ACCEPTANCE)
    dispatch_event(db_session, event, adapter, unlocked_settings())
    adapter.performed.clear()

    assert reconcile_unknown(db_session, event, adapter) is None

    assert event.state is OutboxState.PENDING
    assert len(lease_outbox_events(db_session, dispatcher_id="dispatcher-b", limit=1)) == 1


def test_reconciling_something_that_is_not_unknown_is_refused(db_session: Session) -> None:
    pending_event(db_session)
    event = lease_one(db_session)
    adapter = FakeExternalEffectAdapter()
    dispatch_event(db_session, event, adapter, unlocked_settings())

    with pytest.raises(OutboxError, match="only a delivery_unknown event"):
        reconcile_unknown(db_session, event, adapter)


# --- effectively once (criterion 2) ------------------------------------------------------------


def test_replaying_one_idempotency_key_produces_exactly_one_effect(db_session: Session) -> None:
    """Criterion 2.

    Two dispatch cycles over the same key. The adapter is *called* twice — the transient failure is
    a real second attempt — but only one effect ever happens, because the key is the same and the
    fake keys its ledger by it.
    """
    pending_event(db_session)
    adapter = FakeExternalEffectAdapter(Scenario.RATE_LIMITED)

    first = lease_one(db_session)
    dispatch_event(db_session, first, adapter, unlocked_settings())
    assert first.state is OutboxState.PENDING
    assert adapter.effect_count == 0

    first.next_attempt_at = datetime.now(UTC)
    db_session.flush()
    adapter.scenario = Scenario.SUCCESS
    second = lease_one(db_session, "dispatcher-b")
    dispatch_event(db_session, second, adapter, unlocked_settings())

    assert second.state is OutboxState.DISPATCHED
    assert len(adapter.calls) == 2, "two genuine attempts were made"
    assert adapter.effect_count == 1, "but only one effect happened"


def test_a_dispatched_event_is_never_leased_again(db_session: Session) -> None:
    """The other half of effectively-once: success takes the row out of circulation."""
    pending_event(db_session)
    event = lease_one(db_session)
    adapter = FakeExternalEffectAdapter()
    dispatch_event(db_session, event, adapter, unlocked_settings())
    db_session.flush()

    assert lease_outbox_events(db_session, dispatcher_id="dispatcher-b", limit=10) == []
    assert adapter.effect_count == 1


def test_dispatch_once_leases_and_dispatches(migrated_engine: Engine) -> None:
    """The whole cycle, against a session that really commits."""
    marker = f"once-{uuid.uuid4().hex[:8]}"
    key = hashlib.sha256(marker.encode()).hexdigest()
    adapter = FakeExternalEffectAdapter()

    try:
        with Session(migrated_engine) as session:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            session.add(Account(name=f"Synthetic {marker}", domain=f"{marker}.invalid"))
            enqueue_outbox_event(
                session,
                event_type="send.email",
                idempotency_key=key,
                actor=OPERATOR,
                correlation_id=marker,
            )
            session.commit()

        with Session(migrated_engine) as session:
            assert dispatch_once(session, adapter, unlocked_settings(), dispatcher_id="d1") == 1
            assert dispatch_once(session, adapter, unlocked_settings(), dispatcher_id="d1") == 0

        with Session(migrated_engine) as check:
            stored = check.execute(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
            ).scalar_one()
            assert stored.state is OutboxState.DISPATCHED
        assert adapter.effect_count == 1
    finally:
        with Session(migrated_engine) as cleanup:
            for row in (
                cleanup.execute(select(OutboxEvent).where(OutboxEvent.idempotency_key == key))
                .scalars()
                .all()
            ):
                cleanup.delete(row)
            for account in (
                cleanup.execute(select(Account).where(Account.domain == f"{marker}.invalid"))
                .scalars()
                .all()
            ):
                cleanup.delete(account)
            cleanup.commit()


def test_a_kill_switch_holds_the_event_instead_of_killing_the_dispatcher(
    db_session: Session,
) -> None:
    """A §17.6 switch is an operator decision, not an error.

    It surfaces as `DispatchRefused`, not as the raw `ExternalEffectBlocked` — because `T-139`
    showed that letting the guard's exception propagate kills the worker on its first pending event
    whenever shadow mode is on, and shadow mode is the *shipped default*. The switch has to stop the
    send, not the process.
    """
    pending_event(db_session)
    event = lease_one(db_session)
    adapter = FakeExternalEffectAdapter()
    set_flag(db_session, key=FlagKey.SHADOW_MODE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()

    with pytest.raises(DispatchRefused) as caught:
        dispatch_event(db_session, event, adapter, unlocked_settings())

    assert caught.value.recoverable is True, "the operator will flip the switch back"
    assert isinstance(caught.value.__cause__, ExternalEffectBlocked)
    assert adapter.calls == []
    assert adapter.effect_count == 0
    assert event.state is OutboxState.PENDING, "the work is held, not lost"
    assert event.attempt_count == 0, "and the switch cost it nothing"


# =================================================================================================
# T-138 — outbox dispatch-lease recovery
# =================================================================================================


def leased_outbox_event(session: Session, key: str, marker: str) -> OutboxEvent:
    """An outbox event leased for dispatch, paired with the business row §17.2 requires."""
    session.add(Account(name=f"Synthetic {marker}", domain=f"{marker}.invalid"))
    enqueue_outbox_event(
        session,
        event_type="send.email",
        idempotency_key=key,
        actor=OPERATOR,
        payload={"channel": "email"},
    )
    session.flush()
    leased = lease_outbox_events(session, dispatcher_id="dispatcher-doomed", limit=1)
    assert len(leased) == 1
    return leased[0]


# --- an expired dispatch lease is ambiguous, not re-runnable (criterion 1) ----------------------


def test_a_live_dispatch_lease_is_not_reclaimed(db_session: Session) -> None:
    """A dispatcher still mid-flight must not have its event taken."""
    event = leased_outbox_event(db_session, KEY, "live-dispatch")
    assert event.lease_expires_at is not None
    still_held = event.lease_expires_at - timedelta(seconds=1)

    assert reclaim_expired_dispatch_leases(db_session, now=still_held) == []


def test_the_expiry_boundary_is_inclusive(db_session: Session) -> None:
    """Expiry is `<=`, matching `Job.is_lease_expired_at`.

    Worth pinning rather than leaving to inference: an off-by-one here either reclaims a lease a
    second early — while a dispatcher may still be talking to a provider — or leaves a dead one
    held forever.
    """
    event = leased_outbox_event(db_session, KEY, "boundary")
    assert event.lease_expires_at is not None

    assert reclaim_expired_dispatch_leases(db_session, now=event.lease_expires_at) != []


def test_an_expired_dispatch_lease_becomes_delivery_unknown(db_session: Session) -> None:
    """Criterion 1. The whole reason this is a separate mechanism from job recovery.

    A job that died mid-run committed nothing, so requeueing it is safe. A *dispatcher* that died
    may have reached the provider first, so requeueing would be the blind retry §17.3 forbids.
    """
    event = leased_outbox_event(db_session, KEY, "expired-dispatch")
    assert event.lease_expires_at is not None
    future = event.lease_expires_at + timedelta(seconds=1)

    reclaimed = reclaim_expired_dispatch_leases(db_session, now=future)

    assert [e.id for e in reclaimed] == [event.id]
    assert event.state is OutboxState.DELIVERY_UNKNOWN
    assert event.state is not OutboxState.PENDING
    assert event.leased_by is None
    assert event.lease_expires_at is None
    assert event.last_outcome == EffectOutcome.AMBIGUOUS.value


def test_a_reclaimed_dispatch_lease_is_not_dispatchable(db_session: Session) -> None:
    """The requeue §17.3 forbids is impossible, not merely avoided: the state is not leasable."""
    event = leased_outbox_event(db_session, KEY, "not-dispatchable")
    assert event.lease_expires_at is not None
    reclaim_expired_dispatch_leases(db_session, now=event.lease_expires_at + timedelta(seconds=1))
    db_session.flush()

    assert lease_outbox_events(db_session, dispatcher_id="dispatcher-b", limit=10) == []
    assert OutboxState.DELIVERY_UNKNOWN not in DISPATCHABLE_STATES


def test_a_pending_event_is_never_a_dispatch_reclaim_candidate(db_session: Session) -> None:
    """Only a held lease can expire. An event waiting its turn is not a crash."""
    db_session.add(Account(name="Synthetic pending", domain="pending-reclaim.invalid"))
    enqueue_outbox_event(db_session, event_type="send.email", idempotency_key=KEY, actor=OPERATOR)
    db_session.flush()

    assert find_expired_dispatch_leases(db_session, now=datetime.now(UTC) + timedelta(days=1)) == []


def test_a_settled_event_is_invisible_to_dispatch_reclaim(db_session: Session) -> None:
    """A dispatched event released its lease in the same transaction that recorded the outcome."""
    event = leased_outbox_event(db_session, KEY, "settled")
    dispatch_event(db_session, event, FakeExternalEffectAdapter(), unlocked_settings())
    db_session.flush()
    assert event.state is OutboxState.DISPATCHED

    assert (
        reclaim_expired_dispatch_leases(db_session, now=datetime.now(UTC) + timedelta(days=1)) == []
    )


def test_dispatch_reclaim_is_bounded(db_session: Session) -> None:
    keys = [hashlib.sha256(f"bounded-{i}".encode()).hexdigest() for i in range(4)]
    for index, key in enumerate(keys):
        db_session.add(Account(name="Synthetic bulk", domain=f"bulk{index}-reclaim.invalid"))
        enqueue_outbox_event(
            db_session, event_type="send.email", idempotency_key=key, actor=OPERATOR
        )
    db_session.flush()
    leased = lease_outbox_events(db_session, dispatcher_id="dispatcher-doomed", limit=4)
    assert leased[0].lease_expires_at is not None
    future = leased[0].lease_expires_at + timedelta(seconds=1)

    assert len(reclaim_expired_dispatch_leases(db_session, now=future, limit=2)) == 2


# --- the audit trail (criterion 3) -------------------------------------------------------------


def test_dispatch_reclaim_writes_an_audit_event(db_session: Session) -> None:
    event = leased_outbox_event(db_session, KEY, "audited-dispatch")
    assert event.lease_expires_at is not None

    reclaim_expired_dispatch_leases(db_session, now=event.lease_expires_at + timedelta(seconds=1))
    db_session.flush()

    audit = db_session.execute(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(event.id),
            AuditEvent.action == "outbox.lease_reclaimed",
        )
    ).scalar_one()
    assert audit.from_state == OutboxState.DISPATCHING.value
    assert audit.to_state == OutboxState.DELIVERY_UNKNOWN.value
    assert audit.actor_id == RECOVERY_ACTOR.id
    assert audit.payload["previous_holder"] == "dispatcher-doomed"
    assert audit.payload["lease_expired_at"]


# --- a simulated dispatcher crash (criterion 2) -------------------------------------------------


def test_a_crash_after_the_provider_accepted_never_sends_twice(migrated_engine: Engine) -> None:
    """Criterion 2, and the case §17.3 exists for.

    The dispatcher reached the provider — the effect *happened* — and died before recording it. The
    lease expires, recovery marks the event `delivery_unknown`, and reconciliation discovers the
    truth. Total external effects must be exactly one, and the adapter must not be asked to send
    a second time.
    """
    marker = f"acc{uuid.uuid4().hex[:8]}"
    key = hashlib.sha256(marker.encode()).hexdigest()
    # One adapter instance across all three sessions: its ledger stands in for the provider's.
    adapter = FakeExternalEffectAdapter(Scenario.TIMEOUT)

    try:
        with Session(migrated_engine) as doomed:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            leased_outbox_event(doomed, key, marker)
            # The provider accepts. `TIMEOUT` records the effect while returning AMBIGUOUS.
            adapter.perform(doomed, unlocked_settings(), a_request(key))
            doomed.commit()

        assert adapter.effect_count == 1, "the provider really did perform it"

        with Session(migrated_engine) as healthy:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            stranded = healthy.execute(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
            ).scalar_one()
            assert stranded.state is OutboxState.DISPATCHING, "a lease nobody holds"
            assert stranded.lease_expires_at is not None
            future = stranded.lease_expires_at + timedelta(seconds=1)

            assert len(reclaim_expired_dispatch_leases(healthy, now=future)) == 1
            assert stranded.state is OutboxState.DELIVERY_UNKNOWN

            resolved = reconcile_unknown(healthy, stranded, adapter)
            healthy.commit()

        assert resolved is not None, "reconciliation must find the effect that happened"
        assert resolved.outcome is EffectOutcome.ACCEPTED
        assert adapter.effect_count == 1, "exactly one external effect"
        assert len(adapter.calls) == 1, "reconciliation must not send"

        with Session(migrated_engine) as check:
            stored = check.execute(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
            ).scalar_one()
            assert stored.state is OutboxState.DISPATCHED
    finally:
        dispatch_cleanup(migrated_engine, key, marker)


def test_a_crash_before_the_provider_was_reached_can_be_retried(migrated_engine: Engine) -> None:
    """The mirror: nothing happened, so reconciliation returns the event to `PENDING`.

    This is the only path by which a reclaimed dispatch becomes runnable again, and it goes through
    the provider first. That ordering is the whole of §17.3.
    """
    marker = f"pre{uuid.uuid4().hex[:8]}"
    key = hashlib.sha256(marker.encode()).hexdigest()
    adapter = FakeExternalEffectAdapter()

    try:
        with Session(migrated_engine) as doomed:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            leased_outbox_event(doomed, key, marker)
            # Died before calling the adapter at all.
            doomed.commit()

        assert adapter.effect_count == 0

        with Session(migrated_engine) as healthy:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            stranded = healthy.execute(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
            ).scalar_one()
            assert stranded.lease_expires_at is not None
            future = stranded.lease_expires_at + timedelta(seconds=1)
            reclaim_expired_dispatch_leases(healthy, now=future)

            assert reconcile_unknown(healthy, stranded, adapter) is None
            assert stranded.state is OutboxState.PENDING, "now safe to attempt again"

            event = lease_outbox_events(healthy, dispatcher_id="dispatcher-healthy", limit=1)[0]
            dispatch_event(healthy, event, adapter, unlocked_settings())
            healthy.commit()

        assert adapter.effect_count == 1, "exactly one effect, on the retry"

        with Session(migrated_engine) as check:
            stored = check.execute(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
            ).scalar_one()
            assert stored.state is OutboxState.DISPATCHED
    finally:
        dispatch_cleanup(migrated_engine, key, marker)


def test_two_recovery_passes_reclaim_a_dispatch_lease_exactly_once(
    migrated_engine: Engine,
) -> None:
    """Two reclaims would produce two `delivery_unknown` settlements for one effect."""
    marker = f"race{uuid.uuid4().hex[:8]}"
    keys = [hashlib.sha256(f"{marker}-{i}".encode()).hexdigest() for i in range(4)]

    try:
        with Session(migrated_engine) as setup:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            for index, key in enumerate(keys):
                setup.add(Account(name=f"Synthetic {marker}", domain=f"{marker}{index}.invalid"))
                enqueue_outbox_event(
                    setup,
                    event_type="send.email",
                    idempotency_key=key,
                    actor=OPERATOR,
                    correlation_id=marker,
                )
            setup.flush()
            leased = lease_outbox_events(setup, dispatcher_id="dispatcher-doomed", limit=4)
            expiry = leased[0].lease_expires_at
            assert expiry is not None
            setup.commit()

        future = expiry + timedelta(seconds=1)
        with Session(migrated_engine) as first, Session(migrated_engine) as second:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            first_ids = {e.id for e in reclaim_expired_dispatch_leases(first, now=future, limit=2)}
            second_ids = {
                e.id for e in reclaim_expired_dispatch_leases(second, now=future, limit=2)
            }
            first.commit()
            second.commit()

        assert len(first_ids) == 2
        assert len(second_ids) == 2, "the second pass must not have blocked"
        assert first_ids.isdisjoint(second_ids), "one dispatch lease was reclaimed twice"
    finally:
        for index, key in enumerate(keys):
            dispatch_cleanup(migrated_engine, key, f"{marker}{index}")


def dispatch_cleanup(engine: Engine, key: str, marker: str) -> None:
    """These tests commit. Audit events are left: `audit_event` is append-only by design (T-011)."""
    with Session(engine) as session:
        for row in (
            session.execute(select(OutboxEvent).where(OutboxEvent.idempotency_key == key))
            .scalars()
            .all()
        ):
            session.delete(row)
        for account in (
            session.execute(select(Account).where(Account.domain == f"{marker}.invalid"))
            .scalars()
            .all()
        ):
            session.delete(account)
        session.commit()
