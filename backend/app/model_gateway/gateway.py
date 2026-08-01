"""The model gateway (T-050; specification §18.4, §18.7, §17.5, §5.1, GP-04, GP-14, ADR-017).

Everything model-related goes through `run_task`, and the order inside it is the whole design:

1. Resolve the prompt, schema, model-config, and policy versions the request names. A missing or
   expired version stops the call — business logic never carries a model name (§18.4), so an
   unresolvable configuration means there is nothing legitimate to run.
2. Check the three §18.7 budgets. **Before** any provider exists in the call stack.
3. Build the provider through `registry.build_provider`, the single audited place that decides
   what may be constructed (gate **G-03**).
4. Invoke it, and record a `ModelRun` whatever happens.

**A refusal is recorded, not just raised.** A budget that declines silently leaves no evidence it
worked, and §18.7's cost attribution needs the denominator as much as the numerator.

**The gateway enforces; the adapter computes.** §5.1 forbids the provider adapter from owning
budgets or policy, and this file is where that separation is kept: the adapter is handed a
rendered prompt and parameters, and has no way to reach a budget, a candidate, or a session.

Schema *validation* is `T-051`. The gateway records which schema version applies and returns the
provider's raw text; adding validation here would put retry and escalation in the same function
as budget accounting, and those fail for unrelated reasons.
"""

import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.versioning import (
    ModelConfigVersion,
    PolicyVersion,
    PromptVersion,
    SchemaVersion,
)
from app.core.settings import Settings, get_settings
from app.model_gateway.budgets import BudgetScope, ModelBudgets
from app.model_gateway.models import ModelRun, ModelRunOutcome
from app.model_gateway.protocol import (
    ModelProviderAdapter,
    ModelTaskRequest,
    ModelTaskResult,
)
from app.model_gateway.registry import build_provider

#: `{name}` where `name` is an identifier. Anything else in the template is left alone, so a
#: brace in prose is not mistaken for a placeholder.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ModelGatewayError(Exception):
    """The gateway refused or could not complete a task."""


class VersionUnavailable(ModelGatewayError):
    """A version the request names does not exist or is not effective.

    Raised rather than defaulted: "run it with whatever prompt is current" would make the run
    record a version it did not use (§17.5).
    """


class BudgetExceeded(ModelGatewayError):
    """A §18.7 budget refused the call. Carries the scope so an operator can widen the right one."""

    def __init__(self, scope: str, detail: str, run_id: uuid.UUID | None = None) -> None:
        self.scope = scope
        self.run_id = run_id
        super().__init__(f"{scope}: {detail}")


class ProviderFailed(ModelGatewayError):
    """The provider raised. The run is recorded as `provider_error` before this propagates."""


def _day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """The UTC day containing ``moment``.

    UTC, not a local day: the budget must not reset twice a year, and "today" has to mean the
    same thing to the API process, the worker, and a report.
    """
    start = moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _spend(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    task_name: str | None = None,
    campaign_id: uuid.UUID | None = None,
) -> tuple[int, Decimal]:
    """Calls and cost already recorded in the window, for one scope.

    Refused runs are excluded: a call that never reached a provider spent nothing, and counting
    it would let a burst of refusals lock the budget out for the rest of the day.
    """
    statement = select(func.count(), func.coalesce(func.sum(ModelRun.cost_usd), 0)).where(
        ModelRun.started_at >= start,
        ModelRun.started_at < end,
        ModelRun.outcome != ModelRunOutcome.REFUSED_BUDGET,
    )
    if task_name is not None:
        statement = statement.where(ModelRun.task_name == task_name)
    if campaign_id is not None:
        statement = statement.where(ModelRun.campaign_id == campaign_id)

    calls, cost = session.execute(statement).one()
    return int(calls), Decimal(cost)


def _refusal(scope: BudgetScope, calls: int, cost: Decimal) -> str | None:
    """Why this scope refuses, or ``None``. Both ceilings are inclusive of the call about to run."""
    if calls + 1 > scope.max_calls:
        return f"{calls} calls already made, limit {scope.max_calls}"
    if cost > scope.max_cost_usd:
        return f"{cost} spent, limit {scope.max_cost_usd}"
    return None


