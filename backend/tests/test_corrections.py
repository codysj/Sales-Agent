"""Structured decision reasons for rejections and deferrals (T-066a; §10.6, §12.3 item 7, §8.2).

Four things, and each is asserted against the thing that actually enforces it rather than against
the convenience function in front of it:

* **The eleven categories are the migration's enum.** Read back from `pg_enum` on the migrated
  database, not from the Python class — the tests build the schema from migrations, so a category
  added to the model and forgotten in a migration is exactly the drift this catches.
* **A rejection without a category is refused by the database.** The keyword argument has no
  default, so the near miss is a `TypeError`; the far one is `NOT NULL`, asserted by inserting
  around the module entirely. A guarantee that only holds for callers who used the front door is
  not a guarantee.
* **A deferral must say what it waits for.** Both shapes stored, and the neither-shape refused —
  again at the constraint, because a deferral with no waypoint leaves review and nothing brings it
  back.
* **No policy is rewritten.** §10.6 says this feedback does not automatically rewrite campaign
  policy, so the test asserts the *absence*: the policy version row and its content are identical
  either side of a decision. An absence nobody asserts is an absence that stops being true
  quietly.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
import structlog
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import create_candidate, transition
from app.campaigns.decisions import (
    RECAPTURE_JOB_TYPE,
    CandidateDecision,
    DecisionCategory,
    DecisionKind,
    DecisionRefused,
    defer_candidate,
    reject_candidate,
    request_more_research,
)
from app.campaigns.models import Campaign, CampaignPolicyVersion
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import publish_policy_version
from app.core.lifecycles import CampaignCandidateState, JobState
from app.jobs_and_outbox.models import Job
from app.jobs_and_outbox.queue import IN_FLIGHT_STATES
from app.jobs_and_outbox.registry import registry as default_registry
from app.products_and_claims.models import Product
from app.prospects.models import Account, Contact
from app.research_and_evidence import jobs as research_jobs
from tests.factories import APPROVER, NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")

#: §10.6's list, transcribed from the specification rather than from the enum. Two copies on
#: purpose: a test that imported the enum would agree with whatever the enum said, including a
#: category someone invented.
SPEC_CATEGORIES = [
    "wrong_campaign",
    "wrong_account_or_duplicate",
    "poor_buyer_role",
    "weak_or_stale_evidence",
    "product_not_ready",
    "unsupported_claim",
    "personalization_not_useful",
    "tone_or_positioning_problem",
    "existing_relationship",
    "compliance_or_suppression_concern",
    "defer_until_date_or_event",
]


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-corrections-test")


class World:
    """One campaign with a published policy and one candidate in review."""

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
        self.policy = publish_policy_version(
            session,
            campaign_id=self.campaign.id,
            policy=CampaignPolicy(),
            approved_by=APPROVER,
            approved_at=NOW,
        )

        self.candidate = create_candidate(
            session,
            campaign_id=self.campaign.id,
            account_id=self.account.id,
            contact_id=self.contact.id,
            actor=OPERATOR,
        )
        for step in (
            CampaignCandidateState.ELIGIBLE,
            CampaignCandidateState.RESEARCH_PENDING,
            CampaignCandidateState.RESEARCHED,
            CampaignCandidateState.REVIEW_PENDING,
        ):
            transition(session, self.candidate, step, actor=OPERATOR, reason="SYNTHETIC")


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


@pytest.fixture(autouse=True)
def _registered_job_types() -> Iterator[None]:
    """The process-wide registry, populated as a worker populates it, then restored.

    `request_more_research` enqueues through `queue.enqueue`, which resolves the payload model
    from the *default* registry — so a test that skipped this would fail with `UnknownJobType`
    rather than exercising anything. Snapshot and restore rather than `clear()`, because the
    registry is process-wide and another module's registrations are not this test's to discard.
    """
    preexisting = dict(default_registry._types)
    research_jobs.register(default_registry)
    try:
        yield
    finally:
        default_registry._types.clear()
        default_registry._types.update(preexisting)


# --- criterion 1: the eleven categories are a database enum ---------------------------------------


def test_the_eleven_categories_are_a_database_enum(db_session: Session) -> None:
    """Read from `pg_enum` on the migrated schema, not from the Python class.

    The suite builds its schema from migrations, so a category added to the model and forgotten
    in a migration would pass any test that asked the enum about itself.
    """
    stored = set(
        db_session.execute(
            text(
                "SELECT enumlabel FROM pg_enum "
                "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                "WHERE pg_type.typname = 'decisioncategory'"
            )
        )
        .scalars()
        .all()
    )

    # Stored as the member name, which is this repository's convention for every enum column.
    assert stored == {category.upper() for category in SPEC_CATEGORIES}


def test_the_enum_matches_the_specification_list(db_session: Session) -> None:
    """The Python enum against §10.6 as transcribed above, in order."""
    assert [category.value for category in DecisionCategory] == SPEC_CATEGORIES
    assert len(SPEC_CATEGORIES) == 11


def test_a_category_outside_the_enum_is_refused_by_the_database(
    db_session: Session, world: World
) -> None:
    """The point of an enum over a string column with a convention."""
    with pytest.raises(Exception):  # noqa: B017 - the driver's type error, not ours to name
        db_session.execute(
            text(
                "INSERT INTO candidate_decision "
                "(id, candidate_id, kind, category, decided_by_type, decided_by, decided_at, "
                " created_at, updated_at) "
                "VALUES (gen_random_uuid(), :candidate, 'REJECT', 'HAD_A_BAD_FEELING', "
                "'HUMAN', 'operator-1', now(), now(), now())"
            ),
            {"candidate": world.candidate.id},
        )
    db_session.rollback()


# --- criterion 2: a rejection without a category is refused ---------------------------------------


def test_rejecting_without_a_category_is_a_type_error(db_session: Session, world: World) -> None:
    """`category` has no default. A default would make one category the most common value in the
    evaluation dataset for no reason anybody chose."""
    with pytest.raises(TypeError):
        reject_candidate(db_session, world.candidate, actor=OPERATOR)  # type: ignore[call-arg]


def test_a_null_category_is_refused_by_the_database(db_session: Session, world: World) -> None:
    """Around the module entirely: a guarantee that holds only for callers who used the front
    door is not a guarantee."""
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO candidate_decision "
                "(id, candidate_id, kind, category, decided_by_type, decided_by, decided_at, "
                " created_at, updated_at) "
                "VALUES (gen_random_uuid(), :candidate, 'REJECT', NULL, "
                "'HUMAN', 'operator-1', now(), now(), now())"
            ),
            {"candidate": world.candidate.id},
        )
    db_session.rollback()


def test_rejecting_records_the_category_and_moves_the_candidate(
    db_session: Session, world: World
) -> None:
    decision = reject_candidate(
        db_session,
        world.candidate,
        category=DecisionCategory.POOR_BUYER_ROLE,
        actor=OPERATOR,
        notes="SYNTHETIC: the contact runs facilities, not procurement.",
    )

    assert decision.kind is DecisionKind.REJECT
    assert decision.category is DecisionCategory.POOR_BUYER_ROLE
    assert decision.notes == "SYNTHETIC: the contact runs facilities, not procurement."
    assert world.candidate.state is CampaignCandidateState.REJECTED


def test_notes_are_optional(db_session: Session, world: World) -> None:
    """§10.6: "with optional notes"."""
    decision = reject_candidate(
        db_session, world.candidate, category=DecisionCategory.WRONG_CAMPAIGN, actor=OPERATOR
    )

    assert decision.notes is None


def test_a_blank_note_is_stored_as_no_note(db_session: Session, world: World) -> None:
    """A whitespace note reads as present and says nothing."""
    decision = reject_candidate(
        db_session,
        world.candidate,
        category=DecisionCategory.WRONG_CAMPAIGN,
        actor=OPERATOR,
        notes="   ",
    )

    assert decision.notes is None


def test_rejecting_is_refused_outside_review(db_session: Session, world: World) -> None:
    """§8.2 offers `review_pending -> rejected` and no other edge into rejection."""
    reject_candidate(
        db_session, world.candidate, category=DecisionCategory.WRONG_CAMPAIGN, actor=OPERATOR
    )

    with pytest.raises(DecisionRefused, match="review_pending"):
        reject_candidate(
            db_session, world.candidate, category=DecisionCategory.WRONG_CAMPAIGN, actor=OPERATOR
        )


def test_rejecting_for_a_deferral_reason_is_refused(db_session: Session, world: World) -> None:
    """A candidate rejected for waiting is a candidate nobody will look at again."""
    with pytest.raises(DecisionRefused, match="deferral"):
        reject_candidate(
            db_session,
            world.candidate,
            category=DecisionCategory.DEFER_UNTIL_DATE_OR_EVENT,
            actor=OPERATOR,
        )


def test_a_refused_rejection_leaves_the_candidate_in_review(
    db_session: Session, world: World
) -> None:
    with pytest.raises(DecisionRefused):
        reject_candidate(
            db_session,
            world.candidate,
            category=DecisionCategory.DEFER_UNTIL_DATE_OR_EVENT,
            actor=OPERATOR,
        )

    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING
    assert db_session.execute(select(func.count()).select_from(CandidateDecision)).scalar_one() == 0


# --- criterion 3: a deferral stores the date or the event -----------------------------------------


def test_deferring_stores_a_date(db_session: Session, world: World) -> None:
    until = (NOW + timedelta(days=90)).date()

    decision = defer_candidate(db_session, world.candidate, actor=OPERATOR, until_date=until)

    assert decision.defer_until_date == until
    assert decision.defer_until_event is None
    assert world.candidate.state is CampaignCandidateState.DEFERRED


def test_deferring_stores_an_event(db_session: Session, world: World) -> None:
    """An event for "when they publish their storage roadmap", which has no date yet."""
    decision = defer_candidate(
        db_session,
        world.candidate,
        actor=OPERATOR,
        until_event="SYNTHETIC: when they publish their storage roadmap",
    )

    assert decision.defer_until_event == "SYNTHETIC: when they publish their storage roadmap"
    assert decision.defer_until_date is None


def test_deferring_with_neither_is_refused(db_session: Session, world: World) -> None:
    with pytest.raises(DecisionRefused, match="date or an event"):
        defer_candidate(db_session, world.candidate, actor=OPERATOR)

    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_deferring_with_a_blank_event_is_refused(db_session: Session, world: World) -> None:
    with pytest.raises(DecisionRefused, match="date or an event"):
        defer_candidate(db_session, world.candidate, actor=OPERATOR, until_event="   ")


def test_a_waypointless_deferral_is_refused_by_the_database(
    db_session: Session, world: World
) -> None:
    """The constraint, not the function. A deferral with no waypoint leaves review and nothing
    brings it back, so the guarantee has to hold for a caller that never came through here."""
    with pytest.raises(IntegrityError, match="deferral_has_a_waypoint"):
        db_session.execute(
            text(
                "INSERT INTO candidate_decision "
                "(id, candidate_id, kind, category, decided_by_type, decided_by, decided_at, "
                " created_at, updated_at) "
                "VALUES (gen_random_uuid(), :candidate, 'DEFER', 'DEFER_UNTIL_DATE_OR_EVENT', "
                "'HUMAN', 'operator-1', now(), now(), now())"
            ),
            {"candidate": world.candidate.id},
        )
    db_session.rollback()


def test_a_rejection_cannot_carry_a_waypoint(db_session: Session, world: World) -> None:
    """A date on a rejection would make any future deferral queue wrong in a way nobody would
    look for."""
    with pytest.raises(IntegrityError, match="only_deferrals_wait"):
        db_session.execute(
            text(
                "INSERT INTO candidate_decision "
                "(id, candidate_id, kind, category, defer_until_date, decided_by_type, "
                " decided_by, decided_at, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :candidate, 'REJECT', 'WRONG_CAMPAIGN', "
                "DATE '2026-12-01', 'HUMAN', 'operator-1', now(), now(), now())"
            ),
            {"candidate": world.candidate.id},
        )
    db_session.rollback()


def test_a_deferral_may_name_a_more_specific_category(db_session: Session, world: World) -> None:
    """A reviewer deferring *because* the product is not ready has said something more useful
    than "not now"."""
    decision = defer_candidate(
        db_session,
        world.candidate,
        actor=OPERATOR,
        until_event="SYNTHETIC: when the pilot ships",
        category=DecisionCategory.PRODUCT_NOT_READY,
    )

    assert decision.category is DecisionCategory.PRODUCT_NOT_READY


def test_deferring_is_refused_outside_review(db_session: Session, world: World) -> None:
    defer_candidate(db_session, world.candidate, actor=OPERATOR, until_event="SYNTHETIC: later")

    with pytest.raises(DecisionRefused, match="review_pending"):
        defer_candidate(
            db_session, world.candidate, actor=OPERATOR, until_event="SYNTHETIC: later still"
        )


# --- criterion 4: no decision rewrites policy -----------------------------------------------------


def policy_snapshot(session: Session) -> list[tuple[uuid.UUID, int, str]]:
    """Every policy version, by identity, number, and serialized content."""
    return [
        (version.id, version.version, repr(version.policy))
        for version in session.execute(
            select(CampaignPolicyVersion).order_by(CampaignPolicyVersion.version)
        )
        .scalars()
        .all()
    ]


def test_a_rejection_rewrites_no_policy(db_session: Session, world: World) -> None:
    """§10.6: this feedback becomes evaluation and policy-proposal data; it does not
    automatically rewrite campaign policy. The absence is the behaviour."""
    before = policy_snapshot(db_session)

    reject_candidate(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
        notes="SYNTHETIC: the only evidence is two years old.",
    )

    assert policy_snapshot(db_session) == before


def test_a_deferral_rewrites_no_policy(db_session: Session, world: World) -> None:
    before = policy_snapshot(db_session)

    defer_candidate(db_session, world.candidate, actor=OPERATOR, until_date=date(2026, 12, 1))

    assert policy_snapshot(db_session) == before


def test_no_decision_creates_a_policy_version(db_session: Session, world: World) -> None:
    """Counted as well as compared: a new version appended after the snapshot's last row would
    leave the earlier rows identical."""
    before = db_session.execute(
        select(func.count()).select_from(CampaignPolicyVersion)
    ).scalar_one()

    reject_candidate(
        db_session, world.candidate, category=DecisionCategory.UNSUPPORTED_CLAIM, actor=OPERATOR
    )

    after = db_session.execute(select(func.count()).select_from(CampaignPolicyVersion)).scalar_one()
    assert after == before


# --- the record itself ----------------------------------------------------------------------------


def test_the_decision_records_who_decided(db_session: Session, world: World) -> None:
    """§17.5 wants the actor on every decision, and this table is the evaluation dataset — one
    that needed a join to another subsystem to say who decided is one people will analyse
    without the actor."""
    decision = reject_candidate(
        db_session, world.candidate, category=DecisionCategory.WRONG_CAMPAIGN, actor=OPERATOR
    )

    assert decision.decided_by == "operator-1"
    assert decision.decided_by_type == ActorType.HUMAN.value
    assert decision.decided_at is not None


def test_the_decision_writes_an_audit_event(db_session: Session, world: World) -> None:
    """The transition's own event, carrying both ends of the move (§3.5)."""
    before = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()

    reject_candidate(
        db_session, world.candidate, category=DecisionCategory.EXISTING_RELATIONSHIP, actor=OPERATOR
    )

    after = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
    assert after > before


