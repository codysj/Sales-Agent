"""The job queue (specification §17.1, ADR-003, §7.2).

PostgreSQL is the queue. ADR-010 keeps Redis out until a measured requirement exists, and at
pilot volume a table with `FOR UPDATE SKIP LOCKED` gives durability, queryability, and an audit
trail that a separate broker would not.

"No incomplete work relies only on conversational memory" (§17.1): a job is a row, so a worker
crash loses nothing — the lease expires and the row is still there.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.lifecycles import JobState
from app.db.base import Base, TimestampMixin

#: Lower runs first. 100 is the default so ordinary work can be both raised and lowered later
#: without renumbering everything.
DEFAULT_PRIORITY = 100

#: States a worker may pick up.
RUNNABLE_STATES = (JobState.QUEUED, JobState.RETRY)


class Job(Base, TimestampMixin):
    """One unit of durable work."""

    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint("length(trim(job_type)) > 0", name="job_type_not_blank"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_not_negative"),
        # A leased job must say who holds it and until when; anything else is an orphan that
        # lease recovery cannot reason about (T-032).
        CheckConstraint(
            "(state = 'LEASED') = (lease_expires_at IS NOT NULL AND leased_by IS NOT NULL)",
            name="leased_state_needs_a_holder",
        ),
        # §17.1: "Permanent or exhausted failures move to a dead state with a human-readable
        # reason." Enforced in the database, not only in `mark_dead`, so no future code path can
        # produce a dead job nobody can explain (T-031).
        CheckConstraint(
            "state <> 'DEAD' OR (last_error IS NOT NULL AND length(trim(last_error)) > 0)",
            name="dead_job_must_carry_a_reason",
        ),
        # A job awaiting a person is a dead job with a different disposition, never a live one.
        CheckConstraint(
            "NOT requires_human_review OR state = 'DEAD'",
            name="human_review_is_a_terminal_disposition",
        ),
        # The index the leasing query rides on: partial, so it stays small as succeeded and dead
        # rows accumulate, and ordered exactly as the query orders.
        Index(
            "ix_job_runnable",
            "priority",
            "next_run_at",
            postgresql_where=text("state IN ('QUEUED', 'RETRY')"),
        ),
        Index("ix_job_state", "state"),
        Index("ix_job_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: Registered name. The registry owns which payload model and handler it maps to.
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Validated against the registered Pydantic model before insert — never trusted on read.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    state: Mapped[JobState] = mapped_column(nullable=False, default=JobState.QUEUED)
    priority: Mapped[int] = mapped_column(nullable=False, default=DEFAULT_PRIORITY)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)

    #: Not eligible before this. Retry backoff pushes it forward (T-031).
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leased_by: Mapped[str | None] = mapped_column(String(255))

    #: Human-readable, and required before a job may become `dead` (§17.1, enforced above).
    last_error: Mapped[str | None] = mapped_column(Text)

    #: §7.2's fourth outcome. The job lifecycle in §8.2 has no review *state*, so "requires human
    #: review" is a disposition on `dead` — see `docs/reconciliation.md` R-003. Keeping it separate
    #: from plain `dead` is the point: "we gave up" and "a person must decide" are different
    #: queues for whoever is on duty.
    requires_human_review: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )

    #: Ties the job to the request or job that created it (§17.5).
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)

    def is_lease_expired_at(self, moment: datetime) -> bool:
        if self.state is not JobState.LEASED or self.lease_expires_at is None:
            return False
        return moment >= self.lease_expires_at

    def __repr__(self) -> str:
        return f"Job({self.job_type} {self.state.value} attempt={self.attempt_count})"
