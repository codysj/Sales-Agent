"""Qualification and opportunity classification (T-053; §10.1, §10.2, §10.4, §8.5, ADR-008).

The model is allowed to interpret evidence here — the first place in the pipeline where that is
true — so the tests are mostly about the fence around it:

* it never runs for a candidate hard eligibility refused;
* it is only ever shown stored evidence and currently valid claims;
* every ID it cites back is checked against the database, which is the one thing a JSON Schema
  cannot do;
* a human reviews the result whatever the model asked for;
* and nothing the model says about its own confidence changes any of that.

`T-052`'s `unsupported_claim` fixture exists for this file: schema-valid output that cites a claim
nobody approved and declares no review needed. Both must be caught here or nowhere.
"""

import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.audit_and_operations.versioning import PromptVersion
from app.campaigns.candidate import create_candidate, transition
from app.campaigns.models import Campaign
from app.core.lifecycles import CampaignCandidateState
from app.core.settings import AppEnv, ModelProvider, Settings
from app.model_gateway.gateway import DatabaseModelGateway, ProviderFailed
from app.model_gateway.models import ModelRun, ModelRunOutcome
from app.model_gateway.prompts import (
    PROMPT_TASKS,
    prompt_template,
    register_prompt_versions,
    registered_prompt,
)
from app.model_gateway.protocol import ProviderResponse
from app.model_gateway.providers.fake import FakeModelAdapter
from app.model_gateway.schemas import QUALIFICATION_KEY, register_schema_versions
from app.model_gateway.validation import Escalated
from app.products_and_claims.claim_models import ApprovedClaim, ApprovedClaimCampaign
from app.products_and_claims.models import Product
from app.prospects.models import Account
from app.qualification.models import QualificationRun
from app.qualification.qualify import (
    QUALIFIABLE_STATES,
    CandidateNotQualifiable,
    UngroundedOutput,
    build_inputs,
    check_grounding,
    qualify_candidate,
)
from app.research_and_evidence.models import (
    EvidenceSnapshot,
    ExtractionMethod,
    RetentionClass,
    SourceQuality,
    SourceType,
)
from tests.factories import APPROVER, NOW
from tests.test_model_gateway import make_versions

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
TEST_SETTINGS = Settings(app_env=AppEnv.TEST)
MODULE = Path(__file__).resolve().parents[1] / "app" / "qualification" / "qualify.py"
FIXTURES = Path(__file__).resolve().parents[1] / "app" / "fixtures" / "model_outputs"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-qualification-test")


