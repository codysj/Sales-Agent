"""The pipeline as job types, run by the worker (T-058b1; §17.1, §7.2, §8.3 steps 2-4).

`T-058a` proved the path works by calling each module's entry point in order. This proves the
first two steps work the way production will run them: leased from the queue, executed inside
`runner.execute`, with the handler's writes, the job's new state, and the next job in one
transaction.

The three things worth testing here are not the happy path — `T-058a` and the per-module tests
already cover what the handlers do — but the properties the queue adds:

* **Ownership.** Both types are registered by the module that knows what a candidate is.
  `tests/test_module_boundaries.py` proves `jobs_and_outbox` did not learn anything about the
  domain; the assertion here is the other half, that the handlers exist where they should.
* **Replay.** A queue retries. A handler that is not idempotent turns a transient database error
  into a duplicate candidate or a dead-lettered job that had already succeeded, and neither
  failure is visible until it happens in production.
* **Chaining.** §7.2 says "commit state + audit + next job/outbox atomically". A membership job
  that created candidates but whose follow-on jobs were queued in a second transaction would
  lose them to any crash in between.

These tests use `lease_jobs` + `execute` rather than `run_once`, which commits — `db_session`
rolls its transaction back, and a commit inside it would defeat that. `execute` is the whole
§7.2 cycle; `run_once` only adds the leasing loop and the commit, and `tests/test_jobs.py`
covers those.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns import jobs as campaign_jobs
from app.campaigns.approval import ApprovalRefused, approve_candidate
from app.campaigns.candidate import CampaignCandidate, create_candidate, transition
from app.campaigns.jobs import (
    COMPLETE_RESEARCH_JOB_TYPE,
    MEMBERSHIP_JOB_TYPE,
    NEXT_JOB_TYPE,
    START_RESEARCH_JOB_TYPE,
    CandidatePayload,
    MembershipPayload,
    handle_membership,
)
from app.campaigns.models import Campaign
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import publish_policy_version
from app.core.lifecycles import CampaignCandidateState, MessageRevisionState
from app.core.settings import AppEnv, Settings
from app.drafts_and_approvals import jobs as draft_jobs
from app.drafts_and_approvals.jobs import (
    DRAFT_JOB_TYPE,
    VALIDATE_JOB_TYPE,
    DraftPayload,
    ValidatePayload,
)
from app.drafts_and_approvals.models import MessageRevision
from app.jobs_and_outbox.models import Job, JobState
from app.jobs_and_outbox.queue import enqueue, lease_jobs
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.registry import registry as default_registry
from app.jobs_and_outbox.retry import PermanentFailure
from app.jobs_and_outbox.runner import execute
from app.model_gateway.models import ModelRun
from app.products_and_claims.models import Product, ProductStatusVersion, ReadinessCategory
from app.products_and_claims.status import next_version_number
from app.prospects.models import Account, Contact, ContactPoint, ContactPointType, VerificationState
from app.qualification import jobs as qualification_jobs
from app.qualification.jobs import (
    ELIGIBILITY_JOB_TYPE,
    QUALIFY_JOB_TYPE,
    EligibilityPayload,
    QualifyPayload,
    handle_eligibility,
)
from app.qualification.models import QualificationRun
from app.research_and_evidence import jobs as research_jobs
from app.research_and_evidence.adapters.fixture import FixtureSourceAdapter
from app.research_and_evidence.adapters.registry import (
    FIXTURE_ADAPTER_NAME,
    SourceAdapterNotAvailable,
    build_source_adapter,
    register_source_adapter,
    unregister_source_adapter,
)
from app.research_and_evidence.capture import CaptureRefused, capture_evidence
from app.research_and_evidence.jobs import (
    CAPTURE_JOB_TYPE,
    RECAPTURE_JOB_TYPE,
    CapturePayload,
    RecapturePayload,
    handle_capture,
    handle_recapture,
)
from app.research_and_evidence.models import EvidenceSnapshot
from tests.factories import NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")

SODIUM = "synthetic-sodium-pipeline"

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "fixtures"
SOURCE_DOCUMENTS = FIXTURES / "source_documents"
QUALIFICATION_OUTPUTS = FIXTURES / "model_outputs" / "slice_qualification"
DRAFT_OUTPUTS = FIXTURES / "model_outputs" / "slice_draft_sodium"

#: The one account the fixture corpus actually documents.
DOCUMENTED_DOMAIN = "alpha.example.com"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-pipeline-jobs")


@pytest.fixture
def registry() -> Iterator[JobRegistry]:
    """The process-wide registry, populated the way a worker populates it, then cleared.

    Not a private `JobRegistry()` like `tests/test_jobs.py` uses, and the reason is the chain:
    `handle_membership` enqueues the next job through `queue.enqueue`, which resolves the payload
    model from the *default* registry. A handler cannot be handed a test registry — `JobHandler`
    is `(session, payload, *, job_id)` — so a per-test registry would test a chain that could
    never link. Cleared afterwards so registrations do not leak between tests.
    """
    # Snapshot and restore rather than `clear()`: this is the process-wide registry, and
    # clearing it would discard whatever another module or test registered into it. There is no
    # `deregister`, and adding one to production code for a test's convenience is not worth it.
    preexisting = dict(default_registry._types)
    campaign_jobs.register(default_registry)
    qualification_jobs.register(default_registry)
    research_jobs.register(default_registry)
    draft_jobs.register(default_registry)
    try:
        yield default_registry
    finally:
        default_registry._types.clear()
        default_registry._types.update(preexisting)


class World:
    """One started campaign with a published policy, and one contactable prospect."""

    def __init__(self, session: Session) -> None:
        self.session = session

        self.product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
        session.add(self.product)
        session.flush()

        self.campaign = Campaign(
            slug=SODIUM,
            name="SYNTHETIC-Campaign",
            product_id=self.product.id,
            paused=False,
        )
        self.account = Account(
            domain=f"{uuid.uuid4().hex[:8]}.example.com",
            name="SYNTHETIC-Account",
            country_code="US",
        )
        session.add_all([self.campaign, self.account])
        session.flush()

        publish_policy_version(
            session,
            campaign_id=self.campaign.id,
            policy=CampaignPolicy(),
            approved_by="approver-1",
            approved_at=NOW,
        )

        # Readiness must be explicit before the product may be referenced at all (GP-12), so
        # a world without one produces `ineligible` for a reason that has nothing to do with the
        # prospect — which would make every chain assertion below test the wrong thing.
        session.add(
            ProductStatusVersion(
                product_id=self.product.id,
                version=next_version_number(session, self.product.id),
                readiness_category=ReadinessCategory.EVALUATION_OR_PILOT,
                summary="SYNTHETIC placeholder readiness.",
                approved_by="approver-1",
                approved_at=NOW,
                effective_from=NOW,
                expires_or_review_by=None,
            )
        )
        session.flush()

        self.contact = Contact(account_id=self.account.id, full_name="SYNTHETIC Person")
        session.add(self.contact)
        session.flush()
        session.add(
            ContactPoint(
                contact_id=self.contact.id,
                type=ContactPointType.EMAIL,
                value=f"{uuid.uuid4().hex[:8]}@{self.account.domain}",
                verification_state=VerificationState.VERIFIED,
            )
        )
        session.flush()

    def payload(self, **overrides: Any) -> MembershipPayload:
        values: dict[str, Any] = {
            "account_id": self.account.id,
            "contact_id": self.contact.id,
            "campaign_slugs": [SODIUM],
        }
        values.update(overrides)
        return MembershipPayload(**values)


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


class TaskRoutingFake:
    """A fake that serves the fixture set belonging to the task the prompt came from.

    `FakeModelAdapter` allows one `match: "default"` per directory, and a default answers *any*
    prompt — so a single directory holding both a qualification and a draft default is impossible,
    and one holding only the qualification default answers the *draft* prompt with
    qualification-shaped JSON. That is not a hypothetical: it is what happened, and it surfaced as
    a schema escalation two layers downstream rather than as "wrong fixture".

    Routing on the prompt's own first line keeps each task's expectations in its own reviewable
    directory. Test-only: production installs one adapter for one configured task at a time.
    """

    model_name = "deterministic-fake"

    def __init__(self, directories: dict[str, Path], default: Path) -> None:
        self.directories = directories
        self.default = default

    def _directory_for(self, prompt: str) -> Path:
        for marker, directory in self.directories.items():
            if marker in prompt:
                return directory
        return self.default

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> Any:
        from app.model_gateway.providers.fake import FakeModelAdapter

        adapter = FakeModelAdapter(directory=self._directory_for(prompt))
        return adapter.complete(prompt=prompt, parameters=parameters)


@pytest.fixture
def fake_model() -> Iterator[None]:
    """Install `T-052`'s fixture-keyed fake for the duration, then restore the echo default.

    The CLI's job in a running process, a test's here. Nothing under `app/` does it, which is
    what keeps `app/fixtures/` out of every production import path (`T-040`).
    """
    from app.model_gateway.registry import reset_fake_adapter_factory, set_fake_adapter_factory

    set_fake_adapter_factory(
        lambda: TaskRoutingFake(
            {"SYNTHETIC-PROMPT draft": DRAFT_OUTPUTS},
            default=QUALIFICATION_OUTPUTS,
        )
    )
    try:
        yield
    finally:
        reset_fake_adapter_factory()


@pytest.fixture
def qualifiable_world(db_session: Session, documented_world: World, fake_model: None) -> World:
    """A documented world with the prompt, schema, and model-config versions qualification needs."""
    from app.audit_and_operations.versioning import ModelConfigVersion, content_hash
    from app.core.settings import ModelProvider
    from app.model_gateway.prompts import register_prompt_versions
    from app.model_gateway.schemas import register_schema_versions
    from app.qualification.jobs import DEFAULT_MODEL_CONFIG_KEY

    register_prompt_versions(db_session, created_by="operator-1", at=NOW)
    register_schema_versions(db_session, created_by="operator-1", at=NOW)
    db_session.add(
        ModelConfigVersion(
            key=DEFAULT_MODEL_CONFIG_KEY,
            version=1,
            content_hash=content_hash("qualification-config"),
            effective_from=NOW,
            created_by="operator-1",
            provider=ModelProvider.FAKE,
            model_name="deterministic-fake",
            parameters={"temperature": 0},
        )
    )
    db_session.flush()
    return documented_world


@pytest.fixture
def draftable_world(db_session: Session, qualifiable_world: World) -> World:
    """A qualifiable world with the claim and versions drafting needs."""
    from datetime import timedelta

    from app.audit_and_operations.versioning import ModelConfigVersion, content_hash
    from app.core.settings import ModelProvider
    from app.drafts_and_approvals.jobs import DEFAULT_MODEL_CONFIG_KEY as DRAFT_CONFIG_KEY
    from app.products_and_claims.claim_models import ApprovedClaim, ApprovedClaimCampaign

    claim = ApprovedClaim(
        claim_key="SYNTHETIC-CLAIM-sodium-readiness",
        version=1,
        product_id=qualifiable_world.product.id,
        text="SYNTHETIC EXAMPLE CLAIM — offered for evaluation deployments. Approved by nobody.",
        approved_by="approver-1",
        approved_at=NOW - timedelta(days=1),
        effective_from=NOW - timedelta(days=1),
        expires_or_review_by=NOW + timedelta(days=90),
    )
    db_session.add(claim)
    db_session.flush()
    db_session.add(
        ApprovedClaimCampaign(claim_id=claim.id, campaign_id=qualifiable_world.campaign.id)
    )
    db_session.add(
        ModelConfigVersion(
            key=DRAFT_CONFIG_KEY,
            version=1,
            content_hash=content_hash("draft-config"),
            effective_from=NOW,
            created_by="operator-1",
            provider=ModelProvider.FAKE,
            model_name="deterministic-fake",
            parameters={"temperature": 0},
        )
    )
    db_session.flush()
    return qualifiable_world


@pytest.fixture
def documented_world(db_session: Session) -> World:
    """A world whose account is one the fixture corpus actually has documents for."""
    built = World(db_session)
    built.account.domain = DOCUMENTED_DOMAIN
    db_session.flush()
    return built


@pytest.fixture
def fixture_adapter() -> Iterator[None]:
    """Register the fixture source adapter, then restore the empty default.

    This is the CLI's job in a running process and a test's here. Nothing under `app/` does it,
    which is what keeps `app/fixtures/` out of every production import path (`T-040`).
    """
    register_source_adapter(
        FIXTURE_ADAPTER_NAME, lambda: FixtureSourceAdapter(directory=SOURCE_DOCUMENTS)
    )
    try:
        yield
    finally:
        unregister_source_adapter(FIXTURE_ADAPTER_NAME)


def queued(session: Session, job_type: str) -> list[Job]:
    return list(
        session.execute(select(Job).where(Job.job_type == job_type, Job.state == JobState.QUEUED))
        .scalars()
        .all()
    )


def drain(
    session: Session,
    registry: JobRegistry,
    *,
    limit: int = 50,
    stop_before: str | None = None,
) -> int:
    """Run every runnable job until none is left. Returns how many ran.

    The worker's loop without `run_once`'s commit, for the reason in the module docstring. The
    bound is a runaway guard: a chain that enqueued itself would otherwise hang the suite rather
    than fail it. ``stop_before`` leaves jobs of that type queued, for a test that wants to
    inspect the chain part-way rather than at its end — the leased job is released back to
    `queued` so it stays visible.
    """
    for ran in range(limit):
        leased = lease_jobs(session, worker_id="worker-test", limit=1)
        if not leased:
            return ran
        if stop_before is not None and leased[0].job_type == stop_before:
            release(session, leased[0])
            return ran
        execute(session, leased[0], registry=registry)
    raise AssertionError(f"more than {limit} jobs ran; the chain does not terminate")


def release(session: Session, job: Job) -> None:
    """Put a leased job back on the queue without spending an attempt on it.

    `lease_jobs` increments `attempt_count`, so this walks it back too: a test that peeked at the
    queue must not leave a job that looks like it had already failed once.
    """
    job.state = JobState.QUEUED
    # Both, or the `job` table's check constraint refuses the row: a non-leased job must carry
    # neither a holder nor a lease expiry.
    job.leased_by = None
    job.lease_expires_at = None
    job.attempt_count -= 1
    session.flush()


# --- criterion 1: each step is owned by its domain module ----------------------------------------


def test_both_job_types_are_registered_by_their_owning_module(registry: JobRegistry) -> None:
    """Asserted by handler identity, not by the registry's contents.

    Criterion 1 is about *who owns* each step. Comparing the whole name list would instead assert
    what else happens to be registered, which is another test's business and made this fail in
    the full suite while passing alone.
    """
    assert registry.get(MEMBERSHIP_JOB_TYPE).handler is campaign_jobs.handle_membership
    assert registry.get(ELIGIBILITY_JOB_TYPE).handler is qualification_jobs.handle_eligibility


def test_the_job_types_are_namespaced_to_their_module(registry: JobRegistry) -> None:
    """A name tells a reader which module to look in. `jobs_and_outbox` owns neither."""
    assert MEMBERSHIP_JOB_TYPE.startswith("campaigns.")
    assert ELIGIBILITY_JOB_TYPE.startswith("qualification.")


def test_the_chained_job_name_matches_the_type_it_names() -> None:
    """`campaigns.jobs` names the next step as a string to avoid an import cycle.

    That string and the constant it stands for must not drift apart, and nothing but this test
    would notice if they did.
    """
    assert NEXT_JOB_TYPE == ELIGIBILITY_JOB_TYPE


def test_registering_twice_is_a_no_op(registry: JobRegistry) -> None:
    """Two callers registering the same module must not fight over the name.

    `JobRegistry.register` raises on a duplicate name, so each module's `register()` guards with
    `is_registered`. Asserted on the two names this task owns rather than on the registry's size,
    which is another test's business.
    """
    campaign_jobs.register(registry)
    qualification_jobs.register(registry)

    assert registry.get(MEMBERSHIP_JOB_TYPE).handler is campaign_jobs.handle_membership
    assert registry.get(ELIGIBILITY_JOB_TYPE).handler is qualification_jobs.handle_eligibility


def test_neither_job_type_is_consequential(registry: JobRegistry) -> None:
    """§17.6: a pause stops work going *out*. Neither of these produces an external effect, and
    a pause that stopped candidates being refused would be the wrong way round."""
    assert registry.consequential_names() == []


def test_both_types_declare_a_retry_policy(registry: JobRegistry) -> None:
    """§17.1 wants it explicit per job type; the registry has no default to fall back on."""
    for name in (MEMBERSHIP_JOB_TYPE, ELIGIBILITY_JOB_TYPE):
        assert registry.get(name).retry_policy.max_attempts > 1


# --- criterion 3: the chain, in one transaction --------------------------------------------------


def test_a_membership_job_creates_the_candidate(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    job = enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=world.payload(),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-a", limit=1)

    assert execute(db_session, leased[0], registry=registry) is True
    assert job.state is JobState.SUCCEEDED

    candidates = db_session.execute(select(CampaignCandidate)).scalars().all()
    assert len(candidates) == 1
    assert candidates[0].campaign_id == world.campaign.id


def test_a_membership_job_queues_one_eligibility_job_per_candidate(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """§7.2: the next job is committed with the state change, not after it."""
    enqueue(db_session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR)
    leased = lease_jobs(db_session, worker_id="worker-a", limit=1)

    execute(db_session, leased[0], registry=registry)

    follow_on = queued(db_session, ELIGIBILITY_JOB_TYPE)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    assert len(follow_on) == 1
    assert follow_on[0].payload["candidate_id"] == str(candidate.id)


def test_the_follow_on_job_inherits_the_correlation_id(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """A chain nobody can join end to end is a chain nobody can review (§17.5, §3.5)."""
    first = enqueue(
        db_session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR
    )
    leased = lease_jobs(db_session, worker_id="worker-a", limit=1)

    execute(db_session, leased[0], registry=registry)

    assert queued(db_session, ELIGIBILITY_JOB_TYPE)[0].correlation_id == first.correlation_id


def test_the_whole_chain_runs_to_a_decided_candidate(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """Criterion 3: enqueue one job, let the worker run, end with an evaluated candidate.

    Stopped before `campaigns.start_research`, the link `T-147` added — this one is about the
    membership-to-eligibility pair and should keep failing for that reason alone if it breaks.
    """
    enqueue(db_session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR)

    ran = drain(db_session, registry, stop_before=START_RESEARCH_JOB_TYPE)

    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    assert ran == 2, "one membership job and one eligibility job"
    assert candidate.state is CampaignCandidateState.ELIGIBLE


def test_a_refused_candidate_also_terminates_the_chain(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """An ineligible outcome is a completed chain, not a failed one."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        # No contact: §8.1 allows an account-level membership and eligibility then refuses it.
        payload=world.payload(contact_id=None),
        actor=OPERATOR,
    )

    drain(db_session, registry)

    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    assert candidate.state is CampaignCandidateState.INELIGIBLE
    assert not queued(db_session, ELIGIBILITY_JOB_TYPE)


