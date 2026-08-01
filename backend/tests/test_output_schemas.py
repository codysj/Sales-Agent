"""Versioned output schemas, validation, retry, and escalation (T-051; §10.4, §14.5, §23, GP-09).

§10.4 prints the exact object a qualification run must return, so the first group of tests is a
transcription check: the field set, both ways, and every enum's members. A schema that drifts
from the specification is the failure that would matter most and show up least.

The rest is about what happens when output is wrong: it is refused, retried a small number of
times, and then handed to a person — never coerced, never partially accepted, never dropped.
"""

import json
import re
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.versioning import SchemaVersion, content_hash
from app.core.settings import AppEnv, ModelProvider, Settings
from app.model_gateway.budgets import BudgetScope, ModelBudgets
from app.model_gateway.gateway import BudgetExceeded, DatabaseModelGateway, ProviderFailed
from app.model_gateway.models import ModelRun, ModelRunOutcome
from app.model_gateway.protocol import ModelTaskRequest, ProviderResponse
from app.model_gateway.schemas import (
    OUTPUT_SCHEMAS,
    QUALIFICATION_KEY,
    QualificationOutput,
    SchemaTampered,
    register_schema_versions,
    registered_version,
    schema_document,
    schema_path,
    verify_registered_schema,
)
from app.model_gateway.schemas.qualification import (
    EvidenceCompleteness,
    OpportunityType,
    SourceQualityRating,
)
from app.model_gateway.validation import (
    MAX_ATTEMPTS,
    Escalated,
    OutputValidationError,
    UnknownSchema,
    run_validated_task,
    validate_output,
)
from tests.factories import NOW
from tests.test_model_gateway import make_versions

TEST_SETTINGS = Settings(app_env=AppEnv.TEST)
SPEC = (
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "docs"
    / "MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md"
)

#: §10.4's field list, transcribed. The point of writing it out is that a reviewer can diff this
#: against the specification without running anything.
SPEC_FIELDS = {
    "campaign_id",
    "campaign_candidate_id",
    "eligibility_failures",
    "opportunity_type",
    "fit_summary",
    "use_case",
    "buyer_role_assessment",
    "fit_dimension_scores",
    "evidence_completeness",
    "source_quality",
    "personalization_evidence_ids",
    "applicable_approved_claim_ids",
    "ambiguities",
    "risks",
    "missing_information",
    "human_review_required",
}


def valid_output(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "campaign_id": str(uuid.uuid4()),
        "campaign_candidate_id": str(uuid.uuid4()),
        "eligibility_failures": [],
        "opportunity_type": "pilot",
        "fit_summary": "SYNTHETIC fit summary.",
        "use_case": "SYNTHETIC use case.",
        "buyer_role_assessment": "SYNTHETIC buyer role assessment.",
        "fit_dimension_scores": {
            "product_fit": 3,
            "buyer_relevance": 2,
            "timing": 1,
            "commercial_scale": 0,
        },
        "evidence_completeness": "partial",
        "source_quality": "medium",
        "personalization_evidence_ids": [str(uuid.uuid4())],
        "applicable_approved_claim_ids": ["SYNTHETIC-CLAIM-sodium-readiness"],
        "ambiguities": [],
        "risks": [],
        "missing_information": [],
        "human_review_required": True,
    }
    payload.update(overrides)
    return payload


# --- criterion 1: the §10.4 field set, exactly -------------------------------------------------


def test_the_model_carries_exactly_the_spec_field_set() -> None:
    assert set(QualificationOutput.model_fields) == SPEC_FIELDS


def test_the_field_set_matches_the_specification_text() -> None:
    """Read from the specification itself, so a §10.4 revision cannot pass unnoticed."""
    text = SPEC.read_text(encoding="utf-8")
    block = text.split("### 10.4 Required structured output")[1].split("```")[1]
    from_spec = set(re.findall(r'"([a-z_]+)":', block)) - {
        "product_fit",
        "buyer_relevance",
        "timing",
        "commercial_scale",
    }

    assert from_spec == SPEC_FIELDS


