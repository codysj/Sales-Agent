"""The candidate review queue endpoint (T-063a; §12.3, §17.5, §15.1).

The first authenticated endpoint in this repository, so half of what is worth testing is the
authentication itself: an absent, expired, revoked, or under-privileged session must each be
refused, and refused with the *right* status — `401` means sign in, `403` means signing in again
will not help, and collapsing them sends a reviewer round a login loop that can never succeed.

The other half is the queue's guarantees. Ordering and pagination are tested together because
neither is meaningful alone: pagination over a non-total order repeats rows and skips others,
and the reviewer never learns which one they missed.

The app under test uses the same throwaway migrated database the rest of the suite does, wired
through `dependency_overrides` so the endpoint reads the transaction the test wrote — a real
connection would not see uncommitted rows.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, create_candidate, transition
from app.campaigns.models import Campaign
from app.core.lifecycles import CampaignCandidateState, MessageRevisionState
from app.db.session import dispose_engines
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.models import MessageDraft, MessageRevision
from app.identity.dependencies import SESSION_COOKIE, db_session
from app.identity.models import Role, RoleKey, User, UserRole
from app.identity.sessions import issue_session, revoke
from app.main import create_app
from app.products_and_claims.claim_models import ApprovedClaim, ApprovedClaimCampaign
from app.products_and_claims.models import Product, ProductStatusVersion, ReadinessCategory
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


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-review-api-test")


@pytest.fixture
def client(db_session_for_api: Session) -> Iterator[TestClient]:
    """The app, reading the test's own transaction.

    `dependency_overrides` rather than a real connection: the rows a test writes are never
    committed, so an endpoint opening its own session would correctly see an empty database and
    every assertion would be about nothing.
    """
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session] = lambda: db_session_for_api
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    # The app's lifespan disposes every pooled engine on shutdown, and `dispose_engines` is
    # process-wide. `tests/test_health.py` calls it after its own client for the same reason:
    # leaving a half-disposed pool behind is how one module's fixture reaches into another's.
    dispose_engines()


@pytest.fixture
def db_session_for_api(db_session: Session) -> Session:
    return db_session


class World:
    """One campaign with three candidates in review and one that is not."""

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
        self.other_campaign = Campaign(
            slug=f"synthetic-{uuid.uuid4().hex[:8]}",
            name="SYNTHETIC-Other-Campaign",
            product_id=self.product.id,
            paused=False,
        )
        self.account = Account(
            domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account"
        )
        session.add_all([self.campaign, self.other_campaign, self.account])
        session.flush()
        # One contact per candidate: §8.1's identity triple is unique per
        # `(campaign, account, contact)` (`T-018`), so three candidates in one campaign need
        # three people — which is also what a real account looks like.
        self.contacts = [self._contact(f"SYNTHETIC Person {index}") for index in range(5)]
        # One verified address, reused by every revision: a revision's recipient is a real
        # foreign key (§11.4 binds recipient and revision together), and which address it is
        # does not matter to a query test.
        self.recipient = ContactPoint(
            contact_id=self.contacts[0].id,
            type=ContactPointType.EMAIL,
            value=f"{uuid.uuid4().hex[:8]}@{self.account.domain}",
            verification_state=VerificationState.VERIFIED,
        )
        session.add(self.recipient)
        session.flush()

        self.in_review = [
            self._candidate(
                self.campaign, self.contacts[index], CampaignCandidateState.REVIEW_PENDING
            )
            for index in range(3)
        ]
        self.other = self._candidate(
            self.other_campaign, self.contacts[3], CampaignCandidateState.REVIEW_PENDING
        )
        self.refused = self._candidate(
            self.campaign, self.contacts[4], CampaignCandidateState.INELIGIBLE
        )

    def _contact(self, name: str) -> Contact:
        contact = Contact(account_id=self.account.id, full_name=name)
        self.session.add(contact)
        self.session.flush()
        return contact

    def _candidate(
        self, campaign: Campaign, contact: Contact, state: CampaignCandidateState
    ) -> CampaignCandidate:
        candidate = create_candidate(
            self.session,
            campaign_id=campaign.id,
            account_id=self.account.id,
            contact_id=contact.id,
            actor=OPERATOR,
        )
        route = {
            CampaignCandidateState.INELIGIBLE: (CampaignCandidateState.INELIGIBLE,),
            CampaignCandidateState.REVIEW_PENDING: (
                CampaignCandidateState.ELIGIBLE,
                CampaignCandidateState.RESEARCH_PENDING,
                CampaignCandidateState.RESEARCHED,
                CampaignCandidateState.REVIEW_PENDING,
            ),
        }[state]
        for step in route:
            transition(
                self.session, candidate, step, actor=OPERATOR, reason="SYNTHETIC: parked for a test"
            )
        return candidate


OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")


@pytest.fixture
def world(db_session_for_api: Session) -> World:
    return World(db_session_for_api)


def sign_in(session: Session, *roles: RoleKey) -> str:
    """A user holding ``roles``, and a live session token for them."""
    from sqlalchemy import select

    user = User(
        email=f"synthetic.{uuid.uuid4().hex[:8]}@example.com", display_name="SYNTHETIC Reviewer"
    )
    session.add(user)
    session.flush()
    for role in roles:
        row = session.execute(select(Role).where(Role.key == role.value)).scalar_one()
        session.add(UserRole(user_id=user.id, role_id=row.id, granted_by="operator-1"))
    session.flush()
    return issue_session(session, user, issued_via="test").token


def queue(client: TestClient, token: str | None, **params: object) -> object:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/api/review/candidates", headers=headers, params=params)


# --- criterion 1: the endpoint refuses anyone it should ------------------------------------------


def test_an_unauthenticated_request_is_refused(client: TestClient) -> None:
    response = client.get("/api/review/candidates")

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


def test_an_unknown_token_is_refused(client: TestClient) -> None:
    response = queue(client, "synthetic-not-a-real-token")

    assert response.status_code == 401  # type: ignore[attr-defined]


def test_an_expired_session_is_refused(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    from sqlalchemy import select

    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)
    from app.identity.sessions import UserSession

    held = db_session_for_api.execute(select(UserSession)).scalars().one()
    held.expires_at = NOW - timedelta(days=1)
    held.issued_at = NOW - timedelta(days=2)
    db_session_for_api.flush()

    assert queue(client, token).status_code == 401  # type: ignore[attr-defined]


def test_a_revoked_session_is_refused(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    from sqlalchemy import select

    from app.identity.sessions import UserSession

    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)
    held = db_session_for_api.execute(select(UserSession)).scalars().one()
    revoke(db_session_for_api, held, revoked_by="operator-1", reason="SYNTHETIC")

    assert queue(client, token).status_code == 401  # type: ignore[attr-defined]


def test_a_session_without_the_role_is_forbidden_not_unauthorized(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """`403`, not `401`. Signing in again would not help, and sending someone back to a login
    screen they already passed is a loop that can never succeed."""
    token = sign_in(db_session_for_api)  # no roles at all

    response = queue(client, token)

    assert response.status_code == 403  # type: ignore[attr-defined]
    assert "view_review_queue" in response.json()["detail"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "role",
    [RoleKey.OPERATOR_REVIEWER, RoleKey.VIEWER, RoleKey.CAMPAIGN_SALES_OWNER],
)
def test_a_role_that_grants_the_queue_may_read_it(
    client: TestClient, db_session_for_api: Session, world: World, role: RoleKey
) -> None:
    token = sign_in(db_session_for_api, role)

    assert queue(client, token).status_code == 200  # type: ignore[attr-defined]


def test_a_token_in_the_query_string_does_not_authenticate(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """A query parameter would put session tokens in access logs, browser history, and any
    `Referer` a page leaked. The dependency reads a cookie or a bearer header, and nothing else."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    response = client.get("/api/review/candidates", params={"token": token})

    assert response.status_code == 401


