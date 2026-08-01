"""The model gateway (T-050; §18.4, §18.7, §17.5, §5.1, ADR-017, gate **G-03**).

Four things are under test, and three of them are refusals:

* a real provider cannot be constructed — two independent locks and an empty registry;
* every call writes a `ModelRun` carrying the four versions §17.5 needs to explain it;
* a budget refuses **before** the provider is reached, in all three §18.7 scopes;
* no model name or endpoint appears anywhere in business logic.

The budget tests trip the *call* caps rather than the cost caps, because the only provider that
exists reports zero cost. The cost caps are tested separately with a stub adapter that reports a
price, so the check is proven to work before a real provider ever supplies one.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.versioning import (
    ModelConfigVersion,
    PolicyVersion,
    PromptVersion,
    SchemaVersion,
    content_hash,
)
from app.core.settings import AppEnv, ModelProvider, Settings
from app.model_gateway.budgets import BudgetScope, ModelBudgets
from app.model_gateway.gateway import (
    BudgetExceeded,
    DatabaseModelGateway,
    ProviderFailed,
    VersionUnavailable,
)
from app.model_gateway.models import ModelRun, ModelRunOutcome
from app.model_gateway.protocol import (
    ModelGateway,
    ModelProviderAdapter,
    ModelTaskRequest,
    ProviderResponse,
)
from app.model_gateway.providers.echo import EchoModelAdapter
from app.model_gateway.registry import (
    REAL_PROVIDER_ADAPTERS,
    ProviderNotPermitted,
    build_provider,
)
from tests.factories import NOW

APP = Path(__file__).resolve().parents[1] / "app"

TEST_SETTINGS = Settings(app_env=AppEnv.TEST)


# --- a world of versions ----------------------------------------------------------------------


def make_versions(
    session: Session, *, template: str = "SYNTHETIC prompt for {subject}"
) -> tuple[PromptVersion, SchemaVersion, ModelConfigVersion, PolicyVersion]:
    key = uuid.uuid4().hex[:8]
    prompt = PromptVersion(
        key=f"synthetic-prompt-{key}",
        version=1,
        content_hash=content_hash(template),
        effective_from=NOW - timedelta(days=1),
        created_by="operator-1",
        task_name="synthetic_task",
        template=template,
    )
    schema = SchemaVersion(
        key=f"synthetic-schema-{key}",
        version=1,
        content_hash=content_hash({"type": "object"}),
        effective_from=NOW - timedelta(days=1),
        created_by="operator-1",
        json_schema={"type": "object"},
    )
    config = ModelConfigVersion(
        key=f"synthetic-config-{key}",
        version=1,
        content_hash=content_hash("config"),
        effective_from=NOW - timedelta(days=1),
        created_by="operator-1",
        provider=ModelProvider.FAKE,
        model_name="deterministic-fake",
        parameters={"temperature": 0},
    )
    policy = PolicyVersion(
        key=f"synthetic-policy-{key}",
        version=1,
        content_hash=content_hash({}),
        effective_from=NOW - timedelta(days=1),
        created_by="operator-1",
        policy_type="messaging",
        body={},
    )
    session.add_all([prompt, schema, config, policy])
    session.flush()
    return prompt, schema, config, policy


def make_request(
    session: Session, *, campaign_id: uuid.UUID | None = None, task_name: str = "synthetic_task"
) -> ModelTaskRequest:
    prompt, schema, config, policy = make_versions(session)
    return ModelTaskRequest(
        task_name=task_name,
        prompt_version_id=prompt.id,
        schema_version_id=schema.id,
        model_config_version_id=config.id,
        policy_version_id=policy.id,
        inputs={"subject": "SYNTHETIC-Account"},
        campaign_id=campaign_id,
    )


@dataclass
class PricedAdapter:
    """A stub that reports a price, so the cost caps can be proven before a provider exists."""

    model_name: str = "deterministic-fake"
    price: Decimal = Decimal("1.00")

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
        return ProviderResponse(
            output_text="SYNTHETIC", input_tokens=1, output_tokens=1, cost_usd=self.price
        )


class ExplodingAdapter:
    model_name = "deterministic-fake"

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
        raise RuntimeError("SYNTHETIC provider failure")


# --- criterion 1: only the fake provider can be constructed ------------------------------------


def test_default_configuration_resolves_to_the_fake_provider() -> None:
    assert isinstance(build_provider(TEST_SETTINGS), EchoModelAdapter)
    assert TEST_SETTINGS.model_provider is ModelProvider.FAKE
    assert TEST_SETTINGS.allow_real_model_provider is False


class FutureProvider(StrEnum):
    """Stands in for a member gate **G-03** might one day add to `ModelProvider`.

    Defined here rather than added to the real enum on purpose: the guarantee under test is that
    adding a member changes nothing on its own, and proving that must not require changing the
    thing whose single-member state another test asserts.
    """

    SOME_FUTURE_PROVIDER = "some-future-provider"


def test_a_non_fake_provider_is_refused_without_the_gate_flag() -> None:
    """The first lock. `model_construct` bypasses validation to seat the stand-in member."""
    settings = Settings.model_construct(
        model_provider=FutureProvider.SOME_FUTURE_PROVIDER,  # type: ignore[arg-type]
        allow_real_model_provider=False,
    )

    with pytest.raises(ProviderNotPermitted, match="ALLOW_REAL_MODEL_PROVIDER"):
        build_provider(settings)


def test_a_non_fake_provider_is_still_refused_with_the_gate_flag_set() -> None:
    """The second lock: no real adapter exists to construct, flag or no flag."""
    settings = Settings.model_construct(
        model_provider=FutureProvider.SOME_FUTURE_PROVIDER,  # type: ignore[arg-type]
        allow_real_model_provider=True,
    )

    with pytest.raises(ProviderNotPermitted, match="no adapter exists"):
        build_provider(settings)


def test_the_real_provider_registry_is_empty() -> None:
    """Gate **G-03** is locked and `Q-012` has approved no provider or data-handling terms."""
    assert REAL_PROVIDER_ADAPTERS == {}


def test_the_gate_flag_defaults_to_false_in_a_fresh_environment() -> None:
    assert Settings().allow_real_model_provider is False


def test_the_fake_adapter_performs_no_io() -> None:
    """`test_evidence_capture.py` guards the research path; this guards the model path."""
    import ast

    tree = ast.parse((APP / "model_gateway" / "providers" / "echo.py").read_text("utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not imported & {"httpx", "requests", "urllib", "socket", "http", "pathlib", "random"}


def test_both_protocols_are_satisfied_by_the_shipped_implementations() -> None:
    assert isinstance(EchoModelAdapter(), ModelProviderAdapter)
    assert isinstance(DatabaseModelGateway(settings=TEST_SETTINGS), ModelGateway)


# --- criterion 2: every call writes a ModelRun with all version fields -------------------------


def test_a_successful_call_records_every_version(db_session: Session) -> None:
    request = make_request(db_session)
    gateway = DatabaseModelGateway(settings=TEST_SETTINGS)

    result = gateway.run_task(db_session, request, at=NOW)

    run = db_session.get(ModelRun, result.run_id)
    assert run.outcome is ModelRunOutcome.SUCCEEDED
    assert run.prompt_version_id == request.prompt_version_id
    assert run.schema_version_id == request.schema_version_id
    assert run.model_config_version_id == request.model_config_version_id
    assert run.policy_version_id == request.policy_version_id
    assert run.provider is ModelProvider.FAKE
    assert run.model_name == "deterministic-fake"
    assert run.failure_reason is None
    assert run.started_at == NOW


def test_the_run_records_tokens_cost_and_latency(db_session: Session) -> None:
    request = make_request(db_session)
    gateway = DatabaseModelGateway(settings=TEST_SETTINGS)

    result = gateway.run_task(db_session, request, at=NOW)

    run = db_session.get(ModelRun, result.run_id)
    assert run.input_tokens > 0
    assert run.output_tokens > 0
    assert run.cost_usd == Decimal("0")  # nothing was bought, and the row says so
    assert run.latency_ms >= 0


def test_cost_is_attributable_to_a_campaign_and_candidate(db_session: Session) -> None:
    """§18.7: attribution by campaign and researched candidate."""
    campaign_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    prompt, schema, config, _ = make_versions(db_session)
    request = ModelTaskRequest(
        task_name="synthetic_task",
        prompt_version_id=prompt.id,
        schema_version_id=schema.id,
        model_config_version_id=config.id,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
    )

    result = DatabaseModelGateway(settings=TEST_SETTINGS).run_task(db_session, request, at=NOW)

    run = db_session.get(ModelRun, result.run_id)
    assert run.campaign_id == campaign_id
    assert run.candidate_id == candidate_id


def test_a_provider_failure_is_recorded_before_it_propagates(db_session: Session) -> None:
    request = make_request(db_session)
    gateway = DatabaseModelGateway(settings=TEST_SETTINGS, provider=ExplodingAdapter())

    with pytest.raises(ProviderFailed):
        gateway.run_task(db_session, request, at=NOW)

    run = db_session.execute(select(ModelRun)).scalars().one()
    assert run.outcome is ModelRunOutcome.PROVIDER_ERROR
    assert "SYNTHETIC provider failure" in run.failure_reason


def test_an_unknown_version_stops_the_call(db_session: Session) -> None:
    request = make_request(db_session)
    broken = ModelTaskRequest(
        task_name=request.task_name,
        prompt_version_id=uuid.uuid4(),
        schema_version_id=request.schema_version_id,
        model_config_version_id=request.model_config_version_id,
    )

    with pytest.raises(VersionUnavailable):
        DatabaseModelGateway(settings=TEST_SETTINGS).run_task(db_session, broken, at=NOW)

    assert db_session.execute(select(func.count()).select_from(ModelRun)).scalar_one() == 0


def test_an_expired_version_stops_the_call(db_session: Session) -> None:
    """A run must record the version it used; running under an expired one would misreport it."""
    request = make_request(db_session)
    prompt = db_session.get(PromptVersion, request.prompt_version_id)
    prompt.effective_to = NOW - timedelta(hours=1)
    db_session.flush()

    with pytest.raises(VersionUnavailable, match="not effective"):
        DatabaseModelGateway(settings=TEST_SETTINGS).run_task(db_session, request, at=NOW)


def test_the_database_refuses_a_run_whose_outcome_and_reason_disagree(db_session: Session) -> None:
    """Structural: a success must not carry a failure reason, nor a failure go unexplained."""
    request = make_request(db_session)
    db_session.add(
        ModelRun(
            task_name="synthetic_task",
            prompt_version_id=request.prompt_version_id,
            schema_version_id=request.schema_version_id,
            model_config_version_id=request.model_config_version_id,
            provider=ModelProvider.FAKE,
            model_name="deterministic-fake",
            outcome=ModelRunOutcome.SUCCEEDED,
            failure_reason="SYNTHETIC: a success that claims to have failed",
            started_at=NOW,
        )
    )

    with pytest.raises(Exception, match="failure_reason_matches_outcome"):
        db_session.flush()


def test_the_database_refuses_a_refused_run_that_spent_something(db_session: Session) -> None:
    request = make_request(db_session)
    db_session.add(
        ModelRun(
            task_name="synthetic_task",
            prompt_version_id=request.prompt_version_id,
            schema_version_id=request.schema_version_id,
            model_config_version_id=request.model_config_version_id,
            provider=ModelProvider.FAKE,
            model_name="deterministic-fake",
            outcome=ModelRunOutcome.REFUSED_BUDGET,
            failure_reason="SYNTHETIC refusal",
            cost_usd=Decimal("1.00"),
            started_at=NOW,
        )
    )

    with pytest.raises(Exception, match="a_refused_run_spends_nothing"):
        db_session.flush()


# --- criterion 3: budgets refuse before the provider is invoked --------------------------------


class CountingAdapter:
    """Records whether it was reached at all. The point of criterion 3."""

    model_name = "deterministic-fake"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(output_text="SYNTHETIC", input_tokens=1, output_tokens=1)


def exhausted(**scopes: BudgetScope) -> ModelBudgets:
    """Budgets with everything wide open except the named scopes."""
    generous = BudgetScope(max_calls=1000, max_cost_usd=Decimal("1000"))
    return ModelBudgets(
        per_task=scopes.get("per_task", generous),
        daily=scopes.get("daily", generous),
        per_campaign=scopes.get("per_campaign", generous),
    )


def test_a_per_task_budget_refuses_before_the_provider_is_reached(db_session: Session) -> None:
    provider = CountingAdapter()
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        provider=provider,
        budgets=exhausted(per_task=BudgetScope(max_calls=0, max_cost_usd=Decimal("100"))),
    )

    with pytest.raises(BudgetExceeded, match="per_task"):
        gateway.run_task(db_session, make_request(db_session), at=NOW)

    assert provider.calls == 0, "the budget must refuse before the provider is invoked"


def test_a_daily_budget_refuses_before_the_provider_is_reached(db_session: Session) -> None:
    provider = CountingAdapter()
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        provider=provider,
        budgets=exhausted(daily=BudgetScope(max_calls=0, max_cost_usd=Decimal("100"))),
    )

    with pytest.raises(BudgetExceeded, match="daily"):
        gateway.run_task(db_session, make_request(db_session), at=NOW)

    assert provider.calls == 0


def test_a_campaign_budget_refuses_before_the_provider_is_reached(db_session: Session) -> None:
    provider = CountingAdapter()
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        provider=provider,
        budgets=exhausted(per_campaign=BudgetScope(max_calls=0, max_cost_usd=Decimal("100"))),
    )

    with pytest.raises(BudgetExceeded, match="per_campaign"):
        gateway.run_task(db_session, make_request(db_session, campaign_id=uuid.uuid4()), at=NOW)

    assert provider.calls == 0


def test_a_refusal_is_recorded_as_a_run(db_session: Session) -> None:
    """A budget that declines silently leaves no evidence it worked (§18.7 attribution)."""
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        budgets=exhausted(per_task=BudgetScope(max_calls=0, max_cost_usd=Decimal("100"))),
    )

    with pytest.raises(BudgetExceeded) as refusal:
        gateway.run_task(db_session, make_request(db_session), at=NOW)

    run = db_session.get(ModelRun, refusal.value.run_id)
    assert run.outcome is ModelRunOutcome.REFUSED_BUDGET
    assert run.cost_usd == Decimal("0")
    assert "per_task" in run.failure_reason


def test_a_budget_counts_earlier_runs_in_the_same_day(db_session: Session) -> None:
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        budgets=exhausted(per_task=BudgetScope(max_calls=1, max_cost_usd=Decimal("100"))),
    )
    gateway.run_task(db_session, make_request(db_session), at=NOW)

    with pytest.raises(BudgetExceeded):
        gateway.run_task(db_session, make_request(db_session), at=NOW)


def test_a_budget_does_not_count_yesterdays_runs(db_session: Session) -> None:
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        budgets=exhausted(per_task=BudgetScope(max_calls=1, max_cost_usd=Decimal("100"))),
    )
    gateway.run_task(db_session, make_request(db_session), at=NOW - timedelta(days=1))

    gateway.run_task(db_session, make_request(db_session), at=NOW)  # must not raise


def test_refused_runs_do_not_themselves_consume_the_budget(db_session: Session) -> None:
    """Otherwise a burst of refusals would lock the day out on its own."""
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        budgets=exhausted(daily=BudgetScope(max_calls=1, max_cost_usd=Decimal("100"))),
    )
    gateway.run_task(db_session, make_request(db_session), at=NOW)
    for _ in range(3):
        with pytest.raises(BudgetExceeded):
            gateway.run_task(db_session, make_request(db_session), at=NOW)

    refused = db_session.execute(
        select(func.count())
        .select_from(ModelRun)
        .where(ModelRun.outcome == ModelRunOutcome.REFUSED_BUDGET)
    ).scalar_one()
    assert refused == 3


def test_a_cost_cap_refuses_once_spend_passes_it(db_session: Session) -> None:
    """Proven with a priced stub: the fake reports zero, so only call caps bind in Stage 1."""
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        provider=PricedAdapter(price=Decimal("2.00")),
        budgets=exhausted(daily=BudgetScope(max_calls=1000, max_cost_usd=Decimal("1.50"))),
    )
    gateway.run_task(db_session, make_request(db_session), at=NOW)

    with pytest.raises(BudgetExceeded, match="daily"):
        gateway.run_task(db_session, make_request(db_session), at=NOW)


def test_a_zero_budget_refuses_everything(db_session: Session) -> None:
    """Fail closed: zero means zero, not "unconfigured"."""
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        budgets=ModelBudgets(
            per_task=BudgetScope(max_calls=0, max_cost_usd=Decimal("0")),
            daily=BudgetScope(max_calls=0, max_cost_usd=Decimal("0")),
            per_campaign=BudgetScope(max_calls=0, max_cost_usd=Decimal("0")),
        ),
    )

    with pytest.raises(BudgetExceeded):
        gateway.run_task(db_session, make_request(db_session), at=NOW)


def test_the_shipped_defaults_are_conservative() -> None:
    """`Q-006` has not set pilot spend, so the defaults are small by design."""
    budgets = ModelBudgets()

    assert budgets.per_task.max_calls <= 100
    assert budgets.daily.max_calls <= 500
    assert budgets.daily.max_cost_usd <= Decimal("25")


def test_a_budget_scope_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        BudgetScope(max_calls=-1, max_cost_usd=Decimal("1"))


# --- criterion 4: model names live in configuration only ---------------------------------------


def test_the_gateway_never_names_a_model(db_session: Session) -> None:
    """The run's model name comes from the resolved configuration, not from any literal here."""
    request = make_request(db_session)
    config = db_session.get(ModelConfigVersion, request.model_config_version_id)
    config.model_name = "synthetic-renamed-model"
    db_session.flush()

    result = DatabaseModelGateway(settings=TEST_SETTINGS).run_task(db_session, request, at=NOW)

    assert db_session.get(ModelRun, result.run_id).model_name == "synthetic-renamed-model"


