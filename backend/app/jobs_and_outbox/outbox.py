"""The transactional outbox (specification §17.2, §17.3, ADR-016).

§17.2 exists to close one specific gap: a business decision that is committed locally but lost
before anything external happens. The fix is that the decision and the *intent to act on it* are
the same commit. If the transaction survives, the outbox row survives with it, and a worker will
eventually dispatch it. If the transaction rolls back, neither ever existed.

This module owns the record and the commit discipline. Leasing, dispatch, provider correlation, and
reconciliation are `T-035`.

`OutboxState` lives here rather than in `app/core/lifecycles.py` on purpose. That module holds the
**five entity lifecycles** §8.2 names, and ADR-015 requires them to stay independent; an outbox row
is delivery machinery, not a domain entity, and adding a sixth enum there would blur exactly the
boundary that rule protects.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, SessionTransaction, mapped_column

from app.audit_and_operations.models import AuditEvent
from app.audit_and_operations.service import Actor, current_correlation_id, record_audit_event
from app.db.base import Base, TimestampMixin

ENTITY_TYPE = "outbox_event"

#: Key under which `session.info` accumulates what kinds of row this transaction has written.
_WRITTEN_KINDS = "outbox_written_kinds"

_OUTBOX = "outbox"
_AUDIT = "audit"
_BUSINESS = "business"


class OutboxState(Enum):
    """Where a pending external effect has got to.

    Not one of §8.2's five lifecycles — see the module docstring.
    """

    PENDING = "pending"
    DISPATCHING = "dispatching"
    DISPATCHED = "dispatched"
    FAILED = "failed"
    #: §17.3's distinct state for "it may have happened". Reconciliation is the only way out.
    DELIVERY_UNKNOWN = "delivery_unknown"


#: States a dispatcher may pick up. `DELIVERY_UNKNOWN` is deliberately absent: §17.3 forbids blind
#: retry after an ambiguous result, and the cheapest way to guarantee that is to make such a row
#: unleasable. It leaves only through `reconcile_unknown` (ADR-016).
DISPATCHABLE_STATES = (OutboxState.PENDING,)

#: The outbox's own transitions. Kept here rather than in `core/lifecycles.py` for the reason in the
#: module docstring: that module holds §8.2's five *entity* lifecycles and ADR-015 requires them to
#: stay independent.
OUTBOX_TRANSITIONS: dict[OutboxState, frozenset[OutboxState]] = {
    OutboxState.PENDING: frozenset({OutboxState.DISPATCHING}),
    OutboxState.DISPATCHING: frozenset(
        {
            OutboxState.DISPATCHED,
            OutboxState.FAILED,
            OutboxState.DELIVERY_UNKNOWN,
            # Back to pending for a transient failure — the one outcome §17.3 says never landed.
            OutboxState.PENDING,
        }
    ),
    OutboxState.DISPATCHED: frozenset(),
    OutboxState.FAILED: frozenset(),
    # Reconciliation resolves it either way: the provider confirms the effect (dispatched) or has no
    # record of it, which is the only thing that makes a retry safe again (pending).
    OutboxState.DELIVERY_UNKNOWN: frozenset({OutboxState.DISPATCHED, OutboxState.PENDING}),
}


class OutboxError(Exception):
    """An outbox write or commit was refused."""


class IllegalOutboxTransition(OutboxError):
    """A state change the outbox state machine does not permit."""


def assert_outbox_transition(current: OutboxState, target: OutboxState) -> None:
    """Raise unless the outbox permits ``current -> target``.

    Fails closed, including on a self-transition: re-entering the current state would write an
    audit event describing a change that did not happen (§3.5).
    """
    if target not in OUTBOX_TRANSITIONS[current]:
        allowed = sorted(s.value for s in OUTBOX_TRANSITIONS[current]) or ["(terminal)"]
        raise IllegalOutboxTransition(
            f"illegal outbox transition: {current.value} -> {target.value}. "
            f"Allowed from {current.value}: {allowed}"
        )


class OutboxEvent(Base, TimestampMixin):
    """One external effect that has been decided but not yet performed."""

    __tablename__ = "outbox_event"
    __table_args__ = (
        # §17.3: the key is what makes dispatch effectively-once. Unique, so a re-derived duplicate
        # collides here instead of producing a second external effect.
        UniqueConstraint("idempotency_key", name="uq_outbox_event_idempotency_key"),
        CheckConstraint("length(trim(event_type)) > 0", name="outbox_event_type_not_blank"),
        CheckConstraint("attempt_count >= 0", name="outbox_attempt_count_not_negative"),
        # Same shape as `send_command.idempotency_key`, which is what lets the two be compared.
        CheckConstraint(
            "idempotency_key ~ '^[0-9a-f]{64}$'", name="outbox_idempotency_key_is_sha256_hex"
        ),
        # The dispatcher's query (T-035): partial, so it stays small as dispatched rows accumulate.
        # Ordered as the dispatcher orders, so the lease query is an index scan even once most rows
        # are dispatched (T-035b).
        Index(
            "ix_outbox_pending",
            "next_attempt_at",
            "created_at",
            postgresql_where=text("state = 'PENDING'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    state: Mapped[OutboxState] = mapped_column(nullable=False, default=OutboxState.PENDING)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)

    #: §17.3. **This is the join to `send_command`, and deliberately not a foreign key.**
    #: `jobs_and_outbox` must not know the domain (§18.2, enforced by the boundary suite), so the
    #: outbox cannot reference a table `outreach_and_replies` owns. It does not need to: the key is
    #: derived from approval, revision, and recipient and is unique in *both* tables, so passing a
    #: send command's key here both links the two and makes a second outbox row for the same
    #: approved send impossible. An effect with no command behind it simply derives its own key.
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Ties the effect to the request or job that decided it (§17.5).
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # --- dispatch bookkeeping (T-035b) ---------------------------------------------------------

    #: Not dispatchable before this. A transient failure pushes it forward.
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leased_by: Mapped[str | None] = mapped_column(String(255))

    #: §17.2 step 5 and §17.3: what the provider called this effect. Required to reconcile later.
    provider_correlation_id: Mapped[str | None] = mapped_column(String(255))
    #: The last outcome as the adapter reported it, stored as its value rather than as an enum
    #: column: `EffectOutcome` belongs to the adapter contract, and pinning it into a database type
    #: would make adding an outcome a migration.
    last_outcome: Mapped[str | None] = mapped_column(String(32))
    #: Human-readable, for the dashboard and incident review (§17.5).
    last_detail: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"OutboxEvent({self.event_type} {self.state.value} {self.idempotency_key[:12]})"


def enqueue_outbox_event(
    session: Session,
    *,
    event_type: str,
    idempotency_key: str,
    actor: Actor,
    payload: Mapping[str, Any] | None = None,
    correlation_id: str | None = None,
) -> OutboxEvent:
    """Add an outbox event to the caller's transaction, with its audit event.

    Deliberately does not commit. The caller's transaction decides whether the effect happens, so
    business state, audit, and intent-to-act land together or not at all (§17.2 step 2).
    """
    resolved_correlation = correlation_id or current_correlation_id()
    if not resolved_correlation:
        raise OutboxError(
            f"no correlation_id for outbox event {event_type!r}; an external effect that cannot "
            f"be traced back to the decision that caused it is not auditable (§17.5)"
        )

    event = OutboxEvent(
        event_type=event_type,
        payload=dict(payload or {}),
        state=OutboxState.PENDING,
        attempt_count=0,
        idempotency_key=idempotency_key,
        correlation_id=resolved_correlation,
    )
    session.add(event)
    session.flush()

    record_audit_event(
        session,
        actor=actor,
        action="outbox.enqueued",
        entity_type=ENTITY_TYPE,
        entity_id=event.id,
        to_state=OutboxState.PENDING,
        payload={"event_type": event_type},
        correlation_id=resolved_correlation,
    )
    return event


def _kind(obj: object) -> str:
    if isinstance(obj, OutboxEvent):
        return _OUTBOX
    if isinstance(obj, AuditEvent):
        return _AUDIT
    return _BUSINESS


def _pending_kinds(session: Session) -> set[str]:
    return {_kind(obj) for obj in (*session.new, *session.dirty, *session.deleted)}


@event.listens_for(Session, "after_flush")
def _remember_written_kinds(session: Session, _flush_context: object) -> None:
    """Accumulate what this transaction has written, across every flush it performs.

    Without this, `commit_with_outbox` would be unreliable rather than merely imperfect: a flush
    empties ``session.new``, and both `enqueue_outbox_event` and ordinary autoflush do flush. The
    check would then inspect an empty set and wave through exactly the commit it exists to stop.
    ``after_flush`` fires while the collections are still populated, which is why it is the hook.
    """
    kinds: set[str] = session.info.setdefault(_WRITTEN_KINDS, set())
    kinds |= _pending_kinds(session)


@event.listens_for(Session, "after_commit")
def _clear_after_commit(session: Session) -> None:
    session.info.pop(_WRITTEN_KINDS, None)


@event.listens_for(Session, "after_soft_rollback")
def _clear_after_rollback(session: Session, _previous: SessionTransaction) -> None:
    session.info.pop(_WRITTEN_KINDS, None)


def commit_with_outbox(session: Session) -> None:
    """Commit a transaction that contains an outbox event, refusing the unsafe shapes.

    §17.2 step 2 is "in one database transaction, record the approval-dependent command **and**
    outbox event". A commit that carries an outbox event but no audit event, or no business state
    at all, is not that transaction — it is an external effect appearing from nowhere. Refused
    here rather than after dispatch, when the effect is already irreversible.

    Calling this without an outbox event is fine and commits normally: the point is to make the
    checked path the easy one, not to add a second way to commit.
    """
    if not session.in_transaction():
        raise OutboxError("commit_with_outbox needs an active transaction to inspect")

    # Already-flushed writes plus anything still pending: neither alone is the whole transaction.
    written: set[str] = set(session.info.get(_WRITTEN_KINDS, set())) | _pending_kinds(session)

    if _OUTBOX in written:
        if _AUDIT not in written:
            raise OutboxError(
                "an outbox event would commit with no audit event; §3.5 requires every "
                "consequential action to be attributable"
            )
        if _BUSINESS not in written:
            raise OutboxError(
                "an outbox event would commit with no business state change; §17.2 pairs the "
                "intent to act with the decision that justifies it"
            )

    session.commit()