@pytest.mark.parametrize(
    ("enum_type", "expected"),
    [
        (
            OpportunityType,
            ["direct_sale", "pilot", "strategic_partnership", "future_follow_up", "reject"],
        ),
        (EvidenceCompleteness, ["complete", "partial", "insufficient"]),
        (SourceQualityRating, ["high", "medium", "low"]),
    ],
)
def test_each_enum_matches_the_specification(enum_type: Any, expected: list[str]) -> None:
    assert [member.value for member in enum_type] == expected


def test_the_four_fit_dimensions_are_the_specified_ones() -> None:
    assert set(
        QualificationOutput.model_fields["fit_dimension_scores"].annotation.model_fields
    ) == {
        "product_fit",
        "buyer_relevance",
        "timing",
        "commercial_scale",
    }


def test_no_field_has_a_default() -> None:
    """An omitted `human_review_required` must not become `False` by default (§3.5)."""
    missing_defaults = [
        name for name, field in QualificationOutput.model_fields.items() if not field.is_required()
    ]

    assert missing_defaults == []


# --- validation: refused, never coerced --------------------------------------------------------


def test_a_valid_output_parses() -> None:
    parsed = validate_output(QUALIFICATION_KEY, json.dumps(valid_output()))

    assert isinstance(parsed, QualificationOutput)
    assert parsed.opportunity_type is OpportunityType.PILOT


@pytest.mark.parametrize(
    "broken",
    [
        {"opportunity_type": "maybe_later"},
        {"evidence_completeness": "quite_good"},
        {"source_quality": "excellent"},
        {"human_review_required": "yes please"},
        {"fit_dimension_scores": {"product_fit": 3}},
        {
            "fit_dimension_scores": {
                "product_fit": 99,
                "buyer_relevance": 1,
                "timing": 1,
                "commercial_scale": 1,
            }
        },
        {"personalization_evidence_ids": "not-a-list"},
    ],
)
def test_an_invalid_field_is_refused(broken: dict[str, Any]) -> None:
    with pytest.raises(OutputValidationError):
        validate_output(QUALIFICATION_KEY, json.dumps(valid_output(**broken)))


def test_a_missing_field_is_refused() -> None:
    payload = valid_output()
    del payload["human_review_required"]

    with pytest.raises(OutputValidationError):
        validate_output(QUALIFICATION_KEY, json.dumps(payload))


def test_an_unexpected_field_is_refused() -> None:
    """`extra="forbid"`: a model answering a question nobody asked has not answered this one."""
    with pytest.raises(OutputValidationError):
        validate_output(
            QUALIFICATION_KEY, json.dumps(valid_output(recommended_discount="20 percent"))
        )


def test_text_that_is_not_json_is_refused() -> None:
    with pytest.raises(OutputValidationError):
        validate_output(QUALIFICATION_KEY, "Certainly! Here is the qualification you asked for.")


def test_an_unregistered_schema_key_is_refused() -> None:
    """Fails closed: no contract means nothing to validate against."""
    with pytest.raises(UnknownSchema):
        validate_output("no-such-schema", json.dumps(valid_output()))


def test_the_parsed_output_is_immutable() -> None:
    parsed = validate_output(QUALIFICATION_KEY, json.dumps(valid_output()))

    with pytest.raises(ValidationError):
        parsed.human_review_required = False  # type: ignore[misc]


# --- criterion 2: bounded retry, then escalation ------------------------------------------------


class ScriptedAdapter:
    """Returns the next scripted output on each call, so retry behaviour is exactly specified."""

    model_name = "deterministic-fake"

    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return ProviderResponse(output_text=output, input_tokens=1, output_tokens=1)


def gateway_with(provider: Any, **budget_overrides: BudgetScope) -> DatabaseModelGateway:
    generous = BudgetScope(max_calls=1000, max_cost_usd=Decimal("1000"))
    return DatabaseModelGateway(
        settings=TEST_SETTINGS,
        provider=provider,
        budgets=ModelBudgets(
            per_task=budget_overrides.get("per_task", generous),
            daily=budget_overrides.get("daily", generous),
            per_campaign=budget_overrides.get("per_campaign", generous),
        ),
    )