def test_no_endpoint_or_base_url_appears_in_the_gateway_package() -> None:
    """§18.4: provider endpoints are configuration. `test_versioning.py` covers vendor names."""
    offenders = [
        path.name
        for path in (APP / "model_gateway").rglob("*.py")
        if any(
            marker in path.read_text(encoding="utf-8").lower()
            for marker in ("https://", "http://", "base_url", "api_key", "bearer ")
        )
    ]

    assert not offenders, f"endpoints and credentials belong in configuration: {offenders}"


def test_model_parameters_come_from_the_configuration_version(db_session: Session) -> None:
    """Temperature and the rest are configuration too, and reach the adapter unchanged."""
    seen: dict[str, Any] = {}

    class RecordingAdapter:
        model_name = "deterministic-fake"

        def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
            seen.update(parameters)
            return ProviderResponse(output_text="SYNTHETIC")

    request = make_request(db_session)
    config = db_session.get(ModelConfigVersion, request.model_config_version_id)
    config.parameters = {"temperature": 0, "max_output_tokens": 512}
    db_session.flush()

    DatabaseModelGateway(settings=TEST_SETTINGS, provider=RecordingAdapter()).run_task(
        db_session, request, at=NOW
    )

    assert seen == {"temperature": 0, "max_output_tokens": 512}