def test_decisions_accumulate_rather_than_being_overwritten(
    db_session: Session, world: World
) -> None:
    """A candidate deferred and later rejected has two rows. When a reviewer changed their mind
    is exactly what evaluation data is for."""
    defer_candidate(
        db_session, world.candidate, actor=OPERATOR, until_event="SYNTHETIC: next quarter"
    )
    transition(
        db_session,
        world.candidate,
        CampaignCandidateState.REVIEW_PENDING,
        actor=OPERATOR,
        reason="SYNTHETIC: the event happened",
    )
    reject_candidate(
        db_session, world.candidate, category=DecisionCategory.PRODUCT_NOT_READY, actor=OPERATOR
    )

    rows = (
        db_session.execute(
            select(CandidateDecision)
            .where(CandidateDecision.candidate_id == world.candidate.id)
            .order_by(CandidateDecision.decided_at)
        )
        .scalars()
        .all()
    )
    assert [row.kind for row in rows] == [DecisionKind.DEFER, DecisionKind.REJECT]


# --- T-153: requesting more research (ADR-022) ----------------------------------------------------
#
# §12.3 item 6 asks the card to offer this, and §8.2 gives it no state to move to. ADR-022 decided
# it adds evidence without moving the candidate, so the tests are about the *absence* of a
# transition as much as the presence of a job — an action that quietly took a candidate out of
# review would look identical from the response and be wrong in the one way that matters.


