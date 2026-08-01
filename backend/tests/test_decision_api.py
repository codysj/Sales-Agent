"""The reject and defer endpoints (T-066b1; §10.6, §12.3 item 7, §15.1, §8.2).

`T-066a` proved the decisions; this proves the *route* — which is a different set of failures.
An endpoint can call a correct function and still accept a category nobody defined, apply a
decision to state the reviewer never read, or let a browser be tricked into deciding.

Four things:

* **The decision reaches the database through HTTP.** Asserted end to end, because a response
  body that echoes the request proves only that the request was parsed.
* **The schema refuses a bad category before any handler runs.** `DecisionCategory` is a typed
  field, so this is one guard for both routes rather than one check each — and the test asserts
  `422`, not merely "not 200", since a `500` would also be "not 200" and would mean the opposite.
* **A deferral with no waypoint is refused.** `T-066a` refuses it in two places already; this
  checks the route turns that into an answer a dashboard can show rather than a `500`.
* **Both routes need the permission and refuse a cookie.** Mutations do, until `T-070`.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import create_candidate, transition
from app.campaigns.decisions import CandidateDecision, DecisionCategory, DecisionKind
from app.campaigns.models import Campaign
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import publish_policy_version
from app.core.lifecycles import CampaignCandidateState
from app.db.session import dispose_engines
from app.identity.dependencies import SESSION_COOKIE, db_session
from app.identity.models import Role, RoleKey, User, UserRole
from app.identity.rbac import PERMISSION_TIERS, Permission, Tier, permission_for
from app.identity.sessions import issue_session
from app.jobs_and_outbox.models import Job
from app.jobs_and_outbox.registry import registry as default_registry
from app.main import create_app
from app.products_and_claims.models import Product
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)
from app.research_and_evidence import jobs as research_jobs
from tests.factories import NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-decision-api-test")


@pytest.fixture
def db_session_for_api(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def client(db_session_for_api: Session) -> Iterator[TestClient]:
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session] = lambda: db_session_for_api
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    dispose_engines()


def a_user(session: Session, role: RoleKey) -> User:
    user = User(
        email=f"synthetic.{uuid.uuid4().hex[:8]}@example.com",
        display_name="SYNTHETIC User",
        active=True,
    )
    session.add(user)
    session.flush()
    found = session.execute(select(Role).where(Role.key == role.value)).scalar_one()
    session.add(UserRole(user_id=user.id, role_id=found.id, granted_by="synthetic-admin"))
    session.flush()
    return user


@pytest.fixture
def reviewer_token(db_session: Session) -> str:
    return issue_session(
        db_session, a_user(db_session, RoleKey.OPERATOR_REVIEWER), issued_via="test"
    ).token


@pytest.fixture
def headers(reviewer_token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {reviewer_token}"}


class World:
    """One candidate in review."""

    def __init__(self, session: Session) -> None:
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
        publish_policy_version(
            session,
            campaign_id=self.campaign.id,
            policy=CampaignPolicy(),
            approved_by="approver-1",
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


def reject_url(world: World) -> str:
    return f"/api/review/candidates/{world.candidate.id}/reject"


def defer_url(world: World) -> str:
    return f"/api/review/candidates/{world.candidate.id}/defer"


# --- criterion 1: rejecting over HTTP records the category and moves the candidate ----------------


def test_rejecting_records_the_decision(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    """End to end: the row in the database, not the echo in the response."""
    response = client.post(
        reject_url(world),
        json={"category": "poor_buyer_role", "notes": "SYNTHETIC: runs facilities."},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    stored = db_session.execute(select(CandidateDecision)).scalars().all()
    assert len(stored) == 1
    assert stored[0].category is DecisionCategory.POOR_BUYER_ROLE
    assert stored[0].kind is DecisionKind.REJECT
    assert stored[0].notes == "SYNTHETIC: runs facilities."


def test_rejecting_moves_the_candidate(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    client.post(reject_url(world), json={"category": "wrong_campaign"}, headers=headers)

    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.REJECTED


def test_the_response_reports_what_was_recorded(
    client: TestClient, world: World, headers: dict[str, str]
) -> None:
    """So a dashboard can show the decision back rather than assume it landed."""
    body = client.post(
        reject_url(world), json={"category": "unsupported_claim"}, headers=headers
    ).json()

    assert body["category"] == "unsupported_claim"
    assert body["kind"] == "reject"
    assert body["state"] == "rejected"
    assert body["candidate_id"] == str(world.candidate.id)


def test_supplying_an_actor_is_refused_rather_than_ignored(
    client: TestClient, world: World, headers: dict[str, str]
) -> None:
    """`extra="forbid"`. Silently ignoring the field is what makes someone believe it was
    honoured; §12.2 wants attribution the caller could not choose."""
    response = client.post(
        reject_url(world),
        json={"category": "wrong_campaign", "actor": "somebody-else"},
        headers=headers,
    )

    assert response.status_code == 422


def test_the_actor_comes_from_the_session(
    client: TestClient, db_session: Session, world: World, reviewer_token: str
) -> None:
    """The recorded actor is the session's user, not anything the request said."""
    signed_in = db_session.execute(select(User).order_by(User.created_at.desc())).scalars().first()
    assert signed_in is not None

    client.post(
        reject_url(world),
        json={"category": "wrong_campaign"},
        headers={"authorization": f"Bearer {reviewer_token}"},
    )

    decision = db_session.execute(select(CandidateDecision)).scalars().one()
    assert decision.decided_by == str(signed_in.id)
    assert decision.decided_by_type == ActorType.HUMAN.value


