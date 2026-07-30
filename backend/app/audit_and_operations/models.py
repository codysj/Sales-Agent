"""The audit trail (specification §3.5, §17.5).

Every consequential action must have an actor, a revision, a policy decision, and an audit
event. That is a safety invariant, not a target — so this table is **append-only at the database
level**, not merely by convention: an audit trail an application can edit is not evidence.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ActorType(Enum):
    """Human and service identities stay distinct (§12.2, §15.1).

    ``SYSTEM`` is for actions no identity requested — scheduled sweeps, lease reclamation — and
    is never a substitute for an unknown human.
    """

    HUMAN = "human"
    SERVICE = "service"
    SYSTEM = "system"


class AuditEvent(Base):
    """One immutable record of something consequential having happened."""

    __tablename__ = "audit_event"
    __table_args__ = (
        # An event attributable to nobody is not an audit record.
        CheckConstraint("length(trim(actor_id)) > 0", name="actor_id_not_blank"),
        CheckConstraint("length(trim(correlation_id)) > 0", name="correlation_id_not_blank"),
        CheckConstraint("length(trim(action)) > 0", name="action_not_blank"),
        CheckConstraint("length(trim(entity_id)) > 0", name="entity_id_not_blank"),
        Index("ix_audit_event_entity", "entity_type", "entity_id"),
        Index("ix_audit_event_correlation_id", "correlation_id"),
        Index("ix_audit_event_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Database clock, not the application's: API, worker, and migrations all write here, and an
    # audit ordering that depends on which process wrote would not be evidence of anything.
    #
    # `clock_timestamp()`, not `now()`. In PostgreSQL `now()` is the *transaction* start time, so
    # every event written in one transaction would share a timestamp and the trail could not be
    # ordered — and a transaction is exactly where a sequence of related events happens
    # (request → candidate transition → revision → approval). §17.5 needs that history readable.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    # Joins a request to the jobs it enqueued and the effects they produced (§17.5).
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)

    actor_type: Mapped[ActorType] = mapped_column(nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Lifecycle movement, when this event records one (§8.2). Stored as the enum *values* so a
    # later vocabulary change cannot rewrite what history says happened.
    from_state: Mapped[str | None] = mapped_column(String(50))
    to_state: Mapped[str | None] = mapped_column(String(50))

    # Why a policy allowed or refused the action (§17.5 "policy denials and security events").
    policy_decision: Mapped[str | None] = mapped_column(Text)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    # Versions that make a decision reproducible (§17.5). Only the application version is always
    # known; the rest apply to model-assisted actions.
    app_version: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    schema_version: Mapped[str | None] = mapped_column(String(50))
    policy_version: Mapped[str | None] = mapped_column(String(50))
    model_config_version: Mapped[str | None] = mapped_column(String(50))

    def __repr__(self) -> str:
        return (
            f"AuditEvent({self.action} {self.entity_type}:{self.entity_id} "
            f"by {self.actor_type.value}:{self.actor_id})"
        )