def make_task_request(session: Session) -> ModelTaskRequest:
    prompt, schema, config, _ = make_versions(session)
    return ModelTaskRequest(
        task_name="qualification",
        prompt_version_id=prompt.id,
        schema_version_id=schema.id,
        model_config_version_id=config.id,
        inputs={"subject": "SYNTHETIC-Account"},
    )


def test_valid_output_on_the_first_attempt_calls_once(db_session: Session) -> None:
    provider = ScriptedAdapter(json.dumps(valid_output()))

    parsed = run_validated_task(
        gateway_with(provider),
        db_session,
        make_task_request(db_session),
        schema_key=QUALIFICATION_KEY,
        at=NOW,
    )

    assert isinstance(parsed, QualificationOutput)
    assert provider.calls == 1


def test_invalid_output_is_retried_and_then_succeeds(db_session: Session) -> None:
    provider = ScriptedAdapter("not json at all", json.dumps(valid_output()))

    parsed = run_validated_task(
        gateway_with(provider),
        db_session,
        make_task_request(db_session),
        schema_key=QUALIFICATION_KEY,
        at=NOW,
    )

    assert isinstance(parsed, QualificationOutput)
    assert provider.calls == 2


def test_repeatedly_invalid_output_escalates_to_human_review(db_session: Session) -> None:
    provider = ScriptedAdapter("still not json")

    with pytest.raises(Escalated) as escalation:
        run_validated_task(
            gateway_with(provider),
            db_session,
            make_task_request(db_session),
            schema_key=QUALIFICATION_KEY,
            at=NOW,
        )

    assert escalation.value.human_review_required is True
    assert escalation.value.attempts == MAX_ATTEMPTS
    assert provider.calls == MAX_ATTEMPTS


def test_the_retry_limit_is_small(db_session: Session) -> None:
    """ "Within a small limit" (§10.4). A model that fails twice will not succeed on the fifth."""
    assert MAX_ATTEMPTS <= 3


def test_a_custom_attempt_limit_is_honoured(db_session: Session) -> None:
    provider = ScriptedAdapter("not json")

    with pytest.raises(Escalated):
        run_validated_task(
            gateway_with(provider),
            db_session,
            make_task_request(db_session),
            schema_key=QUALIFICATION_KEY,
            max_attempts=3,
            at=NOW,
        )

    assert provider.calls == 3


def test_invalid_output_is_never_silently_accepted(db_session: Session) -> None:
    """The whole point: the caller gets an exception, not a half-parsed object."""
    provider = ScriptedAdapter(json.dumps(valid_output(opportunity_type="maybe")))

    with pytest.raises(Escalated):
        run_validated_task(
            gateway_with(provider),
            db_session,
            make_task_request(db_session),
            schema_key=QUALIFICATION_KEY,
            at=NOW,
        )


def test_each_failed_attempt_is_recorded_as_invalid_output(db_session: Session) -> None:
    """A task burning budget on unusable output must be visible where cost is (§18.7)."""
    provider = ScriptedAdapter("not json")

    with pytest.raises(Escalated):
        run_validated_task(
            gateway_with(provider),
            db_session,
            make_task_request(db_session),
            schema_key=QUALIFICATION_KEY,
            at=NOW,
        )

    runs = db_session.execute(select(ModelRun)).scalars().all()
    assert len(runs) == MAX_ATTEMPTS
    assert all(run.outcome is ModelRunOutcome.INVALID_OUTPUT for run in runs)
    assert all(run.failure_reason for run in runs)