def test_rejecting_outside_review_is_a_conflict(
    client: TestClient, world: World, headers: dict[str, str]
) -> None:
    """§8.2 offers `review_pending -> rejected` and no other edge. `409`, not `500`."""
    client.post(reject_url(world), json={"category": "wrong_campaign"}, headers=headers)

    again = client.post(reject_url(world), json={"category": "wrong_campaign"}, headers=headers)

    assert again.status_code == 409
    assert "review_pending" in again.json()["detail"]


def test_an_unknown_candidate_is_404(
    client: TestClient, world: World, headers: dict[str, str]
) -> None:
    response = client.post(
        f"/api/review/candidates/{uuid.uuid4()}/reject",
        json={"category": "wrong_campaign"},
        headers=headers,
    )

    assert response.status_code == 404


def test_a_stale_record_version_is_refused(
    client: TestClient, world: World, headers: dict[str, str]
) -> None:
    """A reviewer rejecting a candidate somebody else already moved is a race worth losing
    loudly."""
    response = client.post(
        reject_url(world),
        json={"category": "wrong_campaign", "record_version": "2020-01-01T00:00:00Z"},
        headers=headers,
    )

    assert response.status_code == 409
    assert "reload" in response.json()["detail"]


# --- criterion 2: a bad category is refused by the schema -----------------------------------------