class DatabaseModelGateway:
    """The gateway the application uses. One instance per session is fine; it holds no state."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        budgets: ModelBudgets | None = None,
        provider: ModelProviderAdapter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.budgets = budgets or ModelBudgets()
        # Resolved once, through the audited registry. Passing one in is for tests that need a
        # failing provider; it cannot be used to smuggle a real client past the registry, because
        # no real adapter exists to pass.
        self.provider = provider or build_provider(self.settings)

    # --- version resolution -------------------------------------------------------------------

    def _require_version[T](self, session: Session, model: type[T], version_id: uuid.UUID) -> T:
        found = session.get(model, version_id)
        if found is None:
            raise VersionUnavailable(f"{model.__name__} {version_id} does not exist")
        return found

    # --- budgets ------------------------------------------------------------------------------

    def check_budgets(
        self, session: Session, request: ModelTaskRequest, *, at: datetime
    ) -> tuple[str, str] | None:
        """The first scope that refuses, as ``(scope, detail)``, or ``None``.

        Checked in narrowing order so an operator is told about the tightest limit that applies,
        which is the one they would have to change.
        """
        start, end = _day_bounds(at)

        task_calls, task_cost = _spend(session, start=start, end=end, task_name=request.task_name)
        detail = _refusal(self.budgets.per_task, task_calls, task_cost)
        if detail:
            return f"per_task:{request.task_name}", detail

        if request.campaign_id is not None:
            calls, cost = _spend(session, start=start, end=end, campaign_id=request.campaign_id)
            detail = _refusal(self.budgets.per_campaign, calls, cost)
            if detail:
                return f"per_campaign:{request.campaign_id}", detail

        calls, cost = _spend(session, start=start, end=end)
        detail = _refusal(self.budgets.daily, calls, cost)
        if detail:
            return "daily", detail

        return None

    # --- the entry point ----------------------------------------------------------------------

    def run_task(
        self,
        session: Session,
        request: ModelTaskRequest,
        *,
        at: datetime | None = None,
    ) -> ModelTaskResult:
        """Run one bounded task. Adds the `ModelRun` to ``session`` without committing."""
        moment = at or datetime.now(UTC)

        prompt = self._require_version(session, PromptVersion, request.prompt_version_id)
        schema = self._require_version(session, SchemaVersion, request.schema_version_id)
        config = self._require_version(session, ModelConfigVersion, request.model_config_version_id)
        policy = (
            self._require_version(session, PolicyVersion, request.policy_version_id)
            if request.policy_version_id
            else None
        )
        for version, label in ((prompt, "prompt"), (schema, "schema"), (config, "model config")):
            if not version.is_effective_at(moment):
                raise VersionUnavailable(
                    f"{label} version {version.key} v{version.version} is not effective at "
                    f"{moment.isoformat()}"
                )

        def record(
            outcome: ModelRunOutcome,
            *,
            failure_reason: str | None = None,
            input_tokens: int = 0,
            output_tokens: int = 0,
            cost_usd: Decimal = Decimal("0"),
            latency_ms: int = 0,
        ) -> ModelRun:
            run = ModelRun(
                task_name=request.task_name,
                prompt_version_id=prompt.id,
                schema_version_id=schema.id,
                model_config_version_id=config.id,
                policy_version_id=policy.id if policy else None,
                campaign_id=request.campaign_id,
                candidate_id=request.candidate_id,
                provider=config.provider,
                model_name=config.model_name,
                outcome=outcome,
                failure_reason=failure_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                started_at=moment,
            )
            session.add(run)
            session.flush()
            return run

        refusal = self.check_budgets(session, request, at=moment)
        if refusal is not None:
            scope, detail = refusal
            run = record(ModelRunOutcome.REFUSED_BUDGET, failure_reason=f"{scope}: {detail}")
            raise BudgetExceeded(scope, detail, run_id=run.id)

        rendered = self._render(prompt.template, request.inputs)
        parameters: dict[str, Any] = dict(config.parameters)

        started = time.perf_counter()
        try:
            response = self.provider.complete(prompt=rendered, parameters=parameters)
        except Exception as error:
            latency = int((time.perf_counter() - started) * 1000)
            record(
                ModelRunOutcome.PROVIDER_ERROR,
                failure_reason=f"{type(error).__name__}: {error}",
                latency_ms=latency,
            )
            raise ProviderFailed(f"provider {config.provider.value} failed: {error}") from error

        latency = int((time.perf_counter() - started) * 1000)
        run = record(
            ModelRunOutcome.SUCCEEDED,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=latency,
        )
        return ModelTaskResult(
            run_id=run.id,
            output_text=response.output_text,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
        )

    @staticmethod
    def _render(template: str, inputs: dict[str, Any]) -> str:
        """Substitute `{name}` placeholders, leaving anything unmatched alone.

        `str.format` is deliberately not used: it would evaluate attribute and index lookups from
        the template, and a template is data too.

        **One pass, not one pass per key.** Replacing keys in sequence would re-scan text already
        substituted, so an input whose *value* is `{secret}` would pull in the real secret on a
        later iteration — which is exactly the §15.4 failure this is supposed to prevent. A single
        regex pass inserts every value verbatim and never looks at inserted text again.
        """
        return _PLACEHOLDER.sub(
            lambda match: (
                str(inputs[match.group(1)]) if match.group(1) in inputs else match.group(0)
            ),
            template,
        )
