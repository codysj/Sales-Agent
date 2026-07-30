"""Provider webhook intake (specification §15.2, §19.2, §19.4).

An inbound webhook is the least trusted input the system has: anyone who can reach the endpoint can
post to it, and §19.4 lists "forged or replayed messaging and email webhooks" as a case that must be
tested. So intake does four things and nothing else — verify, store, enqueue, return. It never
interprets the payload, because interpreting untrusted input is what the job that runs *later*, in a
transaction, with the payload already recorded, is for.

**This lives in `outreach_and_replies`, not `messaging`.** The task allowed either, but `messaging`
is forbidden from importing `jobs_and_outbox` (§18.2) precisely because ADR-006 keeps the messaging
gateway out of the workflow — and "enqueue for processing" would make it a workflow dependency.
Delivery and reply webhooks *are* a workflow dependency: they feed §17.3 reconciliation. So they
belong here, where enqueueing is allowed.

**Replay protection is a composition, not a single check.** A verbatim re-send of a captured
request is caught by the timestamp window if it arrives late, and by
`(provider, external_event_id)` uniqueness if it arrives inside the window. Neither alone is
enough: a window with no id check lets an attacker replay freely for the width of the window, and
an id check with no window lets a captured request be replayed the moment its id is purged. A
forward-dated timestamp is rejected too, because a forged future timestamp would otherwise stay
"fresh" indefinitely.
"""

import hashlib
import hmac
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum, StrEnum
from typing import Any

import structlog
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.audit_and_operations.service import Actor, current_correlation_id, record_audit_event
from app.db.base import Base, TimestampMixin
from app.jobs_and_outbox.queue import enqueue
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.registry import registry as default_registry

log = structlog.get_logger(__name__)

ENTITY_TYPE = "webhook_event"

#: How far out of step with our clock a request may be. Wide enough for ordinary provider retries
#: and clock skew, narrow enough that a captured request stops being replayable quickly.
DEFAULT_FRESHNESS = timedelta(minutes=5)

#: The job type intake enqueues. Registered by whatever module knows how to interpret the payload —
#: intake deliberately does not.
PROCESS_JOB_TYPE = "webhook.process"


class WebhookProcessingState(Enum):
    """Where an accepted webhook has got to.

    Not one of §8.2's five lifecycles — an inbound provider notification is not a domain entity. It
    lives here for the same reason `OutboxState` lives in the outbox module (see `R-003`).
    """

    RECEIVED = "received"
    ENQUEUED = "enqueued"
    PROCESSED = "processed"
    FAILED = "failed"


class RejectionReason(StrEnum):
    """Why intake refused, recorded so an operator can tell an attack from a misconfiguration."""

    #: The body or the signature does not match. Tampering, or the wrong secret.
    INVALID_SIGNATURE = "invalid_signature"
    #: Older than the freshness window. A captured request replayed later lands here.
    STALE_TIMESTAMP = "stale_timestamp"
    #: Dated in the future beyond tolerance — a forged timestamp meant to never go stale.
    FUTURE_TIMESTAMP = "future_timestamp"
    #: Malformed or absent timestamp header.
    UNPARSABLE_TIMESTAMP = "unparsable_timestamp"
    #: No signing secret is configured, so nothing can be verified. Fails closed.
    NO_SIGNING_SECRET = "no_signing_secret"
    #: Missing provider or event identifier — nothing to deduplicate on.
    INCOMPLETE_REQUEST = "incomplete_request"


class WebhookRejected(Exception):
    """Intake refused the request. Carries the reason, so the caller can log it structurally."""

    def __init__(self, reason: RejectionReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)


