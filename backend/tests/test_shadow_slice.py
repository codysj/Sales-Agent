"""The Stage 1 shadow slice, end to end (T-058a; §19.6 Stage 1 exit, §24 item 5, §8.3, §3.5).

§24 item 5 names the slice exactly: import candidate, create campaign membership, apply
eligibility, store evidence, qualify and classify, draft from approved claims, show review,
**stop before external send**. This module runs that, once, from an empty migrated database to
at least one `review_pending` revision per campaign, and then proves what did *not* happen.

Three things make it worth more than the sum of the per-module tests it duplicates:

* **It composes the real entry points**, in §8.3 order, with no test double between them except
  the two Stage 1 fakes the gate itself names — a fixture source adapter and the deterministic
  fake model. Every per-module test builds its own small world; this one proves the modules
  agree about the world they hand each other.
* **The network guard is the zero-external-write proof.** It patches `socket.socket.connect`,
  not an HTTP client, so it also covers `smtplib`, a raw socket, and any provider SDK that
  brings its own transport. Nothing but the test database may be reached, and the slice runs
  under it for its whole length.
* **It stops where the specification says to stop.** The last assertions are about absence: no
  send command, no send attempt, no outbox row, no approval. A slice that produced a message and
  then sent it would pass every module test in this repository and violate the one invariant
  Stage 1 exists to establish.

What it deliberately does not do is run through the job worker — no domain module registers a
pipeline job type yet, and building those is `T-058b`. The exit-evidence record and the **G-02**
gate change are `T-058c`. This module owns criteria 1 to 3 only.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor, record_audit_event
from app.audit_and_operations.versioning import ModelConfigVersion, content_hash
from app.campaigns import jobs as campaign_jobs
from app.campaigns.approval import approve_candidate
from app.campaigns.candidate import CampaignCandidate
from app.campaigns.jobs import MEMBERSHIP_JOB_TYPE
from app.campaigns.models import Campaign
from app.core.lifecycles import CampaignCandidateState, MessageRevisionState
from app.core.settings import AppEnv, ModelProvider, Settings
from app.drafts_and_approvals import jobs as draft_jobs
from app.drafts_and_approvals.jobs import DEFAULT_MODEL_CONFIG_KEY as DRAFT_CONFIG_KEY
from app.drafts_and_approvals.models import MessageDraft, MessageRevision
from app.fixtures import PROSPECTS_CSV
from app.fixtures.synthetic import seed_synthetic
from app.intake import enqueue_memberships_for_import
from app.jobs_and_outbox.models import Job, JobState
from app.jobs_and_outbox.queue import enqueue, lease_jobs
from app.jobs_and_outbox.registry import registry as job_registry
from app.jobs_and_outbox.runner import execute
from app.model_gateway.models import ModelRun
from app.model_gateway.prompts import register_prompt_versions
from app.model_gateway.providers.fake import FakeModelAdapter
from app.model_gateway.registry import reset_fake_adapter_factory, set_fake_adapter_factory
from app.model_gateway.schemas import register_schema_versions
from app.products_and_claims.models import Product
from app.prospects.imports import import_csv
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)
from app.qualification import jobs as qualification_jobs
from app.qualification.jobs import DEFAULT_MODEL_CONFIG_KEY as QUALIFY_CONFIG_KEY
from app.qualification.models import QualificationRun
from app.research_and_evidence import jobs as research_jobs
from app.research_and_evidence.adapters.fixture import FixtureSourceAdapter
from app.research_and_evidence.adapters.registry import (
    FIXTURE_ADAPTER_NAME,
    register_source_adapter,
    unregister_source_adapter,
)
from app.research_and_evidence.models import EvidenceSnapshot
from tests.factories import NOW

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND / "app" / "fixtures"
SOURCE_DOCUMENTS = FIXTURES / "source_documents"
QUALIFICATION_OUTPUTS = FIXTURES / "model_outputs" / "slice_qualification"
#: Keyed by the campaign *name*, because that is what a draft prompt carries — the slug never
#: reaches the model. Seeded by `app/fixtures/synthetic.py`.
DRAFT_OUTPUTS_BY_CAMPAIGN_NAME = {
    "SYNTHETIC-Sodium Battery Campaign": FIXTURES / "model_outputs" / "slice_draft_sodium",
    "SYNTHETIC-DC Fast Charging Campaign": FIXTURES / "model_outputs" / "slice_draft_charging",
}

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
TEST_SETTINGS = Settings(app_env=AppEnv.TEST)

#: The seeded campaigns, in the order §24 item 5 would run them. Both must reach a draft: the
#: whole point of ADR-012 is that two campaigns stay independent, and a slice that only proved
#: one would not have exercised that.
CAMPAIGNS = ("synthetic-sodium-battery", "synthetic-dc-fast-charging")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-shadow-slice")


class SliceResult:
    """What one run of the slice produced, read back from the database.

    Populated by querying after the worker has run, not accumulated while calling things. That is
    the point of the rewrite: the direct composition could only report what it had itself done,
    so an assertion about it was partly an assertion about the harness. These are facts about the
    system, gathered the way a reviewer would gather them.
    """

    def __init__(self) -> None:
        self.jobs_before_approval = 0
        self.jobs_after_approval = 0
        self.candidates: list[uuid.UUID] = []
        self.eligible: list[uuid.UUID] = []
        self.evidence: dict[uuid.UUID, int] = {}
        self.qualified: list[uuid.UUID] = []
        self.revisions: dict[str, list[uuid.UUID]] = {slug: [] for slug in CAMPAIGNS}
        self.correlation_ids: dict[uuid.UUID, str] = {}

    def observe(self, session: Session) -> None:
        """Read the run's outcome out of the database."""
        for candidate in session.execute(select(CampaignCandidate)).scalars().all():
            self.candidates.append(candidate.id)
            if candidate.state is not CampaignCandidateState.INELIGIBLE:
                self.eligible.append(candidate.id)
            self.evidence[candidate.id] = session.execute(
                select(func.count())
                .select_from(EvidenceSnapshot)
                .where(EvidenceSnapshot.candidate_id == candidate.id)
            ).scalar_one()
            correlation = session.execute(
                select(AuditEvent.correlation_id)
                .where(AuditEvent.entity_id == str(candidate.id))
                .limit(1)
            ).scalar_one_or_none()
            if correlation:
                self.correlation_ids[candidate.id] = correlation

        self.qualified = list(
            session.execute(select(QualificationRun.candidate_id)).scalars().all()
        )

        for revision, slug in session.execute(
            select(MessageRevision.id, Campaign.slug)
            .join(MessageDraft, MessageRevision.draft_id == MessageDraft.id)
            .join(CampaignCandidate, MessageDraft.candidate_id == CampaignCandidate.id)
            .join(Campaign, CampaignCandidate.campaign_id == Campaign.id)
        ).all():
            self.revisions[slug].append(revision)