class World:
    """An eligible candidate with one stored evidence snapshot and one approved claim."""

    def __init__(self, session: Session) -> None:
        self.session = session

        self.product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
        session.add(self.product)
        session.flush()

        self.campaign = Campaign(
            slug=f"synthetic-{uuid.uuid4().hex[:8]}",
            name="SYNTHETIC-Campaign",
            product_id=self.product.id,
            paused=False,
        )
        self.account = Account(
            domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account"
        )
        session.add_all([self.campaign, self.account])
        session.flush()

        self.claim = ApprovedClaim(
            claim_key="SYNTHETIC-CLAIM-sodium-readiness",
            version=1,
            product_id=self.product.id,
            text="SYNTHETIC EXAMPLE CLAIM.",
            approved_by=APPROVER,
            approved_at=NOW - timedelta(days=1),
            effective_from=NOW - timedelta(days=1),
            expires_or_review_by=NOW + timedelta(days=90),
        )
        session.add(self.claim)
        session.flush()
        session.add(ApprovedClaimCampaign(claim_id=self.claim.id, campaign_id=self.campaign.id))

        self.candidate = create_candidate(
            session,
            campaign_id=self.campaign.id,
            account_id=self.account.id,
            contact_id=None,
            actor=OPERATOR,
        )
        transition(session, self.candidate, CampaignCandidateState.ELIGIBLE, actor=OPERATOR)

        self.evidence = EvidenceSnapshot(
            candidate_id=self.candidate.id,
            source_type=SourceType.SYNTHETIC_FIXTURE,
            retrieved_at=NOW - timedelta(hours=1),
            supporting_excerpt_or_fact="SYNTHETIC: the account is evaluating storage.",
            content_hash="c" * 64,
            extraction_method=ExtractionMethod.STRUCTURED_FIELD,
            source_quality=SourceQuality.MEDIUM,
            license_and_retention_class=RetentionClass.PUBLIC_UNRESTRICTED,
            contains_personal_or_confidential_data=False,
        )
        session.add(self.evidence)
        session.flush()

        # Indexed by key, not position: `register_*_versions` returns every registered artefact
        # in key order, so `[0]` silently became the drafting prompt when `T-054` added one.
        self.prompt = {
            version.key: version
            for version in register_prompt_versions(session, created_by="operator-1", at=NOW)
        }["qualification"]
        self.schema = {
            version.key: version
            for version in register_schema_versions(session, created_by="operator-1", at=NOW)
        }[QUALIFICATION_KEY]
        _, _, self.config, _ = make_versions(session)

    def qualify(self, provider: Any, **kwargs: Any) -> QualificationRun:
        return qualify_candidate(
            self.session,
            self.candidate,
            DatabaseModelGateway(settings=TEST_SETTINGS, provider=provider),
            prompt_version_id=self.prompt.id,
            schema_version_id=self.schema.id,
            model_config_version_id=self.config.id,
            actor=OPERATOR,
            at=NOW,
            **kwargs,
        )

    def output(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "campaign_id": str(self.campaign.id),
            "campaign_candidate_id": str(self.candidate.id),
            "eligibility_failures": [],
            "opportunity_type": "pilot",
            "fit_summary": "SYNTHETIC fit summary.",
            "use_case": "SYNTHETIC use case.",
            "buyer_role_assessment": "SYNTHETIC buyer role assessment.",
            "fit_dimension_scores": {
                "product_fit": 3,
                "buyer_relevance": 2,
                "timing": 2,
                "commercial_scale": 1,
            },
            "evidence_completeness": "partial",
            "source_quality": "medium",
            "personalization_evidence_ids": [str(self.evidence.id)],
            "applicable_approved_claim_ids": [self.claim.claim_key],
            "ambiguities": [],
            "risks": [],
            "missing_information": [],
            "human_review_required": True,
        }
        payload.update(overrides)
        return payload


class Scripted:
    """Returns one fixed output. The prompt is captured so tests can assert what was sent."""

    model_name = "deterministic-fake"

    def __init__(self, output: dict[str, Any] | str) -> None:
        self.output = output if isinstance(output, str) else json.dumps(output)
        self.prompts: list[str] = []

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
        self.prompts.append(prompt)
        return ProviderResponse(output_text=self.output, input_tokens=1, output_tokens=1)


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


# --- criterion 3: an ineligible candidate is never qualified ------------------------------------