class WebhookEvent(Base, TimestampMixin):
    """One accepted inbound notification, stored before anything interprets it."""

    __tablename__ = "webhook_event"
    __table_args__ = (
        # The duplicate guard, and half of the replay guard. A provider retrying the same event —
        # which every provider does — must not produce a second stored event or a second job.
        UniqueConstraint(
            "provider", "external_event_id", name="uq_webhook_event_provider_external_id"
        ),
        CheckConstraint("length(trim(provider)) > 0", name="webhook_provider_not_blank"),
        CheckConstraint(
            "length(trim(external_event_id)) > 0", name="webhook_external_event_id_not_blank"
        ),
        # Only a verified request may be stored at all; an unverified row would look like evidence
        # that a provider said something (§19.4).
        CheckConstraint("signature_valid", name="webhook_event_must_be_verified"),
        Index("ix_webhook_event_received_at", "received_at"),
        # Partial: the backlog an operator or a reprocessing pass cares about stays small as
        # processed events accumulate.
        Index(
            "ix_webhook_event_unprocessed",
            "received_at",
            postgresql_where=text("state IN ('RECEIVED', 'ENQUEUED')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: Which provider sent it. A string rather than an enum: `Q-004` has chosen no provider, and an
    #: enum would have to be migrated the moment one is picked.
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The provider's own id for this notification. The deduplication key.
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)

    #: The provider's clock, as it claimed. Kept alongside `received_at` so skew is visible.
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Always true for a stored row — see the check constraint. Present because §19.2 asks for it
    #: explicitly and because a column that can only hold one value documents the invariant.
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    state: Mapped[WebhookProcessingState] = mapped_column(
        nullable=False, default=WebhookProcessingState.RECEIVED
    )

    #: The raw body as received, never a parsed interpretation of it. §15.5 forbids logging message
    #: bodies, but *storing* the provider's own notification is what makes reconciliation possible;
    #: it is not a log, and it is not what gets written to the audit trail.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)

    def __repr__(self) -> str:
        return f"WebhookEvent({self.provider}:{self.external_event_id} {self.state.value})"


def expected_signature(secret: str, *, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over ``timestamp.body``, hex-encoded.

    The timestamp is inside the signed material on purpose: signing only the body would let an
    attacker keep a captured body and attach a fresh timestamp, defeating the whole window.
    """
    payload = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_signature(secret: str, *, timestamp: str, body: bytes, signature: str) -> None:
    """Raise `WebhookRejected` unless the signature matches."""
    if not secret.strip():
        # Fails closed. An unconfigured endpoint must reject everything rather than accept
        # everything, which is the failure mode of treating a blank secret as "no check needed".
        raise WebhookRejected(
            RejectionReason.NO_SIGNING_SECRET,
            "no webhook signing secret is configured; intake refuses all requests",
        )

    expected = expected_signature(secret, timestamp=timestamp, body=body)
    # Constant-time: a plain `==` leaks how much of the signature matched, which is enough to forge
    # one byte at a time.
    if not hmac.compare_digest(expected, signature):
        raise WebhookRejected(RejectionReason.INVALID_SIGNATURE, "signature does not match body")


def verify_freshness(
    timestamp: str, *, now: datetime | None = None, window: timedelta = DEFAULT_FRESHNESS
) -> datetime:
    """Parse and bound-check the provider's timestamp. Returns it on success."""
    moment = now or datetime.now(UTC)

    try:
        claimed = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (ValueError, OverflowError, OSError) as exc:
        raise WebhookRejected(
            RejectionReason.UNPARSABLE_TIMESTAMP, "timestamp is not a unix epoch integer"
        ) from exc

    if claimed < moment - window:
        raise WebhookRejected(
            RejectionReason.STALE_TIMESTAMP,
            f"timestamp is older than the {window} freshness window",
        )
    if claimed > moment + window:
        # Rejected for its own reason: a forward-dated forgery would otherwise never go stale.
        raise WebhookRejected(
            RejectionReason.FUTURE_TIMESTAMP,
            f"timestamp is more than {window} in the future",
        )
    return claimed


def find_event(session: Session, *, provider: str, external_event_id: str) -> WebhookEvent | None:
    return session.execute(
        select(WebhookEvent).where(
            WebhookEvent.provider == provider,
            WebhookEvent.external_event_id == external_event_id,
        )
    ).scalar_one_or_none()


def receive_webhook(
    session: Session,
    *,
    provider: str,
    external_event_id: str,
    body: bytes,
    signature: str,
    timestamp: str,
    secret: str,
    payload: Mapping[str, Any] | None = None,
    actor: Actor,
    now: datetime | None = None,
    window: timedelta = DEFAULT_FRESHNESS,
    registry: JobRegistry | None = None,
    correlation_id: str | None = None,
) -> tuple[WebhookEvent, bool]:
    """Verify, store, and enqueue one inbound notification.

    Returns ``(event, created)``. ``created`` is `False` when the event had already been received,
    which is the ordinary case for a provider retry and is **not** an error: intake is idempotent,
    so the same event id twice yields one stored row and one job.

    Verification happens **before** any write. A failing request is not stored at all — a table of
    rejected requests would be an attacker-controlled write primitive, and the audit trail already
    records the refusal.
    """
    moment = now or datetime.now(UTC)

    if not provider.strip() or not external_event_id.strip():
        raise WebhookRejected(
            RejectionReason.INCOMPLETE_REQUEST,
            "provider and external event id are both required to deduplicate",
        )

    verify_signature(secret, timestamp=timestamp, body=body, signature=signature)
    claimed = verify_freshness(timestamp, now=moment, window=window)

    resolved_correlation = (
        correlation_id or current_correlation_id() or f"webhook-{uuid.uuid4().hex}"
    )

    existing = find_event(session, provider=provider, external_event_id=external_event_id)
    if existing is not None:
        # A duplicate is expected traffic, not an incident: providers retry. Logged at info and not
        # audited, because nothing changed.
        log.info(
            "webhook.duplicate",
            provider=provider,
            external_event_id=external_event_id,
            state=existing.state.value,
        )
        return existing, False

    event = WebhookEvent(
        provider=provider,
        external_event_id=external_event_id,
        event_timestamp=claimed,
        received_at=moment,
        signature_valid=True,
        state=WebhookProcessingState.RECEIVED,
        payload=dict(payload or {}),
        correlation_id=resolved_correlation,
    )
    session.add(event)
    session.flush()

    active = registry or default_registry
    if active.is_registered(PROCESS_JOB_TYPE):
        enqueue(
            session,
            job_type=PROCESS_JOB_TYPE,
            payload={"webhook_event_id": str(event.id)},
            actor=actor,
            registry=active,
            correlation_id=resolved_correlation,
        )
        event.state = WebhookProcessingState.ENQUEUED
        session.flush()
    else:
        # No handler registered yet (`T-103` classifies replies). The event is still stored and
        # verified, so nothing is lost and a later deploy can process the backlog. Warned, not
        # raised: dropping a verified provider notification is worse than holding it.
        log.warning("webhook.no_handler_registered", provider=provider, job_type=PROCESS_JOB_TYPE)

    record_audit_event(
        session,
        actor=actor,
        action="webhook.received",
        entity_type=ENTITY_TYPE,
        entity_id=event.id,
        to_state=event.state,
        # Identifiers and outcome only. The body stays in `payload` on the row and out of the audit
        # trail, which §15.5 requires.
        payload={
            "provider": provider,
            "external_event_id": external_event_id,
            "enqueued": event.state is WebhookProcessingState.ENQUEUED,
        },
        correlation_id=resolved_correlation,
    )
    return event, True
