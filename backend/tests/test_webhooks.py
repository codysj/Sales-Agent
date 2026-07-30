"""Webhook intake (T-036; §15.2, §19.2, §19.4).

§19.4 names "forged or replayed messaging and email webhooks" as a security case that must be
tested, so these tests are written as an attacker would: keep a captured request and try to get it
accepted a second time, or change one byte and see whether anyone notices.

**No provider secret appears anywhere in this file.** Each test generates its own random secret, so
there is nothing here that could become a committed credential (criterion 3) and nothing that stops
working when `Q-004` finally picks a provider.
"""

import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.core.settings import Settings
from app.jobs_and_outbox.models import Job
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.retry import RetryPolicy
from app.outreach_and_replies.webhooks import (
    DEFAULT_FRESHNESS,
    PROCESS_JOB_TYPE,
    RejectionReason,
    WebhookEvent,
    WebhookProcessingState,
    WebhookRejected,
    expected_signature,
    find_event,
    receive_webhook,
    verify_freshness,
    verify_signature,
)

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
PROVIDER = "synthetic-provider"


class WebhookPayload(BaseModel):
    webhook_event_id: str


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-webhook-test")


@pytest.fixture
def secret() -> str:
    """A fresh random secret per test.

    Generated rather than hard-coded so this file can never become the place a real provider secret
    gets committed (criterion 3).
    """
    return secrets.token_hex(32)


@pytest.fixture
def registry() -> JobRegistry:
    """A registry that knows how to process webhooks, so intake has somewhere to enqueue."""
    registry = JobRegistry()
    registry.register(
        PROCESS_JOB_TYPE,
        WebhookPayload,
        lambda session, payload, *, job_id: None,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=timedelta(seconds=1), jitter=0.0),
        consequential=False,
    )
    return registry


class Request:
    """A signed request, as a provider would send it — and as an attacker would capture it."""

    def __init__(self, secret: str, *, event_id: str | None = None, at: datetime = NOW) -> None:
        self.event_id = event_id or f"evt-{uuid.uuid4().hex[:12]}"
        self.body = json.dumps(
            {"id": self.event_id, "type": "delivery", "recipient": "synthetic@example.invalid"},
            sort_keys=True,
        ).encode()
        self.timestamp = str(int(at.timestamp()))
        self.signature = expected_signature(secret, timestamp=self.timestamp, body=self.body)

    def deliver(
        self,
        session: Session,
        secret: str,
        registry: JobRegistry,
        *,
        now: datetime = NOW,
        body: bytes | None = None,
        signature: str | None = None,
        timestamp: str | None = None,
    ) -> tuple[WebhookEvent, bool]:
        return receive_webhook(
            session,
            provider=PROVIDER,
            external_event_id=self.event_id,
            body=body if body is not None else self.body,
            signature=signature if signature is not None else self.signature,
            timestamp=timestamp if timestamp is not None else self.timestamp,
            secret=secret,
            payload=json.loads(body if body is not None else self.body),
            actor=OPERATOR,
            now=now,
            registry=registry,
        )


# --- the happy path, so every rejection test below means something -----------------------------