class TaskRoutingFake:
    """Serves the fixture set belonging to the task — and campaign — the prompt came from.

    `FakeModelAdapter` allows one `match: "default"` per directory and a default answers *any*
    prompt, so one directory cannot hold both a qualification and a draft expectation, and the
    two campaigns cite different claim keys. Routing on markers the prompt already carries keeps
    each expectation in its own reviewable directory. Test-only: production installs one adapter
    for one configured task.
    """

    model_name = "deterministic-fake"

    def _directory_for(self, prompt: str) -> Path:
        if "SYNTHETIC-PROMPT draft" not in prompt:
            return QUALIFICATION_OUTPUTS
        for name, directory in DRAFT_OUTPUTS_BY_CAMPAIGN_NAME.items():
            if name in prompt:
                return directory
        raise AssertionError("a draft prompt named no campaign this fixture set knows")

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> Any:
        return FakeModelAdapter(directory=self._directory_for(prompt)).complete(
            prompt=prompt, parameters=parameters
        )


def _register_versions(session: Session) -> None:
    """The prompt, schema, and model-config versions the job handlers resolve for themselves.

    Handlers look versions up rather than taking them as arguments (§7.2 "validate policy and
    input version", §14.5), so the slice registers them and never passes an ID anywhere.
    """
    register_prompt_versions(session, created_by="operator-1", at=NOW)
    register_schema_versions(session, created_by="operator-1", at=NOW)
    for key in (QUALIFY_CONFIG_KEY, DRAFT_CONFIG_KEY):
        session.add(
            ModelConfigVersion(
                key=key,
                version=1,
                content_hash=content_hash(key),
                effective_from=NOW,
                created_by="operator-1",
                provider=ModelProvider.FAKE,
                model_name="deterministic-fake",
                parameters={"temperature": 0},
            )
        )
    session.flush()


