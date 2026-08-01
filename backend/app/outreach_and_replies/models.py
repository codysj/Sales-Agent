"""Outreach execution records (specification §11.4, §8.2, §17.3, ADR-016).

**Nothing in this module sends anything.** These are the records an eventual send is made *from*
and reconciled *against*. Dispatch is `T-035`, behind a fake adapter, behind gate **G-07**.

The design follows ADR-016's "effectively-once" position, which starts by admitting that exactly
once is not achievable across a database/provider boundary:

* A ``SendCommand`` is an immutable order carrying the whole §11.4 field list, including a unique
  ``idempotency_key`` derived from what is being sent to whom under which approval. A duplicate
  order therefore collides rather than producing a second message.
* A ``SendAttempt`` records what the provider actually said, including *ambiguous*.
* ``delivery_unknown`` on the thread is a real destination, not an error path. §17.3: "no blind
  retry after an ambiguous send result" — the way out is reconciliation with the provider, and
  `app.core.lifecycles` has no edge from it back to ``sending`` or ``queued``.
"""

import hashlib
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.lifecycles import OutreachThreadState
from app.db.base import Base, TimestampMixin


class ActionType(Enum):
    """§11.4 ``action_type``. Only email exists; a channel is added when its gate opens."""

    EMAIL_SEND = "email_send"


class AttemptOutcome(Enum):
    """What the provider said.

    ``AMBIGUOUS`` is the one that matters: the provider may or may not have accepted the message,
    and §17.3 forbids resolving that by sending again.
    """

    ACCEPTED = "accepted"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    REFUSED_BY_SHADOW_MODE = "refused_by_shadow_mode"


class DeliveryEventType(Enum):
    """Provider-reported outcomes after acceptance (§8.3 steps 13 to 16)."""

    DELIVERED = "delivered"
    BOUNCED = "bounced"
    REPLIED = "replied"
    UNSUBSCRIBED = "unsubscribed"
    COMPLAINED = "complained"
    DEFERRED = "deferred"


class InteractionDirection(Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


def build_idempotency_key(
    *,
    approval_id: uuid.UUID,
    message_revision_id: uuid.UUID,
    recipient_contact_point_id: uuid.UUID,
) -> str:
    """Derive the key from what is being sent, to whom, under which approval.

    Deterministic on purpose: re-deriving it for the same logical send produces the same key, so a
    duplicate order collides on the unique constraint instead of becoming a second message. A
    random key would make every retry look like a new send (§17.3).
    """
    material = f"{approval_id}:{message_revision_id}:{recipient_contact_point_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class OutreachThread(Base, TimestampMixin):
    """The outreach conversation for one campaign membership (§8.2)."""

    __tablename__ = "outreach_thread"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_outreach_thread_candidate"),
        Index("ix_outreach_thread_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign_candidate.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[OutreachThreadState] = mapped_column(
        nullable=False, default=OutreachThreadState.NOT_STARTED
    )

    #: Set when the thread reaches ``delivery_unknown``. A human resolves it; nothing auto-clears.
    unresolved_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    send_commands: Mapped[list["SendCommand"]] = relationship(back_populates="thread")

    def needs_manual_reconciliation(self) -> bool:
        """True while the thread sits in ``delivery_unknown`` (ADR-016, §17.3)."""
        return self.state is OutreachThreadState.DELIVERY_UNKNOWN

    def __repr__(self) -> str:
        return f"OutreachThread({self.state.value} for {self.candidate_id})"


class SendCommand(Base, TimestampMixin):
    """An immutable order to send one exact message (the §11.4 contract).

    Every field the specification lists is present and NOT NULL unless the specification allows
    its absence: a command that cannot say which approval authorized it, which revision it
    carries, or which product and claim versions were in force is not auditable.
    """

    __tablename__ = "send_command"
    __table_args__ = (
        # The duplicate-send guard. Deterministic key + unique constraint = effectively once.
        UniqueConstraint("idempotency_key", name="uq_send_command_idempotency_key"),
        # One command per approval: an approval authorizes one send, not a stream of them.
        UniqueConstraint("approval_id", name="uq_send_command_approval"),
        CheckConstraint("length(trim(actor_id)) > 0", name="actor_id_not_blank"),
        CheckConstraint("idempotency_key ~ '^[0-9a-f]{64}$'", name="idempotency_key_is_sha256_hex"),
        Index("ix_send_command_thread_id", "thread_id"),
    )

    #: §11.4 ``action_id``.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    action_type: Mapped[ActionType] = mapped_column(nullable=False, default=ActionType.EMAIL_SEND)

    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_thread.id", ondelete="RESTRICT"), nullable=False
    )

    #: Who caused the action to exist — an `Actor` id, not a user (ADR-025). `T-136` closed
    #: without converting this one: the dispatcher orders a send as legitimately as a person.
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign.id", ondelete="RESTRICT"), nullable=False
    )
    #: §11.4 ``recipient_id`` — the exact address, not the person.
    recipient_contact_point_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact_point.id", ondelete="RESTRICT"), nullable=False
    )
    message_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message_revision.id", ondelete="RESTRICT"), nullable=False
    )
    approval_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval.id", ondelete="RESTRICT"), nullable=False
    )
    #: Copied, not looked up: the dispatch recheck compares against what was true at order time.
    approval_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: §11.4 ``record_versions`` — whatever row versions the decision depended on.
    record_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    product_status_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_status_version.id", ondelete="RESTRICT")
    )
    approved_claim_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approved_claim_set.id", ondelete="RESTRICT")
    )

    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)

    thread: Mapped[OutreachThread] = relationship(back_populates="send_commands")
    attempts: Mapped[list["SendAttempt"]] = relationship(
        back_populates="command", order_by="SendAttempt.attempt_number"
    )

    def __repr__(self) -> str:
        return f"SendCommand({self.action_type.value} {self.idempotency_key[:12]})"


