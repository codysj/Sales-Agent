"""The transactional outbox (T-034; §17.2, §17.3, ADR-016).

The whole point of §17.2 is that a committed business decision cannot be lost before anything
external happens. So the tests here are mostly about what happens to *pairs* of writes: state and
intent survive together, or neither survives.
"""

import hashlib
import uuid

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor, record_audit_event
from app.jobs_and_outbox.outbox import (
    OutboxError,
    OutboxEvent,
    OutboxState,
    commit_with_outbox,
    enqueue_outbox_event,
)
from app.prospects.models import Account

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-outbox-test")


def a_key(seed: str) -> str:
    """A well-formed sha256 hex key. Shape matters — there is a check constraint on it."""
    return hashlib.sha256(seed.encode()).hexdigest()


def a_business_row(marker: str) -> Account:
    """Some domain state to pair the outbox event with. Any table would do."""
    return Account(name=f"Synthetic {marker}", domain=f"{marker}.invalid")


# --- the record ------------------------------------------------------------------------------


def test_an_enqueued_event_starts_pending_with_its_audit_event(db_session: Session) -> None:
    event = enqueue_outbox_event(
        db_session,
        event_type="send.email",
        idempotency_key=a_key("one"),
        actor=OPERATOR,
        payload={"channel": "email"},
    )
    db_session.flush()

    assert event.state is OutboxState.PENDING
    assert event.attempt_count == 0
    assert event.correlation_id == "corr-outbox-test"

    audit = db_session.execute(
        select(AuditEvent).where(AuditEvent.entity_id == str(event.id))
    ).scalar_one()
    assert audit.action == "outbox.enqueued"


def test_an_event_without_a_correlation_id_is_refused(db_session: Session) -> None:
    """§17.5: an external effect that cannot be traced to its cause is not auditable."""
    structlog.contextvars.clear_contextvars()

    with pytest.raises(OutboxError, match="correlation_id"):
        enqueue_outbox_event(
            db_session, event_type="send.email", idempotency_key=a_key("x"), actor=OPERATOR
        )


def test_a_malformed_idempotency_key_is_refused_by_the_database(db_session: Session) -> None:
    """The key must have the same shape as `send_command.idempotency_key` to be comparable."""
    with pytest.raises(IntegrityError, match="idempotency_key_is_sha256_hex"):
        # `enqueue_outbox_event` flushes, so the constraint fires inside the call.
        enqueue_outbox_event(
            db_session, event_type="send.email", idempotency_key="not-a-sha256", actor=OPERATOR
        )


def test_a_blank_event_type_is_refused_by_the_database(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="event_type_not_blank"):
        enqueue_outbox_event(
            db_session, event_type="   ", idempotency_key=a_key("blank"), actor=OPERATOR
        )


# --- idempotency (criterion 3) ---------------------------------------------------------------


def test_two_events_cannot_share_an_idempotency_key(db_session: Session) -> None:
    """§17.3: the unique key is what stops one decision becoming two external effects."""
    key = a_key("duplicate")
    enqueue_outbox_event(db_session, event_type="send.email", idempotency_key=key, actor=OPERATOR)

    with pytest.raises(IntegrityError, match="uq_outbox_event_idempotency_key"):
        enqueue_outbox_event(
            db_session, event_type="send.email", idempotency_key=key, actor=OPERATOR
        )


def test_an_outbox_event_for_a_send_carries_that_command_s_exact_key(
    db_session: Session,
) -> None:
    """Criterion 3's "when applicable".

    The key *is* the link between the two tables — there is no foreign key, because
    `jobs_and_outbox` may not know about `outreach_and_replies` (§18.2). Passing the command's own
    key both joins them and makes a second outbox row for the same approved send impossible.
    """
    command_key = a_key("approval:revision:recipient")

    event = enqueue_outbox_event(
        db_session,
        event_type="send.email",
        idempotency_key=command_key,
        actor=OPERATOR,
    )
    db_session.flush()

    assert event.idempotency_key == command_key


def test_the_outbox_holds_no_foreign_key_into_the_domain() -> None:
    """A structural guard: an FK here would couple generic machinery to a domain table."""
    referenced = {fk.column.table.name for fk in OutboxEvent.__table__.foreign_keys}

    assert referenced == set()


# --- atomicity (criterion 1) -----------------------------------------------------------------


def test_a_rollback_leaves_neither_business_state_nor_outbox_event(
    migrated_engine: Engine,
) -> None:
    """Criterion 1, against a real transaction that is really rolled back.

    Uses its own session rather than the rolled-back `db_session` fixture, so the rollback under
    test is the one this test performs and the assertions read committed state afterwards.
    """
    marker = f"rb-{uuid.uuid4().hex[:8]}"
    key = a_key(marker)

    with Session(migrated_engine) as session:
        structlog.contextvars.bind_contextvars(correlation_id=marker)
        session.add(a_business_row(marker))
        enqueue_outbox_event(session, event_type="send.email", idempotency_key=key, actor=OPERATOR)
        session.flush()
        # Both rows exist inside the transaction...
        assert session.execute(
            select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
        ).scalar_one_or_none()
        session.rollback()

    with Session(migrated_engine) as check:
        assert (
            check.execute(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
            ).scalar_one_or_none()
            is None
        )
        assert (
            check.execute(
                select(Account).where(Account.domain == f"{marker}.invalid")
            ).scalar_one_or_none()
            is None
        )