def test_two_campaigns_produce_two_candidates_and_two_eligibility_jobs(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    second = Campaign(
        slug="synthetic-second-pipeline",
        name="SYNTHETIC-Second",
        product_id=world.product.id,
        paused=False,
    )
    db_session.add(second)
    db_session.flush()
    publish_policy_version(
        db_session,
        campaign_id=second.id,
        policy=CampaignPolicy(),
        approved_by="approver-1",
        approved_at=NOW,
    )

    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=world.payload(campaign_slugs=[SODIUM, second.slug]),
        actor=OPERATOR,
    )
    drain(db_session, registry)

    candidates = db_session.execute(select(CampaignCandidate)).scalars().all()
    assert len(candidates) == 2
    assert {candidate.campaign_id for candidate in candidates} == {world.campaign.id, second.id}


# --- criterion 2: replay changes nothing ---------------------------------------------------------


def test_replaying_a_membership_job_creates_no_second_candidate(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    handle_membership(db_session, world.payload(), job_id=uuid.uuid4())
    before = db_session.execute(select(func.count()).select_from(CampaignCandidate)).scalar_one()

    handle_membership(db_session, world.payload(), job_id=uuid.uuid4())

    after = db_session.execute(select(func.count()).select_from(CampaignCandidate)).scalar_one()
    assert before == after == 1


def test_replaying_a_membership_job_writes_no_second_candidate_audit_event(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    handle_membership(db_session, world.payload(), job_id=uuid.uuid4())
    before = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_type == "campaign_candidate")
    ).scalar_one()

    handle_membership(db_session, world.payload(), job_id=uuid.uuid4())

    after = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_type == "campaign_candidate")
    ).scalar_one()
    assert before == after