# --- prompt rendering treats inputs as data ----------------------------------------------------


def test_an_input_value_containing_a_placeholder_is_not_expanded(db_session: Session) -> None:
    """§15.4: an untrusted value must not be able to pull a second value into the prompt."""
    rendered: list[str] = []

    class CapturingAdapter:
        model_name = "deterministic-fake"

        def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
            rendered.append(prompt)
            return ProviderResponse(output_text="SYNTHETIC")

    prompt, schema, config, _ = make_versions(
        db_session, template="Subject: {subject}. Secret: {secret}"
    )
    request = ModelTaskRequest(
        task_name="synthetic_task",
        prompt_version_id=prompt.id,
        schema_version_id=schema.id,
        model_config_version_id=config.id,
        inputs={"subject": "{secret}", "secret": "SYNTHETIC-classified"},
    )

    DatabaseModelGateway(settings=TEST_SETTINGS, provider=CapturingAdapter()).run_task(
        db_session, request, at=NOW
    )

    assert rendered[0].startswith("Subject: {secret}.")


def test_rendering_does_not_evaluate_attribute_access(db_session: Session) -> None:
    """`str.format` would evaluate `{x.__class__}`; substitution does not."""
    gateway = DatabaseModelGateway(settings=TEST_SETTINGS)

    assert gateway._render("{a.__class__}", {"a": "x"}) == "{a.__class__}"
    assert gateway._render("{a}", {"a": "x"}) == "x"


