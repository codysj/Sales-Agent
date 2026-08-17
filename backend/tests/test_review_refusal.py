"""A reviewer can refuse wording without writing the replacement (T-208; §10.6, §8.2, §12.3).

`T-071d` ran three readers against the dashboard and **all three decided the draft must not go
out. None of them could record it.** The card offered *approve these words* and *edit this draft*,
so the only artefact a refusal could produce was a new revision — which means a reviewer with no
better wording had nothing to press, and one who wrote replacement copy to express "don't send
this" left a record that says something else happened.

What is asserted here follows the three criteria, plus the boundary that makes the feature
honest:

* the refusal records, with a §10.6 reason and **no replacement text**;
* it is distinguishable in the record from a candidate rejection and from an edit — different
  object, different state, different audit action;
* the refused revision leaves the approval queue and appears where a reviewer looks;
* and it stays a decision about *the message*: the candidate is untouched, and the eight §10.6
  categories that are about the candidate are refused by the schema rather than quietly stored
  against the wrong object.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import AuditEvent
from app.core.lifecycles import CampaignCandidateState, MessageRevisionState
from app.db.session import dispose_engines
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.editing import edit_revision
from app.drafts_and_approvals.revisions import RefusalRefused, refuse
from app.identity.dependencies import db_session as db_session_dependency
from app.identity.models import Role, RoleKey, User, UserRole
from app.identity.sessions import issue_session
from app.main import create_app
from tests.factories import OPERATOR, World

REASON = "tone_or_positioning_problem"


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-review-refusal-test")


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session_dependency] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    dispose_engines()


@pytest.fixture
def world(db_session: Session) -> World:
    """A world whose revision is in `review_pending` — where a reviewer meets it."""
    built = World(db_session)
    revisions.transition(
        db_session, built.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
    )
    return built


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


def post_refusal(client: TestClient, revision_id: uuid.UUID, token: str, **body: object) -> Any:
    payload: dict[str, object] = {"reason": REASON}
    payload.update(body)
    return client.post(
        f"/api/review/revisions/{revision_id}/refuse",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


# --- criterion 1: a refusal records, with a reason and no replacement text ------------------------


def test_a_reviewer_refuses_wording_without_writing_any(
    client: TestClient, db_session: Session, world: World
) -> None:
    """The whole point. No subject, no body — the request has nowhere to put replacement text."""
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    response = post_refusal(client, world.revision.id, token, notes="SYNTHETIC: too salesy")

    assert response.status_code == 200
    db_session.refresh(world.revision)
    assert world.revision.state is MessageRevisionState.INVALIDATED
    assert world.revision.refusal_reason == REASON
    assert world.revision.refusal_notes == "SYNTHETIC: too salesy"


def test_the_refusal_leaves_the_words_exactly_as_they_were(
    client: TestClient, db_session: Session, world: World
) -> None:
    """A refused message must stay readable as refused, the same guarantee an edit gives the
    revision it supersedes."""
    before = (world.revision.subject, world.revision.body, world.revision.content_hash)
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    post_refusal(client, world.revision.id, token)

    db_session.refresh(world.revision)
    assert (world.revision.subject, world.revision.body, world.revision.content_hash) == before


def test_notes_are_optional(client: TestClient, db_session: Session, world: World) -> None:
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    assert post_refusal(client, world.revision.id, token).status_code == 200
    db_session.refresh(world.revision)
    assert world.revision.refusal_notes is None


def test_a_candidate_level_reason_is_refused_by_the_schema(
    client: TestClient, db_session: Session, world: World
) -> None:
    """`wrong_account_or_duplicate` is true of a candidate and meaningless about a paragraph.
    Storing it here would record a true statement against the wrong object."""
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    response = post_refusal(client, world.revision.id, token, reason="wrong_account_or_duplicate")

    assert response.status_code == 422
    db_session.refresh(world.revision)
    assert world.revision.state is MessageRevisionState.REVIEW_PENDING


def test_a_stale_record_version_is_refused(
    client: TestClient, db_session: Session, world: World
) -> None:
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    response = post_refusal(client, world.revision.id, token, record_version="2020-01-01T00:00:00Z")

    assert response.status_code == 409
    assert "reload the card" in response.json()["detail"]


def test_an_already_refused_revision_cannot_be_refused_again(
    client: TestClient, db_session: Session, world: World
) -> None:
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)
    post_refusal(client, world.revision.id, token)
    db_session.refresh(world.revision)

    response = post_refusal(
        client,
        world.revision.id,
        token,
        record_version=world.revision.updated_at.isoformat(),
    )

    assert response.status_code == 409
    assert "invalidated" in response.json()["detail"]


def test_a_validation_failed_revision_may_also_be_refused(db_session: Session) -> None:
    """Broken *and* wrong is a real combination: a reviewer who sees a draft that failed a check
    and also judges the wording unsendable should be able to say the second part."""
    built = World(db_session)
    revisions.transition(
        db_session, built.revision, MessageRevisionState.VALIDATION_FAILED, actor=OPERATOR
    )

    refuse(db_session, built.revision, reason=REASON, actor=OPERATOR)

    assert built.revision.state is MessageRevisionState.INVALIDATED


def test_a_draft_nobody_has_seen_cannot_be_refused(db_session: Session) -> None:
    """The control on `REFUSABLE_STATES`. A `draft` revision has not reached a reviewer, so there
    is no judgement to record about it."""
    built = World(db_session)

    with pytest.raises(RefusalRefused, match="draft"):
        refuse(db_session, built.revision, reason=REASON, actor=OPERATOR)


def test_a_blank_reason_is_refused(db_session: Session, world: World) -> None:
    with pytest.raises(RefusalRefused, match="reason"):
        refuse(db_session, world.revision, reason="   ", actor=OPERATOR)


# --- criterion 2: distinguishable from a rejection and from an edit -------------------------------


def test_the_candidate_is_untouched(client: TestClient, db_session: Session, world: World) -> None:
    """All three rehearsal runs approved the company and refused only the words. Collapsing those
    is the conflation `T-205` was filed to end."""
    before = world.candidate.state
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    post_refusal(client, world.revision.id, token)

    db_session.refresh(world.candidate)
    assert world.candidate.state is before
    assert world.candidate.state is not CampaignCandidateState.REJECTED


def test_the_record_says_refused_and_not_edited(
    client: TestClient, db_session: Session, world: World
) -> None:
    """An edit and a refusal both retire a revision. They must not read alike afterwards: one
    supersedes and names a successor, the other invalidates and names a reason."""
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    post_refusal(client, world.revision.id, token)

    actions = set(
        db_session.execute(
            select(AuditEvent.action).where(AuditEvent.entity_id == str(world.revision.id))
        )
        .scalars()
        .all()
    )
    assert "message_revision.refused" in actions
    db_session.refresh(world.revision)
    assert world.revision.state is not MessageRevisionState.SUPERSEDED


def test_an_edit_records_no_refusal_reason(db_session: Session, world: World) -> None:
    """The other direction of the same claim, and the control on it: editing must not leave a
    refusal behind, or every correction would read as a rejection of the wording."""
    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    db_session.refresh(world.revision)
    assert world.revision.state is MessageRevisionState.SUPERSEDED
    assert world.revision.refusal_reason is None
    assert result.revision.refusal_reason is None


# --- criterion 3: it leaves the queue and is visible somewhere ------------------------------------


def test_the_refused_revision_leaves_the_approval_queue(
    client: TestClient, db_session: Session, world: World
) -> None:
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)
    headers = {"Authorization": f"Bearer {token}"}
    before = client.get("/api/review/revisions", headers=headers).json()["rows"]
    assert str(world.revision.id) in [row["revision_id"] for row in before]

    post_refusal(client, world.revision.id, token)

    after = client.get("/api/review/revisions", headers=headers).json()["rows"]
    assert str(world.revision.id) not in [row["revision_id"] for row in after]


def test_the_refused_revision_appears_on_the_attention_list(
    client: TestClient, db_session: Session, world: World
) -> None:
    """§7.5. Nothing writes a replacement by itself, so a refused draft leaves its candidate with
    nothing approvable — which is exactly what `T-209` built this list to surface."""
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)
    post_refusal(client, world.revision.id, token, notes="SYNTHETIC: too salesy")

    items = client.get(
        "/api/review/attention/revisions", headers={"Authorization": f"Bearer {token}"}
    ).json()["items"]

    assert [item["revision_id"] for item in items] == [str(world.revision.id)]
    assert items[0]["refusal_reason"] == REASON
    assert items[0]["refusal_notes"] == "SYNTHETIC: too salesy"
    # A person decided; no check refused it, and showing checks would ask for a judgement that
    # has already been made.
    assert items[0]["failures"] == []


def test_a_reviewable_revision_is_not_on_the_attention_list(
    client: TestClient, db_session: Session, world: World
) -> None:
    """The control on the test above: the list would prove nothing if it held everything."""
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    items = client.get(
        "/api/review/attention/revisions", headers={"Authorization": f"Bearer {token}"}
    ).json()["items"]

    assert items == []


# --- the route refuses whoever it should ---------------------------------------------------------


def test_an_unauthenticated_refusal_is_refused(client: TestClient, world: World) -> None:
    assert (
        client.post(f"/api/review/revisions/{world.revision.id}/refuse", json={"reason": REASON})
    ).status_code == 401


def test_a_viewer_may_not_refuse(client: TestClient, db_session: Session, world: World) -> None:
    token = sign_in(db_session, RoleKey.VIEWER)

    assert post_refusal(client, world.revision.id, token).status_code == 403