def test_replaying_a_membership_job_still_queues_the_follow_on(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """Deliberate: the replay enqueues for existing candidates too.

    A crash between the membership write and the enqueue would otherwise leave a candidate with
    no follow-on job and nothing to notice it. A duplicate eligibility job is harmless because
    that job is itself idempotent, which is the trade this makes on purpose.
    """
    handle_membership(db_session, world.payload(), job_id=uuid.uuid4())
    handle_membership(db_session, world.payload(), job_id=uuid.uuid4())

    assert len(queued(db_session, ELIGIBILITY_JOB_TYPE)) == 2


def test_replaying_an_eligibility_job_does_not_transition_twice(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """The guard that matters: §8.2 has no `eligible -> eligible` edge (`T-010`).

    Without it a replay would raise an illegal transition, be classified permanent, and
    dead-letter a job that had already succeeded.
    """
    enqueue(db_session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR)
    drain(db_session, registry, stop_before=START_RESEARCH_JOB_TYPE)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    before = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_id == str(candidate.id))
    ).scalar_one()

    handle_eligibility(
        db_session, EligibilityPayload(candidate_id=candidate.id), job_id=uuid.uuid4()
    )

    after = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_id == str(candidate.id))
    ).scalar_one()
    assert candidate.state is CampaignCandidateState.ELIGIBLE
    assert before == after, "a replay wrote a second audit event"


