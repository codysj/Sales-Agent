"""Drafting from approved claims and stored evidence (T-054; §8.3 step 9, §10.5, §14.4).

§10.5's rules are mostly about what a message may not say, so most of these tests are refusals.
The one that matters most is structural rather than behavioural: `DraftOutput` has no `body`
field, so there is no channel through which a model-written product sentence could arrive. The
claim wording in a rendered message is byte-identical to the approved record, and a test asserts
exactly that.
"""

import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import create_candidate, transition
from app.campaigns.models import Campaign
from app.core.lifecycles import CampaignCandidateState, MessageRevisionState
from app.core.settings import AppEnv, Settings
from app.drafts_and_approvals.drafting import (
    PURPOSE_TEMPLATES,
    TEMPLATE_DIR,
    CandidateNotDraftable,
    MissingTemplate,
    UnknownCitation,
    build_inputs,
    draft_message,
    render_body,
)
from app.drafts_and_approvals.models import DraftPurpose, MessageDraft, MessageRevision
from app.model_gateway.gateway import DatabaseModelGateway
from app.model_gateway.models import ModelRun
from app.model_gateway.prompts import prompt_template, register_prompt_versions
from app.model_gateway.protocol import ProviderResponse
from app.model_gateway.schemas import DRAFT_KEY, DraftOutput, register_schema_versions
from app.model_gateway.validation import Escalated
from app.products_and_claims.claim_models import ApprovedClaim, ApprovedClaimCampaign
from app.products_and_claims.models import Product
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)
from app.qualification.models import QualificationRun
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

CLAIM_TEXT = "SYNTHETIC EXAMPLE CLAIM — the module is offered for evaluation deployments."


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-drafting-test")


class World:
    """A qualified candidate with one approved claim, one evidence snapshot, and a recipient."""

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

        self.claim = ApprovedClaim(
            claim_key="SYNTHETIC-CLAIM-sodium-readiness",
            version=1,
            product_id=self.product.id,
            text=CLAIM_TEXT,
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
            contact_id=self.contact.id,
            actor=OPERATOR,
        )
        transition(session, self.candidate, CampaignCandidateState.ELIGIBLE, actor=OPERATOR)

        self.evidence = EvidenceSnapshot(
            candidate_id=self.candidate.id,
            source_type=SourceType.SYNTHETIC_FIXTURE,
            retrieved_at=NOW - timedelta(hours=1),
            supporting_excerpt_or_fact="SYNTHETIC: the account is evaluating storage.",
            content_hash="e" * 64,
            extraction_method=ExtractionMethod.STRUCTURED_FIELD,
            source_quality=SourceQuality.MEDIUM,
            license_and_retention_class=RetentionClass.PUBLIC_UNRESTRICTED,
            contains_personal_or_confidential_data=False,
        )
        session.add(self.evidence)
        session.flush()

        prompts = {
            version.key: version
            for version in register_prompt_versions(session, created_by="operator-1", at=NOW)
        }
        schemas = {
            version.key: version
            for version in register_schema_versions(session, created_by="operator-1", at=NOW)
        }
        self.prompt = prompts["draft"]
        self.schema = schemas[DRAFT_KEY]
        _, _, self.config, _ = make_versions(session)

        self.model_run = self._model_run(session)
        session.add(
            QualificationRun(
                candidate_id=self.candidate.id,
                model_run_id=self.model_run.id,
                opportunity_type="pilot",
                evidence_completeness="partial",
                source_quality="medium",
                product_fit=3,
                buyer_relevance=2,
                timing=2,
                commercial_scale=1,
                human_review_required=True,
                output={},
                qualified_at=NOW,
            )
        )
        session.flush()

    def _model_run(self, session: Session) -> ModelRun:
        from app.core.settings import ModelProvider
        from app.model_gateway.models import ModelRunOutcome

        run = ModelRun(
            task_name="qualification",
            provider=ModelProvider.FAKE,
            model_name="deterministic-fake",
            outcome=ModelRunOutcome.SUCCEEDED,
            started_at=NOW,
        )
        session.add(run)
        session.flush()
        return run

    def output(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "subject": "SYNTHETIC subject line",
            "personalization": "SYNTHETIC: the account is described as evaluating storage.",
            "approved_claim_ids": [self.claim.claim_key],
            "evidence_ids": [str(self.evidence.id)],
        }
        payload.update(overrides)
        return payload

    def draft(self, provider: Any, **kwargs: Any) -> MessageRevision:
        return draft_message(
            self.session,
            self.candidate,
            DatabaseModelGateway(settings=TEST_SETTINGS, provider=provider),
            recipient_contact_point_id=self.recipient.id,
            prompt_version_id=self.prompt.id,
            schema_version_id=self.schema.id,
            model_config_version_id=self.config.id,
            actor=OPERATOR,
            at=NOW,
            **kwargs,
        )