def _start_campaigns(session: Session) -> None:
    """Seeded campaigns are paused (`T-015`), and `create_memberships` gives a paused campaign no
    candidates (§17.6). Starting one is a deliberate operator act, so the slice performs it
    explicitly and audits it rather than seeding them already running — which would have quietly
    removed the control the pause exists to provide."""
    for slug in CAMPAIGNS:
        campaign = session.execute(select(Campaign).where(Campaign.slug == slug)).scalar_one()
        campaign.paused = False
        record_audit_event(
            session,
            actor=OPERATOR,
            action="campaign.resumed",
            entity_type="campaign",
            entity_id=campaign.id,
            policy_decision="shadow-slice:operator started the campaign",
            correlation_id="corr-shadow-slice",
        )
    session.flush()


def drain(session: Session, limit: int = 400) -> int:
    """Run every runnable job until none is left. Returns how many ran.

    `runner.execute` is the §7.2 cycle; `run_once` only adds the leasing loop and a `commit` that
    would defeat the rollback `db_session` depends on. The bound is a runaway guard: a chain that
    enqueued itself would otherwise hang the suite rather than fail it.
    """
    for ran in range(limit):
        leased = lease_jobs(session, worker_id="shadow-slice-worker", limit=1)
        if not leased:
            return ran
        execute(session, leased[0])
    raise AssertionError(f"more than {limit} jobs ran; the chain does not terminate")


def run_slice(session: Session) -> SliceResult:
    """§24 item 5, driven by the worker, on the seeded synthetic world. Commits nothing.

    The slice does three things and waits twice. It seeds the world and starts the campaigns; it
    imports the CSV and enqueues one membership job per row; it drains. Then it approves every
    candidate that reached review and drains again. Everything between those points is the
    worker running registered job types — no pipeline entry point is called from here, which is
    what makes this evidence about the system rather than about the test.

    **Import is not a job** (`T-058b1`): an operator uploading a CSV is a request, not background
    work, so its outcome — including its rejections — stays in front of the person who uploaded
    it rather than in a queue they would have to go looking for.

    **The approval is explicit and separate**, because §8.3 step 9 creates a draft *on candidate
    approval*. The first drain ends with candidates in `review_pending` and nothing queued; only
    the approval produces drafting work. That gap is the shape of the pipeline, and a slice that
    ran straight through would have hidden it.
    """
    result = SliceResult()

    seed_synthetic(session, settings=TEST_SETTINGS, at=NOW)
    _start_campaigns(session)
    _register_versions(session)

    # --- §8.3 step 1: the operator's import ------------------------------------------------------

    imported = import_csv(
        session, content=PROSPECTS_CSV.read_bytes(), source_name="prospects.csv", actor=OPERATOR
    )
    assert not imported.already_imported

    # --- §8.3 step 2 onwards: one membership job per row, then the worker ------------------------

    # **The production function, not a copy** (`T-173`). This loop used to live here, and
    # `app/intake.py` was written from it when `T-169` found that nothing under `app/` turned an
    # import into membership work. Two copies of the same rule are how they stop agreeing, and the
    # one under test should be the one that runs. It still enqueues one job per (row, campaign)
    # with a per-candidate correlation ID; the ID's *shape* changed to
    # `import-<batch>-<row>-<slug>`, which nothing here asserts — the tests read IDs back off the
    # audit events and check only that they are distinct.
    enqueue_memberships_for_import(
        session,
        content=PROSPECTS_CSV.read_bytes(),
        batch_id=imported.batch.id,
        actor=OPERATOR,
    )

    result.jobs_before_approval = drain(session)

    # --- §8.3 step 9: the approval, and only then a draft ----------------------------------------

    reviewable = (
        session.execute(
            select(CampaignCandidate).where(
                CampaignCandidate.state == CampaignCandidateState.REVIEW_PENDING
            )
        )
        .scalars()
        .all()
    )
    assert reviewable, "no candidate reached review; the slice would prove nothing"

    for candidate in reviewable:
        recipient = (
            session.execute(
                select(ContactPoint).where(
                    ContactPoint.contact_id == candidate.contact_id,
                    ContactPoint.type == ContactPointType.EMAIL,
                    ContactPoint.verification_state == VerificationState.VERIFIED,
                )
            )
            .scalars()
            .first()
        )
        assert recipient is not None, "eligibility guarantees a verified email"
        # Threaded explicitly: `enqueue` would otherwise fall back to whatever correlation ID
        # is bound to this *test's* context, and the drafting half of the chain would sit under a
        # different ID from the half that produced the candidate.
        approve_candidate(
            session,
            candidate,
            recipient_contact_point_id=recipient.id,
            actor=OPERATOR,
            reason="SYNTHETIC: approved for the Stage 1 shadow slice",
            correlation_id=session.execute(
                select(AuditEvent.correlation_id)
                .where(AuditEvent.entity_id == str(candidate.id))
                .limit(1)
            ).scalar_one(),
        )

    result.jobs_after_approval = drain(session)
    result.observe(session)
    return result


