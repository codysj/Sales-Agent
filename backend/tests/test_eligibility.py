"""Hard eligibility (T-045; specification §10.1 stage 1, §8.3 step 4, §15.6, GP-12).

Every implemented rule gets a pair: one candidate that passes it and one that fails it, both built
from the same synthetic world so the difference is the rule and nothing else. On top of that sit
the three properties that make this a *hard* gate rather than a suggestion — all reasons are
recorded rather than the first, the result is identical on a re-run, and no model can enter the
decision at all.

The `Q-002`/`Q-013` placeholder values are exercised through `CampaignPolicy` defaults rather than
hard-coded here, so the day real segments and jurisdictions arrive, these tests move with them.
"""

import ast
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, create_candidate
from app.campaigns.models import Campaign
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import NoCurrentPolicy, publish_policy_version
from app.core.lifecycles import CampaignCandidateState
from app.products_and_claims.models import Product, ProductStatusVersion, ReadinessCategory
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)
from app.prospects.suppression import SuppressionScope, SuppressionSource, record_suppression
from app.qualification.eligibility import (
    DEFERRED_RULES,
    IMPLEMENTED_RULES,
    EligibilityFailure,
    Rule,
    apply_eligibility,
    evaluate,
)
from tests.factories import NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
APPROVER = "approver-1"

MODULE = Path(__file__).resolve().parents[1] / "app" / "qualification" / "eligibility.py"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-eligibility-test")


class World:
    """One eligible candidate. Each test breaks exactly one thing about it."""

    def __init__(self, session: Session, *, policy: CampaignPolicy | None = None) -> None:
        self.session = session

        self.product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
        session.add(self.product)
        session.flush()

        self.status = ProductStatusVersion(
            product_id=self.product.id,
            version=1,
            readiness_category=ReadinessCategory.EVALUATION_OR_PILOT,
            approved_by=APPROVER,
            approved_at=NOW,
            effective_from=NOW - timedelta(days=1),
        )
        self.campaign = Campaign(
            slug=f"synthetic-{uuid.uuid4().hex[:8]}",
            name="SYNTHETIC-Campaign",
            product_id=self.product.id,
            paused=False,
        )
        self.account = Account(
            domain=f"{uuid.uuid4().hex[:8]}.example.com",
            name="SYNTHETIC-Account",
            country_code="US",
        )
        session.add_all([self.status, self.campaign, self.account])
        session.flush()

        self.policy_version = publish_policy_version(
            session,
            campaign_id=self.campaign.id,
            policy=policy or CampaignPolicy(),
            approved_by=APPROVER,
            approved_at=NOW,
        )

        self.contact = Contact(account_id=self.account.id, full_name="SYNTHETIC Person")
        session.add(self.contact)
        session.flush()

        self.email = ContactPoint(
            contact_id=self.contact.id,
            type=ContactPointType.EMAIL,
            value=f"{uuid.uuid4().hex[:8]}@{self.account.domain}",
            verification_state=VerificationState.VERIFIED,
        )
        session.add(self.email)
        session.flush()

        self.candidate = create_candidate(
            session,
            campaign_id=self.campaign.id,
            account_id=self.account.id,
            contact_id=self.contact.id,
            actor=OPERATOR,
        )

    def republish(self, policy: CampaignPolicy) -> None:
        publish_policy_version(
            self.session,
            campaign_id=self.campaign.id,
            policy=policy,
            approved_by=APPROVER,
            approved_at=NOW,
        )
        self.session.flush()

    def decide(self) -> list[Rule]:
        return [failure.rule for failure in evaluate(self.session, self.candidate, at=NOW).failures]


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


# --- criterion 1: a positive and a negative test per implemented rule -------------------------


def test_a_fully_valid_candidate_passes_every_rule(world: World) -> None:
    """The positive case for all five rules at once; each negative below breaks one thing."""
    decision = evaluate(world.session, world.candidate, at=NOW)

    assert decision.is_eligible
    assert decision.failures == []


def test_geography_refuses_a_country_outside_the_allowed_set(world: World) -> None:
    world.account.country_code = "DE"
    world.session.flush()

    assert world.decide() == [Rule.GEOGRAPHY]


def test_geography_refuses_an_unknown_country_rather_than_assuming_domestic(world: World) -> None:
    """`Q-013` has not confirmed jurisdictions, so absence must not read as "US"."""
    world.account.country_code = None
    world.session.flush()

    assert world.decide() == [Rule.GEOGRAPHY]


def test_campaign_exclusion_refuses_an_excluded_domain(world: World) -> None:
    world.republish(CampaignPolicy(excluded_domains=(world.account.domain,)))

    assert world.decide() == [Rule.CAMPAIGN_EXCLUSION]


