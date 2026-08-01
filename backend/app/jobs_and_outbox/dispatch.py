"""The external-effect boundary (specification §17.2, §17.3, ADR-016).

Everything the system does to the outside world goes through one narrow contract, and this module
defines it. The dispatcher that consumes it is `T-035b`; the §11.4 rechecks are `T-035c`.

Two properties matter more than the shape of the types:

**Nothing here talks to a network.** No provider client is imported anywhere in the dispatch path
during Stage 1, and `tests/test_dispatch.py` asserts that by inspecting the modules rather than
trusting the convention. Gate **G-07** is what unlocks a real provider.

**A result that might have happened is not a failure.** §17.3 is explicit that exactly-once cannot
be guaranteed across a provider boundary, so the contract makes the ambiguous case a first-class
outcome rather than an exception to be retried. Blind retry after an ambiguous response is the one
thing §17.3 forbids outright, and a type that cannot express "I do not know" is a type that forces
the caller to guess.
"""

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.flags import (
    ConsequentialWorkPaused,
    ExternalEffectBlocked,
    GuardedAdapter,
)
from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor, record_audit_event
from app.core.settings import Settings
from app.jobs_and_outbox.outbox import (
    DISPATCHABLE_STATES,
    ENTITY_TYPE,
    RECHECK_REFUSED_ACTION,
    OutboxError,
    OutboxEvent,
    OutboxState,
    assert_outbox_transition,
)

log = structlog.get_logger(__name__)


class EffectOutcome(Enum):
    """What a provider did with an effect.

    Deliberately four values, not five: a **timeout** and an **explicitly ambiguous acceptance**
    both collapse to `AMBIGUOUS`. They arrive differently — one is silence, one is a provider
    saying "maybe" — but treating them differently is how a blind retry gets written. The
    distinction is preserved in `EffectResult.detail` for humans, not in control flow.
    """

    #: The provider took it and said so. There is a correlation ID.
    ACCEPTED = "accepted"
    #: The provider refused, permanently. Retrying sends the same rejection.
    REJECTED = "rejected"
    #: The request demonstrably never landed. Safe to retry after a delay.
    TRANSIENT_FAILURE = "transient_failure"
    #: It may or may not have happened. §17.3: no blind retry — reconcile first.
    AMBIGUOUS = "ambiguous"


#: Outcomes a caller may retry without reconciling with the provider first (§17.3).
SAFE_TO_RETRY = frozenset({EffectOutcome.TRANSIENT_FAILURE})


@dataclass(frozen=True, slots=True)
class EffectRequest:
    """One external effect to perform.

    Carries the idempotency key rather than deriving one: the key comes from the outbox event,
    which took it from the send command, so the same approved decision keeps one key end to end
    (§17.3).
    """

    idempotency_key: str
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EffectResult:
    """What came back. Immutable, because it is evidence."""

    outcome: EffectOutcome
    #: The provider's own identifier for the effect, when there is one. §17.3 needs this to
    #: reconcile later, so an `ACCEPTED` result without one is a contract violation.
    provider_correlation_id: str | None = None
    #: Human-readable, for the dashboard and for incident review. Never used for control flow.
    detail: str = ""

    def __post_init__(self) -> None:
        if self.outcome is EffectOutcome.ACCEPTED and not self.provider_correlation_id:
            raise ValueError(
                "an ACCEPTED result must carry a provider correlation ID; without one the effect "
                "cannot be reconciled and §17.3 has nothing to check against"
            )

    @property
    def is_safe_to_retry(self) -> bool:
        return self.outcome in SAFE_TO_RETRY


@runtime_checkable
class SupportsReconciliation(Protocol):
    """§17.3's pre-retry reconciliation.

    Any adapter whose effects can be ambiguous must be able to answer "did this already happen?"
    from the provider's side, keyed by the idempotency key we sent. An adapter that cannot is an
    adapter whose ambiguous results can only ever be resolved by a human.
    """

    def reconcile(self, idempotency_key: str) -> EffectResult | None: ...


class ExternalEffectAdapter(GuardedAdapter[EffectRequest, EffectResult]):
    """The contract every outward-facing adapter implements.

    Inherits `perform` from `GuardedAdapter`, which checks the §17.6 switches *before* delegating
    to `_perform`. Subclasses implement `_perform` and `reconcile`; they never write the entry
    point, so no subclass can act while shadow mode is on — including one added later by someone
    who has not read this docstring.
    """

    def _perform(self, session: Session, request: EffectRequest) -> EffectResult:
        raise NotImplementedError

    def reconcile(self, idempotency_key: str) -> EffectResult | None:
        """Ask the provider whether this effect already happened.

        `None` means "the provider has no record", which is only safe to read as "it did not
        happen" for a provider that would have a record. Returning `None` by default would make
        every ambiguous result look resolvable, so this is not implemented here.
        """
        raise NotImplementedError


