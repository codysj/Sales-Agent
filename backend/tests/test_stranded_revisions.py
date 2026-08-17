"""A draft nobody can approve is visible to somebody (T-209; §7.5, §8.2, §12.3).

`T-071d` found this with three readers and no repository access. The sequence is short and every
step of it is correct on its own: a reviewer edits a draft, the edit supersedes the revision that
could have been approved, the new revision fails validation — and the candidate is then in
**neither** list. The review queue shows `review_pending`. The attention page showed approvals.
Two of the three runs reached that state, and the page §7.5 built for exactly this said
*"Nothing needs attention"*.

So the assertions here are about **absence being noticed**, which is the hard half:

* a stranded candidate is listed, and the failing checks come with it;
* the checks are still there on the next request, because the response that produced them is gone
  by the time anyone reloads;
* a candidate that was rescued by a further edit is **not** listed, since burying the stranded
  ones under the recovered ones is the same failure wearing a different hat.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.lifecycles import MessageRevisionState
from app.db.session import dispose_engines
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.editing import edit_revision
from app.identity.dependencies import db_session as db_session_dependency
from app.identity.models import Role, RoleKey, User, UserRole
from app.identity.sessions import issue_session
from app.main import create_app
from tests.factories import OPERATOR, World

ENDPOINT = "/api/review/attention/revisions"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-stranded-revisions-test")


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """The app, reading the test's own transaction.

    Imported as `db_session_dependency` because the pytest fixture is also called `db_session`,
    and overriding one with the other is a mistake that reads as correct.
    """
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session_dependency] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    dispose_engines()


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


def sign_in(session: Session, *roles: RoleKey) -> str:
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


def strand(session: Session, world: World, *, subject: str = "SYNTHETIC edited subject") -> Any:
    """Walk the dead end `T-071d` fell into, and refuse to proceed if it does not happen.

    The guard matters more than the convenience. If a future change made this edit *pass*
    validation, every assertion below would still hold vacuously against an empty list — the test
    would be green and would be checking nothing.
    """
    result = edit_revision(
        session,
        world.revision,
        subject=subject,
        body="SYNTHETIC edited body that cites nothing and is not the rendered template.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )
    assert not result.is_valid, "the edit was expected to fail validation and did not"
    assert result.revision.state is MessageRevisionState.VALIDATION_FAILED
    return result


def fetch(client: TestClient, token: str, **params: object) -> Any:
    return client.get(ENDPOINT, headers={"Authorization": f"Bearer {token}"}, params=params)


# --- criterion 1: the stranded candidate appears somewhere a reviewer looks -----------------------


def test_a_candidate_whose_latest_revision_failed_validation_is_listed(
    client: TestClient, db_session: Session, world: World
) -> None:
    result = strand(db_session, world)
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    response = fetch(client, token)

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["revision_id"] for item in items] == [str(result.revision.id)]
    assert items[0]["candidate_id"] == str(world.candidate.id)


def test_the_row_names_the_account_and_the_campaign(
    client: TestClient, db_session: Session, world: World
) -> None:
    """A UUID starts an investigation; the account name ends one. Same reason `T-068a` carries
    `triggering_id` rather than only the trigger category."""
    strand(db_session, world)
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    item = fetch(client, token).json()["items"][0]

    assert item["account_name"] == world.account.name
    assert item["campaign_name"] == world.campaign.name
    assert item["campaign_id"] == str(world.campaign.id)


def test_a_candidate_with_no_failed_revision_is_not_listed(
    client: TestClient, db_session: Session, world: World
) -> None:
    """The control on criterion 1. `world` has a revision and no failure; a list that showed every
    revision would also have shown the stranded one, and would have proved nothing."""
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    assert fetch(client, token).json()["items"] == []


def test_only_the_latest_revision_counts(
    client: TestClient, db_session: Session, world: World
) -> None:
    """A candidate rescued by a further edit is back in a queue and is not stranded.

    Listing it here as well would bury the ones that are, which is the failure this endpoint
    exists to prevent rather than to relocate.

    There is no filter in the endpoint for this and there should not be: `create_revision`
    supersedes the previous revision in the same call that writes the next one, so the rescued
    revision leaves `validation_failed` on its own. This asserts that mechanism rather than a
    condition — a condition was written first, and this test passed with it removed.
    """
    failed = strand(db_session, world)
    # The rescue: editing the failed revision again. Whether *this* edit passes validation is not
    # the point — the previous revision is superseded either way, so it is no longer the latest.
    edit_revision(
        db_session,
        failed.revision,
        subject="SYNTHETIC rescued subject",
        body="SYNTHETIC rescued body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    listed = [item["revision_id"] for item in fetch(client, token).json()["items"]]

    assert str(failed.revision.id) not in listed


def test_a_refusal_leaves_the_list_once_a_replacement_is_written(
    client: TestClient, db_session: Session, world: World
) -> None:
    """`T-211`. Nothing supersedes an invalidated revision, so the state filter alone would keep a
    refusal on this page forever after somebody wrote the replacement it was asking for — the same
    burying this list exists to prevent, arriving by a different route."""
    revisions.transition(
        db_session, world.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
    )
    revisions.refuse(
        db_session, world.revision, reason="tone_or_positioning_problem", actor=OPERATOR
    )
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)
    assert fetch(client, token).json()["items"] != []

    edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC replacement subject",
        body="SYNTHETIC replacement body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    listed = [item["revision_id"] for item in fetch(client, token).json()["items"]]
    assert str(world.revision.id) not in listed


def test_the_campaign_filter_narrows_the_list(
    client: TestClient, db_session: Session, world: World
) -> None:
    strand(db_session, world)
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    assert fetch(client, token, campaign_id=str(world.campaign.id)).json()["items"] != []
    assert fetch(client, token, campaign_id=str(uuid.uuid4())).json()["items"] == []


# --- criterion 2: the failures are readable after a reload ---------------------------------------


def test_the_row_carries_the_checks_that_refused_it(
    client: TestClient, db_session: Session, world: World
) -> None:
    result = strand(db_session, world)
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    failures = fetch(client, token).json()["items"][0]["failures"]

    assert [failure["check"] for failure in failures] == [
        failure.check.value for failure in result.validation.failures
    ]
    assert all(failure["reason"] for failure in failures)


def test_the_failures_survive_the_response_that_produced_them(
    client: TestClient, db_session: Session, world: World
) -> None:
    """The whole of criterion 2. Every `T-071d` run lost the failure detail on navigation, because
    the only place it had ever existed was the body of the edit response."""
    strand(db_session, world)
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    first = fetch(client, token).json()["items"][0]["failures"]
    second = fetch(client, token).json()["items"][0]["failures"]

    assert first == second
    assert first != []


def test_the_failure_inputs_carry_no_message_content(
    client: TestClient, db_session: Session, world: World
) -> None:
    """§15.5. `ValidationFailure.inputs` is IDs and classifications; this endpoint passes the
    dictionary through rather than assembling one, and that is the property worth pinning."""
    strand(db_session, world, subject="SYNTHETIC-do-not-leak-this-subject")
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    item = fetch(client, token).json()["items"][0]

    for failure in item["failures"]:
        for value in failure["inputs"].values():
            assert "do-not-leak-this-subject" not in value
            assert world.recipient.value not in value


# --- the route refuses whoever it should ---------------------------------------------------------


def test_an_unauthenticated_request_is_refused(client: TestClient) -> None:
    assert client.get(ENDPOINT).status_code == 401


def test_a_role_without_the_queue_permission_is_refused(
    client: TestClient, db_session: Session, world: World
) -> None:
    strand(db_session, world)
    token = sign_in(db_session)

    assert fetch(client, token).status_code == 403