def test_campaign_exclusion_permits_a_domain_that_is_not_listed(world: World) -> None:
    world.republish(CampaignPolicy(excluded_domains=("someone-else.example.org",)))

    assert world.decide() == []


@pytest.mark.parametrize(
    "scope",
    [
        SuppressionScope.EMAIL,
        SuppressionScope.PERSON,
        SuppressionScope.DOMAIN,
        SuppressionScope.ACCOUNT,
    ],
)
def test_suppression_refuses_at_every_scope(world: World, scope: SuppressionScope) -> None:
    identity = {
        SuppressionScope.EMAIL: world.email.value,
        SuppressionScope.PERSON: str(world.contact.id),
        SuppressionScope.DOMAIN: world.account.domain,
        SuppressionScope.ACCOUNT: str(world.account.id),
    }[scope]
    record_suppression(
        world.session,
        scope=scope,
        identity=identity,
        source=SuppressionSource.UNSUBSCRIBE,
        reason="SYNTHETIC opt-out",
        effective_at=NOW - timedelta(days=1),
    )
    world.session.flush()

    assert world.decide() == [Rule.SUPPRESSION]


def test_a_lifted_suppression_no_longer_refuses(world: World) -> None:
    suppression = record_suppression(
        world.session,
        scope=SuppressionScope.DOMAIN,
        identity=world.account.domain,
        source=SuppressionSource.IMPORT,
        reason="SYNTHETIC mistyped import",
        effective_at=NOW - timedelta(days=2),
    )
    suppression.lifted_at = NOW - timedelta(hours=1)
    suppression.lifted_by = OPERATOR.id
    suppression.lifted_reason = "SYNTHETIC correction"
    world.session.flush()

    assert world.decide() == []


def test_campaign_policy_cannot_narrow_which_suppression_scopes_apply(world: World) -> None:
    """§15.6: a policy may widen what it respects, never narrow it."""
    world.republish(
        CampaignPolicy(
            suppression_scope={"person": False, "email": False, "domain": False, "account": False}
        )
    )
    record_suppression(
        world.session,
        scope=SuppressionScope.EMAIL,
        identity=world.email.value,
        source=SuppressionSource.COMPLAINT,
        reason="SYNTHETIC complaint",
        effective_at=NOW - timedelta(days=1),
    )
    world.session.flush()

    assert world.decide() == [Rule.SUPPRESSION]


def test_product_readiness_refuses_a_readiness_the_policy_excludes(world: World) -> None:
    """`sellable_now` is excluded by default until `Q-021`/`Q-022` deliver approved briefs."""
    world.status.readiness_category = ReadinessCategory.SELLABLE_NOW
    world.session.flush()

    assert world.decide() == [Rule.PRODUCT_READINESS]


def test_product_readiness_refuses_when_no_status_version_is_in_force(world: World) -> None:
    """GP-12: no explicit readiness means no readiness, not "probably fine"."""
    world.status.expires_or_review_by = NOW - timedelta(hours=1)
    world.session.flush()

    assert world.decide() == [Rule.PRODUCT_READINESS]


def test_product_readiness_permits_a_readiness_the_policy_allows(world: World) -> None:
    world.status.readiness_category = ReadinessCategory.IN_DEVELOPMENT
    world.session.flush()

    assert world.decide() == []


def test_contactability_refuses_a_contact_with_no_email(world: World) -> None:
    world.session.delete(world.email)
    world.session.flush()

    assert world.decide() == [Rule.CONTACTABILITY]


def test_contactability_refuses_an_unverified_address_when_policy_requires_verification(
    world: World,
) -> None:
    world.email.verification_state = VerificationState.UNVERIFIED
    world.session.flush()

    assert world.decide() == [Rule.CONTACTABILITY]


def test_contactability_refuses_an_invalid_address(world: World) -> None:
    world.email.verification_state = VerificationState.INVALID
    world.session.flush()

    assert world.decide() == [Rule.CONTACTABILITY]


def test_contactability_accepts_an_unverified_address_when_policy_does_not_require_it(
    world: World,
) -> None:
    world.email.verification_state = VerificationState.UNVERIFIED
    world.republish(CampaignPolicy(require_verified_email=False))

    assert world.decide() == []


def test_contactability_refuses_an_account_level_candidate(db_session: Session) -> None:
    world = World(db_session)
    account_level = create_candidate(
        db_session,
        campaign_id=world.campaign.id,
        account_id=world.account.id,
        contact_id=None,
        actor=OPERATOR,
    )

    failures = evaluate(db_session, account_level, at=NOW).failures

    assert [failure.rule for failure in failures] == [Rule.CONTACTABILITY]