def test_an_imported_candidate_is_refused_before_any_model_call(world: World) -> None:
    """Stage 1 decides who may be assessed; stage 2 does not get to reopen it (§10.1)."""
    other = Account(domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account-Two")
    world.session.add(other)
    world.session.flush()
    fresh = create_candidate(
        world.session,
        campaign_id=world.campaign.id,
        account_id=other.id,
        contact_id=None,
        actor=OPERATOR,
    )
    provider = Scripted(world.output())

    with pytest.raises(CandidateNotQualifiable, match="hard eligibility"):
        qualify_candidate(
            world.session,
            fresh,
            DatabaseModelGateway(settings=TEST_SETTINGS, provider=provider),
            prompt_version_id=world.prompt.id,
            schema_version_id=world.schema.id,
            model_config_version_id=world.config.id,
            actor=OPERATOR,
            at=NOW,
        )

    assert provider.prompts == [], "no model call may happen for an unqualifiable candidate"
    assert world.session.execute(select(ModelRun)).scalars().all() == []


def test_an_ineligible_candidate_is_refused(world: World) -> None:
    """Built from `imported`, because §8.2 has no `eligible -> ineligible` edge — a candidate that
    passed the hard rules is invalidated, not retrospectively refused."""
    other = Account(domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account-Three")
    world.session.add(other)
    world.session.flush()
    refused = create_candidate(
        world.session,
        campaign_id=world.campaign.id,
        account_id=other.id,
        contact_id=None,
        actor=OPERATOR,
    )
    transition(
        world.session,
        refused,
        CampaignCandidateState.INELIGIBLE,
        actor=OPERATOR,
        reason="SYNTHETIC: refused by a hard rule",
    )
    provider = Scripted(world.output())

    with pytest.raises(CandidateNotQualifiable):
        qualify_candidate(
            world.session,
            refused,
            DatabaseModelGateway(settings=TEST_SETTINGS, provider=provider),
            prompt_version_id=world.prompt.id,
            schema_version_id=world.schema.id,
            model_config_version_id=world.config.id,
            actor=OPERATOR,
            at=NOW,
        )

    assert provider.prompts == []


def test_the_qualifiable_states_exclude_every_terminal_decision() -> None:
    """A rejected or approved candidate must not be re-qualified into a different answer."""
    assert QUALIFIABLE_STATES.isdisjoint(
        {
            CampaignCandidateState.IMPORTED,
            CampaignCandidateState.INELIGIBLE,
            CampaignCandidateState.APPROVED,
            CampaignCandidateState.REJECTED,
        }
    )


# --- criterion 1: output validates for a fixture candidate --------------------------------------


def test_a_valid_output_produces_a_qualification_run(world: World) -> None:
    run = world.qualify(Scripted(world.output()))

    assert run.opportunity_type == "pilot"
    assert run.product_fit == 3
    assert run.evidence_completeness == "partial"
    assert run.output["fit_summary"] == "SYNTHETIC fit summary."
    assert run.qualified_at == NOW


def test_the_run_points_at_the_model_run_that_produced_it(world: World) -> None:
    """§17.5: the join from an assessment to the prompt, schema, and config it ran under."""
    run = world.qualify(Scripted(world.output()))

    model_run = world.session.get(ModelRun, run.model_run_id)
    assert model_run.outcome is ModelRunOutcome.SUCCEEDED
    assert model_run.task_name == "qualification"
    assert model_run.prompt_version_id == world.prompt.id
    assert model_run.candidate_id == world.candidate.id


def test_output_that_never_validates_escalates_rather_than_being_stored(world: World) -> None:
    with pytest.raises(Escalated):
        world.qualify(Scripted("not json at all"))

    assert world.session.execute(select(QualificationRun)).scalars().all() == []


def test_the_shipped_fake_fixture_qualifies_end_to_end(world: World) -> None:
    """The whole path on the shipped deterministic fake, not a test-local stub."""
    adapter = FakeModelAdapter(directory=FIXTURES)
    # The default fixture cites no evidence and one claim key; align the world's claim with it.
    world.claim.claim_key = "SYNTHETIC-CLAIM-sodium-readiness"
    world.session.flush()

    run = world.qualify(adapter)

    assert run.opportunity_type == "pilot"
    assert run.human_review_required is True


# --- criterion 2: every citation is checked against the database --------------------------------


def test_an_unknown_evidence_id_is_refused(world: World) -> None:
    """GP-02: a personalization fact must resolve to a stored evidence ID."""
    with pytest.raises(UngroundedOutput, match="evidence IDs not stored"):
        world.qualify(Scripted(world.output(personalization_evidence_ids=[str(uuid.uuid4())])))

    assert world.session.execute(select(QualificationRun)).scalars().all() == []


def test_an_unapproved_claim_id_is_refused(world: World) -> None:
    with pytest.raises(UngroundedOutput, match="claim IDs not approved"):
        world.qualify(
            Scripted(world.output(applicable_approved_claim_ids=["SYNTHETIC-CLAIM-invented"]))
        )


def test_the_unsupported_claim_fixture_is_caught_here(world: World) -> None:
    """`T-052` ships schema-valid output citing a claim nobody approved. This is where it dies."""
    fixture = json.loads((FIXTURES / "failure-unsupported_claim.json").read_text(encoding="utf-8"))

    with pytest.raises(UngroundedOutput, match="SYNTHETIC-CLAIM-that-was-never-approved"):
        world.qualify(Scripted(fixture["output"]))


def test_citing_nothing_is_allowed(world: World) -> None:
    """Fewer citations than available is a model that found less to say, not a violation."""
    run = world.qualify(
        Scripted(world.output(personalization_evidence_ids=[], applicable_approved_claim_ids=[]))
    )

    assert run.output["personalization_evidence_ids"] == []


def test_an_expired_claim_is_not_citable(world: World) -> None:
    """The claim set is resolved at run time, so a lapsed claim stops being available.

    The lapsed claim is *published* lapsed rather than edited: `ApprovedClaim` is immutable by
    trigger (`T-014`), which is the right behaviour and means a test has to build the state it
    wants rather than mutate its way there.
    """
    lapsed = ApprovedClaim(
        claim_key="SYNTHETIC-CLAIM-lapsed",
        version=1,
        product_id=world.product.id,
        text="SYNTHETIC EXAMPLE CLAIM that is no longer current.",
        approved_by=APPROVER,
        approved_at=NOW - timedelta(days=10),
        effective_from=NOW - timedelta(days=10),
        expires_or_review_by=NOW - timedelta(hours=1),
    )
    world.session.add(lapsed)
    world.session.flush()
    world.session.add(ApprovedClaimCampaign(claim_id=lapsed.id, campaign_id=world.campaign.id))
    world.session.flush()

    with pytest.raises(UngroundedOutput, match="claim IDs not approved"):
        world.qualify(
            Scripted(world.output(applicable_approved_claim_ids=["SYNTHETIC-CLAIM-lapsed"]))
        )


def test_stale_evidence_is_not_citable(world: World) -> None:
    """Stored stale, not edited stale: `EvidenceSnapshot` is immutable by trigger (`T-019`)."""
    stale = EvidenceSnapshot(
        candidate_id=world.candidate.id,
        source_type=SourceType.SYNTHETIC_FIXTURE,
        retrieved_at=NOW - timedelta(days=400),
        supporting_excerpt_or_fact="SYNTHETIC: a fact that has passed its refresh date.",
        content_hash="d" * 64,
        extraction_method=ExtractionMethod.STRUCTURED_FIELD,
        source_quality=SourceQuality.LOW,
        license_and_retention_class=RetentionClass.PUBLIC_UNRESTRICTED,
        contains_personal_or_confidential_data=False,
        expires_or_refresh_by=NOW - timedelta(hours=1),
    )
    world.session.add(stale)
    world.session.flush()

    with pytest.raises(UngroundedOutput, match="evidence IDs not stored"):
        world.qualify(Scripted(world.output(personalization_evidence_ids=[str(stale.id)])))


def test_grounding_is_checked_against_the_inputs_that_were_sent(world: World) -> None:
    inputs = build_inputs(world.session, world.candidate, at=NOW)

    assert [str(snapshot.id) for snapshot in inputs.evidence] == [str(world.evidence.id)]
    assert inputs.approved_claim_ids == [world.claim.claim_key]
    check_grounding(
        type(
            "Stub",
            (),
            {
                "personalization_evidence_ids": [str(world.evidence.id)],
                "applicable_approved_claim_ids": [world.claim.claim_key],
            },
        )(),  # type: ignore[arg-type]
        inputs,
    )


# --- criterion 4: human review is required, whatever the model said -----------------------------


@pytest.mark.parametrize("model_said", [True, False])
def test_human_review_is_always_required(world: World, model_said: bool) -> None:
    """ADR-008. The model does not get a vote."""
    run = world.qualify(Scripted(world.output(human_review_required=model_said)))

    assert run.human_review_required is True
    assert run.review_reason.startswith("ADR-008")


def test_a_model_asking_for_no_review_is_recorded_as_having_asked(world: World) -> None:
    """Overruled, not ignored: a system that cannot see what the model wanted cannot be audited."""
    run = world.qualify(Scripted(world.output(human_review_required=False)))

    assert run.model_requested_no_review is True
    assert run.human_review_required is True


def test_the_database_refuses_a_run_that_does_not_require_review(world: World) -> None:
    """Structural, in the migration: not merely a value the service remembers to set."""
    run = world.qualify(Scripted(world.output()))
    world.session.expunge(run)

    world.session.add(
        QualificationRun(
            candidate_id=world.candidate.id,
            model_run_id=run.model_run_id,
            opportunity_type="direct_sale",
            evidence_completeness="complete",
            source_quality="high",
            product_fit=5,
            buyer_relevance=5,
            timing=5,
            commercial_scale=5,
            human_review_required=False,
            output={},
            qualified_at=NOW,
        )
    )

    with pytest.raises(Exception, match="human_review_is_always_required"):
        world.session.flush()


def test_the_database_refuses_an_out_of_range_score(world: World) -> None:
    run = world.qualify(Scripted(world.output()))
    world.session.expunge(run)

    world.session.add(
        QualificationRun(
            candidate_id=world.candidate.id,
            model_run_id=run.model_run_id,
            opportunity_type="pilot",
            evidence_completeness="partial",
            source_quality="medium",
            product_fit=99,
            buyer_relevance=1,
            timing=1,
            commercial_scale=1,
            human_review_required=True,
            output={},
            qualified_at=NOW,
        )
    )

    with pytest.raises(Exception, match="product_fit_in_range"):
        world.session.flush()


# --- criterion 5: model self-confidence controls nothing ----------------------------------------


def test_the_schema_has_no_confidence_field() -> None:
    """§10.2: self-reported confidence is not calibrated. There is nowhere to put one."""
    from app.model_gateway.schemas.qualification import QualificationOutput

    assert not [name for name in QualificationOutput.model_fields if "confidence" in name]


def test_no_branch_reads_a_confidence_value() -> None:
    """Prose may discuss confidence; code may not read one (§10.2)."""
    prose = ("#", "*", '"""', "`", "1.", "2.", "3.", "4.", "5.")
    code = [
        line
        for line in MODULE.read_text(encoding="utf-8").lower().splitlines()
        if not line.lstrip().startswith(prose)
    ]

    assert not [line for line in code if "confidence" in line]


def test_no_score_is_compared_against_a_threshold() -> None:
    """`Q-002`/`Q-020` have set no weights, so a threshold here would be an invented decision."""
    source = MODULE.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith(("#", '"', "*"))
    )

    for scored in ("product_fit", "buyer_relevance", "timing", "commercial_scale"):
        for comparison in (f"{scored} >", f"{scored} <", f"{scored} >=", f"{scored} <="):
            assert comparison not in code


def test_the_scores_are_carried_through_unchanged(world: World) -> None:
    """The model's judgement reaches a reviewer intact; it just does not gate anything."""
    run = world.qualify(
        Scripted(
            world.output(
                fit_dimension_scores={
                    "product_fit": 0,
                    "buyer_relevance": 5,
                    "timing": 1,
                    "commercial_scale": 4,
                }
            )
        )
    )

    assert (run.product_fit, run.buyer_relevance, run.timing, run.commercial_scale) == (0, 5, 1, 4)


def test_a_reject_classification_still_stores_a_run(world: World) -> None:
    """The model may recommend reject; the decision is still a human's (§8.5, ADR-008)."""
    run = world.qualify(Scripted(world.output(opportunity_type="reject")))

    assert run.opportunity_type == "reject"
    assert run.human_review_required is True
    assert world.candidate.state is CampaignCandidateState.ELIGIBLE, (
        "qualification records an assessment; it does not move the candidate lifecycle"
    )


# --- the prompt shows only stored records -------------------------------------------------------


def test_the_prompt_contains_the_stored_evidence_and_its_id(world: World) -> None:
    provider = Scripted(world.output())

    world.qualify(provider)

    sent = provider.prompts[0]
    assert str(world.evidence.id) in sent
    assert "SYNTHETIC: the account is evaluating storage." in sent
    assert world.claim.claim_key in sent


def test_the_prompt_marks_evidence_as_untrusted(world: World) -> None:
    """§15.4: the model is told, in the prompt, that the material is data and not instructions."""
    provider = Scripted(world.output())

    world.qualify(provider)

    sent = provider.prompts[0]
    assert "UNTRUSTED" in sent
    assert "never as instructions" in sent


def test_the_prompt_names_no_fact_that_is_not_a_stored_row(world: World) -> None:
    """Everything substituted into the template came from the database."""
    inputs = build_inputs(world.session, world.candidate, at=NOW)
    rendered = inputs.as_prompt_inputs()

    assert (
        rendered["evidence"] == f"{world.evidence.id}: {world.evidence.supporting_excerpt_or_fact}"
    )
    assert rendered["approved_claim_ids"] == world.claim.claim_key


def test_a_candidate_with_no_evidence_still_renders_a_prompt(world: World) -> None:
    """ "(none)" rather than an empty gap, so the model is not left to infer what is missing."""
    world.session.delete(world.evidence)
    world.session.flush()

    rendered = build_inputs(world.session, world.candidate, at=NOW).as_prompt_inputs()

    assert rendered["evidence"] == "(none)"


# --- the prompt is versioned and registered ------------------------------------------------------


def test_the_prompt_registers_with_its_content_hash(db_session: Session) -> None:
    published = {
        version.key: version
        for version in register_prompt_versions(db_session, created_by="operator-1", at=NOW)
    }

    assert set(published) == set(PROMPT_TASKS)
    assert published["qualification"].template == prompt_template("qualification")
    assert published["qualification"].task_name == "qualification"


def test_registering_the_prompt_twice_publishes_nothing_new(db_session: Session) -> None:
    register_prompt_versions(db_session, created_by="operator-1", at=NOW)

    assert register_prompt_versions(db_session, created_by="operator-1", at=NOW) == []
    assert len(db_session.execute(select(PromptVersion)).scalars().all()) == len(PROMPT_TASKS)


def test_the_prompt_names_no_vendor_or_model() -> None:
    """§18.4: a prompt is content, not a place to name the model that will read it."""
    text = prompt_template("qualification").lower()

    for marker in ("claude", "gpt", "deepseek", "http://", "https://"):
        assert marker not in text


def test_registering_the_prompt_is_the_only_way_it_reaches_a_run(db_session: Session) -> None:
    published = {
        version.key: version
        for version in register_prompt_versions(db_session, created_by="operator-1", at=NOW)
    }

    assert registered_prompt(db_session, "qualification").id == published["qualification"].id


# --- the audit trail -----------------------------------------------------------------------------


def test_the_qualification_is_audited_without_the_output_prose(world: World) -> None:
    """§15.5: counts and identifiers. The output body is on the row, not in the trail."""
    world.qualify(Scripted(world.output(fit_summary="SYNTHETIC prose that must not be logged")))

    event = world.session.execute(
        select(AuditEvent).where(AuditEvent.action == "qualification_run.completed")
    ).scalar_one()
    serialized = str(event.payload)
    assert "must not be logged" not in serialized
    assert event.payload["evidence_cited"] == 1
    assert event.payload["human_review_required"] is True


def test_a_refused_qualification_writes_no_run_but_leaves_the_model_run(world: World) -> None:
    """The call cost something and the record says so, even though nothing was stored."""
    with pytest.raises(UngroundedOutput):
        world.qualify(Scripted(world.output(applicable_approved_claim_ids=["SYNTHETIC-nope"])))

    assert world.session.execute(select(QualificationRun)).scalars().all() == []
    assert len(world.session.execute(select(ModelRun)).scalars().all()) == 1


def test_the_provider_is_still_the_fake(world: World) -> None:
    """No provider may be reached from a qualification run (gate G-03)."""
    run = world.qualify(Scripted(world.output()))

    assert world.session.get(ModelRun, run.model_run_id).provider is ModelProvider.FAKE


def test_a_provider_failure_propagates_rather_than_being_stored(world: World) -> None:
    """A provider that raised produced no assessment, so there is nothing to store.

    Driven with a raising stub rather than `T-052`'s timeout fixture: that fixture keys on its own
    prompt, and the prompt this task sends is the rendered qualification template. Pointing the
    fixture at it would mean hashing a template that changes whenever the prompt is edited —
    `test_fake_model.py` already proves the fixture reaches `provider_error` through the gateway.
    """

    class Exploding:
        model_name = "deterministic-fake"

        def complete(self, *, prompt: str, parameters: dict[str, Any]) -> ProviderResponse:
            raise TimeoutError("SYNTHETIC provider timeout")

    with pytest.raises(ProviderFailed):
        world.qualify(Exploding())

    assert world.session.execute(select(QualificationRun)).scalars().all() == []
    run = world.session.execute(select(ModelRun)).scalars().one()
    assert run.outcome is ModelRunOutcome.PROVIDER_ERROR