@pytest.fixture
def stage_one_fakes() -> Iterator[None]:
    """Install the two Stage 1 fakes gate **G-02** names, then restore the empty defaults.

    The CLI's job in a running process, a test's here. Nothing under `app/` installs either,
    which is what keeps `app/fixtures/` out of every production import path (`T-040`) — and it
    means a process that installs nothing reaches no source and no fixture-keyed model at all.
    """
    register_source_adapter(
        FIXTURE_ADAPTER_NAME, lambda: FixtureSourceAdapter(directory=SOURCE_DOCUMENTS)
    )
    set_fake_adapter_factory(TaskRoutingFake)

    # Registered here because **`app/worker.py` registers nothing** — it imports the runner and
    # the dispatcher but calls no module's `register()`, so a running worker's registry is empty
    # and every job would retry on a fixed backoff until someone noticed. Filed as `T-148`;
    # fixing it is a code change, which this task's scope excludes. When it lands, these four
    # lines become the worker's own wiring and this fixture stops needing them.
    preexisting = dict(job_registry._types)
    for module in (campaign_jobs, qualification_jobs, research_jobs, draft_jobs):
        module.register(job_registry)
    try:
        yield
    finally:
        job_registry._types.clear()
        job_registry._types.update(preexisting)
        unregister_source_adapter(FIXTURE_ADAPTER_NAME)
        reset_fake_adapter_factory()


@pytest.fixture
def slice_result(db_session: Session, no_network: None, stage_one_fakes: None) -> SliceResult:
    """The slice, run once under the network guard, for the assertions below to inspect."""
    return run_slice(db_session)


# --- criterion 1: empty database in, review-ready revision per campaign out -----------------------


def test_the_database_starts_empty(db_session: Session) -> None:
    """The precondition criterion 1 names. Asserted, not assumed."""
    for model in (Product, Campaign, Account, CampaignCandidate, MessageRevision):
        count = db_session.execute(select(func.count()).select_from(model)).scalar_one()
        assert count == 0, f"{model.__name__} is not empty at the start of the slice"


def test_each_campaign_reaches_at_least_one_review_pending_revision(
    db_session: Session, slice_result: SliceResult
) -> None:
    for slug in CAMPAIGNS:
        assert slice_result.revisions[slug], f"{slug} produced no revision"

    states = db_session.execute(
        select(MessageRevision.state, func.count()).group_by(MessageRevision.state)
    ).all()

    assert dict(states) == {
        MessageRevisionState.REVIEW_PENDING: sum(
            len(ids) for ids in slice_result.revisions.values()
        )
    }, "every revision the slice produced must be review-ready, and nothing else may exist"


def test_the_two_campaigns_produced_independent_revisions(slice_result: SliceResult) -> None:
    """ADR-012: two campaigns, two judgements. A shared revision would be a shared decision."""
    sodium = set(slice_result.revisions["synthetic-sodium-battery"])
    charging = set(slice_result.revisions["synthetic-dc-fast-charging"])

    assert sodium and charging
    assert not sodium & charging


def test_the_slice_refused_more_candidates_than_it_advanced(slice_result: SliceResult) -> None:
    """The corpus is mostly *refusal* cases (`T-041`), so a slice that advanced everything is
    a slice whose eligibility gate did nothing."""
    assert len(slice_result.eligible) < len(slice_result.candidates)
    assert slice_result.eligible, "no candidate passed; the fixture world would be unusable"