class Scripted:
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


# --- criterion 1: revision 1 records the exact claim and evidence IDs ---------------------------


def test_the_revision_records_the_cited_ids(world: World) -> None:
    revision = world.draft(Scripted(world.output()))

    assert revision.revision_number == 1
    assert revision.approved_claim_ids == [world.claim.id]
    assert revision.evidence_ids == [world.evidence.id]
    assert revision.recipient_contact_point_id == world.recipient.id


def test_the_revision_has_a_content_hash_covering_its_citations(world: World) -> None:
    """§10.5: the hash verifies integrity. `T-020` includes the citation lists in it."""
    from app.drafts_and_approvals.revisions import compute_content_hash

    revision = world.draft(Scripted(world.output()))

    assert revision.content_hash == compute_content_hash(
        recipient_contact_point_id=revision.recipient_contact_point_id,
        subject=revision.subject,
        body=revision.body,
        approved_claim_ids=revision.approved_claim_ids,
        evidence_ids=revision.evidence_ids,
    )


def test_citing_no_claim_is_allowed(world: World) -> None:
    """A message with no product sentence is a message with no claims to cite."""
    revision = world.draft(Scripted(world.output(approved_claim_ids=[], evidence_ids=[])))

    assert revision.approved_claim_ids == []
    assert CLAIM_TEXT not in revision.body


# --- criterion 2: an unknown or expired claim cannot be persisted -------------------------------


def test_an_unknown_claim_id_is_refused(world: World) -> None:
    with pytest.raises(UnknownCitation, match="claim IDs not in the campaign"):
        world.draft(Scripted(world.output(approved_claim_ids=["SYNTHETIC-CLAIM-invented"])))

    assert world.session.execute(select(MessageRevision)).scalars().all() == []


def test_an_expired_claim_id_is_refused(world: World) -> None:
    """Published lapsed, not edited lapsed: `ApprovedClaim` is immutable by trigger (`T-014`)."""
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

    with pytest.raises(UnknownCitation):
        world.draft(Scripted(world.output(approved_claim_ids=["SYNTHETIC-CLAIM-lapsed"])))


def test_a_claim_approved_for_another_campaign_is_refused(world: World) -> None:
    """§14.4's allow-list: a claim approved elsewhere is not approved here."""
    other = ApprovedClaim(
        claim_key="SYNTHETIC-CLAIM-other-campaign",
        version=1,
        product_id=world.product.id,
        text="SYNTHETIC EXAMPLE CLAIM for a different campaign.",
        approved_by=APPROVER,
        approved_at=NOW - timedelta(days=1),
        effective_from=NOW - timedelta(days=1),
        expires_or_review_by=NOW + timedelta(days=90),
    )
    world.session.add(other)
    world.session.flush()

    with pytest.raises(UnknownCitation):
        world.draft(Scripted(world.output(approved_claim_ids=["SYNTHETIC-CLAIM-other-campaign"])))


def test_an_unknown_evidence_id_is_refused(world: World) -> None:
    with pytest.raises(UnknownCitation, match="evidence IDs not stored"):
        world.draft(Scripted(world.output(evidence_ids=[str(uuid.uuid4())])))