def test_no_category_is_refused_by_the_schema(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    response = client.post(reject_url(world), json={}, headers=headers)

    # `422`, not merely "not 200": a `500` would also be "not 200" and would mean the opposite.
    assert response.status_code == 422
    assert db_session.execute(select(func.count()).select_from(CandidateDecision)).scalar_one() == 0


def test_a_category_outside_the_eleven_is_refused_by_the_schema(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    response = client.post(
        reject_url(world), json={"category": "had_a_bad_feeling"}, headers=headers
    )

    assert response.status_code == 422
    assert db_session.execute(select(func.count()).select_from(CandidateDecision)).scalar_one() == 0


def test_a_refused_request_leaves_the_candidate_in_review(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    client.post(reject_url(world), json={"category": "had_a_bad_feeling"}, headers=headers)

    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


@pytest.mark.parametrize("category", [category.value for category in DecisionCategory])
def test_every_specification_category_is_accepted(
    client: TestClient, world: World, headers: dict[str, str], category: str
) -> None:
    """All eleven, not one of them. A schema that accepted only the categories somebody thought
    to test would refuse a reviewer's real answer."""
    response = client.post(reject_url(world), json={"category": category}, headers=headers)

    # The deferral category is refused as a *rejection* reason (`T-066a`), which is a `409` —
    # a decision the domain made, not the schema rejecting the value.
    expected = 409 if category == DecisionCategory.DEFER_UNTIL_DATE_OR_EVENT.value else 200
    assert response.status_code == expected, response.text


# --- criterion 3: a deferral needs a waypoint -----------------------------------------------------


def test_deferring_with_a_date(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    until = (NOW + timedelta(days=60)).date().isoformat()

    response = client.post(defer_url(world), json={"until_date": until}, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["defer_until_date"] == until
    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.DEFERRED


def test_deferring_with_an_event(client: TestClient, world: World, headers: dict[str, str]) -> None:
    response = client.post(
        defer_url(world),
        json={"until_event": "SYNTHETIC: when they publish their storage roadmap"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["defer_until_event"] == (
        "SYNTHETIC: when they publish their storage roadmap"
    )


def test_deferring_with_neither_is_a_conflict(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    """The route turns `T-066a`'s refusal into an answer a dashboard can show, not a `500`."""
    response = client.post(defer_url(world), json={}, headers=headers)

    assert response.status_code == 409
    assert "date or an event" in response.json()["detail"]
    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_a_deferral_may_name_a_more_specific_category(
    client: TestClient, world: World, headers: dict[str, str]
) -> None:
    body = client.post(
        defer_url(world),
        json={"until_event": "SYNTHETIC: when the pilot ships", "category": "product_not_ready"},
        headers=headers,
    ).json()

    assert body["category"] == "product_not_ready"


def test_a_deferral_defaults_to_the_eleventh_category(
    client: TestClient, world: World, headers: dict[str, str]
) -> None:
    body = client.post(
        defer_url(world), json={"until_date": date(2026, 12, 1).isoformat()}, headers=headers
    ).json()

    assert body["category"] == "defer_until_date_or_event"


# --- criterion 4: permission, and no cookie authentication ----------------------------------------


@pytest.mark.parametrize("path", ["reject", "defer"])
def test_a_cookie_cannot_authenticate_a_decision(
    client: TestClient, db_session: Session, world: World, reviewer_token: str, path: str
) -> None:
    """Both routes. A CSRF attack rides on credentials the browser attaches by itself; `T-070`
    adds real protection and until then the exposure is removed rather than accepted."""
    client.cookies.set(SESSION_COOKIE, reviewer_token)

    response = client.post(
        f"/api/review/candidates/{world.candidate.id}/{path}",
        json={"category": "wrong_campaign", "until_event": "SYNTHETIC: later"},
        headers={},
    )

    assert response.status_code == 401
    assert db_session.execute(select(func.count()).select_from(CandidateDecision)).scalar_one() == 0


@pytest.mark.parametrize("path", ["reject", "defer"])
def test_no_session_is_401(client: TestClient, world: World, path: str) -> None:
    response = client.post(
        f"/api/review/candidates/{world.candidate.id}/{path}",
        json={"category": "wrong_campaign", "until_event": "SYNTHETIC: later"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize("path", ["reject", "defer"])
def test_a_role_without_the_permission_is_forbidden(
    client: TestClient, db_session: Session, world: World, path: str
) -> None:
    """`403`, not `401`: signing in again will not help, and sending them round a login loop
    would be worse than telling them."""
    token = issue_session(db_session, a_user(db_session, RoleKey.VIEWER), issued_via="test").token

    response = client.post(
        f"/api/review/candidates/{world.candidate.id}/{path}",
        json={"category": "wrong_campaign", "until_event": "SYNTHETIC: later"},
        headers={"authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert "correct_candidate" in response.json()["detail"]


# --- T-154a: contact points on the detail, and the approve endpoint -------------------------------
#
# The first tier-4 endpoint in the repository. §7.4 calls `APPROVE_CANDIDATE` the approval that
# lets an external effect happen at all, so three things are worth proving separately from the
# tier-3 decisions above: that the reviewer is *shown* the addresses (ADR-008 approves an exact
# recipient, and one nobody saw is one nobody approved), that an address belonging to somebody
# else is refused, and that the permission is genuinely a different one.


def approve_url(world: World) -> str:
    return f"/api/review/candidates/{world.candidate.id}/approve"


def a_contact_point(
    session: Session,
    contact_id: uuid.UUID,
    *,
    verified: bool = True,
    value: str | None = None,
) -> ContactPoint:
    point = ContactPoint(
        contact_id=contact_id,
        type=ContactPointType.EMAIL,
        value=value or f"{uuid.uuid4().hex[:8]}@example.com",
        verification_state=(
            VerificationState.VERIFIED if verified else VerificationState.UNVERIFIED
        ),
    )
    session.add(point)
    session.flush()
    return point


@pytest.fixture
def approver_headers(db_session: Session) -> dict[str, str]:
    """A session holding `APPROVE_CANDIDATE`.

    The operator/reviewer, because §12.1 gives candidate review to that role and `ROLE_GRANTS`
    holds it there alone. Named separately from `headers` even though it resolves to the same role
    today: what these tests need is the *permission*, and the day the matrix separates them this
    fixture is the line that changes.
    """
    token = issue_session(
        db_session, a_user(db_session, RoleKey.OPERATOR_REVIEWER), issued_via="test"
    ).token
    return {"authorization": f"Bearer {token}"}


def detail_url(world: World) -> str:
    return f"/api/review/candidates/{world.candidate.id}"


# --- criterion 1: the detail returns the contact points -------------------------------------------


def test_the_detail_returns_the_contact_points(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    """ADR-008 approves an exact recipient, so the reviewer has to be shown the choices."""
    point = a_contact_point(db_session, world.contact.id)

    body = client.get(detail_url(world), headers=headers).json()

    assert [row["contact_point_id"] for row in body["contact_points"]] == [str(point.id)]
    assert body["contact_points"][0]["value"] == point.value
    assert body["contact_points"][0]["verification_state"] == "verified"
    assert body["contact_points"][0]["approvable"] is True


def test_an_unverified_point_is_shown_and_marked_unapprovable(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    """Shown and refused, not hidden. A reviewer who cannot see the mailbox they expected cannot
    tell "unusable" from "the system does not know about it", and those want different actions."""
    a_contact_point(db_session, world.contact.id, verified=False)

    body = client.get(detail_url(world), headers=headers).json()

    assert len(body["contact_points"]) == 1
    assert body["contact_points"][0]["verification_state"] == "unverified"
    assert body["contact_points"][0]["approvable"] is False


def test_a_candidate_with_no_contact_points_returns_an_empty_list(
    client: TestClient, world: World, headers: dict[str, str]
) -> None:
    body = client.get(detail_url(world), headers=headers).json()

    assert body["contact_points"] == []


def test_the_contact_points_are_deterministically_ordered(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    """A list that reordered itself would move the option under a reviewer's cursor between
    renders -- which, for a choice that authorizes outreach, is the wrong kind of surprise."""
    a_contact_point(db_session, world.contact.id, value="zulu@example.com")
    a_contact_point(db_session, world.contact.id, value="alpha@example.com")

    first = client.get(detail_url(world), headers=headers).json()
    second = client.get(detail_url(world), headers=headers).json()

    assert [row["value"] for row in first["contact_points"]] == [
        "alpha@example.com",
        "zulu@example.com",
    ]
    assert first["contact_points"] == second["contact_points"]


def test_another_contacts_points_are_not_listed(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    """§8.1 scopes a candidate to one contact. Listing somebody else's address would offer an
    approver a recipient this candidate was never about."""
    mine = a_contact_point(db_session, world.contact.id)
    stranger = Contact(account_id=world.account.id, full_name="SYNTHETIC Other")
    db_session.add(stranger)
    db_session.flush()
    a_contact_point(db_session, stranger.id)

    body = client.get(detail_url(world), headers=headers).json()

    assert [row["contact_point_id"] for row in body["contact_points"]] == [str(mine.id)]


# --- criterion 2: approving names a recipient, and a stranger's is refused ------------------------


def test_approving_names_the_chosen_recipient(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    point = a_contact_point(db_session, world.contact.id)

    response = client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(point.id)},
        headers=approver_headers,
    )

    assert response.status_code == 200, response.text
    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.APPROVED
    # The address echoed back, not only its id: an approval confirmed as a UUID is an approval
    # nobody can check by reading.
    assert response.json()["recipient"] == point.value


def test_approving_queues_the_drafting_job(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """§8.3 step 9. The recipient the approver chose is the one the job carries."""
    point = a_contact_point(db_session, world.contact.id)

    client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(point.id)},
        headers=approver_headers,
    )

    job = db_session.execute(select(Job).where(Job.job_type == "drafts.draft_message")).scalar_one()
    assert job.payload["recipient_contact_point_id"] == str(point.id)


def test_another_contacts_recipient_is_refused(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """A contact point id is just a UUID. Without this check an approver could name an address
    belonging to somebody else and the drafting job would write to it."""
    stranger = Contact(account_id=world.account.id, full_name="SYNTHETIC Other")
    db_session.add(stranger)
    db_session.flush()
    theirs = a_contact_point(db_session, stranger.id)

    response = client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(theirs.id)},
        headers=approver_headers,
    )

    assert response.status_code == 404
    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_an_unknown_recipient_and_a_strangers_are_indistinguishable(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """Distinguishing them would let a caller probe which contact point ids exist."""
    stranger = Contact(account_id=world.account.id, full_name="SYNTHETIC Other")
    db_session.add(stranger)
    db_session.flush()
    theirs = a_contact_point(db_session, stranger.id)

    missing = client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(uuid.uuid4())},
        headers=approver_headers,
    )
    foreign = client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(theirs.id)},
        headers=approver_headers,
    )

    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json()


def test_a_refused_approval_queues_nothing(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(uuid.uuid4())},
        headers=approver_headers,
    )

    queued = db_session.execute(
        select(func.count()).select_from(Job).where(Job.job_type == "drafts.draft_message")
    ).scalar_one()
    assert queued == 0


def test_no_recipient_is_refused_by_the_schema(
    client: TestClient, world: World, approver_headers: dict[str, str]
) -> None:
    """No default and no derivation: the address is part of the approver's decision."""
    response = client.post(approve_url(world), json={}, headers=approver_headers)

    assert response.status_code == 422


def test_approving_outside_review_is_a_conflict(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    point = a_contact_point(db_session, world.contact.id)
    client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(point.id)},
        headers=approver_headers,
    )

    again = client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(point.id)},
        headers=approver_headers,
    )

    assert again.status_code == 409


def test_a_stale_record_version_is_refused_on_approval(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    point = a_contact_point(db_session, world.contact.id)

    response = client.post(
        approve_url(world),
        json={
            "recipient_contact_point_id": str(point.id),
            "record_version": "2020-01-01T00:00:00Z",
        },
        headers=approver_headers,
    )

    assert response.status_code == 409
    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


# --- criterion 3: an unverified address cannot be approved ----------------------------------------


def test_an_unverified_recipient_is_refused(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """Approving one would put the reputation risk ADR-008 exists to manage onto a guess about
    whether the mailbox is real."""
    point = a_contact_point(db_session, world.contact.id, verified=False)

    response = client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(point.id)},
        headers=approver_headers,
    )

    assert response.status_code == 409
    assert "unverified" in response.json()["detail"]
    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_an_unverified_recipient_queues_nothing(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    point = a_contact_point(db_session, world.contact.id, verified=False)

    client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(point.id)},
        headers=approver_headers,
    )

    queued = db_session.execute(
        select(func.count()).select_from(Job).where(Job.job_type == "drafts.draft_message")
    ).scalar_one()
    assert queued == 0


# --- criterion 4: tier 4, and no cookie -----------------------------------------------------------


def test_the_route_is_declared_at_tier_four() -> None:
    """Structural, because behaviour cannot show this today: `ROLE_GRANTS` gives both
    `CORRECT_CANDIDATE` and `APPROVE_CANDIDATE` to the operator/reviewer alone, so no role exists
    that would be allowed one and refused the other. The declaration is what keeps approval from
    quietly becoming a tier-3 action — §7.4 puts it at tier 4 because it is the approval that
    lets an external effect happen at all."""
    declared = permission_for("POST", "/api/review/candidates/{candidate_id}/approve")

    assert declared is Permission.APPROVE_CANDIDATE
    assert PERMISSION_TIERS[Permission.APPROVE_CANDIDATE] is Tier.EXTERNAL_COMMUNICATION
    # And the two decisions above are *not* the same permission.
    assert (
        permission_for("POST", "/api/review/candidates/{candidate_id}/reject")
        is Permission.CORRECT_CANDIDATE
    )


def test_a_role_without_the_approval_permission_is_refused(
    client: TestClient, db_session: Session, world: World
) -> None:
    """The campaign/sales owner may manage a campaign and read the queue, and must not be able to
    start outreach."""
    point = a_contact_point(db_session, world.contact.id)
    token = issue_session(
        db_session, a_user(db_session, RoleKey.CAMPAIGN_SALES_OWNER), issued_via="test"
    ).token

    response = client.post(
        approve_url(world),
        json={"recipient_contact_point_id": str(point.id)},
        headers={"authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert "approve_candidate" in response.json()["detail"]
    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_a_cookie_cannot_authenticate_an_approval(
    client: TestClient, db_session: Session, world: World
) -> None:
    point = a_contact_point(db_session, world.contact.id)
    token = issue_session(
        db_session, a_user(db_session, RoleKey.OPERATOR_REVIEWER), issued_via="test"
    ).token
    client.cookies.set(SESSION_COOKIE, token)

    response = client.post(
        approve_url(world), json={"recipient_contact_point_id": str(point.id)}, headers={}
    )

    assert response.status_code == 401
    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_no_session_cannot_approve(client: TestClient, db_session: Session, world: World) -> None:
    point = a_contact_point(db_session, world.contact.id)

    response = client.post(approve_url(world), json={"recipient_contact_point_id": str(point.id)})

    assert response.status_code == 401


# --- T-155: the request-more-research endpoint (ADR-022) ------------------------------------------
#
# `T-153` proved the decision and the job. This proves the route, and the property that separates
# this action from every other decision on the card: it moves the candidate **nowhere**.


def research_url(world: World) -> str:
    return f"/api/review/candidates/{world.candidate.id}/request-research"


@pytest.fixture(autouse=True)
def _research_job_types() -> Iterator[None]:
    """The recapture job type, registered as a worker registers it.

    `request_more_research` enqueues through `queue.enqueue`, which resolves the payload model from
    the default registry — without this the endpoint raises `UnknownJobType` and the tests would be
    about that instead. Snapshot and restore: the registry is process-wide.
    """
    preexisting = dict(default_registry._types)
    research_jobs.register(default_registry)
    try:
        yield
    finally:
        default_registry._types.clear()
        default_registry._types.update(preexisting)


def test_requesting_more_research_records_the_category(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    response = client.post(
        research_url(world),
        json={
            "category": "weak_or_stale_evidence",
            "notes": "SYNTHETIC: evidence is two years old.",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    stored = (
        db_session.execute(
            select(CandidateDecision).where(CandidateDecision.kind == DecisionKind.REQUEST_RESEARCH)
        )
        .scalars()
        .all()
    )
    assert len(stored) == 1
    assert stored[0].category is DecisionCategory.WEAK_OR_STALE_EVIDENCE
    assert stored[0].notes == "SYNTHETIC: evidence is two years old."


def test_requesting_more_research_queues_one_pass(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    client.post(research_url(world), json={"category": "weak_or_stale_evidence"}, headers=headers)

    queued = db_session.execute(
        select(func.count()).select_from(Job).where(Job.job_type == "research.recapture_evidence")
    ).scalar_one()
    assert queued == 1


def test_the_candidate_stays_in_review(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    """ADR-022's decision, at the route. §8.2 offers no edge back to `research_pending`, and the
    card the reviewer is reading must not vanish from the queue underneath them."""
    body = client.post(
        research_url(world), json={"category": "weak_or_stale_evidence"}, headers=headers
    ).json()

    assert body["state"] == "review_pending"
    db_session.refresh(world.candidate)
    assert world.candidate.state is CampaignCandidateState.REVIEW_PENDING


def test_a_second_request_while_one_is_in_flight_is_a_conflict(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    """A reviewer who clicks twice wants one more pass, not two — and the route turns `T-153`'s
    refusal into an answer a dashboard can show rather than a `500`."""
    client.post(research_url(world), json={"category": "weak_or_stale_evidence"}, headers=headers)

    again = client.post(
        research_url(world), json={"category": "weak_or_stale_evidence"}, headers=headers
    )

    assert again.status_code == 409
    assert "already in flight" in again.json()["detail"]
    queued = db_session.execute(
        select(func.count()).select_from(Job).where(Job.job_type == "research.recapture_evidence")
    ).scalar_one()
    assert queued == 1


def test_research_without_a_category_is_refused_by_the_schema(
    client: TestClient, db_session: Session, world: World, headers: dict[str, str]
) -> None:
    response = client.post(research_url(world), json={}, headers=headers)

    assert response.status_code == 422
    assert db_session.execute(select(func.count()).select_from(CandidateDecision)).scalar_one() == 0


def test_requesting_outside_review_is_a_conflict(
    client: TestClient, world: World, headers: dict[str, str]
) -> None:
    client.post(reject_url(world), json={"category": "wrong_campaign"}, headers=headers)

    response = client.post(
        research_url(world), json={"category": "weak_or_stale_evidence"}, headers=headers
    )

    assert response.status_code == 409


def test_a_cookie_cannot_authenticate_a_research_request(
    client: TestClient, db_session: Session, world: World, reviewer_token: str
) -> None:
    client.cookies.set(SESSION_COOKIE, reviewer_token)

    response = client.post(
        research_url(world), json={"category": "weak_or_stale_evidence"}, headers={}
    )

    assert response.status_code == 401
    assert db_session.execute(select(func.count()).select_from(CandidateDecision)).scalar_one() == 0


def test_a_role_without_the_permission_is_refused_research(
    client: TestClient, db_session: Session, world: World
) -> None:
    token = issue_session(db_session, a_user(db_session, RoleKey.VIEWER), issued_via="test").token

    response = client.post(
        research_url(world),
        json={"category": "weak_or_stale_evidence"},
        headers={"authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