# --- criterion 3: every intermediate entity, and one audit chain per candidate --------------------


def test_every_intermediate_entity_exists(db_session: Session, slice_result: SliceResult) -> None:
    """§8.3's steps each leave a row. A missing one means a step was skipped, not that it passed."""
    counts = {
        model.__name__: db_session.execute(select(func.count()).select_from(model)).scalar_one()
        for model in (
            Product,
            Campaign,
            Account,
            Contact,
            ContactPoint,
            CampaignCandidate,
            EvidenceSnapshot,
            ModelRun,
            QualificationRun,
            MessageDraft,
            MessageRevision,
        )
    }

    for name, count in counts.items():
        assert count > 0, f"the slice produced no {name}"

    assert counts["QualificationRun"] == len(slice_result.qualified)
    assert counts["MessageRevision"] == sum(len(ids) for ids in slice_result.revisions.values())


def test_each_advanced_candidate_has_one_complete_audit_chain(
    db_session: Session, slice_result: SliceResult
) -> None:
    """One correlation ID, every consequential step of that candidate under it (§3.5)."""
    for candidate_id in slice_result.qualified:
        correlation_id = slice_result.correlation_ids[candidate_id]
        actions = set(
            db_session.execute(
                select(AuditEvent.action).where(AuditEvent.correlation_id == correlation_id)
            )
            .scalars()
            .all()
        )

        assert actions, f"candidate {candidate_id} produced no audit event"
        # The state changes a reviewer must be able to reconstruct: the candidate became
        # eligible, evidence was captured, and a revision was drafted and then validated.
        assert any("campaign_candidate" in action for action in actions), actions
        assert any("evidence" in action for action in actions), actions
        assert any("revision" in action or "draft" in action for action in actions), actions


#: Entity types whose events belong to one candidate's journey. A batch-level event (an import,
#: a seed) legitimately has no candidate to correlate to; a candidate-level one never does.
CANDIDATE_SCOPED_ENTITIES = (
    "campaign_candidate",
    "evidence_snapshot",
    "qualification_run",
    "message_draft",
    "message_revision",
)


def test_no_candidate_scoped_audit_event_is_missing_its_correlation_id(
    db_session: Session, slice_result: SliceResult
) -> None:
    """An event nobody can join to a candidate is an event nobody can review (§3.5)."""
    orphans = db_session.execute(
        select(AuditEvent.entity_type, AuditEvent.action).where(
            AuditEvent.entity_type.in_(CANDIDATE_SCOPED_ENTITIES),
            AuditEvent.correlation_id.is_(None),
        )
    ).all()

    assert orphans == [], f"candidate-scoped events with no correlation ID: {orphans}"


def test_the_correlation_ids_are_distinct_per_candidate(slice_result: SliceResult) -> None:
    ids = [slice_result.correlation_ids[candidate] for candidate in slice_result.qualified]

    assert len(set(ids)) == len(ids)


# --- the point of Stage 1: it stopped before the send --------------------------------------------


def test_nothing_was_queued_for_sending(db_session: Session, slice_result: SliceResult) -> None:
    """§24 item 5 ends at "show review; stop before external send". This is that assertion."""
    from app.jobs_and_outbox.outbox import OutboxEvent
    from app.outreach_and_replies.models import SendAttempt, SendCommand

    for model in (SendCommand, SendAttempt, OutboxEvent):
        count = db_session.execute(select(func.count()).select_from(model)).scalar_one()
        assert count == 0, f"the shadow slice produced {count} {model.__name__} row(s)"


def test_no_revision_was_approved(db_session: Session, slice_result: SliceResult) -> None:
    """Approval is the dashboard's (Stage 2), and no code path here may anticipate it."""
    from app.drafts_and_approvals.approval import Approval

    count = db_session.execute(select(func.count()).select_from(Approval)).scalar_one()

    assert count == 0


def test_every_model_run_used_the_fake_provider(
    db_session: Session, slice_result: SliceResult
) -> None:
    """Gate **G-03** is locked, so a run against anything else could not have been legitimate."""
    from app.core.settings import ModelProvider

    providers = set(db_session.execute(select(ModelRun.provider)).scalars().all())

    assert providers == {ModelProvider.FAKE}


