"""Message revision validation (T-055; §8.3 step 10, §10.5, §15.6, §15.7).

Nine checks, each with a passing and a failing test, and then the three properties that make the
set worth having: every failure is reported rather than the first, a revision with any failure
never reaches a reviewer, and the whole thing is deterministic with no model in it.

The interesting case is `claim_currency`. A claim that expires between drafting and review leaves
the message *textually unchanged* — same wording, same hash, same everything — and must still
fail. That is the check `T-054` structurally cannot make, because at drafting time the claim was
current.
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
from app.campaigns.candidate import create_candidate
from app.campaigns.candidate import transition as transition_candidate
from app.campaigns.models import Campaign
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import NoCurrentPolicy, publish_policy_version
from app.core.lifecycles import CampaignCandidateState, MessageRevisionState
from app.drafts_and_approvals.drafting import PURPOSE_TEMPLATES, TEMPLATE_DIR, render_body
from app.drafts_and_approvals.models import DraftPurpose, MessageDraft, MessageRevision
from app.drafts_and_approvals.revisions import create_revision
from app.drafts_and_approvals.validation import (
    Check,
    ValidationFailure,
    apply_validation,
    validate_revision,
)
from app.products_and_claims.claim_models import ApprovedClaim, ApprovedClaimCampaign
from app.products_and_claims.models import (
    Product,
    ProductStatusVersion,
    ReadinessCategory,
)
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)
from app.prospects.suppression import SuppressionScope, SuppressionSource, record_suppression
from app.research_and_evidence.models import (
    EvidenceSnapshot,
    ExtractionMethod,
    RetentionClass,
    SourceQuality,
    SourceType,
)
from tests.factories import NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
APPROVER = "approver-1"
MODULE = Path(__file__).resolve().parents[1] / "app" / "drafts_and_approvals" / "validation.py"

CLAIM_TEXT = "SYNTHETIC EXAMPLE CLAIM — offered for evaluation deployments."
PERSONALIZATION = "SYNTHETIC: the account is described as evaluating storage."


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-validation-test")


class World:
    """A revision that validates. Each test breaks exactly one thing about it."""

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
            approved_at=NOW - timedelta(days=1),
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

        publish_policy_version(
            session,
            campaign_id=self.campaign.id,
            policy=policy or CampaignPolicy(),
            approved_by=APPROVER,
            approved_at=NOW,
        )

        self.contact = Contact(account_id=self.account.id, full_name="SYNTHETIC Person")
        session.add(self.contact)
        session.flush()
        self.recipient = ContactPoint(
            contact_id=self.contact.id,
            type=ContactPointType.EMAIL,
            value=f"{uuid.uuid4().hex[:8]}@{self.account.domain}",
            verification_state=VerificationState.VERIFIED,
        )
        session.add(self.recipient)
        session.flush()

        self.claim = self.publish_claim("SYNTHETIC-CLAIM-current", CLAIM_TEXT)

        self.candidate = create_candidate(
            session,
            campaign_id=self.campaign.id,
            account_id=self.account.id,
            contact_id=self.contact.id,
            actor=OPERATOR,
        )
        transition_candidate(
            session, self.candidate, CampaignCandidateState.ELIGIBLE, actor=OPERATOR
        )

        self.evidence = EvidenceSnapshot(
            candidate_id=self.candidate.id,
            source_type=SourceType.SYNTHETIC_FIXTURE,
            retrieved_at=NOW - timedelta(hours=1),
            supporting_excerpt_or_fact="SYNTHETIC: the account is evaluating storage.",
            content_hash="f" * 64,
            extraction_method=ExtractionMethod.STRUCTURED_FIELD,
            source_quality=SourceQuality.MEDIUM,
            license_and_retention_class=RetentionClass.PUBLIC_UNRESTRICTED,
            contains_personal_or_confidential_data=False,
        )
        session.add(self.evidence)
        session.flush()

        self.draft = MessageDraft(
            candidate_id=self.candidate.id, purpose=DraftPurpose.INITIAL_OUTREACH
        )
        session.add(self.draft)
        session.flush()

        self.revision = self.make_revision()

    def publish_claim(
        self, key: str, text: str, *, expires: object = None, scoped: bool = True
    ) -> ApprovedClaim:
        claim = ApprovedClaim(
            claim_key=key,
            version=1,
            product_id=self.product.id,
            text=text,
            approved_by=APPROVER,
            approved_at=NOW - timedelta(days=10),
            effective_from=NOW - timedelta(days=10),
            expires_or_review_by=expires or (NOW + timedelta(days=90)),
        )
        self.session.add(claim)
        self.session.flush()
        if scoped:
            self.session.add(ApprovedClaimCampaign(claim_id=claim.id, campaign_id=self.campaign.id))
            self.session.flush()
        return claim

    def make_revision(
        self,
        *,
        claims: list[ApprovedClaim] | None = None,
        body: str | None = None,
        recipient: ContactPoint | None = None,
        evidence: list[EvidenceSnapshot] | None = None,
    ) -> MessageRevision:
        """Build a revision. Every variation is a *new* revision rather than an edit, because
        `MessageRevision` content is immutable by trigger (`T-020`)."""
        cited = claims if claims is not None else [self.claim]
        return create_revision(
            self.session,
            draft=self.draft,
            recipient_contact_point_id=(recipient or self.recipient).id,
            subject="SYNTHETIC subject line",
            body=body
            or render_body(
                DraftPurpose.INITIAL_OUTREACH, personalization=PERSONALIZATION, claims=cited
            ),
            approved_claim_ids=[claim.id for claim in cited],
            evidence_ids=[
                snapshot.id for snapshot in (evidence if evidence is not None else [self.evidence])
            ],
            created_by="drafting-task",
            actor=OPERATOR,
        )

    def checks(self) -> list[Check]:
        return [
            failure.check
            for failure in validate_revision(self.session, self.revision, at=NOW).failures
        ]


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


# --- criterion 1: a passing and a failing test per check ---------------------------------------


def test_a_well_formed_revision_passes_every_check(world: World) -> None:
    """The positive case for all nine checks; each negative below breaks one thing."""
    result = validate_revision(world.session, world.revision, at=NOW)

    assert result.is_valid
    assert result.failures == []


def test_claim_citations_fail_when_a_cited_claim_no_longer_resolves(world: World) -> None:
    """A claim row deleted out from under a revision leaves it citing nothing."""
    world.session.execute(
        select(ApprovedClaimCampaign).where(ApprovedClaimCampaign.claim_id == world.claim.id)
    )
    for link in (
        world.session.execute(
            select(ApprovedClaimCampaign).where(ApprovedClaimCampaign.claim_id == world.claim.id)
        )
        .scalars()
        .all()
    ):
        world.session.delete(link)
    world.session.delete(world.claim)
    world.session.flush()

    assert Check.CLAIM_CITATIONS in world.checks()


def test_claim_currency_fails_for_an_expired_claim_even_though_the_wording_is_unchanged(
    world: World,
) -> None:
    """Criterion 3, and the reason this task exists separately from `T-054`.

    The revision is byte-identical to the one that validated a moment ago — same body, same
    hash. Only the claim's review date has passed.
    """
    lapsed = world.publish_claim(
        "SYNTHETIC-CLAIM-lapsing",
        "SYNTHETIC EXAMPLE CLAIM that lapses.",
        expires=NOW - timedelta(hours=1),
    )
    world.revision = world.make_revision(claims=[lapsed])
    body_before, hash_before = world.revision.body, world.revision.content_hash

    failures = validate_revision(world.session, world.revision, at=NOW).failures

    assert [failure.check for failure in failures] == [Check.CLAIM_CURRENCY]
    assert world.revision.body == body_before, "the message text has not changed"
    assert world.revision.content_hash == hash_before


def test_claim_currency_passes_for_a_claim_still_in_its_window(world: World) -> None:
    assert Check.CLAIM_CURRENCY not in world.checks()


def test_campaign_scope_fails_for_a_claim_approved_elsewhere(world: World) -> None:
    """§14.4: approval for one campaign is not approval for another."""
    unscoped = world.publish_claim(
        "SYNTHETIC-CLAIM-other", "SYNTHETIC EXAMPLE CLAIM for elsewhere.", scoped=False
    )
    world.revision = world.make_revision(claims=[unscoped])

    assert Check.CAMPAIGN_SCOPE in world.checks()


def test_product_readiness_fails_when_the_status_lapses(world: World) -> None:
    """GP-12: the readiness that justified the message must still hold at review time."""
    world.status.expires_or_review_by = NOW - timedelta(hours=1)
    world.session.flush()

    assert Check.PRODUCT_READINESS in world.checks()


def test_product_readiness_fails_when_policy_stops_permitting_it(db_session: Session) -> None:
    world = World(db_session)
    world.status.readiness_category = ReadinessCategory.SELLABLE_NOW
    db_session.flush()

    assert Check.PRODUCT_READINESS in world.checks()


def test_evidence_citations_fail_when_a_snapshot_goes_stale(world: World) -> None:
    stale = EvidenceSnapshot(
        candidate_id=world.candidate.id,
        source_type=SourceType.SYNTHETIC_FIXTURE,
        retrieved_at=NOW - timedelta(days=400),
        supporting_excerpt_or_fact="SYNTHETIC: a fact past its refresh date.",
        content_hash="a" * 64,
        extraction_method=ExtractionMethod.STRUCTURED_FIELD,
        source_quality=SourceQuality.LOW,
        license_and_retention_class=RetentionClass.PUBLIC_UNRESTRICTED,
        contains_personal_or_confidential_data=False,
        expires_or_refresh_by=NOW - timedelta(hours=1),
    )
    world.session.add(stale)
    world.session.flush()
    world.revision = world.make_revision(evidence=[stale])

    assert Check.EVIDENCE_CITATIONS in world.checks()


def test_evidence_citations_pass_when_the_snapshot_is_current(world: World) -> None:
    assert Check.EVIDENCE_CITATIONS not in world.checks()


def test_recipient_fails_when_the_address_is_unverified(world: World) -> None:
    world.recipient.verification_state = VerificationState.UNVERIFIED
    world.session.flush()

    assert Check.RECIPIENT_CONTACTABLE in world.checks()


def test_recipient_passes_unverified_when_policy_does_not_require_verification(
    db_session: Session,
) -> None:
    world = World(db_session, policy=CampaignPolicy(require_verified_email=False))
    world.recipient.verification_state = VerificationState.UNVERIFIED
    db_session.flush()

    assert Check.RECIPIENT_CONTACTABLE not in world.checks()


def test_recipient_fails_for_a_non_email_contact_point(world: World) -> None:
    phone = ContactPoint(
        contact_id=world.contact.id,
        type=ContactPointType.PHONE,
        value="+SYNTHETIC-PHONE",
    )
    world.session.add(phone)
    world.session.flush()
    world.revision = world.make_revision(recipient=phone)

    assert Check.RECIPIENT_CONTACTABLE in world.checks()


@pytest.mark.parametrize(
    "scope",
    [
        SuppressionScope.EMAIL,
        SuppressionScope.PERSON,
        SuppressionScope.DOMAIN,
        SuppressionScope.ACCOUNT,
    ],
)
def test_suppression_fails_at_every_scope(world: World, scope: SuppressionScope) -> None:
    """§15.6: a suppression recorded after drafting must stop the message before review."""
    identity = {
        SuppressionScope.EMAIL: world.recipient.value,
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
        effective_at=NOW - timedelta(minutes=1),
    )
    world.session.flush()

    assert Check.SUPPRESSION in world.checks()


def test_suppression_passes_when_none_applies(world: World) -> None:
    assert Check.SUPPRESSION not in world.checks()


def test_product_statement_grounding_fails_when_a_sentence_is_inserted(world: World) -> None:
    """§10.5: a product statement nobody approved must fail validation."""
    tampered = world.revision.body.replace(
        CLAIM_TEXT, f"{CLAIM_TEXT}\n\nSYNTHETIC: the product is certified and available now."
    )
    world.revision = world.make_revision(body=tampered)

    assert Check.PRODUCT_STATEMENT_GROUNDING in world.checks()


def test_product_statement_grounding_fails_when_the_claim_wording_is_altered(
    world: World,
) -> None:
    """A paraphrase is not the approved claim, however close it reads."""
    tampered = world.revision.body.replace(CLAIM_TEXT, CLAIM_TEXT.replace("offered", "available"))
    world.revision = world.make_revision(body=tampered)

    assert Check.PRODUCT_STATEMENT_GROUNDING in world.checks()


def test_product_statement_grounding_passes_for_a_rendered_body(world: World) -> None:
    assert Check.PRODUCT_STATEMENT_GROUNDING not in world.checks()


def test_compliance_elements_fail_when_the_boilerplate_is_removed(world: World) -> None:
    boilerplate = (
        (TEMPLATE_DIR / PURPOSE_TEMPLATES[DraftPurpose.INITIAL_OUTREACH])
        .read_text(encoding="utf-8")
        .split("{claims}")[1]
        .strip()
    )
    world.revision = world.make_revision(body=world.revision.body.replace(boilerplate, ""))

    assert Check.COMPLIANCE_ELEMENTS in world.checks()


def test_compliance_elements_pass_when_the_boilerplate_is_intact(world: World) -> None:
    assert Check.COMPLIANCE_ELEMENTS not in world.checks()


def test_a_campaign_with_no_policy_cannot_validate_a_revision(db_session: Session) -> None:
    """No approved rules means no basis on which to call a message valid."""
    world = World(db_session)
    for version in (
        db_session.execute(
            select(__import__("app.campaigns.models", fromlist=["x"]).CampaignPolicyVersion)
        )
        .scalars()
        .all()
    ):
        db_session.delete(version)
    db_session.flush()

    with pytest.raises(NoCurrentPolicy):
        validate_revision(db_session, world.revision, at=NOW)


# --- criterion 2: a failing revision never reaches review_pending -------------------------------


def test_a_valid_revision_moves_to_review_pending(world: World) -> None:
    result = apply_validation(world.session, world.revision, actor=OPERATOR, at=NOW)

    assert result.is_valid
    assert world.revision.state is MessageRevisionState.REVIEW_PENDING


def test_any_failure_sends_the_revision_to_validation_failed(world: World) -> None:
    world.recipient.verification_state = VerificationState.INVALID
    world.session.flush()

    result = apply_validation(world.session, world.revision, actor=OPERATOR, at=NOW)

    assert not result.is_valid
    assert world.revision.state is MessageRevisionState.VALIDATION_FAILED


def test_every_failing_check_is_reported_not_just_the_first(world: World) -> None:
    """A reviewer needs all the reasons; fixing one and rediscovering the next is not review."""
    world.recipient.verification_state = VerificationState.INVALID
    world.status.expires_or_review_by = NOW - timedelta(hours=1)
    record_suppression(
        world.session,
        scope=SuppressionScope.DOMAIN,
        identity=world.account.domain,
        source=SuppressionSource.UNSUBSCRIBE,
        reason="SYNTHETIC opt-out",
        effective_at=NOW - timedelta(minutes=1),
    )
    world.session.flush()

    checks = world.checks()

    assert {Check.RECIPIENT_CONTACTABLE, Check.PRODUCT_READINESS, Check.SUPPRESSION} <= set(checks)


def test_a_failed_revision_cannot_then_be_moved_to_review_pending(world: World) -> None:
    """§8.2 has no `validation_failed -> review_pending` edge: editing creates revision N+1."""
    from app.core.lifecycles import IllegalTransition
    from app.drafts_and_approvals.revisions import transition

    world.recipient.verification_state = VerificationState.INVALID
    world.session.flush()
    apply_validation(world.session, world.revision, actor=OPERATOR, at=NOW)

    with pytest.raises(IllegalTransition):
        transition(
            world.session, world.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
        )


def test_there_is_no_way_to_force_the_passing_transition() -> None:
    """No `override`, no `skip_checks`: a revision reaches a reviewer by passing, or not at all."""
    import inspect

    parameters = set(inspect.signature(apply_validation).parameters)

    assert not parameters & {"override", "force", "skip_checks", "checks", "ignore"}


def test_the_decision_is_audited_with_every_failed_check(world: World) -> None:
    world.recipient.verification_state = VerificationState.INVALID
    world.session.flush()

    apply_validation(world.session, world.revision, actor=OPERATOR, at=NOW)

    event = world.session.execute(
        select(AuditEvent).where(AuditEvent.action == "message_revision.validated")
    ).scalar_one()
    assert event.policy_decision.startswith("validation:fail:")
    assert "recipient_contactable" in event.payload["failed_checks"]


def test_the_audit_payload_carries_no_message_content(world: World) -> None:
    """§15.5: check names and IDs, never the subject, body, or address."""
    apply_validation(world.session, world.revision, actor=OPERATOR, at=NOW)

    event = world.session.execute(
        select(AuditEvent).where(AuditEvent.action == "message_revision.validated")
    ).scalar_one()
    serialized = str(event.payload)
    assert world.recipient.value not in serialized
    assert PERSONALIZATION not in serialized


# --- criterion 4: deterministic, and no model ---------------------------------------------------


def test_the_module_calls_no_model() -> None:
    """`drafts_and_approvals` is permitted to import `model_gateway`, so §8.3 step 10 is what
    forbids it here and this assertion is what enforces it."""
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


def test_validating_twice_produces_an_identical_result(world: World) -> None:
    world.recipient.verification_state = VerificationState.INVALID
    world.session.flush()

    first = validate_revision(world.session, world.revision, at=NOW)
    second = validate_revision(world.session, world.revision, at=NOW)

    assert first.failures == second.failures
    assert first.summary == second.summary


def test_a_failure_compares_by_value(world: World) -> None:
    """Frozen dataclasses, so the determinism test above cannot pass on identity alone."""
    left = ValidationFailure(check=Check.SUPPRESSION, reason="r", inputs={"a": "b"})
    right = ValidationFailure(check=Check.SUPPRESSION, reason="r", inputs={"a": "b"})

    assert left == right
    assert left != ValidationFailure(check=Check.CLAIM_CURRENCY, reason="r", inputs={"a": "b"})


def test_every_check_in_the_enum_is_reachable() -> None:
    """A check nobody can trigger is a check nobody is running."""
    source = MODULE.read_text(encoding="utf-8")

    for check in Check:
        assert f"Check.{check.name}" in source