def test_a_replayed_eligibility_job_succeeds_rather_than_failing(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """The outcome a queue needs: replay is a success, so the job leaves the queue."""
    enqueue(db_session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR)
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()

    replay = enqueue(
        db_session,
        job_type=ELIGIBILITY_JOB_TYPE,
        payload=EligibilityPayload(candidate_id=candidate.id),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-b", limit=1)

    assert execute(db_session, leased[0], registry=registry) is True
    assert replay.state is JobState.SUCCEEDED


@pytest.mark.parametrize(
    "state",
    [
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.INELIGIBLE,
    ],
)
def test_an_already_decided_candidate_is_left_alone(
    db_session: Session, world: World, registry: JobRegistry, state: CampaignCandidateState
) -> None:
    """`imported` is the only state this job has work to do in."""
    handle_membership(db_session, world.payload(), job_id=uuid.uuid4())
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    transition(db_session, candidate, state, actor=OPERATOR, reason="SYNTHETIC: decided already")

    handle_eligibility(
        db_session, EligibilityPayload(candidate_id=candidate.id), job_id=uuid.uuid4()
    )

    assert candidate.state is state


# --- failure handling ----------------------------------------------------------------------------


def test_a_missing_candidate_is_a_permanent_failure(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """No number of retries makes a missing row appear."""
    job = enqueue(
        db_session,
        job_type=ELIGIBILITY_JOB_TYPE,
        payload=EligibilityPayload(candidate_id=uuid.uuid4()),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-a", limit=1)

    assert execute(db_session, leased[0], registry=registry) is False
    assert job.state is JobState.DEAD


def test_an_unknown_campaign_slug_does_not_fail_the_job(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """A file naming one campaign that does not exist must still produce the others."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=world.payload(campaign_slugs=[SODIUM, "synthetic-does-not-exist"]),
        actor=OPERATOR,
    )

    drain(db_session, registry)

    assert db_session.execute(select(func.count()).select_from(CampaignCandidate)).scalar_one() == 1


def test_a_payload_with_no_campaign_is_refused_before_it_is_queued(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """§17.1: a malformed job must never reach the queue to be found by a worker later."""
    from app.jobs_and_outbox.queue import InvalidJobPayload

    with pytest.raises(InvalidJobPayload):
        enqueue(
            db_session,
            job_type=MEMBERSHIP_JOB_TYPE,
            payload={"account_id": str(world.account.id), "campaign_slugs": []},
            actor=OPERATOR,
            registry=registry,
        )


def test_an_unexpected_payload_field_is_refused(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """`extra="forbid"`: a job written against a future field must not silently ignore half of
    what it was asked to do."""
    from app.jobs_and_outbox.queue import InvalidJobPayload

    with pytest.raises(InvalidJobPayload):
        enqueue(
            db_session,
            job_type=ELIGIBILITY_JOB_TYPE,
            payload={"candidate_id": str(uuid.uuid4()), "force_eligible": True},
            actor=OPERATOR,
            registry=registry,
        )


def test_the_eligibility_payload_has_no_field_that_could_force_an_outcome() -> None:
    """Structural, not behavioural: the bypass is absent rather than guarded against.

    §10.1 and §3.5 put the eligibility decision beyond a caller's reach. `apply_eligibility` has
    no override argument, and this asserts the job payload did not reintroduce one.
    """
    assert set(EligibilityPayload.model_fields) == {"candidate_id"}


# --- T-058b2a: the source-adapter registry -------------------------------------------------------


def test_the_source_adapter_registry_is_empty_by_default() -> None:
    """Criterion 1: nothing under `app/` may register an adapter, so the default resolves nothing.

    Asserted against the module source rather than the live dict, because the fixtures in this
    file register into that dict and a runtime assertion after they ran would prove nothing.
    """
    import app.research_and_evidence.adapters.registry as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")

    assert "SOURCE_ADAPTERS: Final[dict[str, Callable[[], SourceAdapter]]] = {}" in source


def test_no_production_module_registers_an_adapter() -> None:
    """The registry stays empty because nothing under `app/` calls the registrar.

    The only Stage 1 adapter reads a directory under `app/fixtures/`, which `T-040` forbids
    production code to import; registering it is the CLI's or a test's act.
    """
    app_dir = Path(__file__).resolve().parents[1] / "app"
    callers = [
        path.name
        for path in app_dir.rglob("*.py")
        if "register_source_adapter(" in path.read_text(encoding="utf-8")
        and path.name != "registry.py"
    ]

    assert callers == [], f"production modules registering a source adapter: {callers}"


def test_an_unregistered_adapter_name_is_refused() -> None:
    with pytest.raises(SourceAdapterNotAvailable):
        build_source_adapter("synthetic-not-registered")


def test_the_refusal_names_the_gate_rather_than_failing_quietly() -> None:
    """A job that silently captured nothing would leave a candidate that looks researched."""
    with pytest.raises(SourceAdapterNotAvailable) as refusal:
        build_source_adapter("synthetic-absent")

    assert "G-06" in str(refusal.value)


def test_a_registered_adapter_resolves(fixture_adapter: None) -> None:
    adapter = build_source_adapter(FIXTURE_ADAPTER_NAME)

    assert adapter.refresh(account_domain="alpha.example.com")


def test_a_blank_adapter_name_is_refused() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        register_source_adapter("   ", lambda: FixtureSourceAdapter(directory=SOURCE_DOCUMENTS))


# --- T-058b2a: evidence capture as a chained job -------------------------------------------------


def test_the_capture_job_is_owned_by_research(registry: JobRegistry) -> None:
    assert registry.get(CAPTURE_JOB_TYPE).handler is research_jobs.handle_capture
    assert CAPTURE_JOB_TYPE.startswith("research.")


def test_an_eligible_candidate_queues_a_capture_job(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    enqueue(db_session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR)
    drain(db_session, registry, stop_before=CAPTURE_JOB_TYPE)

    assert len(queued(db_session, CAPTURE_JOB_TYPE)) == 1


def test_an_ineligible_candidate_queues_no_capture_job(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """§8.2 makes `ineligible` terminal, so research for one would be work nothing could use.

    Counted in *any* state, not just `queued`: `drain` runs whatever it finds, so a capture job
    that had been created and then dead-lettered would leave the queue empty and this assertion
    green. That is exactly what happened when the control was run.
    """
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=world.payload(contact_id=None),
        actor=OPERATOR,
    )
    drain(db_session, registry)

    ever_created = db_session.execute(
        select(func.count()).select_from(Job).where(Job.job_type == CAPTURE_JOB_TYPE)
    ).scalar_one()
    assert ever_created == 0


def test_the_chain_reaches_capture_with_evidence_stored(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Criterion 3: one enqueue, and the worker does the rest."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=documented_world.payload(),
        actor=OPERATOR,
    )

    ran = drain(db_session, registry, stop_before=QUALIFY_JOB_TYPE)

    snapshots = db_session.execute(select(EvidenceSnapshot)).scalars().all()
    assert ran == 5, "membership, eligibility, start_research, capture, complete_research"
    assert snapshots


def test_the_chain_reaches_researched(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=documented_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)

    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    assert candidate.state is CampaignCandidateState.RESEARCHED


def test_the_candidate_passes_through_research_pending(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=documented_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)

    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    reached = (
        db_session.execute(
            select(AuditEvent.to_state).where(AuditEvent.entity_id == str(candidate.id))
        )
        .scalars()
        .all()
    )

    assert "research_pending" in [state for state in reached if state]


def test_a_candidate_with_no_matching_documents_captures_nothing_and_still_succeeds(
    db_session: Session, world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """No evidence is a finding, not a failure (GP-02: missing facts remain missing)."""
    enqueue(db_session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR)

    drain(db_session, registry)

    assert db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one() == 0
    assert queued(db_session, CAPTURE_JOB_TYPE) == []


def test_replaying_a_capture_job_stores_no_second_snapshot(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Criterion 2."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=documented_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    before = db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()

    handle_capture(db_session, CapturePayload(candidate_id=candidate.id), job_id=uuid.uuid4())

    after = db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()
    assert before == after > 0


def test_a_replayed_capture_records_that_it_stored_nothing(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """A replay writes a second audit event, and that is correct — each attempt is a real event.

    What must not happen is a second *snapshot*. So the assertion is on the trail's content: the
    replay's event records `captured: 0`, which is the evidence that dedup did its work rather
    than that the handler declined to run.
    """
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=documented_world.payload(),
        actor=OPERATOR,
    )
    # Stopped before the bracket closes, so the candidate is still `research_pending` and the
    # replay actually reaches `capture_evidence` rather than returning on the state guard.
    drain(db_session, registry, stop_before=COMPLETE_RESEARCH_JOB_TYPE)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    stored = db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()

    handle_capture(db_session, CapturePayload(candidate_id=candidate.id), job_id=uuid.uuid4())

    events = (
        db_session.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "evidence_snapshot.captured")
            .order_by(AuditEvent.occurred_at)
        )
        .scalars()
        .all()
    )
    assert db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one() == (
        stored
    )
    assert stored > 0
    assert events[0].payload["captured"] == stored
    assert events[-1].payload["captured"] == 0
    assert events[-1].payload["duplicates"] == stored


def test_a_replayed_capture_job_succeeds_rather_than_failing(
    db_session: Session, world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """The outcome a queue needs: a replay leaves the queue instead of dead-lettering."""
    enqueue(db_session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR)
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()

    replay = enqueue(
        db_session,
        job_type=CAPTURE_JOB_TYPE,
        payload=CapturePayload(candidate_id=candidate.id),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-c", limit=1)

    assert execute(db_session, leased[0], registry=registry) is True
    assert replay.state is JobState.SUCCEEDED


def test_a_capture_job_with_no_registered_adapter_dies_rather_than_retrying(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """Retrying cannot register an adapter, and the operator needs to see the misconfiguration.

    No `fixture_adapter` fixture here on purpose: this is the production default.
    """
    enqueue(db_session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR)
    drain(db_session, registry, stop_before=CAPTURE_JOB_TYPE)
    job = queued(db_session, CAPTURE_JOB_TYPE)[0]
    leased = lease_jobs(db_session, worker_id="worker-d", limit=1)

    assert execute(db_session, leased[0], registry=registry) is False
    assert job.state is JobState.DEAD


def test_a_capture_job_for_a_missing_candidate_is_permanent(
    db_session: Session, registry: JobRegistry, fixture_adapter: None
) -> None:
    job = enqueue(
        db_session,
        job_type=CAPTURE_JOB_TYPE,
        payload=CapturePayload(candidate_id=uuid.uuid4()),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-e", limit=1)

    assert execute(db_session, leased[0], registry=registry) is False
    assert job.state is JobState.DEAD


def test_a_candidate_past_research_returns_instead_of_dead_lettering(
    db_session: Session, world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """The state guard, exercised.

    `capture_evidence` raises `CaptureRefused` outside `RESEARCHABLE_STATES`, which the runner
    would classify permanent and dead-letter — turning "this candidate is past research" into a
    failed job an operator has to triage. The guard turns it into a successful no-op. Nothing
    moves a candidate out of `eligible` yet (`T-147`), so the test does it directly.
    """
    # Built directly rather than through the membership job, which would queue an eligibility
    # job that `lease_jobs` would hand back before the capture job under test.
    candidate = create_candidate(
        db_session,
        campaign_id=world.campaign.id,
        account_id=world.account.id,
        contact_id=world.contact.id,
        actor=OPERATOR,
    )
    transition(
        db_session,
        candidate,
        CampaignCandidateState.INELIGIBLE,
        actor=OPERATOR,
        reason="SYNTHETIC: put past research for this test",
    )

    job = enqueue(
        db_session,
        job_type=CAPTURE_JOB_TYPE,
        payload=CapturePayload(candidate_id=candidate.id),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-f", limit=1)

    assert execute(db_session, leased[0], registry=registry) is True
    assert job.state is JobState.SUCCEEDED
    assert db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one() == 0


def test_the_capture_payload_defaults_to_the_conventional_adapter_name() -> None:
    assert CapturePayload(candidate_id=uuid.uuid4()).source_adapter == FIXTURE_ADAPTER_NAME


def test_the_capture_job_is_not_consequential(registry: JobRegistry) -> None:
    """A local document read produces no external effect. That stops being true the day a network
    source is permitted (gate **G-06**), and the flag is where that change has to be made."""
    assert registry.get(CAPTURE_JOB_TYPE).consequential is False


def test_the_chain_stops_at_researched(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """`T-058b2b` adds qualification. Until it does, the cascade must end here rather than
    leaving a job type nobody registered queued forever."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=documented_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)

    remaining = (
        db_session.execute(select(Job.job_type).where(Job.state == JobState.QUEUED)).scalars().all()
    )

    assert remaining == []


# --- T-147 / ADR-020: the lifecycle owner brackets the research step -----------------------------


def test_the_bracket_job_types_are_owned_by_campaigns(registry: JobRegistry) -> None:
    """ADR-020's whole point: the transitions live with the module that owns the lifecycle."""
    assert registry.get(START_RESEARCH_JOB_TYPE).handler is campaign_jobs.handle_start_research
    assert (
        registry.get(COMPLETE_RESEARCH_JOB_TYPE).handler is campaign_jobs.handle_complete_research
    )
    assert START_RESEARCH_JOB_TYPE.startswith("campaigns.")
    assert COMPLETE_RESEARCH_JOB_TYPE.startswith("campaigns.")


def test_research_and_evidence_never_imports_the_transition_helper() -> None:
    """The rule ADR-020 exists to keep, asserted where a reader of this file will see it.

    `tests/test_invariants.py` enforces it across every reader; repeated here because the capture
    handler is the one that tried to break it, and a future edit to that file should fail this
    test too rather than only a general one three directories away.
    """
    import ast

    path = Path(__file__).resolve().parents[1] / "app" / "research_and_evidence" / "jobs.py"
    source = path.read_text(encoding="utf-8")
    imported = {
        alias.asname or alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    # Matched as an imported *name*, not as the substring "import transition": the control that
    # re-introduced the violation wrote `from ... import CampaignCandidate, transition`, which a
    # substring check reads straight past.
    assert "transition" not in imported
    assert "candidate.state = " not in source


def test_the_chain_names_the_bracket_types() -> None:
    """Three string-named links, each pinned to the constant it stands for."""
    assert qualification_jobs.NEXT_JOB_TYPE == START_RESEARCH_JOB_TYPE
    assert campaign_jobs.CAPTURE_JOB_TYPE == CAPTURE_JOB_TYPE
    assert research_jobs.NEXT_JOB_TYPE == COMPLETE_RESEARCH_JOB_TYPE


def test_start_research_queues_the_capture_in_the_same_transaction(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    """§7.2. A candidate in `research_pending` with no capture job queued would be one nothing
    will ever finish."""
    candidate = create_candidate(
        db_session,
        campaign_id=world.campaign.id,
        account_id=world.account.id,
        contact_id=world.contact.id,
        actor=OPERATOR,
    )
    transition(db_session, candidate, CampaignCandidateState.ELIGIBLE, actor=OPERATOR)

    campaign_jobs.handle_start_research(
        db_session, CandidatePayload(candidate_id=candidate.id), job_id=uuid.uuid4()
    )

    assert candidate.state is CampaignCandidateState.RESEARCH_PENDING
    assert len(queued(db_session, CAPTURE_JOB_TYPE)) == 1


def test_the_chain_through_research_is_five_jobs(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """ADR-020's stated cost, pinned so it cannot grow unnoticed: membership, eligibility,
    start_research, capture, complete_research.

    Stopped before qualification, which `T-058b2b1` chained on afterwards and which
    `test_the_full_chain_reaches_review_pending` counts.
    """
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=documented_world.payload(),
        actor=OPERATOR,
    )

    ran = drain(db_session, registry, stop_before=QUALIFY_JOB_TYPE)

    assert ran == 5


@pytest.mark.parametrize(
    "handler_name",
    ["handle_start_research", "handle_complete_research"],
)
def test_replaying_a_bracket_job_does_not_transition_twice(
    db_session: Session,
    documented_world: World,
    registry: JobRegistry,
    fixture_adapter: None,
    handler_name: str,
) -> None:
    """§8.2 has no self-edges (`T-010`), so a replay without the guard would raise, be classified
    permanent, and dead-letter a job that had already succeeded."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=documented_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    before = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_id == str(candidate.id))
    ).scalar_one()

    getattr(campaign_jobs, handler_name)(
        db_session, CandidatePayload(candidate_id=candidate.id), job_id=uuid.uuid4()
    )

    after = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_id == str(candidate.id))
    ).scalar_one()
    assert candidate.state is CampaignCandidateState.RESEARCHED
    assert before == after


def test_a_replayed_bracket_job_succeeds_rather_than_failing(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """The outcome a queue needs: a replay leaves the queue instead of dead-lettering."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=documented_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()

    replay = enqueue(
        db_session,
        job_type=COMPLETE_RESEARCH_JOB_TYPE,
        payload=CandidatePayload(candidate_id=candidate.id),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-g", limit=1)

    assert execute(db_session, leased[0], registry=registry) is True
    assert replay.state is JobState.SUCCEEDED


def test_a_bracket_job_for_a_missing_candidate_is_permanent(
    db_session: Session, registry: JobRegistry
) -> None:
    job = enqueue(
        db_session,
        job_type=START_RESEARCH_JOB_TYPE,
        payload=CandidatePayload(candidate_id=uuid.uuid4()),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-h", limit=1)

    assert execute(db_session, leased[0], registry=registry) is False
    assert job.state is JobState.DEAD


def test_neither_bracket_job_is_consequential(registry: JobRegistry) -> None:
    """§17.6: advancing a candidate through the workflow produces no external effect."""
    assert registry.get(START_RESEARCH_JOB_TYPE).consequential is False
    assert registry.get(COMPLETE_RESEARCH_JOB_TYPE).consequential is False


def test_research_and_evidence_is_still_only_a_reader() -> None:
    """The register itself, not only the code.

    ADR-020 rejected widening `LIFECYCLE_OWNERS`, and a future task that widened it quietly would
    defeat the decision without failing anything else here.
    """
    from tests.test_invariants import LIFECYCLE_OWNERS, LIFECYCLE_READERS

    assert "research_and_evidence" not in LIFECYCLE_OWNERS["CampaignCandidateState"]
    assert "research_and_evidence" in LIFECYCLE_READERS["CampaignCandidateState"]


# --- T-058b2b1: the fake-adapter hook ------------------------------------------------------------


def test_build_provider_returns_the_echo_adapter_by_default() -> None:
    """Criterion 1. A process that installs nothing still works, and still reaches no network."""
    from app.model_gateway.providers.echo import EchoModelAdapter
    from app.model_gateway.registry import build_provider

    assert isinstance(build_provider(Settings(app_env=AppEnv.TEST)), EchoModelAdapter)


def test_the_hook_changes_which_fake_is_built(fake_model: None) -> None:
    from app.model_gateway.providers.echo import EchoModelAdapter
    from app.model_gateway.registry import build_provider

    built = build_provider(Settings(app_env=AppEnv.TEST))

    assert isinstance(built, TaskRoutingFake)
    assert not isinstance(built, EchoModelAdapter)


def test_the_hook_cannot_make_a_real_provider_appear(fake_model: None) -> None:
    """The three G-03 locks sit on the other branch of `build_provider`, and installing a fake
    does not touch them. This is the assertion that the hook widened nothing."""
    from app.model_gateway.registry import REAL_PROVIDER_ADAPTERS

    assert REAL_PROVIDER_ADAPTERS == {}


def test_no_production_module_installs_a_fake_adapter() -> None:
    """The fixture-keyed fake reads `app/fixtures/`, which `T-040` forbids production code to
    import, so installing it is the CLI's or a test's act — never a domain module's."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    callers = [
        path.name
        for path in app_dir.rglob("*.py")
        if "set_fake_adapter_factory(" in path.read_text(encoding="utf-8")
        and path.name != "registry.py"
    ]

    assert callers == [], f"production modules installing a fake adapter: {callers}"


def test_build_provider_is_still_the_only_entry_point() -> None:
    """`DatabaseModelGateway` must not construct an adapter of its own."""
    source = (
        Path(__file__).resolve().parents[1] / "app" / "model_gateway" / "gateway.py"
    ).read_text(encoding="utf-8")

    assert "build_provider(" in source
    assert "EchoModelAdapter(" not in source
    assert "FakeModelAdapter(" not in source


# --- T-058b2b1: qualification as the last link in the automatic chain ----------------------------


def test_the_qualify_job_is_owned_by_qualification(registry: JobRegistry) -> None:
    assert registry.get(QUALIFY_JOB_TYPE).handler is qualification_jobs.handle_qualify
    assert QUALIFY_JOB_TYPE.startswith("qualification.")


def test_the_research_bracket_names_the_qualify_type() -> None:
    assert campaign_jobs.QUALIFY_JOB_TYPE == QUALIFY_JOB_TYPE


def test_the_full_chain_reaches_review_pending(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Criterion 2: one enqueue, and the worker carries the candidate to §8.3 step 8."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )

    ran = drain(db_session, registry)

    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    assert ran == 6, "membership, eligibility, start_research, capture, complete_research, qualify"
    assert candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_the_chain_stops_there_and_queues_nothing(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Criterion 2, the load-bearing half.

    §8.3 step 9 creates a draft **on candidate approval**. A chain that drafted here would encode
    "draft without approval" into the production path, and no later test would notice because the
    draft would look perfectly well-formed.
    """
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )

    drain(db_session, registry)

    remaining = (
        db_session.execute(select(Job.job_type).where(Job.state == JobState.QUEUED)).scalars().all()
    )
    assert remaining == []


def test_no_revision_exists_after_the_automatic_chain(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """The same guarantee asserted against the database rather than against the queue."""
    from app.drafts_and_approvals.models import MessageRevision

    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)

    assert db_session.execute(select(func.count()).select_from(MessageRevision)).scalar_one() == 0


def test_a_qualification_run_is_recorded(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)

    runs = db_session.execute(select(QualificationRun)).scalars().all()
    assert len(runs) == 1
    assert runs[0].human_review_required is True


def test_the_run_cites_the_versions_it_used(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """§14.5 and §17.5: a run against no known version is a result nobody can later explain."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)

    run = db_session.execute(select(ModelRun)).scalars().first()
    assert run is not None
    assert run.prompt_version_id is not None
    assert run.schema_version_id is not None
    assert run.model_config_version_id is not None


def test_a_missing_model_config_version_is_permanent(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """A retry cannot register a version, and running against an unknown one is worse than
    failing (§17.5)."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry, stop_before=QUALIFY_JOB_TYPE)
    job = queued(db_session, QUALIFY_JOB_TYPE)[0]
    job.payload = {**job.payload, "model_config_key": "synthetic-never-registered"}
    db_session.flush()

    leased = lease_jobs(db_session, worker_id="worker-q", limit=1)
    assert execute(db_session, leased[0], registry=registry) is False
    assert job.state is JobState.DEAD


def test_replaying_the_qualify_job_creates_no_second_run(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Criterion 3. `qualify_candidate` writes a `QualificationRun` every time it is called, so
    the guard is the only thing standing between a replay and a duplicate judgement."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()

    qualification_jobs.handle_qualify(
        db_session, QualifyPayload(candidate_id=candidate.id), job_id=uuid.uuid4()
    )

    assert db_session.execute(select(func.count()).select_from(QualificationRun)).scalar_one() == 1


def test_replaying_the_qualify_job_does_not_transition_twice(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """§8.2 has no `review_pending -> review_pending` edge (`T-010`)."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    before = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_id == str(candidate.id))
    ).scalar_one()

    qualification_jobs.handle_qualify(
        db_session, QualifyPayload(candidate_id=candidate.id), job_id=uuid.uuid4()
    )

    after = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_id == str(candidate.id))
    ).scalar_one()
    assert candidate.state is CampaignCandidateState.REVIEW_PENDING
    assert before == after


def test_a_replayed_qualify_job_succeeds_rather_than_failing(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()

    replay = enqueue(
        db_session,
        job_type=QUALIFY_JOB_TYPE,
        payload=QualifyPayload(candidate_id=candidate.id),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-r", limit=1)

    assert execute(db_session, leased[0], registry=registry) is True
    assert replay.state is JobState.SUCCEEDED


def test_a_qualify_job_for_a_missing_candidate_is_permanent(
    db_session: Session, registry: JobRegistry, fixture_adapter: None
) -> None:
    job = enqueue(
        db_session,
        job_type=QUALIFY_JOB_TYPE,
        payload=QualifyPayload(candidate_id=uuid.uuid4()),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-s", limit=1)

    assert execute(db_session, leased[0], registry=registry) is False
    assert job.state is JobState.DEAD


def test_the_qualify_job_is_not_consequential(registry: JobRegistry) -> None:
    """It runs a bounded model task against a fake and presents a candidate to a human."""
    assert registry.get(QUALIFY_JOB_TYPE).consequential is False


def test_the_qualify_payload_cannot_carry_a_verdict() -> None:
    """Structural: §10.1 keeps the judgement out of a caller's reach, and the payload must not
    reintroduce it. Only the candidate and which configuration to run under."""
    assert set(QualifyPayload.model_fields) == {"candidate_id", "model_config_key"}


# --- T-058b2b2a: a draft is reachable only from a candidate approval ------------------------------


#: The legal route through §8.2 to each state a test wants to park a candidate in. A single
#: `transition` cannot reach most of them — `imported -> researched` is not an edge (`T-010`) —
#: and pretending otherwise is how a test ends up asserting against a state the system can never
#: actually be in.
ROUTE_TO: dict[CampaignCandidateState, tuple[CampaignCandidateState, ...]] = {
    CampaignCandidateState.ELIGIBLE: (CampaignCandidateState.ELIGIBLE,),
    CampaignCandidateState.INELIGIBLE: (CampaignCandidateState.INELIGIBLE,),
    CampaignCandidateState.RESEARCH_PENDING: (
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
    ),
    CampaignCandidateState.RESEARCHED: (
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
    ),
    CampaignCandidateState.REVIEW_PENDING: (
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
        CampaignCandidateState.REVIEW_PENDING,
    ),
}


def park_in(session: Session, candidate: CampaignCandidate, state: CampaignCandidateState) -> None:
    """Walk a fresh candidate to ``state`` along edges §8.2 actually allows."""
    for step in ROUTE_TO[state]:
        transition(
            session,
            candidate,
            step,
            actor=OPERATOR,
            reason="SYNTHETIC: parked here for this test",
        )


def approve(session: Session, candidate: CampaignCandidate, world: World) -> None:
    """The approval Stage 2's dashboard will perform, with no authority attached."""
    recipient = (
        session.execute(select(ContactPoint).where(ContactPoint.contact_id == world.contact.id))
        .scalars()
        .one()
    )
    approve_candidate(
        session,
        candidate,
        recipient_contact_point_id=recipient.id,
        actor=OPERATOR,
        reason="SYNTHETIC: approved for the shadow pipeline test",
    )


def test_the_draft_job_types_are_owned_by_drafts(registry: JobRegistry) -> None:
    assert registry.get(DRAFT_JOB_TYPE).handler is draft_jobs.handle_draft
    assert registry.get(VALIDATE_JOB_TYPE).handler is draft_jobs.handle_validate
    assert DRAFT_JOB_TYPE.startswith("drafts.")
    assert VALIDATE_JOB_TYPE.startswith("drafts.")


def test_the_approval_names_the_draft_job_type() -> None:
    from app.campaigns import approval as campaign_approval

    assert campaign_approval.DRAFT_JOB_TYPE == DRAFT_JOB_TYPE


def test_neither_draft_job_is_consequential(registry: JobRegistry) -> None:
    """The send is §8.3 step 12, behind a second approval and gate **G-07**. A pause that stopped
    a reviewer's queue from filling would hide the work it was called to inspect."""
    assert registry.get(DRAFT_JOB_TYPE).consequential is False
    assert registry.get(VALIDATE_JOB_TYPE).consequential is False


# --- criterion 1: the automatic chain never reaches drafting -------------------------------------


def test_the_automatic_chain_queues_no_drafting_job(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Counted in *any* state, not just `queued`: `drain` runs whatever it finds, so a drafting
    job that had been created and then failed would leave the queue empty and this green."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )

    drain(db_session, registry)

    ever_created = db_session.execute(
        select(func.count()).select_from(Job).where(Job.job_type == DRAFT_JOB_TYPE)
    ).scalar_one()
    assert ever_created == 0


def test_only_an_approval_enqueues_a_drafting_job(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Criterion 1 from the other direction."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()

    approve(db_session, candidate, qualifiable_world)

    assert candidate.state is CampaignCandidateState.APPROVED
    assert len(queued(db_session, DRAFT_JOB_TYPE)) == 1


def test_the_approval_and_the_job_land_together(
    db_session: Session, qualifiable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """§7.2. An approved candidate with no drafting job queued would be a decision nothing acts
    on, and a queued job with no approval recorded would be the reverse."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=qualifiable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()

    approve(db_session, candidate, qualifiable_world)

    approvals = (
        db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_id == str(candidate.id),
                AuditEvent.policy_decision == "candidate:approved-for-outreach",
            )
        )
        .scalars()
        .all()
    )
    assert len(approvals) == 1
    assert queued(db_session, DRAFT_JOB_TYPE)[0].payload["candidate_id"] == str(candidate.id)


@pytest.mark.parametrize(
    "state",
    [
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.INELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
    ],
)
def test_approving_a_candidate_that_is_not_in_review_is_refused(
    db_session: Session, world: World, registry: JobRegistry, state: CampaignCandidateState
) -> None:
    """§8.3 step 8 presents a candidate for review before step 9 drafts for it."""
    candidate = create_candidate(
        db_session,
        campaign_id=world.campaign.id,
        account_id=world.account.id,
        contact_id=world.contact.id,
        actor=OPERATOR,
    )
    park_in(db_session, candidate, state)

    with pytest.raises(ApprovalRefused):
        approve(db_session, candidate, world)


def test_a_refused_approval_queues_nothing(
    db_session: Session, world: World, registry: JobRegistry
) -> None:
    candidate = create_candidate(
        db_session,
        campaign_id=world.campaign.id,
        account_id=world.account.id,
        contact_id=world.contact.id,
        actor=OPERATOR,
    )
    transition(db_session, candidate, CampaignCandidateState.ELIGIBLE, actor=OPERATOR)

    with pytest.raises(ApprovalRefused):
        approve(db_session, candidate, world)

    assert queued(db_session, DRAFT_JOB_TYPE) == []


# --- criterion 2: the handler fails closed, whoever enqueued it ----------------------------------


@pytest.mark.parametrize(
    "state",
    [
        CampaignCandidateState.ELIGIBLE,
        CampaignCandidateState.INELIGIBLE,
        CampaignCandidateState.RESEARCH_PENDING,
        CampaignCandidateState.RESEARCHED,
        CampaignCandidateState.REVIEW_PENDING,
    ],
)
def test_a_drafting_job_for_an_unapproved_candidate_fails_closed(
    db_session: Session,
    draftable_world: World,
    registry: JobRegistry,
    fixture_adapter: None,
    state: CampaignCandidateState,
) -> None:
    """Criterion 2, and the guarantee the whole task rests on.

    A convention about who enqueues protects nothing — a stray enqueue, a replayed payload from a
    queue dump, a future chain someone adds without reading §8.3, and the draft exists. So the
    precondition lives on the handler, where it holds whoever calls it. Enqueued here directly,
    exactly as those cases would.

    Deliberately `draftable_world`, not `world`: every version drafting needs is registered, so
    the *only* thing standing between this job and a revision is the approval precondition. With
    `world` the job also died — but for want of a draft model-config version, which meant removing
    the precondition left the test green. The control found that; this is the fix.
    """
    candidate = create_candidate(
        db_session,
        campaign_id=draftable_world.campaign.id,
        account_id=draftable_world.account.id,
        contact_id=draftable_world.contact.id,
        actor=OPERATOR,
    )
    park_in(db_session, candidate, state)
    recipient = (
        db_session.execute(
            select(ContactPoint).where(ContactPoint.contact_id == draftable_world.contact.id)
        )
        .scalars()
        .one()
    )

    job = enqueue(
        db_session,
        job_type=DRAFT_JOB_TYPE,
        payload=DraftPayload(candidate_id=candidate.id, recipient_contact_point_id=recipient.id),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-d1", limit=1)

    assert execute(db_session, leased[0], registry=registry) is False
    assert job.state is JobState.DEAD, "a draft nobody approved must not be a retryable failure"
    assert db_session.execute(select(func.count()).select_from(MessageRevision)).scalar_one() == 0


def test_the_refusal_is_permanent_rather_than_silent(
    db_session: Session, draftable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Something asked for a draft §8.3 step 9 does not allow. That is worth a dead job an
    operator can see, not a log line nobody reads."""
    candidate = create_candidate(
        db_session,
        campaign_id=draftable_world.campaign.id,
        account_id=draftable_world.account.id,
        contact_id=draftable_world.contact.id,
        actor=OPERATOR,
    )
    transition(db_session, candidate, CampaignCandidateState.ELIGIBLE, actor=OPERATOR)
    recipient = (
        db_session.execute(
            select(ContactPoint).where(ContactPoint.contact_id == draftable_world.contact.id)
        )
        .scalars()
        .one()
    )

    with pytest.raises(PermanentFailure, match="step 9"):
        draft_jobs.handle_draft(
            db_session,
            DraftPayload(candidate_id=candidate.id, recipient_contact_point_id=recipient.id),
            job_id=uuid.uuid4(),
        )


# --- the approved path, end to end ---------------------------------------------------------------


def test_an_approved_candidate_reaches_a_review_ready_revision(
    db_session: Session, draftable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=draftable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()

    approve(db_session, candidate, draftable_world)
    drain(db_session, registry)

    revision = db_session.execute(select(MessageRevision)).scalars().one()
    assert revision.state is MessageRevisionState.REVIEW_PENDING
    assert revision.approved_claim_ids


def test_drafting_queues_its_own_validation(
    db_session: Session, draftable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """§8.3 step 10 before step 11: a draft nobody validated is a draft nobody may review."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=draftable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    approve(db_session, candidate, draftable_world)

    drain(db_session, registry, stop_before=VALIDATE_JOB_TYPE)

    assert len(queued(db_session, VALIDATE_JOB_TYPE)) == 1


def test_nothing_is_queued_after_validation(
    db_session: Session, draftable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Stage 1 ends here. §8.3 step 12's send waits on a second approval this stage never gives."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=draftable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    approve(db_session, candidate, draftable_world)

    drain(db_session, registry)

    remaining = (
        db_session.execute(select(Job.job_type).where(Job.state == JobState.QUEUED)).scalars().all()
    )
    assert remaining == []


def test_no_send_command_or_outbox_row_exists(
    db_session: Session, draftable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    from app.jobs_and_outbox.outbox import OutboxEvent
    from app.outreach_and_replies.models import SendAttempt, SendCommand

    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=draftable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    approve(db_session, candidate, draftable_world)
    drain(db_session, registry)

    for model in (SendCommand, SendAttempt, OutboxEvent):
        count = db_session.execute(select(func.count()).select_from(model)).scalar_one()
        assert count == 0, f"the shadow pipeline produced {count} {model.__name__} row(s)"


# --- criterion 3: replay creates no second revision ----------------------------------------------


def test_replaying_the_drafting_job_creates_no_second_revision(
    db_session: Session, draftable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """`draft_message` writes a new revision on every call, so the guard is the only thing
    between a replay and two messages a reviewer must choose between, from one decision."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=draftable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    approve(db_session, candidate, draftable_world)
    drain(db_session, registry)
    recipient = (
        db_session.execute(
            select(ContactPoint).where(ContactPoint.contact_id == draftable_world.contact.id)
        )
        .scalars()
        .one()
    )

    draft_jobs.handle_draft(
        db_session,
        DraftPayload(candidate_id=candidate.id, recipient_contact_point_id=recipient.id),
        job_id=uuid.uuid4(),
    )

    assert db_session.execute(select(func.count()).select_from(MessageRevision)).scalar_one() == 1


def test_a_replayed_drafting_job_requeues_the_validation(
    db_session: Session, draftable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """Deliberate: a crash between writing the revision and enqueueing would otherwise leave it
    in `draft` forever. A duplicate validation job is harmless because that job is idempotent."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=draftable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    approve(db_session, candidate, draftable_world)
    drain(db_session, registry)
    recipient = (
        db_session.execute(
            select(ContactPoint).where(ContactPoint.contact_id == draftable_world.contact.id)
        )
        .scalars()
        .one()
    )

    draft_jobs.handle_draft(
        db_session,
        DraftPayload(candidate_id=candidate.id, recipient_contact_point_id=recipient.id),
        job_id=uuid.uuid4(),
    )

    assert len(queued(db_session, VALIDATE_JOB_TYPE)) == 1


def test_replaying_the_validation_job_does_not_transition_twice(
    db_session: Session, draftable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """§8.2 offers no edge back from `review_pending` to `draft` (`T-010`)."""
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=draftable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    approve(db_session, candidate, draftable_world)
    drain(db_session, registry)
    revision = db_session.execute(select(MessageRevision)).scalars().one()
    before = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == str(revision.id))
    ).scalar_one()

    draft_jobs.handle_validate(
        db_session, ValidatePayload(revision_id=revision.id), job_id=uuid.uuid4()
    )

    after = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == str(revision.id))
    ).scalar_one()
    assert revision.state is MessageRevisionState.REVIEW_PENDING
    assert before == after


def test_a_replayed_validation_job_succeeds_rather_than_failing(
    db_session: Session, draftable_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    enqueue(
        db_session,
        job_type=MEMBERSHIP_JOB_TYPE,
        payload=draftable_world.payload(),
        actor=OPERATOR,
    )
    drain(db_session, registry)
    candidate = db_session.execute(select(CampaignCandidate)).scalars().one()
    approve(db_session, candidate, draftable_world)
    drain(db_session, registry)
    revision = db_session.execute(select(MessageRevision)).scalars().one()

    replay = enqueue(
        db_session,
        job_type=VALIDATE_JOB_TYPE,
        payload=ValidatePayload(revision_id=revision.id),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-v1", limit=1)

    assert execute(db_session, leased[0], registry=registry) is True
    assert replay.state is JobState.SUCCEEDED


def test_a_validation_job_for_a_missing_revision_is_permanent(
    db_session: Session, registry: JobRegistry
) -> None:
    job = enqueue(
        db_session,
        job_type=VALIDATE_JOB_TYPE,
        payload=ValidatePayload(revision_id=uuid.uuid4()),
        actor=OPERATOR,
    )
    leased = lease_jobs(db_session, worker_id="worker-v2", limit=1)

    assert execute(db_session, leased[0], registry=registry) is False
    assert job.state is JobState.DEAD


def test_the_draft_payload_carries_the_approved_recipient() -> None:
    """ADR-008 approves an exact recipient and an exact revision together, so the address the
    approver named travels with the job rather than being re-derived when the draft is written."""
    assert set(DraftPayload.model_fields) == {
        "candidate_id",
        "recipient_contact_point_id",
        "model_config_key",
    }


# --- T-153: the re-research pass (ADR-022) --------------------------------------------------------


def review_pending_candidate(
    session: Session, registry: JobRegistry, world: World
) -> CampaignCandidate:
    """One candidate driven through research to `review_pending` — the state a re-request
    comes from."""
    enqueue(session, job_type=MEMBERSHIP_JOB_TYPE, payload=world.payload(), actor=OPERATOR)
    drain(session, registry)
    candidate = session.execute(select(CampaignCandidate)).scalars().one()
    transition(
        session,
        candidate,
        CampaignCandidateState.REVIEW_PENDING,
        actor=OPERATOR,
        reason="SYNTHETIC: ready for review",
    )
    return candidate


def test_a_re_research_pass_leaves_the_candidate_in_review(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """ADR-022's decision, at the handler. §8.2 offers no edge out of `review_pending` except
    approve, reject, defer, and invalidate — and a request for more evidence is none of those."""
    candidate = review_pending_candidate(db_session, registry, documented_world)

    handle_recapture(db_session, RecapturePayload(candidate_id=candidate.id), job_id=uuid.uuid4())

    assert candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_a_re_research_pass_queues_nothing_after_itself(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """The whole difference from `handle_capture`, which chains to `campaigns.complete_research`
    because that job's purpose is a transition. Here the chain ends with the evidence — and a
    chained `complete_research` would try `research_pending -> researched` from `review_pending`
    and dead-letter."""
    candidate = review_pending_candidate(db_session, registry, documented_world)
    before = db_session.execute(select(func.count()).select_from(Job)).scalar_one()

    handle_recapture(db_session, RecapturePayload(candidate_id=candidate.id), job_id=uuid.uuid4())

    after = db_session.execute(select(func.count()).select_from(Job)).scalar_one()
    assert after == before


def test_a_re_research_pass_stores_evidence(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """It has to actually add something, or the action is a no-op a reviewer cannot tell from a
    failure. The fixture adapter returns the same facts, so a *second* pass stores no duplicate —
    what matters here is that the pass ran and the evidence is readable."""
    candidate = review_pending_candidate(db_session, registry, documented_world)
    db_session.execute(delete(EvidenceSnapshot))
    db_session.flush()

    handle_recapture(db_session, RecapturePayload(candidate_id=candidate.id), job_id=uuid.uuid4())

    stored = db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()
    assert stored > 0


def test_a_re_research_pass_is_skipped_once_the_candidate_left_review(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """The reviewer approved, rejected, or deferred while the pass was queued. The request is moot,
    not broken — so the handler returns rather than dead-lettering a job an operator would then go
    looking for a fault in."""
    candidate = review_pending_candidate(db_session, registry, documented_world)
    transition(
        db_session,
        candidate,
        CampaignCandidateState.REJECTED,
        actor=OPERATOR,
        reason="SYNTHETIC: decided while the pass was queued",
    )
    db_session.execute(delete(EvidenceSnapshot))
    db_session.flush()

    handle_recapture(db_session, RecapturePayload(candidate_id=candidate.id), job_id=uuid.uuid4())

    stored = db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()
    assert stored == 0
    assert candidate.state is CampaignCandidateState.REJECTED


def test_the_first_capture_still_refuses_a_candidate_in_review(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """`T-153` gave `capture_evidence` a states argument rather than widening its default. The
    first research pass must still refuse a state it should never see — otherwise serving the
    second situation would have loosened the first."""
    candidate = review_pending_candidate(db_session, registry, documented_world)
    before = db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()

    handle_capture(db_session, CapturePayload(candidate_id=candidate.id), job_id=uuid.uuid4())

    after = db_session.execute(select(func.count()).select_from(EvidenceSnapshot)).scalar_one()
    assert after == before


def test_capture_evidence_still_refuses_review_pending_by_default(
    db_session: Session, documented_world: World, registry: JobRegistry, fixture_adapter: None
) -> None:
    """The parameterisation itself, at `capture_evidence` rather than at the handler.

    `handle_capture` has its own `PENDING_STATES` guard and returns early, so a test that only
    drove the handler would pass even with the default widened — which is exactly what the first
    version of this control showed. Calling `capture_evidence` directly is what pins the default
    set: `T-153` gave it an argument instead of widening it, and this is the assertion that makes
    that a fact rather than an intention.
    """
    candidate = review_pending_candidate(db_session, registry, documented_world)
    adapter = build_source_adapter(FIXTURE_ADAPTER_NAME)

    with pytest.raises(CaptureRefused, match="eligibility gate"):
        capture_evidence(db_session, candidate, adapter, actor=OPERATOR)


def test_the_recapture_job_type_is_registered(registry: JobRegistry) -> None:
    """`T-148` and the `register()` early-return this task rewrote: a second job type added to a
    module whose first was already registered used to register nothing at all."""
    assert registry.is_registered(RECAPTURE_JOB_TYPE)
    assert registry.is_registered(CAPTURE_JOB_TYPE)