def test_every_model_name_is_the_deterministic_fake(
    db_session: Session, slice_result: SliceResult
) -> None:
    names = set(db_session.execute(select(ModelRun.model_name)).scalars().all())

    assert names == {"deterministic-fake"}


# --- criterion 2: the network guard, and proof that it can fail ----------------------------------


def test_the_guard_blocks_an_outbound_connection(no_network: None) -> None:
    """The control for criterion 2. Without this the guard could be a no-op and read as a pass.

    A TEST-NET-1 address (RFC 5737, reserved for documentation) rather than a real host: the
    assertion is that the guard refuses *before* connecting, and it must hold whether or not
    the machine running it has a network at all.
    """
    import socket

    from tests.netguard import NetworkUsed

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as opened, pytest.raises(NetworkUsed):
        opened.connect(("192.0.2.1", 80))


def test_the_guard_blocks_create_connection(no_network: None) -> None:
    import socket

    from tests.netguard import NetworkUsed

    with pytest.raises(NetworkUsed):
        socket.create_connection(("192.0.2.1", 80), timeout=1)


def test_the_guard_blocks_connect_ex(no_network: None) -> None:
    """`connect_ex` returns an error code rather than raising, so a guard that only patched
    `connect` would let it through silently — which is the worst kind of hole."""
    import socket

    from tests.netguard import NetworkUsed

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as opened, pytest.raises(NetworkUsed):
        opened.connect_ex(("192.0.2.1", 80))


def test_the_guard_still_permits_the_test_database(db_session: Session, no_network: None) -> None:
    """A guard that blocked the database would make every slice assertion untestable."""
    assert db_session.execute(select(func.count()).select_from(Product)).scalar_one() == 0


def test_the_whole_slice_runs_under_the_guard(slice_result: SliceResult) -> None:
    """The `slice_result` fixture depends on `no_network`, so reaching here at all is the proof.

    Stated as its own test so the guarantee is named in the report rather than implied by a
    fixture dependency a reader has to notice.
    """
    assert slice_result.qualified


# --- determinism -------------------------------------------------------------------------------


def test_the_slice_is_deterministic(
    db_session: Session, no_network: None, stage_one_fakes: None
) -> None:
    """Two runs over the same fixtures produce the same shape.

    Not the same UUIDs — those are database-assigned — but the same counts and the same set of
    campaigns reaching review. A slice whose outcome moved between runs would make the Stage 1
    exit evidence (`T-058c`) meaningless.
    """
    first = run_slice(db_session)
    shape = {slug: len(ids) for slug, ids in first.revisions.items()}

    db_session.rollback()

    second = run_slice(db_session)

    assert {slug: len(ids) for slug, ids in second.revisions.items()} == shape
    assert len(second.eligible) == len(first.eligible)
    assert len(second.qualified) == len(first.qualified)


def test_the_evidence_captured_matches_the_fixture_documents(
    db_session: Session, slice_result: SliceResult
) -> None:
    """Evidence came from the fixture directory, not from anywhere else (`T-046`)."""
    from app.research_and_evidence.models import SourceType

    sources = set(db_session.execute(select(EvidenceSnapshot.source_type)).scalars().all())

    assert sources == {SourceType.SYNTHETIC_FIXTURE}


def test_some_candidate_has_evidence_and_the_slice_did_not_require_it(
    slice_result: SliceResult,
) -> None:
    """The fixture corpus only documents two accounts, so a slice that demanded evidence of
    every candidate would have stalled — and one that captured none would prove nothing."""
    assert any(count > 0 for count in slice_result.evidence.values())
    assert any(count == 0 for count in slice_result.evidence.values())


def test_every_revision_cites_at_least_one_approved_claim(
    db_session: Session, slice_result: SliceResult
) -> None:
    """GP-02 and §10.5: the message says nothing about the product that nobody approved."""
    revisions = db_session.execute(select(MessageRevision)).scalars().all()

    assert revisions
    for revision in revisions:
        assert revision.approved_claim_ids, f"revision {revision.id} cites no approved claim"