def test_a_refused_draft_leaves_the_model_run_recorded(world: World) -> None:
    """The call cost something; nothing was written, and the cost record says both."""
    with pytest.raises(UnknownCitation):
        world.draft(Scripted(world.output(approved_claim_ids=["SYNTHETIC-nope"])))

    drafting_runs = [
        run
        for run in world.session.execute(select(ModelRun)).scalars().all()
        if run.task_name == "draft"
    ]
    assert len(drafting_runs) == 1


# --- criterion 3: boilerplate is rendered, and claim wording is verbatim -------------------------


def test_the_claim_text_in_the_body_is_byte_identical_to_the_approved_record(
    world: World,
) -> None:
    """§10.5: an approved claim stores exact wording, and this is where that becomes real."""
    revision = world.draft(Scripted(world.output()))

    assert CLAIM_TEXT in revision.body


def test_the_model_cannot_supply_body_text_at_all() -> None:
    """The structural half of §10.5: there is no field a product sentence could arrive in."""
    assert "body" not in DraftOutput.model_fields
    assert set(DraftOutput.model_fields) == {
        "subject",
        "personalization",
        "approved_claim_ids",
        "evidence_ids",
    }


def test_the_body_is_rendered_from_the_shipped_template(world: World) -> None:
    revision = world.draft(Scripted(world.output()))
    template = (TEMPLATE_DIR / PURPOSE_TEMPLATES[DraftPurpose.INITIAL_OUTREACH]).read_text(
        encoding="utf-8"
    )
    boilerplate = template.split("{claims}")[1].strip()

    assert boilerplate in revision.body


def test_a_purpose_with_no_template_cannot_be_drafted(world: World) -> None:
    """ "Rendered from templates when practical" — a missing template is a missing decision."""
    provider = Scripted(world.output())

    with pytest.raises(MissingTemplate):
        world.draft(provider, purpose=DraftPurpose.FOLLOW_UP)

    assert provider.prompts == [], "the refusal must happen before a model call is spent"


def test_rendering_refuses_a_purpose_with_no_template(world: World) -> None:
    """`render_body` is public, so its own guard needs its own test — the check inside
    `draft_message` is the early one and would otherwise be the only thing exercised."""
    with pytest.raises(MissingTemplate):
        render_body(
            DraftPurpose.FOLLOW_UP,
            personalization="SYNTHETIC personalization.",
            claims=[world.claim],
        )


def test_rendering_does_not_alter_the_claim_wording(world: World) -> None:
    body = render_body(
        DraftPurpose.INITIAL_OUTREACH,
        personalization="SYNTHETIC personalization.",
        claims=[world.claim],
    )

    assert world.claim.text in body


def test_the_personalization_reaches_the_body(world: World) -> None:
    revision = world.draft(
        Scripted(world.output(personalization="SYNTHETIC: a specific observation."))
    )

    assert "SYNTHETIC: a specific observation." in revision.body


# --- criterion 4: drafting twice creates revision 2, never mutates revision 1 --------------------


def test_drafting_twice_creates_a_second_revision(world: World) -> None:
    first = world.draft(Scripted(world.output(subject="SYNTHETIC first subject")))
    first_id, first_hash = first.id, first.content_hash

    second = world.draft(Scripted(world.output(subject="SYNTHETIC second subject")))

    assert second.revision_number == 2
    assert second.id != first_id
    surviving = world.session.get(MessageRevision, first_id)
    assert surviving.content_hash == first_hash
    assert surviving.subject == "SYNTHETIC first subject"


def test_the_earlier_revision_is_retired_not_deleted(world: World) -> None:
    first = world.draft(Scripted(world.output()))

    world.draft(Scripted(world.output(subject="SYNTHETIC second subject")))

    assert world.session.get(MessageRevision, first.id).state is MessageRevisionState.SUPERSEDED