def test_a_commit_keeps_business_state_and_outbox_event_together(
    migrated_engine: Engine,
) -> None:
    """The other half of criterion 1: if the decision survives, the intent to act survives."""
    marker = f"ok-{uuid.uuid4().hex[:8]}"
    key = a_key(marker)

    try:
        with Session(migrated_engine) as session:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            session.add(a_business_row(marker))
            enqueue_outbox_event(
                session, event_type="send.email", idempotency_key=key, actor=OPERATOR
            )
            commit_with_outbox(session)

        with Session(migrated_engine) as check:
            assert check.execute(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
            ).scalar_one()
            assert check.execute(
                select(Account).where(Account.domain == f"{marker}.invalid")
            ).scalar_one()
    finally:
        # This test commits, unlike the `db_session` fixture. Audit events are left behind: the
        # table is append-only by design (T-011) and refuses DELETE.
        with Session(migrated_engine) as cleanup:
            for row in cleanup.execute(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
            ).scalars():
                cleanup.delete(row)
            for account in cleanup.execute(
                select(Account).where(Account.domain == f"{marker}.invalid")
            ).scalars():
                cleanup.delete(account)
            cleanup.commit()


# --- the commit discipline (criterion 2) -----------------------------------------------------


def test_an_outbox_event_without_an_audit_event_is_refused(db_session: Session) -> None:
    """Criterion 2. An external effect appearing with nothing accounting for it (§3.5)."""
    db_session.add(a_business_row("no-audit"))
    db_session.add(
        OutboxEvent(
            event_type="send.email",
            payload={},
            state=OutboxState.PENDING,
            attempt_count=0,
            idempotency_key=a_key("no-audit"),
            correlation_id="corr-outbox-test",
        )
    )

    with pytest.raises(OutboxError, match="no audit event"):
        commit_with_outbox(db_session)


def test_an_outbox_event_without_business_state_is_refused(db_session: Session) -> None:
    """§17.2 pairs the intent to act with the decision that justifies it."""
    enqueue_outbox_event(
        db_session, event_type="send.email", idempotency_key=a_key("no-state"), actor=OPERATOR
    )

    with pytest.raises(OutboxError, match="no business state change"):
        commit_with_outbox(db_session)


def test_the_refusal_happens_before_the_commit(db_session: Session) -> None:
    """A refusal that committed anyway would be worse than no check at all."""
    key = a_key("not-committed")
    enqueue_outbox_event(db_session, event_type="send.email", idempotency_key=key, actor=OPERATOR)

    with pytest.raises(OutboxError):
        commit_with_outbox(db_session)

    db_session.rollback()
    assert (
        db_session.execute(
            select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
        ).scalar_one_or_none()
        is None
    )


def test_a_commit_with_no_outbox_event_is_left_alone(migrated_engine: Engine) -> None:
    """The helper adds a check, not a second way to commit. Ordinary writes still work."""
    marker = f"plain-{uuid.uuid4().hex[:8]}"

    try:
        with Session(migrated_engine) as session:
            structlog.contextvars.bind_contextvars(correlation_id=marker)
            session.add(a_business_row(marker))
            record_audit_event(
                session,
                actor=OPERATOR,
                action="account.created",
                entity_type="account",
                entity_id=uuid.uuid4(),
                correlation_id=marker,
            )
            commit_with_outbox(session)

        with Session(migrated_engine) as check:
            assert check.execute(
                select(Account).where(Account.domain == f"{marker}.invalid")
            ).scalar_one()
    finally:
        with Session(migrated_engine) as cleanup:
            for account in cleanup.execute(
                select(Account).where(Account.domain == f"{marker}.invalid")
            ).scalars():
                cleanup.delete(account)
            cleanup.commit()


def test_committing_outside_a_transaction_is_refused(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        session.rollback()  # ends the implicit transaction without starting a new one

        with pytest.raises(OutboxError, match="active transaction"):
            commit_with_outbox(session)


# --- the outbox is not a sixth lifecycle -----------------------------------------------------


def test_outbox_state_is_not_registered_as_a_domain_lifecycle() -> None:
    """ADR-015 keeps §8.2's five lifecycles independent; the outbox is machinery, not an entity."""
    from app.core.lifecycles import LIFECYCLES

    assert OutboxState not in LIFECYCLES
    assert len(LIFECYCLES) == 5
