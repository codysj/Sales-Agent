"""The `QualificationRun` record (T-053; specification §10.4, §17.5, §8.5, ADR-008).

One row per completed qualification of one candidate: the §10.4 object the model returned, the
classification pulled out into columns a reviewer can query, and a foreign key to the `ModelRun`
that produced it. Nothing here duplicates what the model run already records — prompt, schema,
model-config, and policy versions live there, and copying them would create two answers to "what
was this decision based on".

**`human_review_required` is NOT NULL with a database check that it is true.** ADR-008 requires a
human on every candidate in shadow mode and the first pilot, and the model does not get a vote:
`evaluate` sets it, the column enforces it, and `T-069`'s dashboard reads it. When the model asks
for no review, that request is recorded in `model_requested_no_review` rather than honoured —
which is the difference between a system that ignores the model and one that cannot see what the
model wanted.

Runs are append-only in practice: a re-qualification writes a new row, so a reviewer can see what
the earlier assessment said. Nothing updates a stored run.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

#: §10.4 scores are ordinal judgements for a reviewer, not probabilities (§10.2).
SCORE_MIN = 0
SCORE_MAX = 5


class QualificationRun(Base, TimestampMixin):
    """One model-supported assessment of one campaign candidate."""

    __tablename__ = "qualification_run"
    __table_args__ = (
        # ADR-008, enforced by the database rather than by remembering to set it.
        CheckConstraint("human_review_required", name="human_review_is_always_required"),
        CheckConstraint(
            f"product_fit BETWEEN {SCORE_MIN} AND {SCORE_MAX}", name="product_fit_in_range"
        ),
        CheckConstraint(
            f"buyer_relevance BETWEEN {SCORE_MIN} AND {SCORE_MAX}",
            name="buyer_relevance_in_range",
        ),
        CheckConstraint(f"timing BETWEEN {SCORE_MIN} AND {SCORE_MAX}", name="timing_in_range"),
        CheckConstraint(
            f"commercial_scale BETWEEN {SCORE_MIN} AND {SCORE_MAX}",
            name="commercial_scale_in_range",
        ),
        Index("ix_qualification_run_candidate_id", "candidate_id"),
        Index("ix_qualification_run_opportunity_type", "opportunity_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign_candidate.id", ondelete="CASCADE"), nullable=False
    )
    #: RESTRICT: the run that produced this assessment cannot be deleted out from under it.
    model_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_run.id", ondelete="RESTRICT"), nullable=False
    )

    #: §8.5's five types, as the string the schema validated. Not an enum column: the vocabulary
    #: belongs to the versioned schema (`T-051`), and duplicating it here would give a schema
    #: change two places to be wrong.
    opportunity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence_completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    source_quality: Mapped[str] = mapped_column(String(20), nullable=False)

    product_fit: Mapped[int] = mapped_column(nullable=False)
    buyer_relevance: Mapped[int] = mapped_column(nullable=False)
    timing: Mapped[int] = mapped_column(nullable=False)
    commercial_scale: Mapped[int] = mapped_column(nullable=False)

    #: Always true. See the module docstring and the check constraint.
    human_review_required: Mapped[bool] = mapped_column(nullable=False, default=True)
    #: True when the model asked for no review and was overruled. Recorded, not honoured.
    model_requested_no_review: Mapped[bool] = mapped_column(nullable=False, default=False)

    #: The validated §10.4 object exactly as it was returned, so a reviewer sees what the model
    #: said rather than a summary of it.
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    #: Why a human is being asked, in the system's words rather than the model's.
    review_reason: Mapped[str | None] = mapped_column(Text)

    qualified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"QualificationRun({self.candidate_id} {self.opportunity_type})"