def test_both_revisions_share_one_draft(world: World) -> None:
    first = world.draft(Scripted(world.output()))
    second = world.draft(Scripted(world.output(subject="SYNTHETIC second subject")))

    assert first.draft_id == second.draft_id
    assert len(world.session.execute(select(MessageDraft)).scalars().all()) == 1


def test_the_database_refuses_an_edit_to_a_stored_revision(world: World) -> None:
    """`T-020`'s immutability trigger — the reason drafting has no update path to get wrong."""
    revision = world.draft(Scripted(world.output()))

    revision.body = "SYNTHETIC: rewritten after the fact"

    with pytest.raises(Exception, match="immutable"):
        world.session.flush()


# --- ordering: qualification comes first --------------------------------------------------------


def test_an_unqualified_candidate_cannot_be_drafted(db_session: Session) -> None:
    """§8.3 qualifies at step 7 and drafts at step 9."""
    world = World(db_session)
    db_session.execute(select(QualificationRun))
    for run in db_session.execute(select(QualificationRun)).scalars().all():
        db_session.delete(run)
    db_session.flush()
    provider = Scripted(world.output())

    with pytest.raises(CandidateNotDraftable, match="no qualification run"):
        world.draft(provider)

    assert provider.prompts == []


# --- the prompt shows only stored records --------------------------------------------------------


def test_the_prompt_carries_the_claim_wording_and_evidence_ids(world: World) -> None:
    provider = Scripted(world.output())

    world.draft(provider)

    sent = provider.prompts[0]
    assert world.claim.claim_key in sent
    assert CLAIM_TEXT in sent
    assert str(world.evidence.id) in sent


def test_the_prompt_tells_the_model_it_does_not_describe_the_product(world: World) -> None:
    text = prompt_template("draft")

    assert "You do not get to describe the product" in text
    assert "UNTRUSTED" in text


def test_the_prompt_names_no_vendor_or_endpoint() -> None:
    text = prompt_template("draft").lower()

    for marker in ("claude", "gpt", "deepseek", "http://", "https://"):
        assert marker not in text


def test_inputs_contain_only_stored_rows(world: World) -> None:
    rendered = build_inputs(world.session, world.candidate, at=NOW).as_prompt_inputs()

    assert rendered["approved_claims"] == f"{world.claim.claim_key}: {CLAIM_TEXT}"
    assert rendered["evidence"].startswith(str(world.evidence.id))


# --- validation and audit -------------------------------------------------------------------------


def test_output_that_never_validates_escalates(world: World) -> None:
    with pytest.raises(Escalated):
        world.draft(Scripted("not json"))

    assert world.session.execute(select(MessageRevision)).scalars().all() == []


def test_an_over_long_personalization_is_refused(world: World) -> None:
    """The cap is a guard against an essay a reviewer then has to read in full."""
    with pytest.raises(Escalated):
        world.draft(Scripted(world.output(personalization="S" * 5000)))


def test_an_extra_output_field_is_refused(world: World) -> None:
    """`extra="forbid"`: a `body` smuggled in as an unexpected key must not be accepted."""
    with pytest.raises(Escalated):
        world.draft(Scripted({**world.output(), "body": "SYNTHETIC unapproved product sentence"}))


def test_the_draft_is_audited_without_the_message_content(world: World) -> None:
    """§15.5: counts and identifiers. Subject and body are on the revision, not in the trail."""
    world.draft(Scripted(world.output(personalization="SYNTHETIC: must not be logged.")))

    event = world.session.execute(
        select(AuditEvent).where(AuditEvent.action == "message_revision.drafted")
    ).scalar_one()
    serialized = str(event.payload)
    assert "must not be logged" not in serialized
    assert event.payload["claims_cited"] == 1
    assert event.payload["template"] == "initial_outreach.txt"


def test_the_draft_prompt_and_schema_are_registered(world: World) -> None:
    assert world.prompt.task_name == "draft"
    assert world.schema.key == DRAFT_KEY