def test_a_campaign_with_no_published_policy_refuses_rather_than_defaulting(
    db_session: Session,
) -> None:
    """A campaign with no approved rules cannot produce an answer (§10.1)."""
    product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
    db_session.add(product)
    db_session.flush()
    campaign = Campaign(
        slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC", product_id=product.id
    )
    account = Account(domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account")
    db_session.add_all([campaign, account])
    db_session.flush()
    candidate = create_candidate(
        db_session,
        campaign_id=campaign.id,
        account_id=account.id,
        contact_id=None,
        actor=OPERATOR,
    )

    with pytest.raises(NoCurrentPolicy):
        evaluate(db_session, candidate, at=NOW)


# --- criterion 2: all reasons, not just the first ---------------------------------------------


def test_a_candidate_failing_four_rules_records_all_four(world: World) -> None:
    world.account.country_code = "DE"
    world.status.readiness_category = ReadinessCategory.SELLABLE_NOW
    world.email.verification_state = VerificationState.INVALID
    world.republish(CampaignPolicy(excluded_domains=(world.account.domain,)))
    record_suppression(
        world.session,
        scope=SuppressionScope.DOMAIN,
        identity=world.account.domain,
        source=SuppressionSource.UNSUBSCRIBE,
        reason="SYNTHETIC opt-out",
        effective_at=NOW - timedelta(days=1),
    )
    world.session.flush()

    decision = apply_eligibility(world.session, world.candidate, actor=OPERATOR, at=NOW)

    assert [failure.rule for failure in decision.failures] == list(IMPLEMENTED_RULES)
    assert world.candidate.state is CampaignCandidateState.INELIGIBLE
    for rule in IMPLEMENTED_RULES:
        assert rule.value in world.candidate.ineligible_reason


def test_an_ineligible_candidate_records_a_reason_the_database_would_demand(world: World) -> None:
    world.account.country_code = "DE"
    world.session.flush()

    apply_eligibility(world.session, world.candidate, actor=OPERATOR, at=NOW)

    assert world.candidate.ineligible_reason
    assert "geography" in world.candidate.ineligible_reason


def test_the_decision_is_audited_with_every_failed_rule(world: World) -> None:
    world.account.country_code = "DE"
    world.email.verification_state = VerificationState.INVALID
    world.session.flush()

    apply_eligibility(world.session, world.candidate, actor=OPERATOR, at=NOW)

    event = world.session.execute(
        select(AuditEvent).where(AuditEvent.action == "campaign_candidate.transitioned")
    ).scalar_one()
    assert event.policy_decision == "eligibility:fail:geography,contactability"
    assert event.to_state == CampaignCandidateState.INELIGIBLE.value


def test_a_passing_candidate_becomes_eligible_and_says_so(world: World) -> None:
    decision = apply_eligibility(world.session, world.candidate, actor=OPERATOR, at=NOW)

    assert decision.is_eligible
    assert world.candidate.state is CampaignCandidateState.ELIGIBLE
    assert world.candidate.ineligible_reason is None
    event = world.session.execute(
        select(AuditEvent).where(AuditEvent.action == "campaign_candidate.transitioned")
    ).scalar_one()
    assert event.policy_decision == "eligibility:pass"


# --- criterion 3: no model, no nondeterminism -------------------------------------------------


def test_the_module_imports_nothing_from_the_model_gateway() -> None:
    """`qualification` is *allowed* to import `model_gateway`, so the boundary checker cannot
    enforce this. §10.1 requires it, so it is asserted here instead."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not [name for name in imported if "model_gateway" in name]
    assert not [name for name in imported if name.startswith(("httpx", "requests", "openai"))]


def test_eligibility_names_exactly_one_lifecycle() -> None:
    """The compensating check for widening `LIFECYCLE_OWNERS` to include `qualification`.

    That map exists so a function moving two lifecycles has to name both (ADR-015). Adding this
    package as an owner of `CampaignCandidateState` is only safe while eligibility names that one
    lifecycle and no other — so this asserts it, rather than leaving the widening on trust.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    lifecycles = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "app.core.lifecycles"
        for alias in node.names
    }

    assert lifecycles == {"CampaignCandidateState"}


def test_no_entry_point_accepts_an_override(world: World) -> None:
    """A model recommendation must have nowhere to enter the decision (§10.1, §3.5)."""
    import inspect

    for function in (evaluate, apply_eligibility):
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & {
            "override",
            "force",
            "recommendation",
            "model_result",
            "confidence",
            "skip_rules",
        }, f"{function.__name__} exposes an override parameter"


def test_evaluating_twice_produces_an_identical_result(world: World) -> None:
    world.account.country_code = "DE"
    world.email.verification_state = VerificationState.INVALID
    world.session.flush()

    first = evaluate(world.session, world.candidate, at=NOW)
    second = evaluate(world.session, world.candidate, at=NOW)

    assert first.failures == second.failures
    assert first.summary == second.summary