def in_flight_recapture_jobs(session: Session, candidate_id: uuid.UUID) -> int:
    return session.execute(
        select(func.count())
        .select_from(Job)
        .where(
            Job.job_type == "research.recapture_evidence",
            Job.state.in_(IN_FLIGHT_STATES),
            Job.payload["candidate_id"].astext == str(candidate_id),
        )
    ).scalar_one()


def test_requesting_more_research_leaves_the_candidate_in_review(
    db_session: Session, world: World
) -> None:
    """ADR-022's decision, and the one property a reviewer would notice if it were wrong: the card
    they are reading must not vanish from the queue."""
    request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )

    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_requesting_more_research_queues_one_pass(db_session: Session, world: World) -> None:
    request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )

    assert in_flight_recapture_jobs(db_session, world.candidate.id) == 1


def test_the_queued_job_is_the_one_research_registers(db_session: Session, world: World) -> None:
    """A string constant on each side; this is what keeps them the same string."""
    assert RECAPTURE_JOB_TYPE == research_jobs.RECAPTURE_JOB_TYPE


def test_the_request_records_who_asked_and_why(db_session: Session, world: World) -> None:
    """§10.6 structures every other reviewer decision, and "why did somebody want more evidence
    here" is exactly the evaluation data it exists to collect."""
    decision = request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
        notes="SYNTHETIC: the only evidence is two years old.",
    )

    assert decision.kind is DecisionKind.REQUEST_RESEARCH
    assert decision.category is DecisionCategory.WEAK_OR_STALE_EVIDENCE
    assert decision.notes == "SYNTHETIC: the only evidence is two years old."
    assert decision.decided_by == "operator-1"