def test_a_successful_retry_leaves_the_failed_attempt_recorded(db_session: Session) -> None:
    provider = ScriptedAdapter("not json", json.dumps(valid_output()))

    run_validated_task(
        gateway_with(provider),
        db_session,
        make_task_request(db_session),
        schema_key=QUALIFICATION_KEY,
        at=NOW,
    )

    outcomes = [run.outcome for run in db_session.execute(select(ModelRun)).scalars().all()]
    assert sorted(outcome.value for outcome in outcomes) == ["invalid_output", "succeeded"]


def test_retries_are_still_subject_to_the_budget(db_session: Session) -> None:
    """Each attempt is a full `run_task`, so a model looping on invalid output cannot outspend
    the cap that would have stopped a single call."""
    provider = ScriptedAdapter("not json")

    with pytest.raises(BudgetExceeded):
        run_validated_task(
            gateway_with(provider, daily=BudgetScope(max_calls=1, max_cost_usd=Decimal("100"))),
            db_session,
            make_task_request(db_session),
            schema_key=QUALIFICATION_KEY,
            max_attempts=5,
            at=NOW,
        )

    assert provider.calls == 1


def test_a_provider_failure_is_not_retried_as_though_it_were_invalid_output(
    db_session: Session,
) -> None:
    """A provider that raised did not produce output; retrying it here would hide the failure."""

    class ExplodingAdapter:
        model_name = "deterministic-fake"

        def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
            raise RuntimeError("SYNTHETIC provider failure")

    with pytest.raises(ProviderFailed):
        run_validated_task(
            gateway_with(ExplodingAdapter()),
            db_session,
            make_task_request(db_session),
            schema_key=QUALIFICATION_KEY,
            at=NOW,
        )


def test_an_attempt_limit_below_one_is_refused(db_session: Session) -> None:
    with pytest.raises(ValueError):
        run_validated_task(
            gateway_with(ScriptedAdapter("{}")),
            db_session,
            make_task_request(db_session),
            schema_key=QUALIFICATION_KEY,
            max_attempts=0,
            at=NOW,
        )


# --- criterion 3: every schema is content-hashed and registered --------------------------------


def test_the_exported_file_matches_the_model(_: None = None) -> None:
    """The artefact on disk is what §23 makes inspectable; a stale one misstates the contract."""
    for key in OUTPUT_SCHEMAS:
        on_disk = json.loads(schema_path(key).read_text(encoding="utf-8"))

        assert on_disk == schema_document(key), f"{key}.json is stale; re-export it"


def test_every_schema_registers_with_its_content_hash(db_session: Session) -> None:
    published = register_schema_versions(db_session, created_by="operator-1", at=NOW)

    assert {version.key for version in published} == set(OUTPUT_SCHEMAS)
    for version in published:
        assert version.content_hash == content_hash(schema_document(version.key))
        assert version.version == 1
        assert version.json_schema == schema_document(version.key)


def test_registering_twice_publishes_nothing_new(db_session: Session) -> None:
    register_schema_versions(db_session, created_by="operator-1", at=NOW)

    again = register_schema_versions(db_session, created_by="operator-1", at=NOW)

    assert again == []
    assert len(db_session.execute(select(SchemaVersion)).scalars().all()) == len(OUTPUT_SCHEMAS)


# --- criterion 4: a schema change is a new version, never an edit -------------------------------


def test_a_changed_schema_publishes_the_next_version(db_session: Session) -> None:
    # Indexed by key, not position: registration returns every schema in key order, so `[0]`
    # silently became the drafting schema when `T-054` added one.
    first = {
        version.key: version
        for version in register_schema_versions(db_session, created_by="operator-1", at=NOW)
    }[QUALIFICATION_KEY]
    original_hash = first.content_hash

    # Stand in for a genuine schema change without editing the shipped model. The previous
    # version's window must close first: `ex_schema_version_no_overlap` refuses two open windows
    # for one key, which is what makes "the current version" unambiguous.
    changed = dict(schema_document(QUALIFICATION_KEY))
    changed["title"] = "SYNTHETIC changed schema"
    first.effective_to = NOW + timedelta(hours=1)
    db_session.add(
        SchemaVersion(
            key=QUALIFICATION_KEY,
            version=first.version + 1,
            content_hash=content_hash(changed),
            effective_from=NOW + timedelta(hours=1),
            created_by="operator-1",
            json_schema=changed,
        )
    )
    db_session.flush()

    latest = registered_version(db_session, QUALIFICATION_KEY)
    assert latest.version == 2
    assert db_session.get(SchemaVersion, first.id).content_hash == original_hash