def test_a_failure_is_comparable_by_value_so_determinism_is_testable() -> None:
    """Frozen dataclasses, not objects that compare by identity — otherwise the test above
    would pass for two runs that disagreed."""
    left = EligibilityFailure(rule=Rule.GEOGRAPHY, reason="r", inputs={"a": "b"})
    right = EligibilityFailure(rule=Rule.GEOGRAPHY, reason="r", inputs={"a": "b"})

    assert left == right
    assert left != EligibilityFailure(rule=Rule.SUPPRESSION, reason="r", inputs={"a": "b"})


def test_failure_inputs_carry_no_contact_details(world: World) -> None:
    """§15.5: a rule may report the scope it matched, never the address it matched on."""
    record_suppression(
        world.session,
        scope=SuppressionScope.EMAIL,
        identity=world.email.value,
        source=SuppressionSource.COMPLAINT,
        reason="SYNTHETIC complaint",
        effective_at=NOW - timedelta(days=1),
    )
    world.session.flush()

    decision = evaluate(world.session, world.candidate, at=NOW)
    rendered = f"{decision.summary} {[f.inputs for f in decision.failures]}"

    assert world.email.value not in rendered
    assert world.contact.full_name not in rendered


# --- the rule register is honest about what is not implemented --------------------------------


def test_every_rule_is_either_implemented_or_explicitly_deferred() -> None:
    """§10.1 names eight checks. A rule in neither collection is one nobody decided about."""
    assert set(IMPLEMENTED_RULES) | set(DEFERRED_RULES) == set(Rule)
    assert not set(IMPLEMENTED_RULES) & set(DEFERRED_RULES)


def test_each_deferred_rule_names_the_task_that_will_implement_it() -> None:
    """A gap with no task ID is a gap that gets forgotten."""
    for rule, reason in DEFERRED_RULES.items():
        assert "T-1" in reason, f"{rule.value} does not name a task"


def test_the_deferred_rules_are_exactly_the_three_without_inputs() -> None:
    assert set(DEFERRED_RULES) == {
        Rule.EXISTING_RELATIONSHIP,
        Rule.APPROVED_SOURCE_BASIS,
        Rule.OBVIOUS_NON_FIT,
    }


def test_no_deferred_rule_can_appear_in_a_decision(world: World) -> None:
    """A rule that cannot run must never look like it passed *or* failed."""
    world.account.country_code = "DE"
    world.session.flush()

    decision = evaluate(world.session, world.candidate, at=NOW)

    assert not {failure.rule for failure in decision.failures} & set(DEFERRED_RULES)


# --- criterion 4: the fixture rows that must be ineligible by default --------------------------


def test_the_non_us_fixture_row_is_ineligible(db_session: Session) -> None:
    """`T-041`'s `non-us-record` case: DE, verified, otherwise perfect."""
    world = World(db_session)
    world.account.country_code = "DE"
    db_session.flush()

    apply_eligibility(db_session, world.candidate, actor=OPERATOR, at=NOW)

    assert world.candidate.state is CampaignCandidateState.INELIGIBLE


def test_the_suppressed_fixture_row_is_ineligible(db_session: Session) -> None:
    """`T-041`'s `suppressed-email` case is verified and US on purpose, so only suppression
    can be what refuses it."""
    world = World(db_session)
    record_suppression(
        db_session,
        scope=SuppressionScope.EMAIL,
        identity=world.email.value,
        source=SuppressionSource.UNSUBSCRIBE,
        reason="SYNTHETIC opt-out",
        effective_at=NOW - timedelta(days=1),
    )
    db_session.flush()

    decision = apply_eligibility(db_session, world.candidate, actor=OPERATOR, at=NOW)

    assert world.candidate.state is CampaignCandidateState.INELIGIBLE
    assert [failure.rule for failure in decision.failures] == [Rule.SUPPRESSION]


def test_an_ineligible_candidate_cannot_be_walked_back_by_a_second_pass(world: World) -> None:
    """§8.2: `ineligible` is terminal for this lifecycle. Re-running must not resurrect it."""
    world.account.country_code = "DE"
    world.session.flush()
    apply_eligibility(world.session, world.candidate, actor=OPERATOR, at=NOW)
    world.account.country_code = "US"
    world.session.flush()

    with pytest.raises(Exception, match="ineligible"):
        apply_eligibility(world.session, world.candidate, actor=OPERATOR, at=NOW)

    assert (
        world.session.get(CampaignCandidate, world.candidate.id).state
        is CampaignCandidateState.INELIGIBLE
    )