def test_a_cookie_authenticates(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """How the dashboard will call it."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.get("/api/review/candidates")

    assert response.status_code == 200


# --- criterion 2: filters, ordering, pagination --------------------------------------------------


def test_the_queue_returns_only_what_is_waiting(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """Without a state filter the default is `review_pending`: a queue mixing in refused and
    approved candidates would answer a question nobody asked."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = queue(client, token).json()  # type: ignore[attr-defined]

    returned = {row["candidate_id"] for row in body["rows"]}
    assert str(world.refused.id) not in returned
    assert body["total"] == 4  # three in one campaign, one in the other


def test_filtering_by_campaign(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = queue(client, token, campaign_id=str(world.campaign.id)).json()  # type: ignore[attr-defined]

    assert body["total"] == 3
    assert {row["campaign_id"] for row in body["rows"]} == {str(world.campaign.id)}


def test_filtering_by_state(client: TestClient, db_session_for_api: Session, world: World) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = queue(client, token, state="ineligible").json()  # type: ignore[attr-defined]

    assert [row["candidate_id"] for row in body["rows"]] == [str(world.refused.id)]


def test_an_unknown_state_is_rejected_rather_than_ignored(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """A typo silently returning the default queue would be a filter that lied."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    assert queue(client, token, state="synthetic_not_a_state").status_code == 422  # type: ignore[attr-defined]


def test_pagination_covers_every_row_exactly_once(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """The guarantee that needs the tiebreak: every candidate here was written in one
    transaction, so `updated_at` ties across all of them. Without `id` as a second key, two
    pages of a tied set repeat a row and skip another — and nothing would say so."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    seen: list[str] = []
    for offset in range(0, 4, 2):
        body = queue(client, token, limit=2, offset=offset).json()  # type: ignore[attr-defined]
        seen.extend(row["candidate_id"] for row in body["rows"])

    assert len(seen) == 4
    assert len(set(seen)) == 4


def test_ordering_is_stable_across_identical_requests(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    first = [row["candidate_id"] for row in queue(client, token).json()["rows"]]  # type: ignore[attr-defined]
    second = [row["candidate_id"] for row in queue(client, token).json()["rows"]]  # type: ignore[attr-defined]

    assert first == second


def test_the_page_size_is_capped(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """An unbounded page is a query whose cost the caller chooses."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    assert queue(client, token, limit=1000).status_code == 422  # type: ignore[attr-defined]


def test_a_negative_offset_is_rejected(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    assert queue(client, token, offset=-1).status_code == 422  # type: ignore[attr-defined]


def test_the_page_reports_its_own_window(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """So a client can ask for the next page without guessing what it asked for."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = queue(client, token, limit=2, offset=2).json()  # type: ignore[attr-defined]

    assert body["limit"] == 2
    assert body["offset"] == 2
    assert body["total"] == 4


# --- criterion 3: the record version -------------------------------------------------------------


def test_every_row_carries_a_record_version(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """§11.4's optimistic-concurrency stamp. `T-035c` already compares `*_updated_at`, so a
    second mechanism would be a second thing to keep in step."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = queue(client, token).json()  # type: ignore[attr-defined]

    assert body["rows"]
    for row in body["rows"]:
        assert row["record_version"]


def test_the_record_version_is_the_rows_updated_at(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """Named as the version a mutation sends back, so it has to *be* the stamp the recheck
    compares rather than something that merely changes."""
    from datetime import datetime

    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)
    body = queue(client, token, campaign_id=str(world.campaign.id)).json()  # type: ignore[attr-defined]

    by_id = {row["candidate_id"]: row["record_version"] for row in body["rows"]}
    for candidate in world.in_review:
        db_session_for_api.refresh(candidate)
        assert datetime.fromisoformat(by_id[str(candidate.id)]) == candidate.updated_at


def test_the_row_does_not_carry_a_decision(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """§12.3's card wants evidence, product status, claims, and the exact revision. A list that
    returned all of it would invite deciding from the list, and the card is `T-064`."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = queue(client, token).json()  # type: ignore[attr-defined]

    for row in body["rows"]:
        for absent in ("evidence", "claims", "body", "subject", "approval"):
            assert absent not in row


def test_the_ordering_is_a_total_order(client: TestClient) -> None:
    """Structural, because behaviour cannot prove this one.

    A control that removed the `id` tiebreak left every pagination test green: the set is small,
    and Postgres happened to return a stable order anyway. `process.md` §5 says to pin a
    mechanism like that with a compiled-SQL assertion rather than trusting a run that got lucky.
    """
    from sqlalchemy import select

    from app.drafts_and_approvals.api import QUEUE_ORDER

    compiled = str(select(CampaignCandidate.id).order_by(*QUEUE_ORDER))

    assert "campaign_candidate.updated_at ASC" in compiled
    assert "campaign_candidate.id ASC" in compiled, (
        "without the id tiebreak, two pages of a tied set repeat a row and skip another"
    )


# --- T-063b: the revision queue -------------------------------------------------------------------


def make_revision(
    session: Session,
    candidate: CampaignCandidate,
    world: World,
    *,
    state: MessageRevisionState = MessageRevisionState.REVIEW_PENDING,
    opportunity_type: str | None = "pilot",
) -> MessageRevision:
    """One draft and one revision for ``candidate``, parked in ``state``.

    Built directly rather than through `draft_message`: this is a query test, and routing it
    through the model gateway would make it fail for reasons that have nothing to do with the
    endpoint under test.
    """
    draft = MessageDraft(candidate_id=candidate.id)
    session.add(draft)
    session.flush()
    revision = MessageRevision(
        draft_id=draft.id,
        revision_number=1,
        recipient_contact_point_id=world.recipient.id,
        subject="SYNTHETIC subject",
        body="SYNTHETIC body.",
        approved_claim_ids=[],
        evidence_ids=[],
        content_hash="d" * 64,
        state=MessageRevisionState.DRAFT,
        created_by="drafting-task",
    )
    session.add(revision)
    session.flush()
    if state is not MessageRevisionState.DRAFT:
        revisions.transition(session, revision, state, actor=OPERATOR)
    if opportunity_type is not None:
        session.add(_qualification_run(session, candidate, opportunity_type))
        session.flush()
    return revision


def _qualification_run(
    session: Session, candidate: CampaignCandidate, opportunity_type: str
) -> QualificationRun:
    from app.core.settings import ModelProvider
    from app.model_gateway.models import ModelRun, ModelRunOutcome

    run = ModelRun(
        task_name="qualification",
        provider=ModelProvider.FAKE,
        model_name="deterministic-fake",
        outcome=ModelRunOutcome.SUCCEEDED,
        started_at=NOW,
    )
    session.add(run)
    session.flush()
    return QualificationRun(
        candidate_id=candidate.id,
        model_run_id=run.id,
        opportunity_type=opportunity_type,
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


def revisions_queue(client: TestClient, token: str | None, **params: object) -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/api/review/revisions", headers=headers, params=params)


def test_the_revision_queue_refuses_an_unauthenticated_request(client: TestClient) -> None:
    assert client.get("/api/review/revisions").status_code == 401


def test_the_revision_queue_refuses_a_session_without_the_role(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api)

    assert revisions_queue(client, token).status_code == 403


def test_the_revision_queue_returns_only_what_is_waiting(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    waiting = make_revision(db_session_for_api, world.in_review[0], world)
    make_revision(
        db_session_for_api,
        world.in_review[1],
        world,
        state=MessageRevisionState.DRAFT,
        opportunity_type=None,
    )
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = revisions_queue(client, token).json()

    assert [row["revision_id"] for row in body["rows"]] == [str(waiting.id)]


def test_filtering_revisions_by_campaign(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    make_revision(db_session_for_api, world.in_review[0], world)
    make_revision(db_session_for_api, world.other, world)
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = revisions_queue(client, token, campaign_id=str(world.campaign.id)).json()

    assert body["total"] == 1
    assert body["rows"][0]["campaign_id"] == str(world.campaign.id)


def test_filtering_revisions_by_opportunity_type(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    make_revision(db_session_for_api, world.in_review[0], world, opportunity_type="pilot")
    make_revision(db_session_for_api, world.in_review[1], world, opportunity_type="expansion")
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = revisions_queue(client, token, opportunity_type="expansion").json()

    assert body["total"] == 1
    assert body["rows"][0]["opportunity_type"] == "expansion"


def test_filtering_revisions_by_state(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    make_revision(
        db_session_for_api,
        world.in_review[0],
        world,
        state=MessageRevisionState.DRAFT,
        opportunity_type=None,
    )
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = revisions_queue(client, token, state="draft").json()

    assert body["total"] == 1


def test_an_unknown_revision_state_is_rejected(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    assert revisions_queue(client, token, state="synthetic_nonsense").status_code == 422


# --- criterion 2: backlog age --------------------------------------------------------------------


def test_backlog_age_is_computed_not_stored() -> None:
    """A stored age would be wrong the moment after it was written, and would need a job to keep
    it wrong less often."""
    from app.drafts_and_approvals.api import RevisionRow, backlog_age_hours

    entered = datetime(2026, 7, 31, 6, 0, tzinfo=UTC)

    assert backlog_age_hours(entered, now=entered + timedelta(hours=5)) == 5
    assert backlog_age_hours(entered, now=entered + timedelta(hours=5, minutes=59)) == 5
    assert "backlog_age_hours" not in {column.name for column in MessageRevision.__table__.columns}
    assert "backlog_age_hours" in RevisionRow.model_fields


def test_backlog_age_is_stable_for_a_fixed_clock() -> None:
    """Criterion 2. Two calls with the same reference time give the same number, so a test can
    assert an exact figure rather than "roughly"."""
    from app.drafts_and_approvals.api import backlog_age_hours

    entered = datetime(2026, 7, 31, 6, 0, tzinfo=UTC)
    now = entered + timedelta(hours=9, minutes=30)

    assert backlog_age_hours(entered, now=now) == backlog_age_hours(entered, now=now) == 9


def test_a_future_stamp_reports_zero_rather_than_a_negative_age() -> None:
    """Clock skew between the database and the API. "-3 hours waiting" would be worse than no
    number at all, because a reviewer would believe it."""
    from app.drafts_and_approvals.api import backlog_age_hours

    entered = datetime(2026, 7, 31, 6, 0, tzinfo=UTC)

    assert backlog_age_hours(entered, now=entered - timedelta(hours=3)) == 0


def test_every_revision_row_reports_its_backlog_age(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    make_revision(db_session_for_api, world.in_review[0], world)
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = revisions_queue(client, token).json()

    assert body["rows"]
    for row in body["rows"]:
        assert row["backlog_age_hours"] >= 0


def test_filtering_by_minimum_age(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """The filter has to mean the same thing as the reported number, or a reviewer chasing
    everything older than a day would be shown rows that say they are younger."""
    old = make_revision(db_session_for_api, world.in_review[0], world)
    make_revision(db_session_for_api, world.in_review[1], world)
    old.updated_at = datetime.now(UTC) - timedelta(hours=48)
    db_session_for_api.flush()
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = revisions_queue(client, token, min_age_hours=24).json()

    assert [row["revision_id"] for row in body["rows"]] == [str(old.id)]
    assert body["rows"][0]["backlog_age_hours"] >= 24


def test_a_negative_minimum_age_is_rejected(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    assert revisions_queue(client, token, min_age_hours=-1).status_code == 422


# --- criterion 3: the same guarantees as the candidate queue --------------------------------------


def test_the_revision_ordering_is_a_total_order() -> None:
    """Structural, for the reason `test_the_ordering_is_a_total_order` records: a small tied set
    often comes back stably whether or not you asked for a total order."""
    from sqlalchemy import select

    from app.drafts_and_approvals.api import REVISION_ORDER

    compiled = str(select(MessageRevision.id).order_by(*REVISION_ORDER))

    assert "message_revision.updated_at ASC" in compiled
    assert "message_revision.id ASC" in compiled


def test_revision_pagination_covers_every_row_exactly_once(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    for candidate in world.in_review:
        make_revision(db_session_for_api, candidate, world)
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    seen: list[str] = []
    for offset in (0, 2):
        body = revisions_queue(client, token, limit=2, offset=offset).json()
        seen.extend(row["revision_id"] for row in body["rows"])

    assert len(seen) == 3
    assert len(set(seen)) == 3


def test_every_revision_row_carries_a_record_version(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    revision = make_revision(db_session_for_api, world.in_review[0], world)
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = revisions_queue(client, token).json()

    db_session_for_api.refresh(revision)
    assert datetime.fromisoformat(body["rows"][0]["record_version"]) == revision.updated_at


def test_the_revision_page_size_is_capped(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    assert revisions_queue(client, token, limit=1000).status_code == 422


def test_a_revision_row_does_not_carry_the_message_body(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """A queue is for choosing what to open. A list showing the whole message would invite
    approving from the list, and the card is `T-064`."""
    make_revision(db_session_for_api, world.in_review[0], world)
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = revisions_queue(client, token).json()

    for row in body["rows"]:
        assert "body" not in row
        assert "approved_claim_ids" not in row
        assert "evidence_ids" not in row


def test_a_revision_without_a_qualification_run_still_appears(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """Reported as unknown rather than dropped: hiding work from a reviewer is worse than
    showing it with a missing field."""
    make_revision(db_session_for_api, world.in_review[0], world, opportunity_type=None)
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = revisions_queue(client, token).json()

    assert body["total"] == 1
    assert body["rows"][0]["opportunity_type"] is None


# --- T-149: the review card's data (§12.3 items 1-5) ---------------------------------------------


def detail(client: TestClient, token: str | None, candidate_id: object) -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get(f"/api/review/candidates/{candidate_id}", headers=headers)


def add_evidence(
    session: Session,
    candidate: CampaignCandidate,
    *,
    quality: SourceQuality,
    excerpt: str,
    retrieved_at: object = None,
) -> EvidenceSnapshot:
    snapshot = EvidenceSnapshot(
        candidate_id=candidate.id,
        source_type=SourceType.SYNTHETIC_FIXTURE,
        retrieved_at=retrieved_at or NOW,
        supporting_excerpt_or_fact=excerpt,
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        extraction_method=ExtractionMethod.STRUCTURED_FIELD,
        source_quality=quality,
        license_and_retention_class=RetentionClass.PUBLIC_UNRESTRICTED,
        contains_personal_or_confidential_data=False,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def add_readiness_and_claim(session: Session, world: World) -> ApprovedClaim:
    from app.products_and_claims.status import next_version_number

    session.add(
        ProductStatusVersion(
            product_id=world.product.id,
            version=next_version_number(session, world.product.id),
            readiness_category=ReadinessCategory.EVALUATION_OR_PILOT,
            summary="SYNTHETIC placeholder readiness.",
            approved_by=APPROVER,
            approved_at=NOW - timedelta(days=1),
            effective_from=NOW - timedelta(days=1),
            expires_or_review_by=None,
        )
    )
    claim = ApprovedClaim(
        claim_key="SYNTHETIC-CLAIM-review-card",
        version=1,
        product_id=world.product.id,
        text="SYNTHETIC EXAMPLE CLAIM — approved by nobody, never for a real recipient.",
        approved_by=APPROVER,
        approved_at=NOW - timedelta(days=1),
        effective_from=NOW - timedelta(days=1),
        expires_or_review_by=NOW + timedelta(days=90),
    )
    session.add(claim)
    session.flush()
    session.add(ApprovedClaimCampaign(claim_id=claim.id, campaign_id=world.campaign.id))
    session.flush()
    return claim


# --- criterion 5: authorization and the missing case ---------------------------------------------


def test_the_detail_endpoint_refuses_an_unauthenticated_request(
    client: TestClient, world: World
) -> None:
    assert client.get(f"/api/review/candidates/{world.in_review[0].id}").status_code == 401


def test_the_detail_endpoint_refuses_a_session_without_the_role(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api)

    assert detail(client, token, world.in_review[0].id).status_code == 403


def test_an_unknown_candidate_is_404(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    assert detail(client, token, uuid.uuid4()).status_code == 404


def test_a_malformed_candidate_id_is_422(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """Not a 404: "you sent nonsense" and "that does not exist" are different answers."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    assert detail(client, token, "not-a-uuid").status_code == 422


# --- criterion 1: item 1, who this is ------------------------------------------------------------


def test_the_card_identifies_the_account_contact_campaign_and_opportunity(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """§12.3 item 1."""
    candidate = world.in_review[0]
    db_session_for_api.add(_qualification_run(db_session_for_api, candidate, "pilot"))
    db_session_for_api.flush()
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, candidate.id).json()

    assert body["account_name"] == world.account.name
    assert body["account_domain"] == world.account.domain
    assert body["campaign_name"] == world.campaign.name
    assert body["contact_name"] == world.contacts[0].full_name
    assert body["opportunity_type"] == "pilot"
    assert body["state"] == CampaignCandidateState.REVIEW_PENDING.value


def test_an_unqualified_candidate_reports_no_opportunity_type(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    assert body["opportunity_type"] is None


# --- criterion 2: item 2, evidence with provenance -----------------------------------------------


def test_evidence_rows_carry_source_quality_and_retrieval_time(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """§12.3 item 2 names both. A fact is only as good as where it came from and when."""
    candidate = world.in_review[0]
    add_evidence(db_session_for_api, candidate, quality=SourceQuality.MEDIUM, excerpt="SYNTHETIC A")
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, candidate.id).json()

    assert len(body["evidence"]) == 1
    row = body["evidence"][0]
    assert row["source_quality"] == "medium"
    assert row["retrieved_at"]
    assert row["excerpt"] == "SYNTHETIC A"


def test_the_strongest_evidence_comes_first(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """§12.3 item 2 says "strongest evidence". A card led by whatever the database returned
    first would make a reviewer hunt for the reason to act."""
    candidate = world.in_review[0]
    add_evidence(db_session_for_api, candidate, quality=SourceQuality.LOW, excerpt="SYNTHETIC low")
    add_evidence(
        db_session_for_api, candidate, quality=SourceQuality.HIGH, excerpt="SYNTHETIC high"
    )
    add_evidence(
        db_session_for_api, candidate, quality=SourceQuality.MEDIUM, excerpt="SYNTHETIC medium"
    )
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, candidate.id).json()

    assert [row["source_quality"] for row in body["evidence"]] == ["high", "medium", "low"]


def test_evidence_of_equal_quality_is_newest_first(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    candidate = world.in_review[0]
    add_evidence(
        db_session_for_api,
        candidate,
        quality=SourceQuality.HIGH,
        excerpt="SYNTHETIC older",
        retrieved_at=NOW - timedelta(days=2),
    )
    add_evidence(
        db_session_for_api,
        candidate,
        quality=SourceQuality.HIGH,
        excerpt="SYNTHETIC newer",
        retrieved_at=NOW - timedelta(hours=1),
    )
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, candidate.id).json()

    assert [row["excerpt"] for row in body["evidence"]] == ["SYNTHETIC newer", "SYNTHETIC older"]


def test_a_candidate_with_no_evidence_reports_an_empty_list(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """GP-02: missing facts remain missing. An empty list is the honest answer, and a reviewer
    seeing one knows there is nothing to act on."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    assert body["evidence"] == []


# --- criterion 1: item 3, readiness and claims ---------------------------------------------------


def test_the_card_shows_product_readiness_and_approved_claims(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """§12.3 item 3."""
    claim = add_readiness_and_claim(db_session_for_api, world)
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    assert body["product_readiness"] == ReadinessCategory.EVALUATION_OR_PILOT.value
    assert body["product_readiness_summary"]
    assert [row["claim_key"] for row in body["approved_claims"]] == [claim.claim_key]
    assert body["approved_claims"][0]["text"] == claim.text


def test_a_product_with_no_readiness_reports_none_rather_than_a_guess(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """GP-12: technical relevance is not availability. Absent readiness is `null`, never a
    default — a card that implied availability would be the worst possible default."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    assert body["product_readiness"] is None
    assert body["approved_claims"] == []


# --- criterion 3 and 4: item 4, suppression and CRM ----------------------------------------------


def test_an_unsuppressed_candidate_is_not_flagged(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    assert body["suppression"] == {"contact_suppressed": False, "account_suppressed": False}


def test_a_suppressed_contact_is_flagged(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """§12.3 item 4. A reviewer must see this before acting, not after."""
    from app.prospects.suppression import Suppression, SuppressionScope, SuppressionSource

    db_session_for_api.add(
        Suppression(
            scope=SuppressionScope.PERSON,
            identity=str(world.contacts[0].id),
            source=SuppressionSource.UNSUBSCRIBE,
            reason="SYNTHETIC: suppressed for a test",
            effective_at=NOW - timedelta(days=1),
        )
    )
    db_session_for_api.flush()
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    assert body["suppression"]["contact_suppressed"] is True


def test_the_crm_relationship_is_reported_as_unknown(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """Criterion 4, and the reason is worth stating: there is no CRM adapter. ADR-004 makes
    HubSpot conditional on `Q-001` and gate **G-05** is locked, so `null` means *nobody asked a
    CRM*. Reporting "no relationship" would be an answer this system cannot give, and a reviewer
    might act on it."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    assert body["crm_relationship"] is None


# --- criterion 1: item 5, the exact revision and what happens next -------------------------------


def test_the_card_shows_the_exact_revision(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """§12.3 item 5, and ADR-008's requirement: approving without seeing exactly what will be
    sent is the failure the whole approval model exists to prevent. Unlike the queue row, this
    carries the body."""
    candidate = world.in_review[0]
    revision = make_revision(db_session_for_api, candidate, world)
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, candidate.id).json()

    assert body["current_revision"]["revision_id"] == str(revision.id)
    assert body["current_revision"]["body"] == "SYNTHETIC body."
    assert body["current_revision"]["content_hash"] == revision.content_hash


def test_a_candidate_with_no_revision_reports_none(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    assert body["current_revision"] is None


def test_the_card_says_nothing_will_be_sent(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """Shadow mode sends nothing (§19.6, gate **G-07**). A card that did not say so would let a
    reviewer believe they had just sent an email."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    assert "Nothing is sent" in body["what_happens_next"]
    assert "shadow mode" in body["what_happens_next"]
    assert "G-07" in body["what_happens_next"]


def test_the_card_names_what_approving_produces_only_one_way(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """`T-215` criterion 1, the half that lives on this side of the wire.

    This sentence and the dashboard's approve form both name the thing approval produces, and they
    named it differently: "queues a draft" one section above "creates no outbound message". Both
    accurate, and read together a contradiction — a reader has no way to know the two nouns are
    two objects. One of the rehearsal readers reconstructed the distinction and said they were not
    certain they had it right, which is the worst state to leave somebody in about whether they
    have just sent an email.

    The frontend half is `frontend/tests/reviewer-vocabulary.test.ts`; neither test can see the
    other's string, which is exactly why the two sentences drifted apart.
    """
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    sentence = detail(client, token, world.in_review[0].id).json()["what_happens_next"]

    assert "draft" in sentence
    for alternate in ("outbound message", "outbound email", "outgoing message"):
        assert alternate not in sentence.lower(), (
            f"the card calls the product of approval a draft and also a {alternate!r}; two nouns "
            f"for one object is what T-215 removed"
        )

    # Having removed the second noun, the first has to carry the meaning alone.
    assert "delivered to nobody" in sentence


def test_the_card_offers_no_actions(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """§12.3 items 6 and 7 are things a reviewer *does*, and this endpoint returns nothing that
    does anything. A read endpoint shipping an action list would describe authority it does not
    enforce; `T-065` onwards owns the mutations."""
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, world.in_review[0].id).json()

    for absent in ("actions", "available_actions", "correction_reasons", "approve_url"):
        assert absent not in body


def test_the_card_carries_a_record_version(
    client: TestClient, db_session_for_api: Session, world: World
) -> None:
    """The same optimistic-concurrency stamp the queue returns, so a mutation built on this card
    compares the same value."""
    candidate = world.in_review[0]
    token = sign_in(db_session_for_api, RoleKey.OPERATOR_REVIEWER)

    body = detail(client, token, candidate.id).json()

    db_session_for_api.refresh(candidate)
    assert datetime.fromisoformat(body["record_version"]) == candidate.updated_at