def test_no_revision_body_contains_a_claim_that_was_not_cited(
    db_session: Session, slice_result: SliceResult
) -> None:
    """The `T-055` grounding check already passed for each; asserted here across the whole run
    so a future change that weakened it shows up in the slice, not only in the unit test."""
    from app.products_and_claims.claim_models import ApprovedClaim

    for revision in db_session.execute(select(MessageRevision)).scalars().all():
        cited = (
            db_session.execute(
                select(ApprovedClaim).where(ApprovedClaim.id.in_(revision.approved_claim_ids))
            )
            .scalars()
            .all()
        )
        for claim in cited:
            assert claim.text in revision.body


def test_starting_the_campaigns_is_audited(db_session: Session, slice_result: SliceResult) -> None:
    """The act that made the slice possible must itself be reviewable (§3.5)."""
    events = (
        db_session.execute(select(AuditEvent).where(AuditEvent.action == "campaign.resumed"))
        .scalars()
        .all()
    )

    assert len(events) == len(CAMPAIGNS)
    for event in events:
        assert event.policy_decision
        assert event.correlation_id


def test_the_slice_left_the_import_batch_recorded(
    db_session: Session, slice_result: SliceResult
) -> None:
    """Provenance: the candidates trace back to a batch with a content hash (§9.5)."""
    from app.prospects.imports import ImportBatch

    batches = db_session.execute(select(ImportBatch)).scalars().all()

    assert len(batches) == 1
    assert batches[0].content_hash
    assert batches[0].rejected_count >= 0


def test_reimporting_the_same_bytes_is_a_noop(
    db_session: Session, slice_result: SliceResult
) -> None:
    """The slice is re-runnable, which `T-058b` will depend on when the worker replays a job."""
    again = import_csv(
        db_session,
        content=PROSPECTS_CSV.read_bytes(),
        source_name="prospects.csv",
        actor=OPERATOR,
    )

    assert again.already_imported


def test_the_ineligible_candidates_carry_their_reason(
    db_session: Session, slice_result: SliceResult
) -> None:
    """A refused candidate a reviewer cannot ask "why" about is a refusal nobody can audit."""
    ineligible = (
        db_session.execute(
            select(CampaignCandidate).where(
                CampaignCandidate.state == CampaignCandidateState.INELIGIBLE
            )
        )
        .scalars()
        .all()
    )

    assert ineligible, "the corpus contains refusal cases; none was refused"
    for candidate in ineligible:
        events = (
            db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == str(candidate.id),
                    AuditEvent.correlation_id == slice_result.correlation_ids.get(candidate.id, ""),
                )
            )
            .scalars()
            .all()
        )
        assert any(event.policy_decision for event in events), (
            f"candidate {candidate.id} was refused with no recorded policy decision"
        )


def test_the_evidence_is_not_stale_relative_to_the_run(
    db_session: Session, slice_result: SliceResult
) -> None:
    snapshots = db_session.execute(select(EvidenceSnapshot)).scalars().all()

    assert snapshots
    for snapshot in snapshots:
        # Against the wall clock, not `NOW`. A job handler takes no `at=` — it is running for
        # real, so its evidence is stamped when it ran. What still matters is that no snapshot
        # is dated in the future, which would make "current evidence" queries answer wrongly.
        assert snapshot.retrieved_at <= datetime.now(UTC) + timedelta(seconds=1)


# --- T-058b2b2b: the slice is driven by the worker, not by this file -----------------------------

#: Every pipeline entry point the direct composition used to call. `run_slice` must call none of
#: them: if it did, the slice would be evidence about the harness rather than about the system.
PIPELINE_ENTRY_POINTS = (
    "apply_eligibility",
    "capture_evidence",
    "qualify_candidate",
    "draft_message",
    "apply_validation",
    "create_memberships",
)