def test_a_valid_request_is_stored_and_enqueued(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    request = Request(secret)

    event, created = request.deliver(db_session, secret, registry)
    db_session.flush()

    assert created is True
    assert event.signature_valid is True
    assert event.state is WebhookProcessingState.ENQUEUED
    assert event.provider == PROVIDER
    assert event.event_timestamp == NOW
    assert db_session.query(Job).filter(Job.job_type == PROCESS_JOB_TYPE).count() == 1


def test_intake_does_not_interpret_the_payload(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """Intake stores the provider's own notification verbatim and enqueues; nothing more.

    Interpreting untrusted input is the job's work, not intake's — by then the payload is recorded
    and the interpretation happens inside a transaction that can be rolled back.
    """
    request = Request(secret)

    event, _ = request.deliver(db_session, secret, registry)

    assert event.payload == json.loads(request.body)
    assert event.state is WebhookProcessingState.ENQUEUED


def test_a_verified_event_is_stored_even_with_no_handler_registered(
    db_session: Session, secret: str
) -> None:
    """Dropping a verified provider notification is worse than holding one nobody can process yet.

    `T-103` classifies replies. Until it exists, the event is stored and stays `RECEIVED`, so a
    later deploy can work through the backlog.
    """
    request = Request(secret)

    event, created = request.deliver(db_session, secret, JobRegistry())

    assert created is True
    assert event.state is WebhookProcessingState.RECEIVED
    assert db_session.query(Job).count() == 0


def test_intake_writes_an_audit_event_without_the_body(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """§15.5: the payload lives on the row, not in the audit trail."""
    request = Request(secret)
    event, _ = request.deliver(db_session, secret, registry)
    db_session.flush()

    audit = db_session.execute(
        select(AuditEvent).where(AuditEvent.entity_id == str(event.id))
    ).scalar_one()
    assert audit.action == "webhook.received"
    assert audit.payload["external_event_id"] == request.event_id
    assert "recipient" not in json.dumps(audit.payload), "no message content in the audit trail"


# --- 1. tampered signature (criterion 1) -------------------------------------------------------


def test_a_tampered_body_is_rejected(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """One changed byte must invalidate the signature."""
    request = Request(secret)
    tampered = request.body.replace(b"synthetic@example.invalid", b"attacker@example.invalid")
    assert tampered != request.body

    with pytest.raises(WebhookRejected) as caught:
        request.deliver(db_session, secret, registry, body=tampered)

    assert caught.value.reason is RejectionReason.INVALID_SIGNATURE
    assert db_session.query(WebhookEvent).count() == 0, "a rejected request must not be stored"


def test_a_forged_signature_is_rejected(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    request = Request(secret)

    with pytest.raises(WebhookRejected) as caught:
        request.deliver(db_session, secret, registry, signature="0" * 64)

    assert caught.value.reason is RejectionReason.INVALID_SIGNATURE


def test_a_signature_from_the_wrong_secret_is_rejected(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """The case where an attacker has the algorithm but not the key."""
    request = Request(secrets.token_hex(32))

    with pytest.raises(WebhookRejected) as caught:
        request.deliver(db_session, secret, registry)

    assert caught.value.reason is RejectionReason.INVALID_SIGNATURE


def test_the_timestamp_is_inside_the_signed_material(secret: str) -> None:
    """Otherwise an attacker keeps a captured body and attaches a fresh timestamp.

    That single omission would defeat the entire freshness window, so it is pinned directly rather
    than inferred from the intake tests.
    """
    body = b'{"id": "evt-1"}'
    early = expected_signature(secret, timestamp="1000", body=body)
    later = expected_signature(secret, timestamp="2000", body=body)

    assert early != later


def test_an_unconfigured_secret_rejects_everything(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """Fail closed. A blank secret must not read as "no check needed"."""
    request = Request(secret)

    with pytest.raises(WebhookRejected) as caught:
        request.deliver(db_session, "", registry)

    assert caught.value.reason is RejectionReason.NO_SIGNING_SECRET


def test_the_shipped_secret_is_blank() -> None:
    """Criterion 3: nothing provider-specific is committed, and the default is the safe one."""
    assert Settings().webhook_signing_secret == ""


# --- 2. stale and forward-dated timestamps (criterion 1) ---------------------------------------


def test_a_stale_request_is_rejected(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """A correctly signed request that arrives too late. This is a captured request, replayed."""
    request = Request(secret, at=NOW - DEFAULT_FRESHNESS - timedelta(seconds=1))

    with pytest.raises(WebhookRejected) as caught:
        request.deliver(db_session, secret, registry)

    assert caught.value.reason is RejectionReason.STALE_TIMESTAMP


def test_a_forward_dated_request_is_rejected(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """Its own reason, because a forged future timestamp would otherwise never go stale.

    Without this check an attacker signs one request dated a year out and replays it all year.
    """
    request = Request(secret, at=NOW + DEFAULT_FRESHNESS + timedelta(seconds=1))

    with pytest.raises(WebhookRejected) as caught:
        request.deliver(db_session, secret, registry)

    assert caught.value.reason is RejectionReason.FUTURE_TIMESTAMP


def test_a_request_at_the_edge_of_the_window_is_accepted(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """The boundary is inclusive, so ordinary clock skew does not drop real notifications."""
    request = Request(secret, at=NOW - DEFAULT_FRESHNESS)

    _, created = request.deliver(db_session, secret, registry)

    assert created is True


def test_an_unparsable_timestamp_is_rejected(secret: str) -> None:
    with pytest.raises(WebhookRejected) as caught:
        verify_freshness("not-a-number", now=NOW)

    assert caught.value.reason is RejectionReason.UNPARSABLE_TIMESTAMP


# --- 3. duplicates are idempotent, not errors (criteria 1 and 2) --------------------------------


def test_the_same_event_twice_yields_one_event_and_one_job(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """Criterion 2. Every provider retries; a retry must not double-process."""
    request = Request(secret)

    first, created_first = request.deliver(db_session, secret, registry)
    db_session.flush()
    second, created_second = request.deliver(db_session, secret, registry)
    db_session.flush()

    assert created_first is True
    assert created_second is False, "a duplicate is expected traffic, not an error"
    assert first.id == second.id
    assert db_session.query(WebhookEvent).count() == 1
    assert db_session.query(Job).filter(Job.job_type == PROCESS_JOB_TYPE).count() == 1


def test_a_duplicate_does_not_advance_the_state(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """A re-delivery of an already-processed event must not send it back through processing."""
    request = Request(secret)
    event, _ = request.deliver(db_session, secret, registry)
    event.state = WebhookProcessingState.PROCESSED
    db_session.flush()

    again, created = request.deliver(db_session, secret, registry)

    assert created is False
    assert again.state is WebhookProcessingState.PROCESSED


def test_two_different_events_are_both_stored(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    Request(secret).deliver(db_session, secret, registry)
    Request(secret).deliver(db_session, secret, registry)
    db_session.flush()

    assert db_session.query(WebhookEvent).count() == 2


def test_the_same_event_id_from_a_different_provider_is_a_different_event(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """Deduplication is per provider: two providers can legitimately use the same id space."""
    request = Request(secret)
    request.deliver(db_session, secret, registry)
    receive_webhook(
        db_session,
        provider="other-synthetic-provider",
        external_event_id=request.event_id,
        body=request.body,
        signature=request.signature,
        timestamp=request.timestamp,
        secret=secret,
        actor=OPERATOR,
        now=NOW,
        registry=registry,
    )
    db_session.flush()

    assert db_session.query(WebhookEvent).count() == 2


# --- 4. replay (criterion 1) -------------------------------------------------------------------


def test_a_captured_request_replayed_inside_the_window_is_deduplicated(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """§19.4's replay case, first half.

    The attacker has a byte-perfect copy of a real request — valid signature, fresh timestamp. The
    id uniqueness is what stops it, and the outcome is *one* stored event and *one* job.
    """
    captured = Request(secret)
    captured.deliver(db_session, secret, registry)
    db_session.flush()

    _, created = captured.deliver(db_session, secret, registry, now=NOW + timedelta(minutes=1))
    db_session.flush()

    assert created is False
    assert db_session.query(WebhookEvent).count() == 1
    assert db_session.query(Job).filter(Job.job_type == PROCESS_JOB_TYPE).count() == 1


def test_a_captured_request_replayed_after_the_window_is_rejected_outright(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """§19.4's replay case, second half.

    Once the window has passed the request is refused before anything is looked up, so replay does
    not depend on the event id still being on file. The two guards cover different halves of the
    attack, which is why both exist.
    """
    captured = Request(secret)

    with pytest.raises(WebhookRejected) as caught:
        captured.deliver(
            db_session, secret, registry, now=NOW + DEFAULT_FRESHNESS + timedelta(seconds=1)
        )

    assert caught.value.reason is RejectionReason.STALE_TIMESTAMP
    assert db_session.query(WebhookEvent).count() == 0


def test_every_rejection_has_its_own_reason() -> None:
    """Criterion 1 asks for distinct reasons, so an operator can tell an attack from a typo."""
    reasons = {reason.value for reason in RejectionReason}

    assert len(reasons) == len(list(RejectionReason))
    assert {
        "invalid_signature",
        "stale_timestamp",
        "future_timestamp",
        "no_signing_secret",
    } <= reasons


# --- what the schema refuses on its own --------------------------------------------------------


def test_an_incomplete_request_is_refused(
    db_session: Session, secret: str, registry: JobRegistry
) -> None:
    """Without a provider and an id there is nothing to deduplicate on, so nothing is safe."""
    request = Request(secret)

    with pytest.raises(WebhookRejected) as caught:
        receive_webhook(
            db_session,
            provider=PROVIDER,
            external_event_id="   ",
            body=request.body,
            signature=request.signature,
            timestamp=request.timestamp,
            secret=secret,
            actor=OPERATOR,
            now=NOW,
            registry=registry,
        )

    assert caught.value.reason is RejectionReason.INCOMPLETE_REQUEST


def test_the_database_refuses_an_unverified_event(db_session: Session) -> None:
    """A stored row asserts a provider really said this, so `signature_valid` cannot be false."""
    from sqlalchemy.exc import IntegrityError

    db_session.add(
        WebhookEvent(
            provider=PROVIDER,
            external_event_id="evt-unverified",
            event_timestamp=NOW,
            received_at=NOW,
            signature_valid=False,
            state=WebhookProcessingState.RECEIVED,
            payload={},
            correlation_id="corr-webhook-test",
        )
    )

    with pytest.raises(IntegrityError, match="webhook_event_must_be_verified"):
        db_session.flush()


def test_the_database_refuses_two_rows_for_one_provider_event(db_session: Session) -> None:
    """`receive_webhook` reads before writing, so this constraint is what covers the race."""
    from sqlalchemy.exc import IntegrityError

    def row() -> WebhookEvent:
        return WebhookEvent(
            provider=PROVIDER,
            external_event_id="evt-raced",
            event_timestamp=NOW,
            received_at=NOW,
            signature_valid=True,
            state=WebhookProcessingState.RECEIVED,
            payload={},
            correlation_id="corr-webhook-test",
        )

    db_session.add(row())
    db_session.flush()
    db_session.add(row())

    with pytest.raises(IntegrityError, match="uq_webhook_event_provider_external_id"):
        db_session.flush()


# --- helpers used directly ---------------------------------------------------------------------


def test_verify_signature_accepts_a_correct_signature(secret: str) -> None:
    body = b'{"id": "evt-1"}'
    signature = expected_signature(secret, timestamp="1000", body=body)

    verify_signature(secret, timestamp="1000", body=body, signature=signature)


def test_find_event_returns_none_for_an_unknown_event(db_session: Session) -> None:
    assert find_event(db_session, provider=PROVIDER, external_event_id="evt-absent") is None