# --- the dispatcher (T-035b) ---------------------------------------------------------------------

#: How long a dispatcher holds an outbox event. Shorter than the job lease: a dispatch either
#: reaches the provider quickly or is ambiguous, and a long lease delays discovering that.
DEFAULT_DISPATCH_LEASE = timedelta(minutes=2)

#: Backoff after a transient failure. Flat rather than exponential on purpose — `T-031`'s policy is
#: per *job type*, and an outbox event is not a job. A dedicated policy is `T-035c` territory if
#: measurement shows this matters.
TRANSIENT_BACKOFF = timedelta(seconds=30)

#: Jobs and dispatchers run unattended, so the actor is the system (§12.2).
DISPATCHER_ACTOR = Actor(type=ActorType.SERVICE, id="dispatcher")


class PreconditionCheck(Protocol):
    """The §11.4 recheck, injected rather than imported.

    `jobs_and_outbox` must not know what an approval is (§18.2), so the dispatcher cannot call the
    rechecks directly — it calls whatever the domain hands it. Takes the idempotency key rather
    than the outbox row, so a domain module is never handed one of the queue's own records.

    Raises to refuse. `app.outreach_and_replies.preconditions.send_precondition_check` is the
    implementation for sends.
    """

    def __call__(self, session: Session, idempotency_key: str) -> None: ...


class DispatchRefused(OutboxError):
    """A §11.4 recheck refused this dispatch. Nothing was sent."""

    def __init__(self, check: str, detail: str, *, recoverable: bool) -> None:
        self.check = check
        self.detail = detail
        self.recoverable = recoverable
        super().__init__(f"dispatch refused by {check}: {detail}")