def test_the_slice_calls_no_pipeline_entry_point() -> None:
    """Criterion 1, asserted structurally rather than by reading the code.

    `import_csv` is deliberately absent from the list: an operator uploading a CSV is a request,
    not background work (`T-058b1`), so the slice performs it directly on purpose.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(run_slice))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    offenders = sorted(called & set(PIPELINE_ENTRY_POINTS))

    assert not offenders, f"the slice calls pipeline entry points directly: {offenders}"


def test_the_slice_module_imports_no_pipeline_entry_point() -> None:
    """The stronger form: it cannot call what it never imported."""
    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert not imported & set(PIPELINE_ENTRY_POINTS)


def test_every_pipeline_step_ran_as_a_job(db_session: Session, slice_result: SliceResult) -> None:
    """Each §8.3 step the slice performs left a `job` row of its own type."""
    ran = set(
        db_session.execute(select(Job.job_type).where(Job.state == JobState.SUCCEEDED))
        .scalars()
        .all()
    )

    assert ran == {
        "campaigns.create_membership",
        "qualification.apply_eligibility",
        "campaigns.start_research",
        "research.capture_evidence",
        "campaigns.complete_research",
        "qualification.qualify_candidate",
        "drafts.draft_message",
        "drafts.validate_revision",
    }


def test_no_job_died_or_is_still_queued(db_session: Session, slice_result: SliceResult) -> None:
    """A dead job is work an operator has to triage; a queued one is a chain that did not finish.
    The slice must end with neither."""
    leftover = db_session.execute(
        select(Job.job_type, Job.state, Job.last_error).where(
            Job.state.notin_([JobState.SUCCEEDED])
        )
    ).all()

    assert leftover == []


def test_the_worker_did_the_work_in_two_waves(slice_result: SliceResult) -> None:
    """The shape §8.3 requires: everything up to review runs unattended, and nothing past it
    runs until a person approves."""
    assert slice_result.jobs_before_approval > 0
    assert slice_result.jobs_after_approval > 0


def test_no_draft_exists_before_the_approval(
    db_session: Session, no_network: None, stage_one_fakes: None
) -> None:
    """The gap is the point. §8.3 step 9 creates a draft *on candidate approval*, so a slice that
    ran straight through would have hidden the one place a human is required.

    Run here by draining only the automatic half and stopping.
    """
    seed_synthetic(db_session, settings=TEST_SETTINGS, at=NOW)
    _start_campaigns(db_session)
    _register_versions(db_session)
    import_csv(
        db_session,
        content=PROSPECTS_CSV.read_bytes(),
        source_name="prospects.csv",
        actor=OPERATOR,
    )
    account = db_session.execute(
        select(Account).where(Account.domain == "alpha.example.com")
    ).scalar_one()
    contact = (
        db_session.execute(select(Contact).where(Contact.account_id == account.id))
        .scalars()
        .first()
    )
    assert contact is not None
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload={
            "account_id": str(account.id),
            "contact_id": str(contact.id),
            "campaign_slugs": ["synthetic-sodium-battery"],
        },
        actor=OPERATOR,
        correlation_id="corr-slice-approval-gap",
    )

    drain(db_session)

    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    assert candidate.state is CampaignCandidateState.REVIEW_PENDING
    assert db_session.execute(select(func.count()).select_from(MessageRevision)).scalar_one() == 0
    assert (
        db_session.execute(
            select(func.count()).select_from(Job).where(Job.state == JobState.QUEUED)
        ).scalar_one()
        == 0
    )
    # Counted in *any* state, not just `queued`, and not by looking for a revision: a drafting
    # job that was created and then failed would leave the queue empty and no revision behind,
    # and this assertion would pass while the chain had in fact reached step 9 without an
    # approval. The control that chained qualification into drafting passed this test until the
    # count moved here.
    drafting_jobs = db_session.execute(
        select(func.count()).select_from(Job).where(Job.job_type == "drafts.draft_message")
    ).scalar_one()
    assert drafting_jobs == 0, "the automatic chain reached step 9 without an approval"


def test_a_paused_campaign_still_produces_nothing_through_the_worker(
    db_session: Session, no_network: None, stage_one_fakes: None
) -> None:
    """`T-015` and §17.6, now proven against the job rather than against `create_memberships`.

    The seeded world is inert until an operator starts a campaign, and the job respects that —
    which is the version that matters, since the job is what production runs.
    """
    seed_synthetic(db_session, settings=TEST_SETTINGS, at=NOW)
    _register_versions(db_session)
    import_csv(
        db_session,
        content=PROSPECTS_CSV.read_bytes(),
        source_name="prospects.csv",
        actor=OPERATOR,
    )
    account = db_session.execute(select(Account)).scalars().first()
    assert account is not None

    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload={
            "account_id": str(account.id),
            "contact_id": None,
            "campaign_slugs": list(CAMPAIGNS),
        },
        actor=OPERATOR,
        correlation_id="corr-slice-paused",
    )
    drain(db_session)

    assert db_session.execute(select(func.count()).select_from(CampaignCandidate)).scalar_one() == 0