def test_the_request_kind_is_a_database_enum_value(db_session: Session, world: World) -> None:
    """Read from `pg_enum` on the migrated schema: Alembic does not autogenerate a new enum value,
    so a model-only change would have left the column unable to store what the code writes."""
    stored = set(
        db_session.execute(
            text(
                "SELECT enumlabel FROM pg_enum "
                "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                "WHERE pg_type.typname = 'decisionkind'"
            )
        )
        .scalars()
        .all()
    )

    assert stored == {"REJECT", "DEFER", "REQUEST_RESEARCH"}


def test_a_request_carries_no_waypoint(db_session: Session, world: World) -> None:
    """`ck_candidate_decision_only_deferrals_wait` allows a waypoint only on a deferral, so the
    new kind has to be waypointless — a constraint written before this kind existed."""
    decision = request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )
    db_session.flush()

    assert decision.defer_until_date is None
    assert decision.defer_until_event is None


def test_a_second_request_while_one_is_in_flight_is_refused(
    db_session: Session, world: World
) -> None:
    """A reviewer who clicks twice wants one more pass, not two."""
    request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )

    with pytest.raises(DecisionRefused, match="already in flight"):
        request_more_research(
            db_session,
            world.candidate,
            category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
            actor=OPERATOR,
        )

    assert in_flight_recapture_jobs(db_session, world.candidate.id) == 1