def test_the_content_hash_of_a_registered_version_cannot_be_rewritten(
    db_session: Session,
) -> None:
    """`T-023`'s trigger pins the hash, so a re-registered schema cannot claim to be the old one."""
    version = {
        schema.key: schema
        for schema in register_schema_versions(db_session, created_by="operator-1", at=NOW)
    }[QUALIFICATION_KEY]

    version.content_hash = content_hash({"type": "object", "title": "SYNTHETIC rewritten"})

    with pytest.raises(Exception, match="immutable"):
        db_session.flush()


def test_a_body_edited_after_registration_is_detected(db_session: Session) -> None:
    """The one hole the trigger deliberately leaves: `json_schema` stays writable so a window can
    close. `verify_registered_schema` is what makes editing it detectable rather than silent."""
    register_schema_versions(db_session, created_by="operator-1", at=NOW)
    assert verify_registered_schema(db_session, QUALIFICATION_KEY)  # clean before tampering

    tampered = registered_version(db_session, QUALIFICATION_KEY)
    tampered.json_schema = {"type": "object", "title": "SYNTHETIC rewritten"}
    db_session.flush()

    with pytest.raises(SchemaTampered, match="edited after registration"):
        verify_registered_schema(db_session, QUALIFICATION_KEY)


def test_verification_refuses_a_schema_that_was_never_registered(db_session: Session) -> None:
    with pytest.raises(SchemaTampered):
        verify_registered_schema(db_session, QUALIFICATION_KEY)


def test_two_versions_of_one_key_cannot_share_a_number(db_session: Session) -> None:
    register_schema_versions(db_session, created_by="operator-1", at=NOW)

    db_session.add(
        SchemaVersion(
            key=QUALIFICATION_KEY,
            version=1,
            content_hash=content_hash({"different": True}),
            effective_from=NOW,
            created_by="operator-1",
            json_schema={"different": True},
        )
    )

    with pytest.raises(Exception, match="uq_schema_version_key_version"):
        db_session.flush()


def test_the_registered_schema_is_the_one_a_run_can_cite(db_session: Session) -> None:
    """The join that makes a decision explainable: run -> schema version -> the exact contract."""
    version = {
        schema.key: schema
        for schema in register_schema_versions(db_session, created_by="operator-1", at=NOW)
    }[QUALIFICATION_KEY]
    prompt, _, config, _ = make_versions(db_session)
    request = ModelTaskRequest(
        task_name="qualification",
        prompt_version_id=prompt.id,
        schema_version_id=version.id,
        model_config_version_id=config.id,
    )

    parsed = run_validated_task(
        gateway_with(ScriptedAdapter(json.dumps(valid_output()))),
        db_session,
        request,
        schema_key=QUALIFICATION_KEY,
        at=NOW,
    )

    run = db_session.execute(select(ModelRun)).scalars().one()
    assert run.schema_version_id == version.id
    assert db_session.get(SchemaVersion, run.schema_version_id).json_schema == schema_document(
        QUALIFICATION_KEY
    )
    assert isinstance(parsed, QualificationOutput)


def test_the_schema_file_carries_no_vendor_or_endpoint(_: None = None) -> None:
    """§18.4, applied to the artefact as well as the code."""
    for key in OUTPUT_SCHEMAS:
        text = schema_path(key).read_text(encoding="utf-8").lower()

        assert "http://" not in text
        assert "api." not in text


def test_the_provider_enum_is_untouched_by_this_task() -> None:
    """A schema task must not become the place a provider quietly appears."""
    assert [provider.value for provider in ModelProvider] == ["fake"]