def test_the_echo_adapter_is_deterministic() -> None:
    adapter = EchoModelAdapter()

    first = adapter.complete(prompt="SYNTHETIC prompt", parameters={})
    second = adapter.complete(prompt="SYNTHETIC prompt", parameters={})

    assert first == second
    assert first.cost_usd == Decimal("0")


def test_the_gateway_holds_no_session_of_its_own() -> None:
    """One instance per process is safe: the session is a per-call argument, so a gateway cannot
    accidentally write a run into a transaction that has already been committed elsewhere."""
    import inspect

    assert "session" in inspect.signature(DatabaseModelGateway.run_task).parameters
    assert "session" not in inspect.signature(DatabaseModelGateway.__init__).parameters


def test_a_day_boundary_is_utc(db_session: Session) -> None:
    """A budget that reset on a local day would reset twice a year, or differently per process."""
    gateway = DatabaseModelGateway(
        settings=TEST_SETTINGS,
        budgets=exhausted(daily=BudgetScope(max_calls=1, max_cost_usd=Decimal("100"))),
    )
    just_before_midnight = datetime(2026, 7, 30, 23, 59, tzinfo=UTC)
    gateway.run_task(db_session, make_request(db_session), at=just_before_midnight)

    gateway.run_task(
        db_session, make_request(db_session), at=just_before_midnight + timedelta(minutes=2)
    )  # a new UTC day, so it must not raise
