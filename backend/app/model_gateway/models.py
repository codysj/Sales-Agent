"""The `ModelRun` record (T-050; specification §17.5, §18.7, §19.3, ADR-017).

One row per attempted model call, written whether the call succeeded, was refused by a budget, or
failed. Two jobs:

* **Explainability.** §17.5 requires a decision to be reconstructible, and a model decision is
  only reconstructible if the prompt, schema, model configuration, and policy versions it ran
  under are recorded. They are foreign keys, not strings, so a version cannot be deleted out from
  under the run that cites it.
* **Cost attribution (§18.7).** By provider, task type, campaign, and candidate. `campaign_id`
  and `candidate_id` are plain UUID columns with **no** foreign key: `model_gateway` is a generic
  mechanism that §5.1 forbids from owning domain state, and a foreign key here would make the
  gateway a participant in the candidate lifecycle rather than a recorder of what it cost. The
  same reasoning `CRMMapping` uses for its polymorphic internal ID.

A refused run is still a run. Recording the refusal is what makes "we stopped spending" visible
later; a budget that silently declines to act leaves no evidence it worked.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import ModelProvider
from app.db.base import Base, TimestampMixin

#: Money is stored exactly. Floating point cost that drifts by a cent per call is a budget that
#: cannot be reconciled against a provider invoice.
COST_PRECISION = 12
COST_SCALE = 6


class ModelRunOutcome(Enum):
    """How one attempted call ended.

    Not one of §8.2's five lifecycles — a model call is an event, not a domain entity, and it has
    no transitions. It reaches one of these and stops (the same reasoning as `OutboxState`,
    recorded in `R-003`).
    """

    SUCCEEDED = "succeeded"
    #: Refused by a §18.7 budget before the provider was invoked.
    REFUSED_BUDGET = "refused_budget"
    #: The provider was invoked and failed or timed out.
    PROVIDER_ERROR = "provider_error"
    #: Output did not satisfy its schema. Written by `T-051`, which owns validation and retry.
    INVALID_OUTPUT = "invalid_output"


class ModelRun(Base, TimestampMixin):
    """One attempted model call and what it cost."""

    __tablename__ = "model_run"
    __table_args__ = (
        CheckConstraint("length(trim(task_name)) > 0", name="task_name_not_blank"),
        CheckConstraint("input_tokens >= 0", name="input_tokens_not_negative"),
        CheckConstraint("output_tokens >= 0", name="output_tokens_not_negative"),
        CheckConstraint("cost_usd >= 0", name="cost_not_negative"),
        CheckConstraint("latency_ms >= 0", name="latency_not_negative"),
        # A refusal or an error must say why; a success must not invent one.
        CheckConstraint(
            "(outcome = 'SUCCEEDED') = (failure_reason IS NULL)",
            name="failure_reason_matches_outcome",
        ),
        # Nothing may be spent on a call the budget refused.
        CheckConstraint(
            "outcome <> 'REFUSED_BUDGET' OR (input_tokens = 0 AND output_tokens = 0 "
            "AND cost_usd = 0)",
            name="a_refused_run_spends_nothing",
        ),
        Index("ix_model_run_task_name_started_at", "task_name", "started_at"),
        Index("ix_model_run_started_at", "started_at"),
        Index("ix_model_run_campaign_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: The bounded task, e.g. qualification or drafting (§10.2).
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)

    #: The four versions §17.5 needs to explain the decision. RESTRICT: a version cited by a run
    #: cannot be deleted, or the run stops being explainable.
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_version.id", ondelete="RESTRICT")
    )
    schema_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schema_version.id", ondelete="RESTRICT")
    )
    model_config_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_config_version.id", ondelete="RESTRICT")
    )
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_version.id", ondelete="RESTRICT")
    )

    #: Cost attribution (§18.7). Deliberately not foreign keys — see the module docstring.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column()
    candidate_id: Mapped[uuid.UUID | None] = mapped_column()

    #: Copied from the model configuration at run time, so a run still reports what it used after
    #: the configuration moves on. Never a literal in business logic (§18.4).
    provider: Mapped[ModelProvider] = mapped_column(nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)

    outcome: Mapped[ModelRunOutcome] = mapped_column(nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(COST_PRECISION, COST_SCALE), nullable=False, default=Decimal("0")
    )
    latency_ms: Mapped[int] = mapped_column(nullable=False, default=0)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"ModelRun({self.task_name} {self.outcome.value} {self.cost_usd})"