def test_a_leased_pass_still_counts_as_in_flight(db_session: Session, world: World) -> None:
    """`leased` is precisely the state a job is in while a reviewer waits and clicks again. A
    check that counted only `queued` would queue a second pass exactly when it is least wanted."""
    request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )
    job = db_session.execute(
        select(Job).where(Job.job_type == "research.recapture_evidence")
    ).scalar_one()
    # `ck_job_leased_state_needs_a_holder` makes the lease fields part of what `leased` *means*,
    # so a test that set only the state would be asserting about a row the schema forbids.
    job.state = JobState.LEASED
    job.leased_by = "synthetic-worker"
    job.lease_expires_at = NOW + timedelta(minutes=5)
    db_session.flush()

    with pytest.raises(DecisionRefused, match="already in flight"):
        request_more_research(
            db_session,
            world.candidate,
            category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
            actor=OPERATOR,
        )


def test_a_finished_pass_does_not_block_a_new_request(db_session: Session, world: World) -> None:
    """One at a time, not one ever. A reviewer who read the new evidence and still wants more must
    be able to ask again."""
    request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )
    job = db_session.execute(
        select(Job).where(Job.job_type == "research.recapture_evidence")
    ).scalar_one()
    job.state = JobState.SUCCEEDED
    db_session.flush()

    request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )

    assert in_flight_recapture_jobs(db_session, world.candidate.id) == 1