def lease_outbox_events(
    session: Session,
    *,
    dispatcher_id: str,
    limit: int = 1,
    lease: timedelta = DEFAULT_DISPATCH_LEASE,
    now: datetime | None = None,
) -> list[OutboxEvent]:
    """Claim up to ``limit`` dispatchable outbox events (§17.2 step 4).

    Same `FOR UPDATE SKIP LOCKED` shape as the job queue, and for the same reason: two dispatchers
    must never take one event, and neither may block behind the other. Here the stakes are higher —
    a double lease is a double external effect.

    Only `PENDING` is dispatchable. A `DELIVERY_UNKNOWN` row is invisible to this query, which is
    how §17.3's "no blind retry" is enforced structurally rather than by a branch someone can
    forget.
    """
    moment = now or datetime.now(UTC)

    candidate_ids = (
        session.execute(
            select(OutboxEvent.id)
            .where(
                OutboxEvent.state.in_(DISPATCHABLE_STATES),
                OutboxEvent.next_attempt_at <= moment,
            )
            .order_by(OutboxEvent.next_attempt_at, OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    if not candidate_ids:
        return []

    for event in (
        session.execute(select(OutboxEvent).where(OutboxEvent.id.in_(candidate_ids)))
        .scalars()
        .all()
    ):
        assert_outbox_transition(event.state, OutboxState.DISPATCHING)
        event.state = OutboxState.DISPATCHING
        event.leased_by = dispatcher_id
        event.lease_expires_at = moment + lease
        event.attempt_count += 1
    session.flush()

    return list(
        session.execute(select(OutboxEvent).where(OutboxEvent.id.in_(candidate_ids)))
        .scalars()
        .all()
    )


def _settle(
    session: Session,
    event: OutboxEvent,
    target: OutboxState,
    result: EffectResult,
    *,
    actor: Actor,
    next_attempt_at: datetime | None = None,
    refused_check: str | None = None,
    refused_scope: str | None = None,
) -> None:
    """Record an outcome against an outbox event, atomically with its audit event (§17.2)."""
    previous = event.state
    assert_outbox_transition(previous, target)

    event.state = target
    event.leased_by = None
    event.lease_expires_at = None
    event.last_outcome = result.outcome.value
    event.last_detail = result.detail
    if result.provider_correlation_id:
        event.provider_correlation_id = result.provider_correlation_id
    if next_attempt_at is not None:
        event.next_attempt_at = next_attempt_at
    session.flush()

    payload: dict[str, Any] = {
        "event_type": event.event_type,
        "outcome": result.outcome.value,
        "attempt": event.attempt_count,
    }
    if refused_check is not None:
        # §11.4 criterion 2: the trail has to say *which* condition stopped the send, or a reviewer
        # cannot tell a revoked approval from a paused campaign.
        payload["refused_check"] = refused_check
    if refused_scope is not None:
        # `T-161`: the scope that matched, so a suppressed-send attempt is a countable row and not
        # a substring somebody greps `last_detail` for. A category only — see `_refusal_attributes`.
        payload["refused_scope"] = refused_scope

    record_audit_event(
        session,
        actor=actor,
        action=RECHECK_REFUSED_ACTION if refused_check else "outbox.dispatched",
        entity_type=ENTITY_TYPE,
        entity_id=event.id,
        from_state=previous,
        to_state=target,
        payload=payload,
        correlation_id=event.correlation_id,
    )


def _refusal_attributes(error: Exception) -> tuple[str, str, bool, str | None]:
    """Read the check name, detail, recoverability, and matched scope off a domain refusal.

    Read by attribute rather than by importing the domain's exception type, because importing it
    would be exactly the §18.2 violation the injected check exists to avoid. A refusal that does
    not carry these attributes is still refused — it is only described less precisely.

    ``scope`` is optional and only suppression sets it today (`T-161`). It is a category, never an
    address or a name: §15.5 keeps those out of the trail, and the exception that raises it is
    responsible for having stripped them (`outreach_and_replies.preconditions.SuppressedAtSend`).
    """
    check = str(getattr(error, "check", "") or type(error).__name__)
    detail = str(getattr(error, "detail", "") or error)
    recoverable = bool(getattr(error, "is_recoverable", False))
    raw_scope = getattr(error, "scope", None)
    scope = str(raw_scope) if isinstance(raw_scope, str) and raw_scope.strip() else None
    return check, detail, recoverable, scope


def _run_preconditions(
    session: Session,
    event: OutboxEvent,
    check: PreconditionCheck,
    *,
    actor: Actor,
) -> None:
    """Run the §11.4 rechecks and settle the event if any of them refuses.

    A refusal is not a provider failure, so it never touches the adapter and never counts as an
    attempt at the provider. Two outcomes:

    * **recoverable** (a paused campaign, a volume cap) → back to `PENDING` with the attempt
      refunded. §17.1 requires held work to stay intact, and burning the retry budget on a
      condition that will become valid again eventually dead-letters work nobody abandoned.
    * **permanent** (a revoked approval, a suppressed recipient) → `FAILED`. Retrying would refuse
      identically forever.
    """
    try:
        check(session, event.idempotency_key)
    except OutboxError:
        raise
    except Exception as error:
        name, detail, recoverable, scope = _refusal_attributes(error)
        result = EffectResult(
            outcome=EffectOutcome.TRANSIENT_FAILURE if recoverable else EffectOutcome.REJECTED,
            detail=f"§11.4 recheck {name} refused: {detail}",
        )

        if recoverable:
            # Refund the attempt the lease spent. The condition is expected to change, and this
            # dispatch cost the provider nothing.
            event.attempt_count = max(0, event.attempt_count - 1)
            _settle(
                session,
                event,
                OutboxState.PENDING,
                result,
                actor=actor,
                next_attempt_at=datetime.now(UTC) + TRANSIENT_BACKOFF,
                refused_check=name,
                refused_scope=scope,
            )
        else:
            _settle(
                session,
                event,
                OutboxState.FAILED,
                result,
                actor=actor,
                refused_check=name,
                refused_scope=scope,
            )

        log.warning(
            "outbox.recheck_refused",
            event_type=event.event_type,
            check=name,
            recoverable=recoverable,
            state=event.state.value,
        )
        raise DispatchRefused(name, detail, recoverable=recoverable) from error


def _settle_blocked(
    session: Session, event: OutboxEvent, blocked: Exception, *, actor: Actor
) -> None:
    """Return an event to the queue because a §17.6 switch refused it. Nothing was sent."""
    # The lease charged an attempt; refund it. A switch costs the provider nothing, and burning the
    # budget while shadow mode is on would dead-letter the entire outbox before going live.
    event.attempt_count = max(0, event.attempt_count - 1)
    _settle(
        session,
        event,
        OutboxState.PENDING,
        EffectResult(
            outcome=EffectOutcome.TRANSIENT_FAILURE,
            detail=f"refused by an operational switch: {blocked}",
        ),
        actor=actor,
        next_attempt_at=datetime.now(UTC) + TRANSIENT_BACKOFF,
        refused_check=type(blocked).__name__,
    )
    log.info(
        "outbox.blocked_by_switch",
        event_type=event.event_type,
        switch=type(blocked).__name__,
        state=event.state.value,
    )


def dispatch_event(
    session: Session,
    event: OutboxEvent,
    adapter: ExternalEffectAdapter,
    settings: Settings,
    *,
    actor: Actor = DISPATCHER_ACTOR,
    campaign_paused: bool = False,
    precondition_check: PreconditionCheck | None = None,
) -> EffectResult:
    """Perform one leased outbox event's effect and record what happened.

    When ``precondition_check`` is supplied it runs **inside this transaction, before the adapter is
    touched** — that placement is the whole of §11.4. Approval may have happened hours ago; between
    then and now an approval can be revoked, a recipient can unsubscribe, a campaign can be paused.

    Passing no check dispatches without rechecking, which is correct only for effects that have no
    §11.4 contract behind them. A send always has one.
    """
    if event.state is not OutboxState.DISPATCHING:
        raise OutboxError(
            f"outbox event {event.id} is {event.state.value}, not leased for dispatch; "
            f"dispatching an unleased event is how two dispatchers duplicate one effect"
        )

    if precondition_check is not None:
        _run_preconditions(session, event, precondition_check, actor=actor)

    request = EffectRequest(
        idempotency_key=event.idempotency_key,
        event_type=event.event_type,
        payload=event.payload,
    )

    try:
        result = adapter.perform(session, settings, request, campaign_paused=campaign_paused)
    except (ExternalEffectBlocked, ConsequentialWorkPaused) as blocked:
        # A §17.6 switch is an operator decision, not a failure. Letting it propagate would kill the
        # worker on its first pending event whenever shadow mode is on — which is the *default*
        # configuration — so the switch would take the whole process down instead of the send.
        # Treated as recoverable: the operator will flip it back, and the work must still be there.
        _settle_blocked(session, event, blocked, actor=actor)
        raise DispatchRefused(type(blocked).__name__, str(blocked), recoverable=True) from blocked

    if result.outcome is EffectOutcome.ACCEPTED:
        _settle(session, event, OutboxState.DISPATCHED, result, actor=actor)
    elif result.outcome is EffectOutcome.REJECTED:
        _settle(session, event, OutboxState.FAILED, result, actor=actor)
    elif result.outcome is EffectOutcome.TRANSIENT_FAILURE:
        # The one outcome that demonstrably never landed, so back to the queue.
        _settle(
            session,
            event,
            OutboxState.PENDING,
            result,
            actor=actor,
            next_attempt_at=datetime.now(UTC) + TRANSIENT_BACKOFF,
        )
    else:
        # §17.3: it may have happened. No retry is scheduled and the row becomes unleasable;
        # `reconcile_unknown` is the only way out.
        _settle(session, event, OutboxState.DELIVERY_UNKNOWN, result, actor=actor)

    log.info(
        "outbox.dispatched",
        event_type=event.event_type,
        outcome=result.outcome.value,
        state=event.state.value,
        attempt=event.attempt_count,
    )
    return result


def dispatch_once(
    session: Session,
    adapter: ExternalEffectAdapter,
    settings: Settings,
    *,
    dispatcher_id: str,
    limit: int = 1,
    actor: Actor = DISPATCHER_ACTOR,
    precondition_check: PreconditionCheck | None = None,
) -> int:
    """Lease and dispatch up to ``limit`` events. Returns how many were attempted.

    Split from any polling loop so the whole cycle is testable without sleeping.
    """
    events = lease_outbox_events(session, dispatcher_id=dispatcher_id, limit=limit)
    if not events:
        return 0

    for event in events:
        # A refusal is already settled and recorded by `_run_preconditions`; suppressing it here
        # only stops one refused event from ending the batch.
        with suppress(DispatchRefused):
            dispatch_event(
                session,
                event,
                adapter,
                settings,
                actor=actor,
                precondition_check=precondition_check,
            )
        session.commit()
    return len(events)


def reconcile_unknown(
    session: Session,
    event: OutboxEvent,
    adapter: ExternalEffectAdapter,
    *,
    actor: Actor = DISPATCHER_ACTOR,
) -> EffectResult | None:
    """Resolve a `DELIVERY_UNKNOWN` event against the provider (§17.3, §17.2 step 6).

    The only exit from `DELIVERY_UNKNOWN`, and the only thing that makes a retry safe. Asks the
    provider what really happened **before** anything is sent again:

    * the provider has a record → the effect happened; mark it dispatched and send nothing;
    * the provider has none → it did not happen; return the event to `PENDING`, where the ordinary
      dispatcher may pick it up.

    Returns what the provider said, or `None` if it had no record.
    """
    if event.state is not OutboxState.DELIVERY_UNKNOWN:
        raise OutboxError(
            f"outbox event {event.id} is {event.state.value}; only a delivery_unknown event needs "
            f"reconciliation"
        )

    truth = adapter.reconcile(event.idempotency_key)

    if truth is None:
        _settle(
            session,
            event,
            OutboxState.PENDING,
            EffectResult(
                outcome=EffectOutcome.TRANSIENT_FAILURE,
                detail="provider has no record of this effect; safe to attempt again",
            ),
            actor=actor,
            next_attempt_at=datetime.now(UTC),
        )
        log.info("outbox.reconciled", event_type=event.event_type, resolution="not_performed")
        return None

    _settle(session, event, OutboxState.DISPATCHED, truth, actor=actor)
    log.info("outbox.reconciled", event_type=event.event_type, resolution="already_performed")
    return truth