class SendAttempt(Base, TimestampMixin):
    """One try at handing a command to a provider, and what came back (§17.3)."""

    __tablename__ = "send_attempt"
    __table_args__ = (
        UniqueConstraint(
            "send_command_id", "attempt_number", name="uq_send_attempt_command_number"
        ),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        Index("ix_send_attempt_command_id", "send_command_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    send_command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("send_command.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[AttemptOutcome | None] = mapped_column()

    #: What the provider called it. Needed to reconcile an ambiguous attempt without resending.
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    provider_response_code: Mapped[str | None] = mapped_column(String(50))
    #: Type or short description only — never the provider's raw body, which can quote the
    #: message and the recipient (§15.5).
    error_summary: Mapped[str | None] = mapped_column(Text)

    command: Mapped[SendCommand] = relationship(back_populates="attempts")

    def __repr__(self) -> str:
        outcome = self.outcome.value if self.outcome else "in-flight"
        return f"SendAttempt(#{self.attempt_number} {outcome})"


class DeliveryEvent(Base, TimestampMixin):
    """A provider-reported outcome, recorded idempotently (§15.2, §8.3 step 13)."""

    __tablename__ = "delivery_event"
    __table_args__ = (
        # Providers redeliver webhooks. The same provider event must never be counted twice.
        UniqueConstraint("provider", "provider_event_id", name="uq_delivery_event_provider_event"),
        Index("ix_delivery_event_thread_id", "thread_id"),
        Index("ix_delivery_event_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_thread.id", ondelete="CASCADE"), nullable=False
    )
    #: Nullable: a provider may report an event we cannot tie back to one command.
    send_command_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("send_command.id", ondelete="SET NULL")
    )

    event_type: Mapped[DeliveryEventType] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    def __repr__(self) -> str:
        return f"DeliveryEvent({self.event_type.value} from {self.provider})"


class Interaction(Base, TimestampMixin):
    """Something that happened with the prospect, in either direction (§14.1).

    Substantive replies are handed to a named human (§8.3 step 17). Autonomous reply handling is
    rejected (§21.2), so ``requires_human`` starts true for anything inbound.
    """

    __tablename__ = "interaction"
    __table_args__ = (Index("ix_interaction_thread_id", "thread_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_thread.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[InteractionDirection] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: A short description, not the message body (§15.5).
    summary: Mapped[str | None] = mapped_column(Text)
    requires_human: Mapped[bool] = mapped_column(nullable=False, default=True)
    handled_by: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:
        return f"Interaction({self.direction.value} at {self.occurred_at:%Y-%m-%d})"