def test_another_candidates_pass_does_not_block_this_one(db_session: Session, world: World) -> None:
    """The in-flight check is per candidate. Without the payload filter it would serialize the
    whole review queue behind whoever asked first."""
    other = World(db_session)
    request_more_research(
        db_session,
        other.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )

    request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )

    assert in_flight_recapture_jobs(db_session, world.candidate.id) == 1
    assert in_flight_recapture_jobs(db_session, other.candidate.id) == 1


def test_requesting_outside_review_is_refused(db_session: Session, world: World) -> None:
    reject_candidate(
        db_session, world.candidate, category=DecisionCategory.WRONG_CAMPAIGN, actor=OPERATOR
    )

    with pytest.raises(DecisionRefused, match="in review"):
        request_more_research(
            db_session,
            world.candidate,
            category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
            actor=OPERATOR,
        )


def test_a_refused_request_queues_nothing(db_session: Session, world: World) -> None:
    reject_candidate(
        db_session, world.candidate, category=DecisionCategory.WRONG_CAMPAIGN, actor=OPERATOR
    )

    with pytest.raises(DecisionRefused):
        request_more_research(
            db_session,
            world.candidate,
            category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
            actor=OPERATOR,
        )

    assert in_flight_recapture_jobs(db_session, world.candidate.id) == 0


def test_requesting_more_research_rewrites_no_policy(db_session: Session, world: World) -> None:
    """§10.6 again: this feedback is evaluation data, not a policy edit."""
    before = policy_snapshot(db_session)

    request_more_research(
        db_session,
        world.candidate,
        category=DecisionCategory.WEAK_OR_STALE_EVIDENCE,
        actor=OPERATOR,
    )

    assert policy_snapshot(db_session) == before
